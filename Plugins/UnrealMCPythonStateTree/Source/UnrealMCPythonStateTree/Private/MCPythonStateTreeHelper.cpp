// Copyright (c) 2025 GenOrca. All Rights Reserved.

#include "MCPythonStateTreeHelper.h"

#include "StateTree.h"
#include "StateTreeConditionBase.h"
#include "StateTreeConsiderationBase.h"
#include "StateTreeEditingSubsystem.h"
#include "StateTreeCompilerLog.h"
#include "StateTreeEditorData.h"
#include "StateTreeEditorNode.h"
#include "StateTreeEditorPropertyBindings.h"
#include "StateTreeEvaluatorBase.h"
#include "StateTreeState.h"
#include "StateTreeTaskBase.h"
#include "StateTreeTypes.h"

#include "UObject/UObjectIterator.h"

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

// ── node kinds ────────────────────────────────────────────────────────────────

/** Every slot a node can occupy, with the base struct that slot accepts. */
struct FNodeKindInfo
{
	const TCHAR* Kind;
	const UScriptStruct* Base;
	bool bGlobal;   // lives on the tree rather than on a state
	bool bSingle;   // one node, not an array
};

TArray<FNodeKindInfo> AllNodeKinds()
{
	return {
		{TEXT("task"),            FStateTreeTaskBase::StaticStruct(),          false, false},
		{TEXT("single_task"),     FStateTreeTaskBase::StaticStruct(),          false, true },
		{TEXT("enter_condition"), FStateTreeConditionBase::StaticStruct(),     false, false},
		{TEXT("consideration"),   FStateTreeConsiderationBase::StaticStruct(), false, false},
		{TEXT("evaluator"),       FStateTreeEvaluatorBase::StaticStruct(),     true,  false},
		{TEXT("global_task"),     FStateTreeTaskBase::StaticStruct(),          true,  false},
	};
}

const FNodeKindInfo* FindNodeKind(const FString& Kind)
{
	static const TArray<FNodeKindInfo> Kinds = AllNodeKinds();
	for (const FNodeKindInfo& Info : Kinds)
	{
		if (Kind.Equals(Info.Kind, ESearchCase::IgnoreCase))
		{
			return &Info;
		}
	}
	return nullptr;
}

/** Lists the valid kinds in the error, so a typo does not need a second round trip. */
FString MakeUnknownKindError(const FString& Kind)
{
	TArray<FString> Names;
	for (const FNodeKindInfo& Info : AllNodeKinds())
	{
		Names.Add(Info.Kind);
	}
	return MakeJsonError(FString::Printf(TEXT("Unknown node kind: '%s'. Expected one of: %s."),
	                                     *Kind, *FString::Join(Names, TEXT(", "))));
}

/**
 * Resolves a node struct by reflection name.
 *
 * By name and not by type on purpose: the types worth adding (FStateTreeDelayTask,
 * FStateTreeDebugTextTask) live in StateTreeModule/Private, so no header can name
 * them here — but they are registered UScriptStructs, and reflection reaches them.
 * Accepts both "StateTreeDelayTask" and "FStateTreeDelayTask".
 */
const UScriptStruct* FindNodeStruct(const FString& NodeStruct)
{
	if (const UScriptStruct* Found = FindFirstObject<UScriptStruct>(*NodeStruct, EFindFirstObjectOptions::None))
	{
		return Found;
	}
	if (NodeStruct.StartsWith(TEXT("F")))
	{
		return FindFirstObject<UScriptStruct>(*NodeStruct.RightChop(1), EFindFirstObjectOptions::None);
	}
	return nullptr;
}

/**
 * The array a kind maps to, or null for single_task (which is one node, not an array).
 *
 * State is null for the global kinds, which live on the editor data instead.
 */
TArray<FStateTreeEditorNode>* ResolveNodeArray(UStateTreeEditorData* EditorData, UStateTreeState* State,
                                               const FNodeKindInfo& Info)
{
	if (Info.bSingle)
	{
		return nullptr;
	}
	if (Info.bGlobal)
	{
		return FCString::Stricmp(Info.Kind, TEXT("evaluator")) == 0
			? &EditorData->Evaluators
			: &EditorData->GlobalTasks;
	}
	if (FCString::Stricmp(Info.Kind, TEXT("task")) == 0)
	{
		return &State->Tasks;
	}
	if (FCString::Stricmp(Info.Kind, TEXT("enter_condition")) == 0)
	{
		return &State->EnterConditions;
	}
	return &State->Considerations;
}

/** DisplayName metadata when the struct carries one, otherwise the reflection name. */
FString NodeTypeDisplayName(const UScriptStruct* Struct)
{
#if WITH_EDITORONLY_DATA
	const FString Meta = Struct->GetMetaData(TEXT("DisplayName"));
	if (!Meta.IsEmpty())
	{
		return Meta;
	}
#endif
	return Struct->GetName();
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

// ── Phase B: node edits ───────────────────────────────────────────────────────

FString UMCPythonStateTreeHelper::ListStateTreeNodeTypes(const FString& NodeKind)
{
	TArray<FNodeKindInfo> Kinds;
	if (NodeKind.IsEmpty())
	{
		Kinds = AllNodeKinds();
	}
	else
	{
		const FNodeKindInfo* Info = FindNodeKind(NodeKind);
		if (!Info)
		{
			return MakeUnknownKindError(NodeKind);
		}
		Kinds.Add(*Info);
	}

	// A kind's base struct can repeat (task, single_task and global_task all take
	// FStateTreeTaskBase), so gather per base once and report the kinds that share it.
	TArray<TSharedPtr<FJsonValue>> Types;
	TSet<const UScriptStruct*> Seen;
	for (const FNodeKindInfo& Info : Kinds)
	{
		if (Seen.Contains(Info.Base))
		{
			continue;
		}
		Seen.Add(Info.Base);

		for (TObjectIterator<UScriptStruct> It; It; ++It)
		{
			UScriptStruct* Struct = *It;
			if (Struct == Info.Base || !Struct->IsChildOf(Info.Base))
			{
				continue;
			}
			// The *Base and *CommonBase layers are real structs but exist to be derived
			// from, never instantiated. Nothing marks that in reflection, so go by name.
			if (Struct->GetName().EndsWith(TEXT("Base")))
			{
				continue;
			}

			const TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
			Entry->SetStringField(TEXT("struct"), Struct->GetName());
			Entry->SetStringField(TEXT("display_name"), NodeTypeDisplayName(Struct));
			Entry->SetStringField(TEXT("base"), Info.Base->GetName());
			Types.Add(MakeShared<FJsonValueObject>(Entry));
		}
	}

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("node_kind"), NodeKind);
	Obj->SetNumberField(TEXT("count"), Types.Num());
	Obj->SetArrayField(TEXT("node_types"), Types);
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::AddStateTreeNode(UStateTree* StateTree, const FString& StatePath,
                                                   const FString& NodeKind, const FString& NodeStruct)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	const FNodeKindInfo* Info = FindNodeKind(NodeKind);
	if (!Info)
	{
		return MakeUnknownKindError(NodeKind);
	}
	if (NodeStruct.IsEmpty())
	{
		return MakeJsonError(TEXT("NodeStruct is required. Take one from list_state_tree_node_types."));
	}

	const UScriptStruct* Struct = FindNodeStruct(NodeStruct);
	if (!Struct)
	{
		return MakeJsonError(FString::Printf(
			TEXT("Unknown node struct: '%s'. Take one from list_state_tree_node_types."), *NodeStruct));
	}
	if (!Struct->IsChildOf(Info->Base))
	{
		return MakeJsonError(FString::Printf(
			TEXT("'%s' is not a %s, so it cannot be added as a '%s'."),
			*Struct->GetName(), *Info->Base->GetName(), Info->Kind));
	}

	// The global kinds hang off the editor data, so they take no state.
	UStateTreeState* State = nullptr;
	if (!Info->bGlobal)
	{
		State = FindStateByPath(EditorData, StatePath);
		if (!State)
		{
			return MakeStateNotFoundError(EditorData, StatePath);
		}
	}

	MarkDirty(StateTree, EditorData);
	if (State)
	{
		State->Modify();
	}

	// InitializeAs outers the node's instance data to the editor data, which is what the
	// StateTree editor itself does — anything else and the instance data serialises into
	// the wrong package.
	FStateTreeEditorNode* Node = nullptr;
	bool bReplaced = false;
	if (Info->bSingle)
	{
		bReplaced = State->SingleTask.Node.IsValid();
		Node = &State->SingleTask;
	}
	else
	{
		TArray<FStateTreeEditorNode>* Nodes = ResolveNodeArray(EditorData, State, *Info);
		Node = &Nodes->AddDefaulted_GetRef();
	}
	Node->InitializeAs(EditorData, Struct);

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("state_path"), State ? MakeStatePath(State) : TEXT("<global>"));
	Obj->SetStringField(TEXT("node_kind"), Info->Kind);
	Obj->SetStringField(TEXT("node_struct"), Struct->GetName());
	Obj->SetStringField(TEXT("struct_id"), Node->ID.ToString(EGuidFormats::DigitsWithHyphens));
	Obj->SetBoolField(TEXT("replaced_existing"), bReplaced);
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::RemoveStateTreeNode(UStateTree* StateTree, const FString& StatePath,
                                                      const FString& NodeKind, const FString& StructId)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	const FNodeKindInfo* Info = FindNodeKind(NodeKind);
	if (!Info)
	{
		return MakeUnknownKindError(NodeKind);
	}

	FGuid Guid;
	if (!ParseGuid(StructId, Guid, Error))
	{
		return MakeJsonError(Error);
	}

	UStateTreeState* State = nullptr;
	if (!Info->bGlobal)
	{
		State = FindStateByPath(EditorData, StatePath);
		if (!State)
		{
			return MakeStateNotFoundError(EditorData, StatePath);
		}
	}

	MarkDirty(StateTree, EditorData);
	if (State)
	{
		State->Modify();
	}

	int32 RemovedCount = 0;
	if (Info->bSingle)
	{
		if (State->SingleTask.ID == Guid)
		{
			State->SingleTask.Reset();
			RemovedCount = 1;
		}
	}
	else
	{
		TArray<FStateTreeEditorNode>* Nodes = ResolveNodeArray(EditorData, State, *Info);
		RemovedCount = Nodes->RemoveAll([&Guid](const FStateTreeEditorNode& Node)
		{
			return Node.ID == Guid;
		});
	}

	// Nothing removed is a failure, not a silent no-op: the caller passed an ID that is
	// not in that slot, and reporting success would hide the mistake.
	if (RemovedCount == 0)
	{
		return MakeJsonError(FString::Printf(
			TEXT("No '%s' node with ID %s. Take one from get_state_tree_bindable_structs."),
			Info->Kind, *StructId));
	}

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("state_path"), State ? MakeStatePath(State) : TEXT("<global>"));
	Obj->SetStringField(TEXT("node_kind"), Info->Kind);
	Obj->SetNumberField(TEXT("removed_count"), RemovedCount);
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

// ── transitions ───────────────────────────────────────────────────────────────

namespace
{

/** Resolves an enum entry by name, accepting both the bare and the fully qualified form. */
template <typename TEnum>
bool ResolveEnum(const FString& Name, TEnum& OutValue, FString& OutError)
{
	const UEnum* Enum = StaticEnum<TEnum>();
	int64 Value = Enum->GetValueByNameString(Name);
	if (Value == INDEX_NONE)
	{
		// GetValueByNameString misses the short form on namespaced enums.
		Value = Enum->GetValueByNameString(FString::Printf(TEXT("%s::%s"), *Enum->GetName(), *Name));
	}
	if (Value == INDEX_NONE)
	{
		TArray<FString> Accepted;
		for (int32 i = 0; i < Enum->NumEnums() - 1; ++i)
		{
			if (!Enum->HasMetaData(TEXT("Hidden"), i))
			{
				Accepted.Add(Enum->GetNameStringByIndex(i));
			}
		}
		OutError = FString::Printf(TEXT("Unknown %s: '%s'. Expected one of: %s."),
			*Enum->GetName(), *Name, *FString::Join(Accepted, TEXT(", ")));
		return false;
	}
	OutValue = static_cast<TEnum>(Value);
	return true;
}

/** One transition as JSON. Index is the caller's handle for removal. */
TSharedRef<FJsonObject> TransitionToJson(const FStateTreeTransition& Transition, const int32 Index)
{
	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetNumberField(TEXT("index"), Index);
	Obj->SetStringField(TEXT("id"), Transition.ID.ToString());
	Obj->SetStringField(TEXT("trigger"),
		StaticEnum<EStateTreeTransitionTrigger>()->GetNameStringByValue(static_cast<int64>(Transition.Trigger)));
	Obj->SetStringField(TEXT("transition_type"),
		StaticEnum<EStateTreeTransitionType>()->GetNameStringByValue(static_cast<int64>(Transition.State.LinkType)));
	Obj->SetStringField(TEXT("target_state"), Transition.State.Name.ToString());
	Obj->SetStringField(TEXT("priority"),
		StaticEnum<EStateTreeTransitionPriority>()->GetNameStringByValue(static_cast<int64>(Transition.Priority)));
	Obj->SetBoolField(TEXT("delay_transition"), Transition.bDelayTransition);
	Obj->SetNumberField(TEXT("delay_duration"), Transition.DelayDuration);
	Obj->SetNumberField(TEXT("condition_count"), Transition.Conditions.Num());
	Obj->SetBoolField(TEXT("enabled"), Transition.bTransitionEnabled);
	return Obj;
}

} // namespace

FString UMCPythonStateTreeHelper::GetStateTreeTransitions(UStateTree* StateTree, const FString& StatePath)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	UStateTreeState* State = FindStateByPath(EditorData, StatePath);
	if (!State)
	{
		return MakeStateNotFoundError(EditorData, StatePath);
	}

	TArray<TSharedPtr<FJsonValue>> Items;
	for (int32 i = 0; i < State->Transitions.Num(); ++i)
	{
		Items.Add(MakeShared<FJsonValueObject>(TransitionToJson(State->Transitions[i], i)));
	}

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("state_path"), MakeStatePath(State));
	Obj->SetArrayField(TEXT("transitions"), Items);
	Obj->SetNumberField(TEXT("count"), Items.Num());
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::AddStateTreeTransition(UStateTree* StateTree, const FString& StatePath,
                                                         const FString& Trigger, const FString& TransitionType,
                                                         const FString& TargetStatePath, const FString& Priority,
                                                         float DelayDuration)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	UStateTreeState* State = FindStateByPath(EditorData, StatePath);
	if (!State)
	{
		return MakeStateNotFoundError(EditorData, StatePath);
	}

	EStateTreeTransitionTrigger ResolvedTrigger = EStateTreeTransitionTrigger::OnStateCompleted;
	if (!Trigger.IsEmpty() && !ResolveEnum(Trigger, ResolvedTrigger, Error))
	{
		return MakeJsonError(Error);
	}

	EStateTreeTransitionType ResolvedType = EStateTreeTransitionType::GotoState;
	if (!TransitionType.IsEmpty() && !ResolveEnum(TransitionType, ResolvedType, Error))
	{
		return MakeJsonError(Error);
	}

	EStateTreeTransitionPriority ResolvedPriority = EStateTreeTransitionPriority::Normal;
	if (!Priority.IsEmpty() && !ResolveEnum(Priority, ResolvedPriority, Error))
	{
		return MakeJsonError(Error);
	}

	// Only GotoState carries a target; the others resolve relative to the tree,
	// so a target path there would silently do nothing.
	UStateTreeState* TargetState = nullptr;
	if (ResolvedType == EStateTreeTransitionType::GotoState)
	{
		if (TargetStatePath.IsEmpty())
		{
			return MakeJsonError(TEXT("TargetStatePath is required when TransitionType is GotoState."));
		}
		TargetState = FindStateByPath(EditorData, TargetStatePath);
		if (!TargetState)
		{
			return MakeStateNotFoundError(EditorData, TargetStatePath);
		}
	}
	else if (!TargetStatePath.IsEmpty())
	{
		return MakeJsonError(FString::Printf(
			TEXT("TargetStatePath is only meaningful for GotoState, not '%s'."),
			*StaticEnum<EStateTreeTransitionType>()->GetNameStringByValue(static_cast<int64>(ResolvedType))));
	}

	MarkDirty(StateTree, EditorData);
	State->Modify();

	FStateTreeTransition& NewTransition = State->Transitions.AddDefaulted_GetRef();
	NewTransition.Trigger = ResolvedTrigger;
	NewTransition.State = FStateTreeStateLink(ResolvedType);
	if (TargetState)
	{
		NewTransition.State.Name = TargetState->Name;
		NewTransition.State.ID = TargetState->ID;
	}
	NewTransition.Priority = ResolvedPriority;
	NewTransition.ID = FGuid::NewGuid();
	if (DelayDuration > 0.0f)
	{
		NewTransition.bDelayTransition = true;
		NewTransition.DelayDuration = DelayDuration;
	}

	const int32 Index = State->Transitions.Num() - 1;
	const TSharedRef<FJsonObject> Obj = TransitionToJson(NewTransition, Index);
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("state_path"), MakeStatePath(State));
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::RemoveStateTreeTransition(UStateTree* StateTree, const FString& StatePath,
                                                            int32 Index)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	UStateTreeState* State = FindStateByPath(EditorData, StatePath);
	if (!State)
	{
		return MakeStateNotFoundError(EditorData, StatePath);
	}

	if (!State->Transitions.IsValidIndex(Index))
	{
		return MakeJsonError(FString::Printf(
			TEXT("Transition index %d is out of range; state '%s' has %d transition(s)."),
			Index, *StatePath, State->Transitions.Num()));
	}

	MarkDirty(StateTree, EditorData);
	State->Modify();
	State->Transitions.RemoveAt(Index);

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("state_path"), MakeStatePath(State));
	Obj->SetNumberField(TEXT("removed_index"), Index);
	Obj->SetNumberField(TEXT("count"), State->Transitions.Num());
	return SerializeJsonObj(Obj);
}

FString UMCPythonStateTreeHelper::SetStateSelectionBehavior(UStateTree* StateTree, const FString& StatePath,
                                                            const FString& Behavior)
{
	FString Error;
	UStateTreeEditorData* EditorData = GetEditorData(StateTree, Error);
	if (!EditorData)
	{
		return MakeJsonError(Error);
	}

	UStateTreeState* State = FindStateByPath(EditorData, StatePath);
	if (!State)
	{
		return MakeStateNotFoundError(EditorData, StatePath);
	}

	EStateTreeStateSelectionBehavior Resolved = EStateTreeStateSelectionBehavior::TrySelectChildrenInOrder;
	if (!ResolveEnum(Behavior, Resolved, Error))
	{
		return MakeJsonError(Error);
	}

	const FString Previous =
		StaticEnum<EStateTreeStateSelectionBehavior>()->GetNameStringByValue(static_cast<int64>(State->SelectionBehavior));

	MarkDirty(StateTree, EditorData);
	State->Modify();
	State->SelectionBehavior = Resolved;

	const TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("success"), true);
	Obj->SetStringField(TEXT("asset_path"), StateTree->GetPathName());
	Obj->SetStringField(TEXT("state_path"), MakeStatePath(State));
	Obj->SetStringField(TEXT("previous_behavior"), Previous);
	Obj->SetStringField(TEXT("selection_behavior"),
		StaticEnum<EStateTreeStateSelectionBehavior>()->GetNameStringByValue(static_cast<int64>(Resolved)));
	return SerializeJsonObj(Obj);
}
