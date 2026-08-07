// Copyright (c) 2025 GenOrca. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MCPythonStateTreeHelper.generated.h"

class UStateTree;

/**
 * StateTree authoring entry points for the Python action layer.
 *
 * Everything here needs C++ because the StateTree editor API is not script-exposed:
 * UStateTreeEditingSubsystem is UCLASS(MinimalAPI) whose methods are plain statics,
 * UStateTreeState::Children is BlueprintReadOnly with no Edit flag so Python cannot
 * append to it, and UStateTreeEditorData::EditorBindings is a bare UPROPERTY().
 *
 * State paths use the same "/Root/Child" convention that state_tree_actions.py
 * produces for reads, so a path from get_state_tree_structure can be fed straight
 * back in here.
 *
 * Mutating functions mark the package dirty and stop there. Saving is the caller's
 * decision, so a failed authoring step never leaves a half-written asset on disk.
 */
UCLASS()
class UNREALMCPYTHONSTATETREE_API UMCPythonStateTreeHelper : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	// ── Phase B: compile and validate ─────────────────────────────────────────

	/** Compiles the tree and returns the compiler log as JSON. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString CompileStateTree(UStateTree* StateTree);

	/** Applies schema restrictions and fixes up editor data. Mutates the asset. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString ValidateStateTree(UStateTree* StateTree);

	/** True when the editor data has changed since the last compile. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static bool StateTreeNeedsRecompile(UStateTree* StateTree);

	// ── Phase B: structure edits ──────────────────────────────────────────────

	/** Adds a child state under ParentStatePath, or a new subtree when it is empty. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString AddChildState(UStateTree* StateTree, const FString& ParentStatePath,
	                             FName StateName, const FString& StateType);

	/** Removes a state and everything under it. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString RemoveState(UStateTree* StateTree, const FString& StatePath);

	// ── Phase B: node edits ───────────────────────────────────────────────────
	//
	// NodeKind names the slot a node goes into, using the same vocabulary the
	// "role" field of GetStateTreeBindableStructs reports: task, single_task,
	// enter_condition and consideration live on a state; evaluator and
	// global_task live on the tree and take an empty StatePath.

	/**
	 * Lists the node types available for a NodeKind, by script struct name.
	 *
	 * Discovery matters here because the useful types are not reachable any other
	 * way: FStateTreeDelayTask and friends live in StateTreeModule/Private, so no
	 * header names them, yet they are registered UScriptStructs and bind fine.
	 * An empty NodeKind lists every kind.
	 */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString ListStateTreeNodeTypes(const FString& NodeKind);

	/**
	 * Adds a task, condition, consideration or evaluator and returns its struct ID.
	 *
	 * This is what makes bindings authorable at all: a binding needs a node to bind
	 * into, and until this existed a tree built through the MCP surface had none.
	 *
	 * Global tasks run for the tree's whole lifetime — one that ever calls
	 * FinishTask terminates the tree instead of the state. Put one-shot tasks in a
	 * state's Tasks, not in GlobalTasks.
	 */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString AddStateTreeNode(UStateTree* StateTree, const FString& StatePath,
	                                const FString& NodeKind, const FString& NodeStruct);

	/** Removes the node with StructId from the slot NodeKind names. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString RemoveStateTreeNode(UStateTree* StateTree, const FString& StatePath,
	                                   const FString& NodeKind, const FString& StructId);

	// ── Phase C: property bindings ────────────────────────────────────────────

	/**
	 * Lists the struct IDs a binding can refer to.
	 *
	 * With an empty TargetStructId, walks the tree and returns every node ID with the
	 * state that owns it — a binding cannot be authored without those IDs, and nothing
	 * else surfaces them. With one set, returns what the schema allows binding *into*
	 * that node instead.
	 */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString GetStateTreeBindableStructs(UStateTree* StateTree, const FString& TargetStructId);

	/** Lists the tree's existing property bindings. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString GetStateTreeBindings(UStateTree* StateTree);

	/** Binds SourcePath to TargetPath. Struct IDs come from GetStateTreeBindableStructs. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString AddStateTreeBinding(UStateTree* StateTree,
	                                   const FString& SourceStructId, const FString& SourcePath,
	                                   const FString& TargetStructId, const FString& TargetPath);

	/** Removes whatever is bound into TargetPath. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString RemoveStateTreeBinding(UStateTree* StateTree,
	                                      const FString& TargetStructId, const FString& TargetPath);

	// --- Transitions -------------------------------------------------------
	// UStateTreeState::Transitions is BlueprintReadOnly, so Python can read the
	// array but cannot append to it. Selection behaviour is worse: the property
	// carries no Blueprint flag at all and is invisible to script.

	/** Lists a state's transitions, structured rather than as a raw export string. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString GetStateTreeTransitions(UStateTree* StateTree, const FString& StatePath);

	/**
	 * Appends a transition to a state and returns its index.
	 *
	 * Trigger is an EStateTreeTransitionTrigger name (OnStateCompleted,
	 * OnStateSucceeded, OnStateFailed, OnTick, OnEvent, OnDelegate).
	 * TransitionType is an EStateTreeTransitionType name; GotoState is the only
	 * one that reads TargetStatePath, the rest resolve on their own.
	 * Priority is an EStateTreeTransitionPriority name and defaults to Normal.
	 */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString AddStateTreeTransition(UStateTree* StateTree, const FString& StatePath,
	                                      const FString& Trigger, const FString& TransitionType,
	                                      const FString& TargetStatePath, const FString& Priority,
	                                      float DelayDuration);

	/** Removes the transition at Index from a state. */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString RemoveStateTreeTransition(UStateTree* StateTree, const FString& StatePath,
	                                         int32 Index);

	/**
	 * Sets how a state treats its children when selected.
	 *
	 * Behaviour is an EStateTreeStateSelectionBehavior name — None, TryEnterState,
	 * TrySelectChildrenInOrder, TrySelectChildrenAtRandom,
	 * TrySelectChildrenWithHighestUtility,
	 * TrySelectChildrenAtRandomWeightedByUtility or TryFollowTransitions.
	 */
	UFUNCTION(BlueprintCallable, Category="Editor|MCPython")
	static FString SetStateSelectionBehavior(UStateTree* StateTree, const FString& StatePath,
	                                         const FString& Behavior);
};
