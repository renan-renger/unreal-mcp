// Copyright (c) 2025 GenOrca (by zenoengine). All Rights Reserved.
// Shared internal helpers for the split MCPythonHelper_*.cpp translation units.
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonSerializer.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraph/EdGraphPin.h"
#include "Engine/Blueprint.h"

inline FString MakeJsonError(const FString& Message)
{
    TSharedPtr<FJsonObject> Obj = MakeShareable(new FJsonObject());
    Obj->SetBoolField(TEXT("success"), false);
    Obj->SetStringField(TEXT("message"), Message);
    FString Out;
    TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&Out);
    FJsonSerializer::Serialize(Obj.ToSharedRef(), W);
    return Out;
}

inline FString MakeJsonSuccess(const FString& Message)
{
    TSharedPtr<FJsonObject> Obj = MakeShareable(new FJsonObject());
    Obj->SetBoolField(TEXT("success"), true);
    Obj->SetStringField(TEXT("message"), Message);
    FString Out;
    TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&Out);
    FJsonSerializer::Serialize(Obj.ToSharedRef(), W);
    return Out;
}

inline FString SerializeJsonObj(TSharedPtr<FJsonObject> Obj)
{
    FString Out;
    TSharedRef<TJsonWriter<>> W = TJsonWriterFactory<>::Create(&Out);
    FJsonSerializer::Serialize(Obj.ToSharedRef(), W);
    return Out;
}

// ─── Blueprint graph resolution ───────────────────────────────────────────────
//
// A Blueprint's graphs form a forest, not a flat list. The roots live in the
// Blueprint's own arrays (UbergraphPages / FunctionGraphs / MacroGraphs /
// DelegateSignatureGraphs), but a collapsed graph (UK2Node_Composite) — and an
// anim state machine, state, conduit or transition — hangs off a *node* inside
// another graph and can nest arbitrarily deep. Scanning only the Blueprint's
// arrays therefore makes every collapsed graph unaddressable by name, which is
// what these helpers fix.
//
// Children are collected from two independent sources, unioned:
//   * UEdGraph::SubGraphs   — the parent graph's own bookkeeping array
//   * UEdGraphNode::GetSubGraphs() — virtual, overridden by K2Node_Composite,
//     AnimGraphNode_StateMachineBase, AnimStateNode, AnimStateConduitNode,
//     AnimStateTransitionNode and MaterialGraphNode_Composite.
// Neither is reliably a superset of the other (BehaviorTreeGraphNode_Composite-
// Decorator populates SubGraphs without overriding the virtual), and using the
// base-class virtual keeps this header free of any new module dependency.

// The region between these sentinels depends only on FString/TArray/TSet/TPair and
// the two graph types, so mcp-server/tests/test_graph_resolution_cpp.py slices it out
// and compiles it against stubs to test the path/ambiguity semantics without an
// editor. Keep it free of anything that needs the wider engine, and move the
// sentinels if you add code that does.
// >>> MCPYTHON_GRAPH_RESOLUTION_BEGIN

/** One graph in the Blueprint's graph forest, with the slash path that addresses it. */
struct FMCPythonGraphEntry
{
    /** Slash-delimited path from a root graph, e.g. "EventGraph/PrepareRefs/CalculateSpeed_2". */
    FString Path;
    UEdGraph* Graph = nullptr;
    /** Which Blueprint array this subtree is rooted in: Ubergraph / Function / Macro / DelegateSignature. */
    FString RootKind;
    /** Node that owns this graph, or nullptr for a root graph. */
    UEdGraphNode* OwningNode = nullptr;
    int32 Depth = 0;
};

/** Direct child graphs of a graph: union of Graph->SubGraphs and every node's GetSubGraphs(). */
inline void CollectChildGraphs(UEdGraph* Graph, TArray<TPair<UEdGraph*, UEdGraphNode*>>& OutChildren)
{
    if (!Graph) return;

    TSet<UEdGraph*> Seen;

    // Source 1: nodes that own a bound graph. Preferred, because it also tells us
    // which node the graph hangs off — useful context in list_blueprint_graphs.
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (!Node) continue;
        for (UEdGraph* Sub : Node->GetSubGraphs())
        {
            if (Sub && !Seen.Contains(Sub))
            {
                Seen.Add(Sub);
                OutChildren.Emplace(Sub, Node);
            }
        }
    }

    // Source 2: the graph's own SubGraphs array, for anything the virtual missed.
    for (UEdGraph* Sub : Graph->SubGraphs)
    {
        if (Sub && !Seen.Contains(Sub))
        {
            Seen.Add(Sub);
            OutChildren.Emplace(Sub, nullptr);
        }
    }
}

/** Depth-first walk of one root graph, appending every graph in its subtree. */
inline void EnumerateGraphSubtree(UEdGraph* Graph, const FString& ParentPath, const FString& RootKind,
    UEdGraphNode* OwningNode, int32 Depth, TSet<UEdGraph*>& Visited, TArray<FMCPythonGraphEntry>& Out)
{
    // Visited guards against a graph reachable by two routes (or, defensively, a
    // cycle): without it a shared bound graph would recurse forever.
    if (!Graph || Visited.Contains(Graph)) return;
    Visited.Add(Graph);

    FMCPythonGraphEntry Entry;
    Entry.Path = ParentPath.IsEmpty() ? Graph->GetName() : (ParentPath + TEXT("/") + Graph->GetName());
    Entry.Graph = Graph;
    Entry.RootKind = RootKind;
    Entry.OwningNode = OwningNode;
    Entry.Depth = Depth;
    Out.Add(Entry);

    TArray<TPair<UEdGraph*, UEdGraphNode*>> Children;
    CollectChildGraphs(Graph, Children);
    for (const TPair<UEdGraph*, UEdGraphNode*>& Child : Children)
    {
        EnumerateGraphSubtree(Child.Key, Entry.Path, RootKind, Child.Value, Depth + 1, Visited, Out);
    }
}

/** Every graph reachable from the Blueprint, each with its full slash path. */
inline TArray<FMCPythonGraphEntry> EnumerateBlueprintGraphs(UBlueprint* Blueprint)
{
    TArray<FMCPythonGraphEntry> Out;
    if (!Blueprint) return Out;

    TSet<UEdGraph*> Visited;

    // IntermediateGeneratedGraphs and EventGraphs are transient compile artefacts
    // (UPROPERTY(transient, duplicatetransient)) — deliberately not enumerated.
    auto AddRoots = [&](const TArray<TObjectPtr<UEdGraph>>& Roots, const TCHAR* Kind)
    {
        for (UEdGraph* Graph : Roots)
        {
            EnumerateGraphSubtree(Graph, FString(), Kind, nullptr, 0, Visited, Out);
        }
    };

    AddRoots(Blueprint->UbergraphPages, TEXT("Ubergraph"));
    AddRoots(Blueprint->FunctionGraphs, TEXT("Function"));
    AddRoots(Blueprint->MacroGraphs, TEXT("Macro"));
    AddRoots(Blueprint->DelegateSignatureGraphs, TEXT("DelegateSignature"));

    return Out;
}

/** Split a graph path on '/', trimming blanks so "/A//B/" behaves as "A/B". */
inline TArray<FString> SplitGraphPath(const FString& GraphPath)
{
    TArray<FString> Raw;
    GraphPath.ParseIntoArray(Raw, TEXT("/"), /*InCullEmpty=*/true);

    TArray<FString> Segments;
    for (FString& Segment : Raw)
    {
        Segment.TrimStartAndEndInline();
        if (!Segment.IsEmpty())
            Segments.Add(Segment);
    }
    return Segments;
}

/**
 * Does an entry's path end with the requested segments?
 *
 * Matching on a suffix means the caller may give as little or as much of the path
 * as they need to be unambiguous: a bare "CalculateSpeed_2", the partial
 * "PrepareRefs/CalculateSpeed_2", or the full "EventGraph/PrepareRefs/CalculateSpeed_2"
 * all resolve to the same graph, and a name that collides is disambiguated by
 * prepending parents rather than by inventing a separate syntax.
 */
inline bool GraphPathMatchesSuffix(const FMCPythonGraphEntry& Entry, const TArray<FString>& Segments, ESearchCase::Type Case)
{
    TArray<FString> EntrySegments = SplitGraphPath(Entry.Path);
    if (Segments.Num() == 0 || Segments.Num() > EntrySegments.Num())
        return false;

    const int32 Offset = EntrySegments.Num() - Segments.Num();
    for (int32 i = 0; i < Segments.Num(); ++i)
    {
        if (!EntrySegments[Offset + i].Equals(Segments[i], Case))
            return false;
    }
    return true;
}

/**
 * Resolve a graph by bare name or slash path, searching collapsed graphs too.
 *
 * Returns nullptr and fills OutError on failure. An ambiguous bare name is ALWAYS
 * an error listing the candidate paths — never a silent pick of the first match,
 * which would edit the wrong graph.
 */
inline UEdGraph* ResolveBlueprintGraph(UBlueprint* Blueprint, const FString& GraphPath, FString& OutError)
{
    OutError.Reset();
    if (!Blueprint)
    {
        OutError = TEXT("Invalid Blueprint.");
        return nullptr;
    }

    const TArray<FString> Segments = SplitGraphPath(GraphPath);
    if (Segments.Num() == 0)
    {
        OutError = TEXT("Graph name is empty.");
        return nullptr;
    }

    const TArray<FMCPythonGraphEntry> All = EnumerateBlueprintGraphs(Blueprint);

    auto Gather = [&](ESearchCase::Type Case)
    {
        TArray<const FMCPythonGraphEntry*> Hits;
        for (const FMCPythonGraphEntry& Entry : All)
        {
            if (GraphPathMatchesSuffix(Entry, Segments, Case))
                Hits.Add(&Entry);
        }
        return Hits;
    };

    // Case-sensitive first: an exact-case hit must win over a case-insensitive one,
    // otherwise two graphs differing only in case would report as ambiguous even
    // when the caller spelled one of them exactly.
    TArray<const FMCPythonGraphEntry*> Hits = Gather(ESearchCase::CaseSensitive);
    if (Hits.Num() == 0)
        Hits = Gather(ESearchCase::IgnoreCase);

    if (Hits.Num() == 1)
        return Hits[0]->Graph;

    if (Hits.Num() > 1)
    {
        TArray<FString> Candidates;
        for (const FMCPythonGraphEntry* Hit : Hits)
            Candidates.Add(Hit->Path);
        OutError = FString::Printf(
            TEXT("Graph '%s' is ambiguous - %d graphs match: %s. Pass a longer path to disambiguate (e.g. 'EventGraph/%s')."),
            *GraphPath, Hits.Num(), *FString::Join(Candidates, TEXT(", ")), *Segments.Last());
        return nullptr;
    }

    // Not found: list what IS available, so the caller is not left guessing. The
    // old behaviour reported only "not found", with no way to discover real names.
    TArray<FString> Available;
    for (const FMCPythonGraphEntry& Entry : All)
        Available.Add(Entry.Path);

    static constexpr int32 MaxListed = 40;
    FString AvailableStr;
    if (Available.Num() == 0)
    {
        AvailableStr = TEXT("(none)");
    }
    else if (Available.Num() <= MaxListed)
    {
        AvailableStr = FString::Join(Available, TEXT(", "));
    }
    else
    {
        TArray<FString> Head(Available.GetData(), MaxListed);
        AvailableStr = FString::Join(Head, TEXT(", "))
            + FString::Printf(TEXT(", ... (%d more, use list_blueprint_graphs)"), Available.Num() - MaxListed);
    }

    OutError = FString::Printf(TEXT("Graph '%s' not found in Blueprint. Available graphs: %s"), *GraphPath, *AvailableStr);
    return nullptr;
}

/** Back-compat shorthand for callers that only need the pointer (error text discarded). */
inline UEdGraph* FindGraphByName(UBlueprint* Blueprint, const FString& GraphName)
{
    FString Unused;
    return ResolveBlueprintGraph(Blueprint, GraphName, Unused);
}

// <<< MCPYTHON_GRAPH_RESOLUTION_END

inline UEdGraphNode* FindBPNodeByName(UEdGraph* Graph, const FString& NodeName)
{
    for (UEdGraphNode* Node : Graph->Nodes)
    {
        if (Node && Node->GetName() == NodeName)
            return Node;
    }
    return nullptr;
}

inline UEdGraphPin* FindPinByName(UEdGraphNode* Node, const FString& PinName, EEdGraphPinDirection Direction = EGPD_MAX)
{
    for (UEdGraphPin* Pin : Node->Pins)
    {
        if (!Pin || Pin->bHidden) continue;
        if (Direction != EGPD_MAX && Pin->Direction != Direction) continue;

        // Match by internal name
        if (Pin->GetName() == PinName)
            return Pin;
        // Match by friendly name
        FString Friendly = Pin->PinFriendlyName.ToString();
        if (!Friendly.IsEmpty() && Friendly == PinName)
            return Pin;
    }
    return nullptr;
}
