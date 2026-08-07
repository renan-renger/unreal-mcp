// Copyright (c) 2025 GenOrca. All Rights Reserved.

#include "MCPythonStateTreeHelper.h"

#include "StateTree.h"
#include "StateTreeEditingSubsystem.h"
#include "StateTreeCompilerLog.h"
#include "StateTreeEditorData.h"
#include "StateTreeEditorNode.h"
#include "StateTreeEditorPropertyBindings.h"
#include "StateTreeState.h"
#include "StateTreeTypes.h"

#include "Dom/JsonObject.h"
#include "Logging/TokenizedMessage.h"
#include "PropertyBindingPath.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
// The core plugin's equivalents live in its Private/MCPythonHelperInternal.h, which is
// not reachable from another module. Duplicated rather than promoted to Public: keeping
// the core plugin's surface unchanged is worth more than sharing twelve lines.
FString SerializeJsonObj(const TSharedRef<FJsonObject>& Obj)
{
	FString Out;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(Obj, Writer);
	return Out;
}

FString MakeJsonError(const FString& Message)
{
	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), false);
	Obj->SetStringField(TEXT("message"), Message);
	return SerializeJsonObj(Obj);
}

/**
 * Resolves the StateTree's editor data, or explains why it could not.
 *
 * UStateTree::EditorData is typed UObject, so the cast is not a formality — a
 * compiled-only or corrupt asset has it null or holding something else.
 */
UStateTreeEditorData* GetEditorData(UStateTree* StateTree, FString& OutError)
{
	if (!StateTree)
	{
		OutError = TEXT("StateTree is null.");
		return nullptr;
	}
	UStateTreeEditorData* EditorData = Cast<UStateTreeEditorData>(StateTree->EditorData);
	if (!EditorData)
	{
		OutError = FString::Printf(TEXT("StateTree has no editor data: %s. The asset may be "
		                                "compiled-only or corrupt."), *StateTree->GetPathName());
	}
	return EditorData;
}

/**
 * Builds a state's path the way state_tree_actions.py does: a leading slash, then every
 * ancestor name.
 *
 * UStateTreeState::GetPath() exists but renders "Root/Child" without the leading slash,
 * so a path taken from get_state_tree_structure would not round-trip through it.
 */
FString MakeStatePath(const UStateTreeState* State)
{
	TArray<const UStateTreeState*, TInlineAllocator<8>> Chain;
	for (const UStateTreeState* Current = State; Current; Current = Current->Parent)
	{
		Chain.Add(Current);
	}
	Algo::Reverse(Chain);

	FString Path;
	for (const UStateTreeState* Current : Chain)
	{
		Path += TEXT("/") + Current->Name.ToString();
	}
	return Path;
}

UStateTreeState* FindStateByPath(UStateTreeEditorData* EditorData, const FString& StatePath)
{
	UStateTreeState* Found = nullptr;

	TFunction<void(UStateTreeState*)> Visit = [&](UStateTreeState* State)
	{
		if (!State || Found)
		{
			return;
		}
		if (MakeStatePath(State) == StatePath)
		{
			Found = State;
			return;
		}
		for (UStateTreeState* Child : State->Children)
		{
			Visit(Child);
		}
	};

	for (UStateTreeState* Root : EditorData->SubTrees)
	{
		Visit(Root);
	}
	return Found;
}

void CollectStatePaths(UStateTreeEditorData* EditorData, TArray<FString>& OutPaths)
{
	TFunction<void(UStateTreeState*)> Visit = [&](UStateTreeState* State)
	{
		if (!State)
		{
			return;
		}
		OutPaths.Add(MakeStatePath(State));
		for (UStateTreeState* Child : State->Children)
		{
			Visit(Child);
		}
	};

	for (UStateTreeState* Root : EditorData->SubTrees)
	{
		Visit(Root);
	}
}

/** Adds the known state paths to an error payload, so a typo is self-correcting. */
FString MakeStateNotFoundError(UStateTreeEditorData* EditorData, const FString& StatePath)
{
	TArray<FString> Paths;
	CollectStatePaths(EditorData, Paths);

	TArray<TSharedPtr<FJsonValue>> Known;
	for (const FString& Path : Paths)
	{
		Known.Add(MakeShared<FJsonValueString>(Path));
	}

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), false);
	Obj->SetStringField(TEXT("message"), FString::Printf(TEXT("State not found: %s"), *StatePath));
	Obj->SetArrayField(TEXT("known_states"), Known);
	return SerializeJsonObj(Obj);
}

/** Name of a task/condition/evaluator, mirroring _node_name() on the Python side. */
FString NodeDisplayName(const FStateTreeEditorNode& Node)
{
	if (Node.InstanceObject)
	{
		return Node.InstanceObject->GetClass()->GetName();
	}
	if (const UScriptStruct* Struct = Node.Node.GetScriptStruct())
	{
		return Struct->GetName();
	}
	return TEXT("<empty>");
}

FString SeverityToString(const EMessageSeverity::Type Severity)
{
	switch (Severity)
	{
	case EMessageSeverity::Error:              return TEXT("error");
	case EMessageSeverity::PerformanceWarning: return TEXT("performance_warning");
	case EMessageSeverity::Warning:            return TEXT("warning");
	default:                                   return TEXT("info");
	}
}

bool ParseGuid(const FString& Text, FGuid& OutGuid, FString& OutError)
{
	if (!FGuid::Parse(Text, OutGuid))
	{
		OutError = FString::Printf(TEXT("Not a valid struct ID: '%s'. Take one from "
		                                "get_state_tree_bindable_structs."), *Text);
		return false;
	}
	return true;
}

/**
 * Builds a binding path from a struct ID and a property path string.
 *
 * This is what UStateTreeEditorData's string overload of AddPropertyBinding does with a
 * node, unpacked so the source can also be a context struct or a parameter — those have
 * struct IDs but are not FStateTreeEditorNodes, and binding to them is the common case.
 */
bool MakeBindingPath(const FString& StructId, const FString& PropertyPath,
                     FPropertyBindingPath& OutPath, FString& OutError)
{
	FGuid Guid;
	if (!ParseGuid(StructId, Guid, OutError))
	{
		return false;
	}
	OutPath.SetStructID(Guid);
	if (!PropertyPath.IsEmpty() && !OutPath.FromString(PropertyPath))
	{
		OutError = FString::Printf(TEXT("Could not parse property path: '%s'."), *PropertyPath);
		return false;
	}
	return true;
}

/** Records one node's ID against the state that owns it. */
void AddBindableNode(TArray<TSharedPtr<FJsonValue>>& Out, const FStateTreeEditorNode& Node,
                     const FString& Owner, const FString& Role)
{
	if (!Node.ID.IsValid())
	{
		return;
	}
	const TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
	Entry->SetStringField(TEXT("struct_id"), Node.ID.ToString(EGuidFormats::DigitsWithHyphens));
	Entry->SetStringField(TEXT("name"), NodeDisplayName(Node));
	Entry->SetStringField(TEXT("owner"), Owner);
	Entry->SetStringField(TEXT("role"), Role);
	Out.Add(MakeShared<FJsonValueObject>(Entry));
}

void AddBindableNodes(TArray<TSharedPtr<FJsonValue>>& Out, const TArray<FStateTreeEditorNode>& Nodes,
                      const FString& Owner, const FString& Role)
{
	for (const FStateTreeEditorNode& Node : Nodes)
	{
		AddBindableNode(Out, Node, Owner, Role);
	}
}

/** Marks the asset dirty so a later compile and save pick the change up. */
void MarkDirty(UStateTree* StateTree, UStateTreeEditorData* EditorData)
{
	StateTree->Modify();
	EditorData->Modify();
	UStateTreeEditingSubsystem::MarkAsModified(StateTree);
}
} // namespace

// ── Phase B: compile and validate ─────────────────────────────────────────────

FString UMCPythonStateTreeHelper::CompileStateTree(UStateTree* StateTree)
{
	FString Error;
	if (!GetEditorData(StateTree, Error))
	{
		return MakeJsonError(Error);
	}

	FStateTreeCompilerLog Log;
	const bool bCompiled = UStateTreeEditingSubsystem::CompileStateTree(StateTree, Log);

	// FStateTreeCompilerLog::Messages is protected, so the tokenized form is the only
	// public way to read what the compiler said.
	TArray<TSharedPtr<FJsonValue>> Messages;
	int32 ErrorCount = 0;
	int32 WarningCount = 0;
	for (const TSharedRef<FTokenizedMessage>& Message : Log.ToTokenizedMessages())
	{
		const EMessageSeverity::Type Severity = Message->GetSeverity();
		ErrorCount   += (Severity == EMessageSeverity::Error) ? 1 : 0;
		WarningCount += (Severity == EMessageSeverity::Warning
		                 || Severity == EMessageSeverity::PerformanceWarning) ? 1 : 0;

		const TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
		Entry->SetStringField(TEXT("severity"), SeverityToString(Severity));
		Entry->SetStringField(TEXT("message"), Message->ToText().ToString());
		Messages.Add(MakeShared<FJsonValueObject>(Entry));
	}

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), bCompiled);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetNumberField(TEXT("error_count"), ErrorCount);
	Obj->SetNumberField(TEXT("warning_count"), WarningCount);
	Obj->SetArrayField(TEXT("messages"), Messages);
	if (!bCompiled)
	{
		Obj->SetStringField(TEXT("message"), TEXT("Compilation failed; see messages."));
	}
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::ValidateStateTree(UStateTree* StateTree)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	// ValidateStateTree is the editor's "safety net": it applies schema restrictions and
	// fixes up state links and unused nodes. It writes, so the asset is dirtied here.
	StateTree->Modify();
	EditorData->Modify();
	UStateTreeEditingSubsystem::ValidateStateTree(StateTree);

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetBoolField(TEXT("needs_recompile"), UStateTreeEditingSubsystem::NeedsRecompile(StateTree));
	return SerializeJsonObj(Obj);
}

bool UMCPythonStateTreeHelper::StateTreeNeedsRecompile(UStateTree* StateTree)
{
	return StateTree ? UStateTreeEditingSubsystem::NeedsRecompile(StateTree) : false;
}

// ── Phase B: structure edits ──────────────────────────────────────────────────

FString UMCPythonStateTreeHelper::AddChildState(UStateTree* StateTree, const FString& ParentStatePath,
                                                FName StateName, const FString& StateType)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}
	if (StateName.IsNone())
	{
		return MakeJsonError(TEXT("StateName is required."));
	}

	const FString TypeName = StateType.IsEmpty() ? TEXT("State") : StateType;
	const int64 TypeValue = StaticEnum<EStateTreeStateType>()->GetValueByNameString(TypeName);
	if (TypeValue == INDEX_NONE)
	{
		return MakeJsonError(FString::Printf(
			TEXT("Unknown state type: '%s'. Expected State, Group, Linked or LinkedAsset."),
			*TypeName));
	}
	const EStateTreeStateType ResolvedType = static_cast<EStateTreeStateType>(TypeValue);

	MarkDirty(StateTree, EditorData);

	// An empty parent path means a new subtree root rather than a child of something.
	UStateTreeState* NewState = nullptr;
	if (ParentStatePath.IsEmpty())
	{
		NewState = &EditorData->AddSubTree(StateName, ResolvedType);
	}
	else
	{
		UStateTreeState* Parent = FindStateByPath(EditorData, ParentStatePath);
		if (!Parent)
		{
			return MakeStateNotFoundError(EditorData, ParentStatePath);
		}
		Parent->Modify();
		NewState = &Parent->AddChildState(StateName, ResolvedType);
	}

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("state_path"), MakeStatePath(NewState));
	Obj->SetStringField(TEXT("name"), NewState->Name.ToString());
	Obj->SetStringField(TEXT("type"), TypeName);
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::RemoveState(UStateTree* StateTree, const FString& StatePath)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}
	if (StatePath.IsEmpty())
	{
		return MakeJsonError(TEXT("StatePath is required."));
	}

	UStateTreeState* State = FindStateByPath(EditorData, StatePath);
	if (!State)
	{
		return MakeStateNotFoundError(EditorData, StatePath);
	}

	// Count before unlinking: the subtree is unreachable once it is detached.
	int32 RemovedCount = 0;
	TFunction<void(const UStateTreeState*)> Count = [&](const UStateTreeState* Current)
	{
		++RemovedCount;
		for (const UStateTreeState* Child : Current->Children)
		{
			if (Child)
			{
				Count(Child);
			}
		}
	};
	Count(State);

	MarkDirty(StateTree, EditorData);

	if (UStateTreeState* Parent = State->Parent)
	{
		Parent->Modify();
		Parent->Children.Remove(State);
	}
	else
	{
		EditorData->SubTrees.Remove(State);
	}
	State->Parent = nullptr;

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("state_path"), StatePath);
	Obj->SetNumberField(TEXT("removed_state_count"), RemovedCount);
	return SerializeJsonObj(Obj);
}

// ── Phase C: property bindings ────────────────────────────────────────────────

FString UMCPythonStateTreeHelper::GetStateTreeBindableStructs(UStateTree* StateTree,
                                                              const FString& TargetStructId)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	TArray<TSharedPtr<FJsonValue>> Structs;

	if (TargetStructId.IsEmpty())
	{
		// No target given: enumerate the tree's own nodes. These IDs exist nowhere in the
		// read domain, and a binding cannot be authored without them.
		AddBindableNodes(Structs, EditorData->Evaluators, TEXT("<global>"), TEXT("evaluator"));
		AddBindableNodes(Structs, EditorData->GlobalTasks, TEXT("<global>"), TEXT("global_task"));

		TFunction<void(UStateTreeState*)> Visit = [&](UStateTreeState* State)
		{
			if (!State)
			{
				return;
			}
			const FString Path = MakeStatePath(State);
			AddBindableNodes(Structs, State->Tasks, Path, TEXT("task"));
			AddBindableNodes(Structs, State->EnterConditions, Path, TEXT("enter_condition"));
			AddBindableNodes(Structs, State->Considerations, Path, TEXT("consideration"));
			AddBindableNode(Structs, State->SingleTask, Path, TEXT("single_task"));
			for (UStateTreeState* Child : State->Children)
			{
				Visit(Child);
			}
		};
		for (UStateTreeState* Root : EditorData->SubTrees)
		{
			Visit(Root);
		}
	}
	else
	{
		FGuid TargetGuid;
		if (!ParseGuid(TargetStructId, TargetGuid, Error))
		{
			return MakeJsonError(Error);
		}

		// With a target, the schema decides what may be bound into it — which is a
		// different and usually much shorter list than every node in the tree.
		TArray<TInstancedStruct<FPropertyBindingBindableStructDescriptor>> Descs;
		EditorData->GetBindableStructs(TargetGuid, Descs);
		for (const TInstancedStruct<FPropertyBindingBindableStructDescriptor>& Desc : Descs)
		{
			const FPropertyBindingBindableStructDescriptor* Ptr = Desc.GetPtr();
			if (!Ptr)
			{
				continue;
			}
			const TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
			Entry->SetStringField(TEXT("struct_id"), Ptr->ID.ToString(EGuidFormats::DigitsWithHyphens));
			Entry->SetStringField(TEXT("name"), Ptr->Name.ToString());
			Entry->SetStringField(TEXT("struct"), Ptr->Struct ? Ptr->Struct->GetName() : TEXT(""));
			Entry->SetStringField(TEXT("description"), Ptr->ToString());
			Structs.Add(MakeShared<FJsonValueObject>(Entry));
		}
	}

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("target_struct_id"), TargetStructId);
	Obj->SetNumberField(TEXT("count"), Structs.Num());
	Obj->SetArrayField(TEXT("structs"), Structs);
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::GetStateTreeBindings(UStateTree* StateTree)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	const FStateTreeEditorPropertyBindings* Bindings = EditorData->GetPropertyEditorBindings();
	if (!Bindings)
	{
		return MakeJsonError(TEXT("StateTree editor data exposes no property bindings."));
	}

	// Resolves a struct ID to something a human can act on. The descriptor lookup can
	// legitimately fail for a binding whose source node was deleted — those are exactly
	// the ones worth seeing, so an unresolved entry is reported rather than skipped.
	auto DescribePath = [EditorData](const FPropertyBindingPath& Path)
	{
		const TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
		Entry->SetStringField(TEXT("struct_id"), Path.GetStructID().ToString(EGuidFormats::DigitsWithHyphens));
		Entry->SetStringField(TEXT("path"), Path.ToString());

		TInstancedStruct<FPropertyBindingBindableStructDescriptor> Desc;
		if (EditorData->GetBindableStructByID(Path.GetStructID(), Desc) && Desc.GetPtr())
		{
			Entry->SetStringField(TEXT("name"), Desc.GetPtr()->Name.ToString());
			Entry->SetBoolField(TEXT("resolved"), true);
		}
		else
		{
			Entry->SetBoolField(TEXT("resolved"), false);
		}
		return Entry;
	};

	TArray<TSharedPtr<FJsonValue>> Out;
	int32 UnresolvedCount = 0;
	for (const FStateTreePropertyPathBinding& Binding : Bindings->GetBindings())
	{
		const TSharedRef<FJsonObject> Source = DescribePath(Binding.GetSourcePath());
		const TSharedRef<FJsonObject> Target = DescribePath(Binding.GetTargetPath());
		UnresolvedCount += (!Source->GetBoolField(TEXT("resolved"))
		                    || !Target->GetBoolField(TEXT("resolved"))) ? 1 : 0;

		const TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
		Entry->SetObjectField(TEXT("source"), Source);
		Entry->SetObjectField(TEXT("target"), Target);
		Out.Add(MakeShared<FJsonValueObject>(Entry));
	}

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetNumberField(TEXT("count"), Out.Num());
	Obj->SetNumberField(TEXT("unresolved_count"), UnresolvedCount);
	Obj->SetArrayField(TEXT("bindings"), Out);
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::AddStateTreeBinding(UStateTree* StateTree,
                                                      const FString& SourceStructId, const FString& SourcePath,
                                                      const FString& TargetStructId, const FString& TargetPath)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	FPropertyBindingPath Source;
	FPropertyBindingPath Target;
	if (!MakeBindingPath(SourceStructId, SourcePath, Source, Error)
		|| !MakeBindingPath(TargetStructId, TargetPath, Target, Error))
	{
		return MakeJsonError(Error);
	}

	MarkDirty(StateTree, EditorData);
	EditorData->AddPropertyBinding(Source, Target);

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("source"), Source.ToString());
	Obj->SetStringField(TEXT("target"), Target.ToString());
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::RemoveStateTreeBinding(UStateTree* StateTree,
                                                         const FString& TargetStructId, const FString& TargetPath)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	FPropertyBindingPath Target;
	if (!MakeBindingPath(TargetStructId, TargetPath, Target, Error))
	{
		return MakeJsonError(Error);
	}

	const FStateTreeEditorPropertyBindings* Bindings = EditorData->GetPropertyEditorBindings();
	const int32 CountBefore = Bindings ? Bindings->GetBindings().Num() : 0;

	MarkDirty(StateTree, EditorData);
	EditorData->RemovePropertyBinding(Target);

	const int32 CountAfter = Bindings ? Bindings->GetBindings().Num() : 0;

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("target"), Target.ToString());
	Obj->SetNumberField(TEXT("removed_count"), CountBefore - CountAfter);
	return SerializeJsonObj(Obj);
}
