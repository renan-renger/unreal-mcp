// Copyright (c) 2025 GenOrca (by zenoengine). All Rights Reserved.
//
// Landscape / level-build helpers. Ported from MadorasRebirth PR #1511
// (UMadoraLevelBuildLibrary); every default and rule here was measured, not invented —
// the measurement is quoted where it drives the code. This module is Editor-only, so no
// WITH_EDITOR guards are needed.

#include "MCPythonHelper.h"

#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"

#include "Landscape.h"
#include "LandscapeEdit.h"
#include "LandscapeEditLayer.h"
#include "LandscapeInfo.h"
#include "LandscapeLayerInfoObject.h"
#include "LandscapeProxy.h"
#include "LandscapeSubsystem.h"
#include "Materials/MaterialInterface.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "UObject/Package.h"

ALandscape* UMCPythonHelper::CreateFlatLandscape(
	UObject* WorldContextObject,
	FVector Location,
	FVector Scale,
	int32 QuadsPerSection,
	int32 SectionsPerComponent,
	int32 ComponentCountX,
	int32 ComponentCountY,
	UMaterialInterface* LandscapeMaterial,
	FString& OutError)
{
	OutError.Reset();

	UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
	if (World == nullptr)
	{
		OutError = TEXT("No world: pass a valid WorldContextObject.");
		return nullptr;
	}

	// Engine constraints, not preferences. A subsection is a square of one of these sizes and a component
	// holds one or four of them; anything else produces a landscape the renderer cannot page.
	const bool bValidQuads = (QuadsPerSection == 7) || (QuadsPerSection == 15) || (QuadsPerSection == 31)
		|| (QuadsPerSection == 63) || (QuadsPerSection == 127) || (QuadsPerSection == 255);
	if (!bValidQuads)
	{
		OutError = FString::Printf(TEXT("QuadsPerSection=%d is invalid; must be 7, 15, 31, 63, 127 or 255."), QuadsPerSection);
		return nullptr;
	}

	if (SectionsPerComponent != 1 && SectionsPerComponent != 2)
	{
		OutError = FString::Printf(TEXT("SectionsPerComponent=%d is invalid; must be 1 or 2."), SectionsPerComponent);
		return nullptr;
	}

	if (ComponentCountX <= 0 || ComponentCountY <= 0)
	{
		OutError = FString::Printf(TEXT("ComponentCount must be positive; got %d x %d."), ComponentCountX, ComponentCountY);
		return nullptr;
	}

	if (Scale.X <= 0.0 || Scale.Y <= 0.0 || FMath::IsNearlyZero(Scale.Z))
	{
		OutError = TEXT("Scale must have positive X and Y and a non-zero Z.");
		return nullptr;
	}

	// A grid-based (World Partition) world does not take a single ALandscape: the engine splits it into
	// streaming proxies and, past a region size, into LocationVolume regions. That path is substantially
	// more code, so refuse loudly rather than leave a half-built landscape behind.
	if (const ULandscapeSubsystem* LandscapeSubsystem = World->GetSubsystem<ULandscapeSubsystem>())
	{
		if (LandscapeSubsystem->IsGridBased())
		{
			OutError = TEXT("This world is grid-based (World Partition); CreateFlatLandscape only supports non-partitioned levels.");
			return nullptr;
		}
	}

	const int32 QuadsPerComponent = SectionsPerComponent * QuadsPerSection;
	const int32 SizeX = ComponentCountX * QuadsPerComponent + 1;
	const int32 SizeY = ComponentCountY * QuadsPerComponent + 1;

	// Both maps must be keyed by the default FGuid - that is the "final layer" the import reads - and
	// Import checks that the two have the same number of entries. Empty height data means flat.
	TMap<FGuid, TArray<uint16>> HeightDataPerLayers;
	TMap<FGuid, TArray<FLandscapeImportLayerInfo>> MaterialLayerDataPerLayers;
	HeightDataPerLayers.Add(FGuid(), TArray<uint16>());
	MaterialLayerDataPerLayers.Add(FGuid(), TArray<FLandscapeImportLayerInfo>());

	ALandscape* Landscape = World->SpawnActor<ALandscape>(Location, FRotator::ZeroRotator);
	if (Landscape == nullptr)
	{
		OutError = TEXT("SpawnActor<ALandscape> failed.");
		return nullptr;
	}

	Landscape->LandscapeMaterial = LandscapeMaterial;
	Landscape->SetActorRelativeScale3D(Scale);

	// Lighting LOD that will not blow up Lightmass, copied from the engine's own New Landscape path:
	// < 2048x2048 -> LOD0, >= 2048x2048 -> LOD1, >= 4096x4096 -> LOD2, >= 8192x8192 -> LOD3.
	Landscape->StaticLightingLOD = FMath::DivideAndRoundUp(FMath::CeilLogTwo((SizeX * SizeY) / (2048 * 2048) + 1), (uint32)2);

	// Empty file name rather than nullptr: this is only stored for reimport bookkeeping, and a null TCHAR*
	// is not what the callers in the engine pass.
	Landscape->Import(
		FGuid::NewGuid(),
		0, 0, SizeX - 1, SizeY - 1,
		SectionsPerComponent, QuadsPerSection,
		HeightDataPerLayers,
		TEXT(""),
		MaterialLayerDataPerLayers,
		ELandscapeImportAlphamapType::Additive,
		TArrayView<const FLandscapeLayer>());

	ULandscapeInfo* LandscapeInfo = Landscape->GetLandscapeInfo();
	if (LandscapeInfo == nullptr)
	{
		OutError = TEXT("Landscape was imported but has no ULandscapeInfo; the actor is left in the level for inspection.");
		return Landscape;
	}

	LandscapeInfo->UpdateLayerInfoMap(Landscape);

	return Landscape;
}

FString UMCPythonHelper::SculptBorderMountains(
	ALandscape* Landscape,
	float RidgeDistanceUU,
	float RidgeHalfWidthUU,
	float PeakHeightUU,
	float HeightVariationUU,
	float MinPeakHeightUU,
	float RidgeWanderUU,
	float NoiseWavelengthUU,
	float RoughnessUU,
	float GroundHeightUU,
	int32 Seed,
	bool bWestEdge,
	bool bEastEdge,
	bool bSouthEdge,
	bool bNorthEdge)
{
	if (Landscape == nullptr)
	{
		return TEXT("Landscape is null.");
	}

	if (!bWestEdge && !bEastEdge && !bSouthEdge && !bNorthEdge)
	{
		return TEXT("All four edges are disabled; there is nothing to sculpt.");
	}

	if (RidgeHalfWidthUU <= 0.0f)
	{
		return FString::Printf(TEXT("RidgeHalfWidthUU must be positive; got %.1f."), RidgeHalfWidthUU);
	}

	if (NoiseWavelengthUU <= 0.0f)
	{
		return FString::Printf(TEXT("NoiseWavelengthUU must be positive; got %.1f."), NoiseWavelengthUU);
	}

	if (RidgeDistanceUU < 0.0f)
	{
		return FString::Printf(TEXT("RidgeDistanceUU cannot be negative; got %.1f."), RidgeDistanceUU);
	}

	if (MinPeakHeightUU < 0.0f)
	{
		return FString::Printf(TEXT("MinPeakHeightUU cannot be negative; got %.1f."), MinPeakHeightUU);
	}

	// A floor above the mean does not clamp the noise, it erases it: every peak lands on the floor and
	// the range comes out uniform.
	if (MinPeakHeightUU > PeakHeightUU)
	{
		return FString::Printf(
			TEXT("MinPeakHeightUU %.0f is above PeakHeightUU %.0f, which would flatten the whole range to the floor."),
			MinPeakHeightUU, PeakHeightUU);
	}

	ULandscapeInfo* Info = Landscape->GetLandscapeInfo();
	if (Info == nullptr)
	{
		return TEXT("Landscape has no ULandscapeInfo; it may not be fully registered yet.");
	}

	int32 MinX = 0, MinY = 0, MaxX = 0, MaxY = 0;
	if (!Info->GetLandscapeExtent(MinX, MinY, MaxX, MaxY))
	{
		return TEXT("GetLandscapeExtent failed; the landscape has no components.");
	}

	const FVector Scale = Landscape->GetActorScale3D();
	if (Scale.X <= 0.0 || Scale.Y <= 0.0 || FMath::IsNearlyZero(Scale.Z))
	{
		return TEXT("Landscape scale must have positive X and Y and a non-zero Z.");
	}

	const int32 VertsX = MaxX - MinX + 1;
	const int32 VertsY = MaxY - MinY + 1;

	// The mountain zone reaches this far in. Refusing here beats handing back a map that is all mountain.
	const double ZoneUU = RidgeDistanceUU + RidgeWanderUU + RidgeHalfWidthUU;
	const double HalfSpanX = (VertsX - 1) * Scale.X * 0.5;
	const double HalfSpanY = (VertsY - 1) * Scale.Y * 0.5;
	if (ZoneUU >= FMath::Min(HalfSpanX, HalfSpanY))
	{
		return FString::Printf(
			TEXT("The mountain zone reaches %.0f uu inward, leaving no flat ground: the map's half-span is %.0f x %.0f."),
			ZoneUU, HalfSpanX, HalfSpanY);
	}

	// Offsets keep the three noise fields independent, and the seed moves all of them.
	//
	// They MUST stay small. FMath::PerlinNoise2D casts its argument down to float internally - the engine
	// marks the line "LWC_TODO: Precision loss" - so a coordinate in the hundreds of millions has a float
	// spacing of ~32 and loses its fractional part entirely. The noise then evaluates exactly on a lattice
	// point and returns 0.0 for every vertex. That is not a subtle artefact: an earlier version derived
	// the offset as Seed * 17.317, which for seed 20260818 gave ~3.5e8, and the whole range came out at
	// precisely the mean height with a measured standard deviation of 0.0.
	const FRandomStream SeedStream(Seed);
	auto RandomOffset = [&SeedStream]() {
		return FVector2D(SeedStream.FRandRange(-256.0f, 256.0f), SeedStream.FRandRange(-256.0f, 256.0f));
	};
	const FVector2D OffsetHeight = RandomOffset();
	const FVector2D OffsetWander = RandomOffset();
	const FVector2D OffsetRough = RandomOffset();

	// Roughness rides a shorter wavelength than the ridge itself, otherwise it just restates the same
	// shape and the result reads as smooth again.
	const double RoughWavelength = FMath::Max(NoiseWavelengthUU * 0.28, 1.0);

	TArray<uint16> Heights;
	Heights.SetNumUninitialized(VertsX * VertsY);

	// A disabled edge contributes an infinite distance, so its side of the map stays flat
	// ground and the chains of the enabled edges still meet cleanly at shared corners.
	const double Far = TNumericLimits<double>::Max();

	for (int32 Y = 0; Y < VertsY; ++Y)
	{
		const double WorldY = Y * Scale.Y;
		const double DistY = FMath::Min(
			bSouthEdge ? Y * Scale.Y : Far,
			bNorthEdge ? (VertsY - 1 - Y) * Scale.Y : Far);

		for (int32 X = 0; X < VertsX; ++X)
		{
			const double WorldX = X * Scale.X;
			const double DistX = FMath::Min(
				bWestEdge ? X * Scale.X : Far,
				bEastEdge ? (VertsX - 1 - X) * Scale.X : Far);

			// Nearest enabled edge, so the chains meet at the corners instead of crossing.
			const double Dist = FMath::Min(DistX, DistY);

			double HeightUU = GroundHeightUU;

			// Sampling the noise in 2D world space rather than along each edge separately is what keeps the
			// corners continuous - an edge-parametrised noise would jump where two sides meet.
			const FVector2D NoisePos(WorldX / NoiseWavelengthUU, WorldY / NoiseWavelengthUU);

			const double Wander = FMath::PerlinNoise2D(NoisePos + OffsetWander) * RidgeWanderUU;
			const double Ridge = FMath::Max(RidgeDistanceUU + Wander, 0.0);

			const double U = (Dist - Ridge) / RidgeHalfWidthUU;
			if (FMath::Abs(U) < 1.0)
			{
				const double PeakNoise = FMath::PerlinNoise2D(NoisePos + OffsetHeight) * HeightVariationUU;

				// The floor is what seals the chain. Clamping here rather than reducing HeightVariationUU
				// keeps the variation everywhere the noise is above the floor - only the troughs deep
				// enough to open a gap get lifted.
				const double Peak = FMath::Max(PeakHeightUU + PeakNoise, static_cast<double>(MinPeakHeightUU));

				const double Falloff = 0.5 * (1.0 + FMath::Cos(UE_DOUBLE_PI * U));
				double Bump = Peak * Falloff;

				// Fine detail only on the mountain: adding it to the flat interior would make the playable
				// floor bumpy for no reason.
				const FVector2D RoughPos(WorldX / RoughWavelength, WorldY / RoughWavelength);
				Bump += FMath::PerlinNoise2D(RoughPos + OffsetRough) * RoughnessUU * Falloff;

				HeightUU += FMath::Max(Bump, 0.0);
			}

			// Landscape stores height as uint16 where 32768 is the actor's own Z and one unit of local
			// height is 1/128 - see LandscapeDataAccess::GetLocalHeight. World height is local * Scale.Z.
			const double Local = HeightUU / Scale.Z;
			const double Raw = 32768.0 + Local * 128.0;
			Heights[Y * VertsX + X] = static_cast<uint16>(FMath::Clamp(FMath::RoundToDouble(Raw), 0.0, 65535.0));
		}
	}

	// Write into the first edit layer when the landscape has one. Editing without the GUID targets the
	// merged result, which the layer system then recomposites over - the edit would appear to take and
	// then vanish on the next update.
	const ULandscapeEditLayerBase* EditLayer = Landscape->GetEditLayerConst(0);
	TUniquePtr<FLandscapeEditDataInterface> LandscapeEdit =
		(EditLayer != nullptr)
			? MakeUnique<FLandscapeEditDataInterface>(Info, EditLayer->GetGuid())
			: MakeUnique<FLandscapeEditDataInterface>(Info);

	// InStride 0 means "one row is X2 - X1 + 1 entries", which is how Heights is laid out.
	LandscapeEdit->SetHeightData(MinX, MinY, MaxX, MaxY, Heights.GetData(), 0, /*InCalcNormals=*/true);
	LandscapeEdit->Flush();

	if (EditLayer != nullptr)
	{
		Landscape->ForceLayersFullUpdate();
	}

	// Collision is a separate representation from the rendered heightfield; without this the terrain
	// looks right and the player still walks through the mountains.
	Landscape->RecreateCollisionComponents();

	return FString();
}

FString UMCPythonHelper::SculptRectRegion(
	ALandscape* Landscape,
	float MinXUU,
	float MinYUU,
	float MaxXUU,
	float MaxYUU,
	float TargetHeightUU,
	float FalloffUU)
{
	if (Landscape == nullptr)
	{
		return TEXT("Landscape is null.");
	}

	if (MaxXUU <= MinXUU || MaxYUU <= MinYUU)
	{
		return FString::Printf(TEXT("Region is empty: (%.0f..%.0f) x (%.0f..%.0f)."), MinXUU, MaxXUU, MinYUU, MaxYUU);
	}

	if (FalloffUU <= 0.0f)
	{
		return FString::Printf(TEXT("FalloffUU must be positive; got %.1f."), FalloffUU);
	}

	ULandscapeInfo* Info = Landscape->GetLandscapeInfo();
	if (Info == nullptr)
	{
		return TEXT("Landscape has no ULandscapeInfo; it may not be fully registered yet.");
	}

	int32 MinX = 0, MinY = 0, MaxX = 0, MaxY = 0;
	if (!Info->GetLandscapeExtent(MinX, MinY, MaxX, MaxY))
	{
		return TEXT("GetLandscapeExtent failed; the landscape has no components.");
	}

	const FVector Scale = Landscape->GetActorScale3D();
	if (Scale.X <= 0.0 || Scale.Y <= 0.0 || FMath::IsNearlyZero(Scale.Z))
	{
		return TEXT("Landscape scale must have positive X and Y and a non-zero Z.");
	}

	const int32 VertsX = MaxX - MinX + 1;
	const int32 VertsY = MaxY - MinY + 1;

	const ULandscapeEditLayerBase* EditLayer = Landscape->GetEditLayerConst(0);
	TUniquePtr<FLandscapeEditDataInterface> LandscapeEdit =
		(EditLayer != nullptr)
			? MakeUnique<FLandscapeEditDataInterface>(Info, EditLayer->GetGuid())
			: MakeUnique<FLandscapeEditDataInterface>(Info);

	// Blend against what is there, unlike SculptBorderMountains: this is a local edit, so it
	// must read the existing heights first rather than assume a flat interior.
	TArray<uint16> Heights;
	Heights.SetNumZeroed(VertsX * VertsY);
	LandscapeEdit->GetHeightDataFast(MinX, MinY, MaxX, MaxY, Heights.GetData(), 0);

	const double TargetLocal = TargetHeightUU / Scale.Z;
	const double TargetRaw = FMath::Clamp(32768.0 + TargetLocal * 128.0, 0.0, 65535.0);

	bool bTouched = false;
	for (int32 Y = 0; Y < VertsY; ++Y)
	{
		const double WorldY = Y * Scale.Y;
		// Distance outside the rect along each axis; 0 inside.
		const double DY = FMath::Max3(MinYUU - WorldY, WorldY - MaxYUU, 0.0);

		for (int32 X = 0; X < VertsX; ++X)
		{
			const double WorldX = X * Scale.X;
			const double DX = FMath::Max3(MinXUU - WorldX, WorldX - MaxXUU, 0.0);

			const double Dist = FMath::Sqrt(DX * DX + DY * DY);
			if (Dist >= FalloffUU)
			{
				continue;
			}

			// Smoothstep from full effect inside the rect to none at the falloff's edge —
			// a hard step here reads as a machined trench wall from any angle.
			const double T = 1.0 - Dist / FalloffUU;
			const double Blend = T * T * (3.0 - 2.0 * T);

			const int32 Idx = Y * VertsX + X;
			const double NewRaw = FMath::Lerp(static_cast<double>(Heights[Idx]), TargetRaw, Blend);
			Heights[Idx] = static_cast<uint16>(FMath::Clamp(FMath::RoundToDouble(NewRaw), 0.0, 65535.0));
			bTouched = true;
		}
	}

	if (!bTouched)
	{
		return TEXT("The region (plus falloff) does not overlap the landscape.");
	}

	LandscapeEdit->SetHeightData(MinX, MinY, MaxX, MaxY, Heights.GetData(), 0, /*InCalcNormals=*/true);
	LandscapeEdit->Flush();

	if (EditLayer != nullptr)
	{
		Landscape->ForceLayersFullUpdate();
	}

	Landscape->RecreateCollisionComponents();

	return FString();
}

ULandscapeLayerInfoObject* UMCPythonHelper::FindOrCreateLandscapeLayerInfo(
	const FString& PackagePath,
	FName LayerName,
	FString& OutError)
{
	OutError.Reset();

	if (LayerName.IsNone())
	{
		OutError = TEXT("LayerName is None.");
		return nullptr;
	}

	if (PackagePath.IsEmpty() || !PackagePath.StartsWith(TEXT("/")))
	{
		OutError = FString::Printf(TEXT("PackagePath must be a content path like /Game/Foo; got '%s'."), *PackagePath);
		return nullptr;
	}

	// Naming matches the editor's own convention for layer info assets, so a landscape painted here and
	// one painted by hand do not end up with two different naming schemes in the same folder.
	const FString AssetName = FString::Printf(TEXT("LI_%s"), *LayerName.ToString());
	const FString PackageName = FString::Printf(TEXT("%s/%s"), *PackagePath, *AssetName);

	if (UPackage* Existing = FindPackage(nullptr, *PackageName))
	{
		if (ULandscapeLayerInfoObject* Found = FindObject<ULandscapeLayerInfoObject>(Existing, *AssetName))
		{
			return Found;
		}
	}

	if (ULandscapeLayerInfoObject* Loaded = LoadObject<ULandscapeLayerInfoObject>(nullptr, *(PackageName + TEXT(".") + AssetName), nullptr, LOAD_NoWarn | LOAD_Quiet))
	{
		return Loaded;
	}

	UPackage* Package = CreatePackage(*PackageName);
	if (Package == nullptr)
	{
		OutError = FString::Printf(TEXT("CreatePackage failed for '%s'."), *PackageName);
		return nullptr;
	}

	ULandscapeLayerInfoObject* LayerInfo = NewObject<ULandscapeLayerInfoObject>(
		Package, *AssetName, RF_Public | RF_Standalone | RF_Transactional);
	if (LayerInfo == nullptr)
	{
		OutError = FString::Printf(TEXT("NewObject<ULandscapeLayerInfoObject> failed for '%s'."), *AssetName);
		return nullptr;
	}

	// The asset's own LayerName is what binds it to the material's paint layer. Getting this wrong gives
	// an asset that exists, registers, and paints nothing. (Setter, not the property: the raw member is
	// deprecated as of 5.7. bInModify false — the package is brand new, there is no undo state to record.)
	LayerInfo->SetLayerName(LayerName, /*bInModify=*/false);

	FAssetRegistryModule::AssetCreated(LayerInfo);
	Package->MarkPackageDirty();

	return LayerInfo;
}

FString UMCPythonHelper::PaintLandscapeBySlope(
	ALandscape* Landscape,
	ULandscapeLayerInfoObject* FlatLayer,
	ULandscapeLayerInfoObject* SlopeLayer,
	float SlopeStartDegrees,
	float SlopeFullDegrees)
{
	if (Landscape == nullptr)
	{
		return TEXT("Landscape is null.");
	}

	if (FlatLayer == nullptr || SlopeLayer == nullptr)
	{
		return TEXT("Both FlatLayer and SlopeLayer must be set.");
	}

	if (SlopeFullDegrees <= SlopeStartDegrees)
	{
		return FString::Printf(TEXT("SlopeFullDegrees (%.1f) must be greater than SlopeStartDegrees (%.1f)."),
			SlopeFullDegrees, SlopeStartDegrees);
	}

	ULandscapeInfo* Info = Landscape->GetLandscapeInfo();
	if (Info == nullptr)
	{
		return TEXT("Landscape has no ULandscapeInfo; it may not be fully registered yet.");
	}

	int32 MinX = 0, MinY = 0, MaxX = 0, MaxY = 0;
	if (!Info->GetLandscapeExtent(MinX, MinY, MaxX, MaxY))
	{
		return TEXT("GetLandscapeExtent failed; the landscape has no components.");
	}

	const FVector Scale = Landscape->GetActorScale3D();
	const int32 VertsX = MaxX - MinX + 1;
	const int32 VertsY = MaxY - MinY + 1;

	// Register before painting. SetAlphaData on a layer the landscape does not list as a target layer is
	// accepted and then discarded, which looks exactly like painting that had no effect.
	Landscape->AddTargetLayer(FlatLayer->GetLayerName(), FLandscapeTargetLayerSettings(FlatLayer));
	Landscape->AddTargetLayer(SlopeLayer->GetLayerName(), FLandscapeTargetLayerSettings(SlopeLayer));
	Info->UpdateLayerInfoMap(Landscape);

	const ULandscapeEditLayerBase* EditLayer = Landscape->GetEditLayerConst(0);
	TUniquePtr<FLandscapeEditDataInterface> LandscapeEdit =
		(EditLayer != nullptr)
			? MakeUnique<FLandscapeEditDataInterface>(Info, EditLayer->GetGuid())
			: MakeUnique<FLandscapeEditDataInterface>(Info);

	TArray<uint16> Heights;
	Heights.SetNumZeroed(VertsX * VertsY);
	LandscapeEdit->GetHeightDataFast(MinX, MinY, MaxX, MaxY, Heights.GetData(), 0);

	TArray<uint8> FlatWeights;
	TArray<uint8> SlopeWeights;
	FlatWeights.SetNumUninitialized(VertsX * VertsY);
	SlopeWeights.SetNumUninitialized(VertsX * VertsY);

	// One height unit is 1/128 of a local unit; local times Scale.Z is world. Doing the conversion once
	// here keeps the inner loop to a subtraction.
	const double HeightToWorld = Scale.Z / 128.0;
	const double TanStart = FMath::Tan(FMath::DegreesToRadians(FMath::Max(SlopeStartDegrees, 0.0f)));
	const double TanFull = FMath::Tan(FMath::DegreesToRadians(FMath::Clamp(SlopeFullDegrees, 0.01f, 89.9f)));

	for (int32 Y = 0; Y < VertsY; ++Y)
	{
		for (int32 X = 0; X < VertsX; ++X)
		{
			// Central difference, clamped at the borders so the edge vertices use a one-sided difference
			// instead of sampling outside the array.
			const int32 X0 = FMath::Max(X - 1, 0);
			const int32 X1 = FMath::Min(X + 1, VertsX - 1);
			const int32 Y0 = FMath::Max(Y - 1, 0);
			const int32 Y1 = FMath::Min(Y + 1, VertsY - 1);

			const double DzX = (static_cast<double>(Heights[Y * VertsX + X1]) - static_cast<double>(Heights[Y * VertsX + X0])) * HeightToWorld;
			const double DzY = (static_cast<double>(Heights[Y1 * VertsX + X]) - static_cast<double>(Heights[Y0 * VertsX + X])) * HeightToWorld;

			const double RunX = FMath::Max((X1 - X0) * Scale.X, UE_DOUBLE_KINDA_SMALL_NUMBER);
			const double RunY = FMath::Max((Y1 - Y0) * Scale.Y, UE_DOUBLE_KINDA_SMALL_NUMBER);

			const double GradX = DzX / RunX;
			const double GradY = DzY / RunY;
			const double TanSlope = FMath::Sqrt(GradX * GradX + GradY * GradY);

			const double T = FMath::Clamp((TanSlope - TanStart) / FMath::Max(TanFull - TanStart, UE_DOUBLE_KINDA_SMALL_NUMBER), 0.0, 1.0);

			// Weight-blend layers that do not sum to full weight render darker than they should, so the two
			// weights are written as exact complements rather than each being computed on its own.
			const uint8 SlopeW = static_cast<uint8>(FMath::RoundToInt32(T * 255.0));
			SlopeWeights[Y * VertsX + X] = SlopeW;
			FlatWeights[Y * VertsX + X] = static_cast<uint8>(255 - SlopeW);
		}
	}

	LandscapeEdit->SetAlphaData(FlatLayer, MinX, MinY, MaxX, MaxY, FlatWeights.GetData(), 0);
	LandscapeEdit->SetAlphaData(SlopeLayer, MinX, MinY, MaxX, MaxY, SlopeWeights.GetData(), 0);
	LandscapeEdit->Flush();

	if (EditLayer != nullptr)
	{
		Landscape->ForceLayersFullUpdate();
	}

	return FString();
}

AActor* UMCPythonHelper::SpawnHISMScatterActor(
	UObject* WorldContextObject,
	const FString& Label,
	UStaticMesh* Mesh,
	FString& OutError)
{
	OutError.Reset();

	UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
	if (World == nullptr)
	{
		OutError = TEXT("No world: pass a valid WorldContextObject.");
		return nullptr;
	}

	if (Mesh == nullptr)
	{
		OutError = TEXT("Mesh is null.");
		return nullptr;
	}

	AActor* Actor = World->SpawnActor<AActor>(FVector::ZeroVector, FRotator::ZeroRotator);
	if (Actor == nullptr)
	{
		OutError = TEXT("SpawnActor<AActor> failed.");
		return nullptr;
	}

	UHierarchicalInstancedStaticMeshComponent* Hism =
		NewObject<UHierarchicalInstancedStaticMeshComponent>(Actor, TEXT("Instances"), RF_Transactional);
	if (Hism == nullptr)
	{
		World->DestroyActor(Actor);
		OutError = TEXT("NewObject<UHierarchicalInstancedStaticMeshComponent> failed.");
		return nullptr;
	}

	// AddInstanceComponent is what makes the component serialize with the actor into the level - a
	// component that is only registered renders until the map is reloaded and then is gone.
	Actor->SetRootComponent(Hism);
	Actor->AddInstanceComponent(Hism);
	Hism->SetStaticMesh(Mesh);
	Hism->RegisterComponent();

	if (!Label.IsEmpty())
	{
		Actor->SetActorLabel(Label);
	}

	return Actor;
}
