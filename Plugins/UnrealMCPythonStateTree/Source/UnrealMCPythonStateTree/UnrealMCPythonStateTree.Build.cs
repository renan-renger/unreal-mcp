// Copyright (c) 2025 GenOrca. All Rights Reserved.

using UnrealBuildTool;

public class UnrealMCPythonStateTree : ModuleRules
{
	public UnrealMCPythonStateTree(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		// StateTreeEditorModule is UncookedOnly. This module is Editor, which is a
		// subset of that, so the link is safe. It is also why the dependency lives in
		// a separate plugin rather than in UnrealMCPython: a hard dependency there
		// would force StateTree on every consumer project and take the whole MCP
		// server down whenever StateTree is disabled.
		PublicDependencyModuleNames.AddRange(
			new string[]
			{
				"Core",
				"CoreUObject",
				"Engine",
				"Json",
				"StateTreeModule",
				"StateTreeEditorModule",
			}
			);

		PrivateDependencyModuleNames.AddRange(
			new string[]
			{
				"UnrealEd",
				"EditorSubsystem",
				// StateTreeEditingSubsystem.h pulls in StateTreeViewModel.h, which is
				// Slate-facing even though nothing here touches a widget.
				"Slate",
				"SlateCore",
				"GameplayTags",
				"PropertyBindingUtils",
			}
			);
	}
}
