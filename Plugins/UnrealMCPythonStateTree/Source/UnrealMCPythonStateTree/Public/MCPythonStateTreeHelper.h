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
};
