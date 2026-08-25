// Copyright (c) 2025 GenOrca (by zenoengine). All Rights Reserved.

using UnrealBuildTool;

public class UnrealMCPython : ModuleRules
{
	public UnrealMCPython(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;
		
		PublicIncludePaths.AddRange(
			new string[] {
				// ... add public include paths required here ...
			}
			);
				
		
		PrivateIncludePaths.AddRange(
			new string[] {
				// ... add other private include paths required here ...
			}
			);
			
		
		PublicDependencyModuleNames.AddRange(
			new string[]
			{
				"Core",
				"CoreUObject",
				"Engine",
				"InputCore",
				"Sockets",
				"Networking",
				"Json",
				"JsonUtilities",
				"PythonScriptPlugin"
			}
			);
			

		PrivateDependencyModuleNames.AddRange(
			new string[]
			{
				"CoreUObject",
				"Engine",
				"Slate",
				"SlateCore",
				"UnrealEd",
				"EditorSubsystem",
				"AssetTools",
				"BlueprintGraph",
				"Kismet",
				"AIModule",
				"GameplayTasks",
				"AIGraph",
				"BehaviorTreeEditor",
				"UMG",
				"UMGEditor",
				"AnimGraph",
				"AnimGraphRuntime",
				// Landscape helpers (MCPythonHelper_Landscape.cpp). Foliage is pulled in by
				// engine headers, not by choice: LandscapeEdit.h includes InstancedFoliageActor.h.
				// AssetRegistry is what makes a created ULandscapeLayerInfoObject appear in the
				// content browser.
				"Landscape",
				"Foliage",
				"AssetRegistry",
			}
			);

		if (Target.bWithLiveCoding)
		{
			PrivateDependencyModuleNames.Add("LiveCoding");
		}
		
		
		DynamicallyLoadedModuleNames.AddRange(
			new string[]
			{
				// ... add any modules that your module loads dynamically here ...
			}
			);
	}
}
