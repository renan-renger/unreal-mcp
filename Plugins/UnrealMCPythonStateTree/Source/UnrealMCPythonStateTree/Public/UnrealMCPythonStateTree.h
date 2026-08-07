// Copyright (c) 2025 GenOrca. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

/**
 * Carries UMCPythonStateTreeHelper and nothing else.
 *
 * The module has no startup work: the helper is a UObject of static UFUNCTIONs that
 * Python reaches through reflection, so merely being loaded is enough.
 */
class FUnrealMCPythonStateTreeModule : public IModuleInterface
{
};
