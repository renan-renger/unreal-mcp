// Copyright (c) 2025 GenOrca (by zenoengine). All Rights Reserved.
// UMG Widget Blueprint authoring — split out of MCPythonHelper.cpp.

#include "MCPythonHelper.h"
#include "MCPythonHelperInternal.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "WidgetBlueprint.h"
#include "UObject/Package.h"          // GetTransientPackage, for banishing removed widgets
#include "Blueprint/WidgetTree.h"
#include "Components/Widget.h"
#include "Components/PanelWidget.h"
#include "Editor.h"
#include "Subsystems/AssetEditorSubsystem.h"
#include "Toolkits/AssetEditorToolkit.h"
#include "BlueprintEditor.h"
#include "BehaviorTree/BehaviorTree.h"
#include "BehaviorTree/BlackboardData.h"
#include "BehaviorTree/BTCompositeNode.h"
#include "BehaviorTree/BTTaskNode.h"
#include "BehaviorTree/BTDecorator.h"
#include "BehaviorTree/BTService.h"
#include "BehaviorTreeEditor.h"
#include "BehaviorTreeGraphNode.h"
#include "BehaviorTreeGraph.h"
#include "BehaviorTreeGraphNode_Root.h"
#include "BehaviorTreeGraphNode_Composite.h"
#include "BehaviorTreeGraphNode_Task.h"
#include "BehaviorTreeGraphNode_Decorator.h"
#include "BehaviorTreeGraphNode_Service.h"
#include "BehaviorTreeGraphNode_SimpleParallel.h"
#include "BehaviorTreeGraphNode_SubtreeTask.h"
#include "EdGraphSchema_BehaviorTree.h"
#include "EdGraph/EdGraph.h"
#include "UObject/UObjectIterator.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/SkeletalMeshSocket.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonReader.h"
// Blueprint graph includes
#include "K2Node_Event.h"
#include "K2Node_ComponentBoundEvent.h"
#include "K2Node_CustomEvent.h"
#include "K2Node_CallFunction.h"
#include "K2Node_IfThenElse.h"
#include "K2Node_ExecutionSequence.h"
#include "K2Node_VariableGet.h"
#include "K2Node_VariableSet.h"
#include "K2Node_MacroInstance.h"
#include "K2Node_DynamicCast.h"
#include "K2Node_InputKey.h"
#include "K2Node_SpawnActorFromClass.h"
#include "EdGraphSchema_K2.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Engine/Blueprint.h"
#include "UObject/UnrealType.h"
#include "UObject/TextProperty.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/TextBlock.h"
// AnimGraph authoring (editor-only AnimGraph module)
#include "Animation/AnimBlueprint.h"
#include "Animation/AnimSequence.h"
#include "AnimGraphNode_StateMachine.h"
#include "AnimGraphNode_SequencePlayer.h"
#include "AnimGraphNode_Root.h"
#include "AnimGraphNode_StateResult.h"
#include "AnimGraphNode_TransitionResult.h"
#include "AnimStateNode.h"
#include "AnimStateTransitionNode.h"
#include "AnimStateEntryNode.h"
#include "AnimationStateMachineGraph.h"
#include "Kismet/KismetMathLibrary.h"
// Editor viewport projection
#include "LevelEditorViewport.h"
#include "EditorViewportClient.h"
#include "SceneView.h"

// ─── UMG Widget Blueprint Helpers ─────────────────────────────────────────────

namespace
{
    static UClass* FindUMGWidgetClass(const FString& TypeName)
    {
        static const TMap<FString, FString> TypeMap = {
            {TEXT("CanvasPanel"),      TEXT("/Script/UMG.CanvasPanel")},
            {TEXT("TextBlock"),        TEXT("/Script/UMG.TextBlock")},
            {TEXT("Button"),           TEXT("/Script/UMG.Button")},
            {TEXT("Image"),            TEXT("/Script/UMG.Image")},
            {TEXT("HorizontalBox"),    TEXT("/Script/UMG.HorizontalBox")},
            {TEXT("VerticalBox"),      TEXT("/Script/UMG.VerticalBox")},
            {TEXT("Border"),           TEXT("/Script/UMG.Border")},
            {TEXT("Overlay"),          TEXT("/Script/UMG.Overlay")},
            {TEXT("ScrollBox"),        TEXT("/Script/UMG.ScrollBox")},
            {TEXT("SizeBox"),          TEXT("/Script/UMG.SizeBox")},
            {TEXT("CheckBox"),         TEXT("/Script/UMG.CheckBox")},
            {TEXT("EditableText"),     TEXT("/Script/UMG.EditableText")},
            {TEXT("EditableTextBox"),  TEXT("/Script/UMG.EditableTextBox")},
            {TEXT("ProgressBar"),      TEXT("/Script/UMG.ProgressBar")},
            {TEXT("Slider"),           TEXT("/Script/UMG.Slider")},
        };
        if (const FString* Path = TypeMap.Find(TypeName))
        {
            return LoadObject<UClass>(nullptr, **Path);
        }

        // The map above is a convenience list, not the set of widgets UMG can construct - it omits
        // ScaleBox, RichTextBlock, WrapBox, BackgroundBlur and every user widget (a project's own
        // WBC_Button_C and friends). Building a screen that matches the rest of a project's UI is
        // impossible without those, so fall through to a real class lookup.
        //
        // Order matters: an explicit object path first (so a caller can name a Blueprint widget
        // exactly), then the UMG script package, then a global search for anything else already
        // loaded - which is how user widgets resolve, since their generated class is UWidget-derived
        // but lives under /Game.
        UClass* Found = nullptr;

        if (TypeName.Contains(TEXT("/")))
        {
            // "/Game/Blueprints/Widgets/WBC_Button.WBC_Button_C" or a /Script/ path.
            Found = LoadObject<UClass>(nullptr, *TypeName);
        }

        if (!Found)
        {
            Found = LoadObject<UClass>(nullptr, *FString::Printf(TEXT("/Script/UMG.%s"), *TypeName));
        }

        if (!Found)
        {
            // Bare name, e.g. "WBC_Button_C". NativeFirst keeps an engine class winning over a
            // same-named asset, matching how the explicit map behaved.
            Found = FindFirstObject<UClass>(*TypeName, EFindFirstObjectOptions::NativeFirst);
        }

        // Guard the fallback: ConstructWidget<UWidget> would assert on a non-widget class, and an
        // abstract one cannot be instantiated at all. Returning null yields the caller's normal
        // "Unknown widget type" error instead of taking the editor down.
        if (Found && (!Found->IsChildOf(UWidget::StaticClass()) || Found->HasAnyClassFlags(CLASS_Abstract)))
        {
            Found = nullptr;
        }

        return Found;
    }

    // Move a widget and everything under it out of the widget blueprint, and report the names freed.
    //
    // Detaching is not enough. UBaseWidgetBlueprint::ForEachSourceWidgetImpl walks
    // ForEachObjectWithOuter(WidgetTree), not the parent/child links, so a widget stays a *source
    // widget* for as long as it is outered to the tree - unparented or not. The next compile therefore
    // finds it and re-adds any GUID we dropped, and the entry only turns stale after the asset is
    // saved and reloaded without the orphan, at which point every later compile reports
    //     Variable [X] was deleted but still has a GUID referenced by WidgetBlueprint [Y]
    // Re-outering to the transient package is what the widget editor itself does in
    // FWidgetBlueprintEditorUtils::DeleteWidgets, and it frees the name for a same-name replacement.
    //
    // Each descendant is outered to the tree in its own right, so the whole subtree has to be walked -
    // renaming the parent moves only the parent. Names are collected before the first rename, and
    // ForWidgetAndChildren visits descendants only, hence the explicit entry for the widget itself.
    static void BanishWidgetSubtree(UWidget* Widget, TArray<FName>& OutNames)
    {
        if (!Widget) return;

        TArray<UWidget*> Doomed;
        Doomed.Add(Widget);
        UWidgetTree::ForWidgetAndChildren(Widget, [&Doomed](UWidget* Descendant)
        {
            Doomed.Add(Descendant);
        });

        for (UWidget* Banished : Doomed)
        {
            OutNames.Add(Banished->GetFName());
            Banished->SetFlags(RF_Transactional);
            Banished->Modify();
            Banished->Rename(nullptr, GetTransientPackage());
        }
    }

    // Drop the variable GUID of every banished name no live widget answers to any more.
    //
    // The survivor check is not redundant: a replacement that reuses the outgoing widget's name keeps
    // the GUID, so anything referencing that variable externally still resolves. Same rule the widget
    // editor applies when a delete comes from a replace.
    static void PruneOrphanedVariableGuids(UWidgetBlueprint* WB, const TArray<FName>& Names)
    {
        if (!WB) return;

        const TArray<UWidget*> Live = WB->GetAllSourceWidgets();
        for (const FName& Name : Names)
        {
            const bool bStillLive = Live.ContainsByPredicate(
                [&Name](const UWidget* W) { return W && W->GetFName() == Name; });
            if (!bStillLive)
            {
                WB->OnVariableRemoved(Name);
            }
        }
    }

    static FString UmgErrorJson(const FString& Msg)
    {
        TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
        Obj->SetBoolField(TEXT("success"), false);
        Obj->SetStringField(TEXT("message"), Msg);
        return SerializeJsonObj(Obj);
    }
}

FString UMCPythonHelper::UmgGetWidgetInfo(UBlueprint* WidgetBP)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB) return UmgErrorJson(TEXT("Asset is not a WidgetBlueprint."));

    UWidgetTree* WT = WB->WidgetTree;
    if (!WT) return UmgErrorJson(TEXT("Widget tree is null."));

    TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("success"), true);

    if (WT->RootWidget)
        Root->SetStringField(TEXT("root_widget"), WT->RootWidget->GetName());
    else
        Root->SetField(TEXT("root_widget"), MakeShared<FJsonValueNull>());

    TArray<TSharedPtr<FJsonValue>> WidgetArr;
    WT->ForEachWidget([&](UWidget* W) {
        TSharedPtr<FJsonObject> WObj = MakeShared<FJsonObject>();
        WObj->SetStringField(TEXT("name"), W->GetName());
        WObj->SetStringField(TEXT("type"), W->GetClass()->GetName());
        if (UWidget* Parent = W->GetParent())
            WObj->SetStringField(TEXT("parent"), Parent->GetName());
        WidgetArr.Add(MakeShared<FJsonValueObject>(WObj));
    });

    Root->SetArrayField(TEXT("widgets"), WidgetArr);
    Root->SetNumberField(TEXT("widget_count"), WidgetArr.Num());

    // Names the blueprint tracks a variable GUID for. Not script-visible on UWidgetBlueprint, and
    // the only way to see whether add/remove kept the map in step with the tree - a name here with
    // no matching widget is what makes the widget compiler complain on every later compile.
    TArray<TSharedPtr<FJsonValue>> GuidNames;
    for (const TPair<FName, FGuid>& Entry : WB->WidgetVariableNameToGuidMap)
        GuidNames.Add(MakeShared<FJsonValueString>(Entry.Key.ToString()));
    Root->SetArrayField(TEXT("variable_guid_names"), GuidNames);

    return SerializeJsonObj(Root);
}

FString UMCPythonHelper::UmgAddWidget(UBlueprint* WidgetBP, const FString& WidgetType, const FString& WidgetName, const FString& ParentName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB) return UmgErrorJson(TEXT("Asset is not a WidgetBlueprint."));

    UWidgetTree* WT = WB->WidgetTree;
    if (!WT) return UmgErrorJson(TEXT("Widget tree is null."));

    UClass* WidgetClass = FindUMGWidgetClass(WidgetType);
    if (!WidgetClass)
        return UmgErrorJson(FString::Printf(TEXT("Unknown widget type '%s'."), *WidgetType));

    WT->Modify();
    UWidget* NewWidget = WT->ConstructWidget<UWidget>(WidgetClass, FName(*WidgetName));
    if (!NewWidget)
        return UmgErrorJson(FString::Printf(TEXT("Failed to construct widget '%s'."), *WidgetName));

    // Mark as variable so Blueprint graph can reference it directly
    NewWidget->bIsVariable = true;

    // Every widget outered to the tree needs a variable GUID, or the widget
    // compiler ensures ("was added but did not get a GUID") and patches one in.
    WB->OnVariableAdded(NewWidget->GetFName());

    FString ActualParent;
    bool bIsRoot = false;

    if (!ParentName.IsEmpty())
    {
        UWidget* ParentWidget = WT->FindWidget(FName(*ParentName));
        if (!ParentWidget)
            return UmgErrorJson(FString::Printf(TEXT("Parent widget '%s' not found."), *ParentName));

        UPanelWidget* Panel = Cast<UPanelWidget>(ParentWidget);
        if (!Panel)
            return UmgErrorJson(FString::Printf(TEXT("Parent '%s' is not a panel widget."), *ParentName));

        Panel->AddChild(NewWidget);
        ActualParent = ParentName;
    }
    else if (!WT->RootWidget)
    {
        WT->RootWidget = NewWidget;
        bIsRoot = true;
    }
    else
    {
        UPanelWidget* RootPanel = Cast<UPanelWidget>(WT->RootWidget);
        if (!RootPanel)
            return UmgErrorJson(TEXT("Root widget is not a panel. Specify 'parent_name' explicitly."));
        RootPanel->AddChild(NewWidget);
        ActualParent = RootPanel->GetName();
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WB);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("success"), true);
    Result->SetStringField(TEXT("widget_name"), NewWidget->GetName());
    Result->SetStringField(TEXT("widget_type"), WidgetType);
    Result->SetBoolField(TEXT("is_root"), bIsRoot);
    if (!ActualParent.IsEmpty())
        Result->SetStringField(TEXT("parent"), ActualParent);

    return SerializeJsonObj(Result);
}

UWidget* UMCPythonHelper::UmgFindWidget(UBlueprint* WidgetBP, const FString& WidgetName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree) return nullptr;
    return WB->WidgetTree->FindWidget(FName(*WidgetName));
}

FString UMCPythonHelper::UmgRemoveWidget(UBlueprint* WidgetBP, const FString& WidgetName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB) return UmgErrorJson(TEXT("Asset is not a WidgetBlueprint."));

    UWidgetTree* WT = WB->WidgetTree;
    if (!WT) return UmgErrorJson(TEXT("Widget tree is null."));

    UWidget* Widget = WT->FindWidget(FName(*WidgetName));
    if (!Widget)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    WT->Modify();

    UPanelWidget* Parent = Cast<UPanelWidget>(Widget->GetParent());
    if (Parent)
    {
        Parent->RemoveChild(Widget);
    }
    else if (WT->RootWidget && WT->RootWidget->GetName() == WidgetName)
    {
        WT->RootWidget = nullptr;
    }
    else
    {
        return UmgErrorJson(FString::Printf(TEXT("Cannot remove '%s': not attached to a panel or root."), *WidgetName));
    }

    TArray<FName> Banished;
    BanishWidgetSubtree(Widget, Banished);
    PruneOrphanedVariableGuids(WB, Banished);

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WB);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("success"), true);
    Result->SetStringField(TEXT("message"), FString::Printf(TEXT("Widget '%s' removed successfully."), *WidgetName));
    return SerializeJsonObj(Result);
}

// ─── UmgSetWidgetIsVariable UFUNCTION ────────────────────────────────────────

FString UMCPythonHelper::UmgSetWidgetIsVariable(UBlueprint* WidgetBP, const FString& WidgetName, bool bIsVariable)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB) return UmgErrorJson(TEXT("Asset is not a WidgetBlueprint."));

    UWidgetTree* WT = WB->WidgetTree;
    if (!WT) return UmgErrorJson(TEXT("Widget tree is null."));

    UWidget* Widget = WT->FindWidget(FName(*WidgetName));
    if (!Widget)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    Widget->Modify();
    Widget->bIsVariable = bIsVariable;

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WB);

    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("success"), true);
    Result->SetStringField(TEXT("widget_name"), WidgetName);
    Result->SetBoolField(TEXT("is_variable"), bIsVariable);
    return SerializeJsonObj(Result);
}

// ─── UmgSetSlotLayout UFUNCTION ──────────────────────────────────────────────

FString UMCPythonHelper::UmgSetSlotLayout(UBlueprint* WidgetBP, const FString& WidgetName,
    float AnchorMinX, float AnchorMinY, float AnchorMaxX, float AnchorMaxY,
    float OffsetX, float OffsetY, float SizeX, float SizeY)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree)
        return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));

    UWidget* Widget = WB->WidgetTree->FindWidget(FName(*WidgetName));
    if (!Widget)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    UCanvasPanelSlot* CPS = Cast<UCanvasPanelSlot>(Widget->Slot);
    if (!CPS)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' is not in a CanvasPanel."), *WidgetName));

    CPS->Modify();
    FAnchorData Data;
    Data.Anchors.Minimum = FVector2D(AnchorMinX, AnchorMinY);
    Data.Anchors.Maximum = FVector2D(AnchorMaxX, AnchorMaxY);
    Data.Offsets = FMargin(OffsetX, OffsetY, SizeX, SizeY);
    Data.Alignment = FVector2D(0.5f, 0.5f);
    CPS->SetLayout(Data);

    FBlueprintEditorUtils::MarkBlueprintAsModified(WB);

    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), true);
    R->SetStringField(TEXT("widget"), WidgetName);
    R->SetStringField(TEXT("message"), FString::Printf(TEXT("Layout set on '%s'."), *WidgetName));
    return SerializeJsonObj(R);
}

// ─── UmgSetTextStyle UFUNCTION ───────────────────────────────────────────────

FString UMCPythonHelper::UmgSetTextStyle(UBlueprint* WidgetBP, const FString& WidgetName,
    int32 FontSize, float ColorR, float ColorG, float ColorB, float ColorA,
    int32 OutlineSize)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree)
        return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));

    UWidget* Widget = WB->WidgetTree->FindWidget(FName(*WidgetName));
    if (!Widget)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    UTextBlock* TB = Cast<UTextBlock>(Widget);
    if (!TB)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' is not a TextBlock."), *WidgetName));

    TB->Modify();

    FSlateFontInfo Font = TB->GetFont();
    Font.Size = FontSize;
    if (OutlineSize >= 0)
        Font.OutlineSettings.OutlineSize = OutlineSize;
    TB->SetFont(Font);

    FLinearColor Color(ColorR, ColorG, ColorB, ColorA);
    TB->SetColorAndOpacity(FSlateColor(Color));

    FBlueprintEditorUtils::MarkBlueprintAsModified(WB);

    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), true);
    R->SetStringField(TEXT("widget"), WidgetName);
    R->SetStringField(TEXT("message"), FString::Printf(TEXT("Text style set on '%s': size=%d outline=%d."), *WidgetName, FontSize, OutlineSize));
    return SerializeJsonObj(R);
}

// ─── UmgGetWidgetProperty UFUNCTION ──────────────────────────────────────────

FString UMCPythonHelper::UmgGetWidgetProperty(UBlueprint* WidgetBP, const FString& WidgetName, const FString& PropertyName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree)
        return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));

    UWidget* Widget = WB->WidgetTree->FindWidget(FName(*WidgetName));
    if (!Widget)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    FProperty* Prop = Widget->GetClass()->FindPropertyByName(FName(*PropertyName));
    if (!Prop)
        return UmgErrorJson(FString::Printf(TEXT("Property '%s' not found on widget '%s'."), *PropertyName, *WidgetName));

    FString ValueStr;
    const void* ValueAddr = Prop->ContainerPtrToValuePtr<void>(Widget);
    Prop->ExportTextItem_Direct(ValueStr, ValueAddr, nullptr, Widget, PPF_None);

    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), true);
    R->SetStringField(TEXT("widget"), WidgetName);
    R->SetStringField(TEXT("property"), PropertyName);
    R->SetStringField(TEXT("value"), ValueStr);
    R->SetStringField(TEXT("type"), Prop->GetCPPType());
    return SerializeJsonObj(R);
}

// ─── UmgSetWidgetProperty UFUNCTION ──────────────────────────────────────────

FString UMCPythonHelper::UmgSetWidgetProperty(UBlueprint* WidgetBP, const FString& WidgetName, const FString& PropertyName, const FString& Value)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree)
        return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));

    UWidget* Widget = WB->WidgetTree->FindWidget(FName(*WidgetName));
    if (!Widget)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    FProperty* Prop = Widget->GetClass()->FindPropertyByName(FName(*PropertyName));
    if (!Prop)
        return UmgErrorJson(FString::Printf(TEXT("Property '%s' not found on widget '%s'."), *PropertyName, *WidgetName));

    Widget->Modify();
    void* ValueAddr = Prop->ContainerPtrToValuePtr<void>(Widget);
    const TCHAR* ImportResult = Prop->ImportText_Direct(*Value, ValueAddr, Widget, PPF_None);
    if (!ImportResult)
        return UmgErrorJson(FString::Printf(TEXT("Failed to set property '%s' to '%s'."), *PropertyName, *Value));

    FBlueprintEditorUtils::MarkBlueprintAsModified(WB);

    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), true);
    R->SetStringField(TEXT("widget"), WidgetName);
    R->SetStringField(TEXT("property"), PropertyName);
    R->SetStringField(TEXT("value"), Value);
    return SerializeJsonObj(R);
}

// ─── UMG hierarchy ops (reparent / wrap / replace) ───────────────────────────

// True if Ancestor is Widget itself or one of its ancestors (for reparent cycle guard).
static bool UmgIsAncestorOf(UWidget* Ancestor, UWidget* Widget)
{
    for (UWidget* W = Widget; W; W = W->GetParent())
        if (W == Ancestor) return true;
    return false;
}

FString UMCPythonHelper::UmgReparentWidget(UBlueprint* WidgetBP, const FString& WidgetName, const FString& NewParentName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree) return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));
    UWidgetTree* WT = WB->WidgetTree;

    UWidget* Widget = WT->FindWidget(FName(*WidgetName));
    if (!Widget) return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));
    UWidget* NewParentWidget = WT->FindWidget(FName(*NewParentName));
    if (!NewParentWidget) return UmgErrorJson(FString::Printf(TEXT("New parent '%s' not found."), *NewParentName));
    UPanelWidget* NewParent = Cast<UPanelWidget>(NewParentWidget);
    if (!NewParent) return UmgErrorJson(FString::Printf(TEXT("New parent '%s' is not a panel widget."), *NewParentName));
    if (Widget == NewParent) return UmgErrorJson(TEXT("Cannot reparent a widget into itself."));
    if (UmgIsAncestorOf(Widget, NewParent))
        return UmgErrorJson(TEXT("Cannot reparent: target is an ancestor of the new parent (cycle)."));
    if (!NewParent->CanHaveMultipleChildren() && NewParent->GetChildrenCount() > 0)
        return UmgErrorJson(FString::Printf(TEXT("Panel '%s' already holds its single allowed child."), *NewParentName));

    WT->Modify();
    if (UPanelWidget* OldParent = Cast<UPanelWidget>(Widget->GetParent()))
        OldParent->RemoveChild(Widget);
    else if (WT->RootWidget == Widget)
        WT->RootWidget = nullptr;
    NewParent->AddChild(Widget);

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WB);
    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), true);
    R->SetStringField(TEXT("widget"), WidgetName);
    R->SetStringField(TEXT("new_parent"), NewParentName);
    return SerializeJsonObj(R);
}

FString UMCPythonHelper::UmgWrapWidget(UBlueprint* WidgetBP, const FString& WidgetName, const FString& WrapperType, const FString& WrapperName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree) return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));
    UWidgetTree* WT = WB->WidgetTree;

    UWidget* Widget = WT->FindWidget(FName(*WidgetName));
    if (!Widget) return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    UClass* WrapperClass = FindUMGWidgetClass(WrapperType);
    if (!WrapperClass) return UmgErrorJson(FString::Printf(TEXT("Unknown widget type '%s'."), *WrapperType));
    if (!WrapperClass->IsChildOf(UPanelWidget::StaticClass()))
        return UmgErrorJson(FString::Printf(TEXT("Wrapper type '%s' is not a panel widget."), *WrapperType));

    // Same as UmgReplaceWidget: settle the destination before constructing, so the error path
    // cannot leave a registered-but-unattached wrapper behind.
    UPanelWidget* OldParent = Cast<UPanelWidget>(Widget->GetParent());
    const bool bWrappingRoot = (!OldParent && WT->RootWidget == Widget);
    if (!OldParent && !bWrappingRoot)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' is not attached to a panel or root."), *WidgetName));

    WT->Modify();
    UPanelWidget* Wrapper = WT->ConstructWidget<UPanelWidget>(WrapperClass, FName(*WrapperName));
    if (!Wrapper) return UmgErrorJson(FString::Printf(TEXT("Failed to construct wrapper '%s'."), *WrapperName));
    Wrapper->bIsVariable = true;
    WB->OnVariableAdded(Wrapper->GetFName());

    if (OldParent)
    {
        const int32 Index = OldParent->GetChildIndex(Widget);
        OldParent->ReplaceChildAt(Index, Wrapper);   // wrapper takes the widget's slot
    }
    else
    {
        WT->RootWidget = Wrapper;
    }
    Wrapper->AddChild(Widget);                        // widget moves inside the wrapper

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WB);
    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), true);
    R->SetStringField(TEXT("wrapped"), WidgetName);
    R->SetStringField(TEXT("wrapper"), Wrapper->GetName());
    R->SetStringField(TEXT("wrapper_type"), WrapperType);
    return SerializeJsonObj(R);
}

FString UMCPythonHelper::UmgReplaceWidget(UBlueprint* WidgetBP, const FString& WidgetName, const FString& NewType, const FString& NewName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree) return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));
    UWidgetTree* WT = WB->WidgetTree;

    UWidget* Widget = WT->FindWidget(FName(*WidgetName));
    if (!Widget) return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    UClass* NewClass = FindUMGWidgetClass(NewType);
    if (!NewClass) return UmgErrorJson(FString::Printf(TEXT("Unknown widget type '%s'."), *NewType));

    // Decide where the replacement goes before constructing anything, so the unattached-widget
    // error cannot leave a half-registered widget behind.
    UPanelWidget* OldParent = Cast<UPanelWidget>(Widget->GetParent());
    const bool bReplacingRoot = (!OldParent && WT->RootWidget == Widget);
    if (!OldParent && !bReplacingRoot)
        return UmgErrorJson(FString::Printf(TEXT("Widget '%s' is not attached to a panel or root."), *WidgetName));

    // The slot index has to be read while the outgoing widget is still a child; banishing it below
    // leaves the pointer in place, so the index stays valid.
    const int32 Index = OldParent ? OldParent->GetChildIndex(Widget) : INDEX_NONE;

    WT->Modify();

    // Banish before constructing: it frees the name, so NewName == WidgetName yields the name asked
    // for instead of a "<name>_1" the caller never sees coming.
    TArray<FName> Banished;
    BanishWidgetSubtree(Widget, Banished);

    UWidget* NewWidget = WT->ConstructWidget<UWidget>(NewClass, FName(*NewName));
    if (!NewWidget) return UmgErrorJson(FString::Printf(TEXT("Failed to construct widget '%s'."), *NewName));
    NewWidget->bIsVariable = true;

    if (OldParent)
    {
        OldParent->ReplaceChildAt(Index, NewWidget);   // old widget (and its subtree) is discarded
    }
    else
    {
        WT->RootWidget = NewWidget;
    }

    // Prune first, then register: a same-name replacement is already live by now, so its name survives
    // the prune and keeps the old GUID - and OnVariableAdded ensures on a name that still has one.
    PruneOrphanedVariableGuids(WB, Banished);
    if (!WB->WidgetVariableNameToGuidMap.Contains(NewWidget->GetFName()))
    {
        WB->OnVariableAdded(NewWidget->GetFName());
    }

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WB);
    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), true);
    R->SetStringField(TEXT("replaced"), WidgetName);
    R->SetStringField(TEXT("new_widget"), NewWidget->GetName());
    R->SetStringField(TEXT("new_type"), NewType);
    return SerializeJsonObj(R);
}

// ─── UMG event binding (widget delegate -> bound event node) ─────────────────

FString UMCPythonHelper::UmgListWidgetEvents(UBlueprint* WidgetBP, const FString& WidgetName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree) return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));
    UWidget* W = WB->WidgetTree->FindWidget(FName(*WidgetName));
    if (!W) return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    TArray<TSharedPtr<FJsonValue>> Events;
    for (TFieldIterator<FMulticastDelegateProperty> It(W->GetClass()); It; ++It)
        Events.Add(MakeShareable(new FJsonValueString(It->GetName())));

    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), true);
    R->SetStringField(TEXT("widget"), WidgetName);
    R->SetStringField(TEXT("widget_class"), W->GetClass()->GetName());
    R->SetArrayField(TEXT("events"), Events);
    return SerializeJsonObj(R);
}

FString UMCPythonHelper::UmgBindWidgetEvent(UBlueprint* WidgetBP, const FString& WidgetName, const FString& EventName)
{
    UWidgetBlueprint* WB = Cast<UWidgetBlueprint>(WidgetBP);
    if (!WB || !WB->WidgetTree) return UmgErrorJson(TEXT("Not a WidgetBlueprint or no WidgetTree."));
    UWidget* W = WB->WidgetTree->FindWidget(FName(*WidgetName));
    if (!W) return UmgErrorJson(FString::Printf(TEXT("Widget '%s' not found."), *WidgetName));

    // The delegate must exist on the widget class.
    if (!FindFProperty<FMulticastDelegateProperty>(W->GetClass(), FName(*EventName)))
    {
        TArray<FString> Avail;
        for (TFieldIterator<FMulticastDelegateProperty> It(W->GetClass()); It; ++It) Avail.Add(It->GetName());
        return UmgErrorJson(FString::Printf(TEXT("Event '%s' not found on %s. Available: %s"),
            *EventName, *W->GetClass()->GetName(), *FString::Join(Avail, TEXT(", "))));
    }

    // A bindable widget must be a variable.
    if (!W->bIsVariable)
    {
        W->bIsVariable = true;
        FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WB);
    }

    // Resolve the generated variable property; compile ONCE only if it isn't present yet.
    FObjectProperty* VarProp = FindFProperty<FObjectProperty>(WB->SkeletonGeneratedClass, FName(*WidgetName));
    if (!VarProp)
    {
        FKismetEditorUtilities::CompileBlueprint(WB);
        VarProp = FindFProperty<FObjectProperty>(WB->SkeletonGeneratedClass, FName(*WidgetName));
    }
    if (!VarProp)
        return UmgErrorJson(FString::Printf(TEXT("Could not resolve the widget variable property for '%s'."), *WidgetName));

    const bool bAlready = FKismetEditorUtilities::FindBoundEventForComponent(WB, FName(*EventName), VarProp->GetFName()) != nullptr;
    if (!bAlready)
    {
        // Mirror UMG's own detail panel: create the node and let the editor recompile on its
        // deferred tick / on save. A manual CompileBlueprint here triggers mid-task reinstancing
        // that crashes a subsequent save/delete of the same asset within one game-thread task.
        FKismetEditorUtilities::CreateNewBoundEventForClass(W->GetClass(), FName(*EventName), WB, VarProp);
        FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(WB);
    }

    const UK2Node_ComponentBoundEvent* Node =
        FKismetEditorUtilities::FindBoundEventForComponent(WB, FName(*EventName), VarProp->GetFName());

    TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
    R->SetBoolField(TEXT("success"), Node != nullptr);
    if (!Node)
    {
        R->SetStringField(TEXT("message"), TEXT("Bound event node was not created."));
        return SerializeJsonObj(R);
    }
    R->SetStringField(TEXT("widget"), WidgetName);
    R->SetStringField(TEXT("event"), EventName);
    R->SetStringField(TEXT("node"), Node->GetName());
    R->SetBoolField(TEXT("already_existed"), bAlready);
    return SerializeJsonObj(R);
}
