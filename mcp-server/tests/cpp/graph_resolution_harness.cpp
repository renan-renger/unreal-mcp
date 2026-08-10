// Copyright (c) 2025 GenOrca. All Rights Reserved.
//
// Behaviour spec for Blueprint graph resolution. The logic under test is SLICED FROM
// the real MCPythonHelperInternal.h at test time (see test_graph_resolution_cpp.py),
// never copied here, so this cannot pass against stale duplicated code.
//
// Exit code 0 = all assertions passed.

#include "ue_stubs.h"
#include "graph_resolution.inc"
#include <cassert>

struct FComposite : UEdGraphNode {
    UEdGraph* Bound = nullptr;
    TArray<UEdGraph*> GetSubGraphs() const override {
        TArray<UEdGraph*> R; if (Bound) R.Add(Bound); return R;
    }
};

static int Failures = 0;
static void Check(bool Cond, const char* What) {
    printf("%s  %s\n", Cond ? "PASS" : "FAIL", What);
    if (!Cond) ++Failures;
}

int main() {
    // Mirrors AB_Goblin_Elite_New: EventGraph > PrepareRefs > CalculateSpeed_2
    UBlueprint BP;
    UEdGraph Event("EventGraph"), Prepare("PrepareRefs"), Calc("CalculateSpeed_2");
    UEdGraph Ctor("UserConstructionScript");
    FComposite C1, C2; C1.Bound = &Prepare; C2.Bound = &Calc;
    Event.Nodes.Add(&C1); Prepare.Nodes.Add(&C2);
    BP.UbergraphPages.Add(TObjectPtr<UEdGraph>(&Event));
    BP.FunctionGraphs.Add(TObjectPtr<UEdGraph>(&Ctor));

    auto All = EnumerateBlueprintGraphs(&BP);
    Check(All.Num() == 4, "enumerates all 4 graphs incl. 2 nested");
    Check(All[1].Path.S == "EventGraph/PrepareRefs", "depth-1 path");
    Check(All[2].Path.S == "EventGraph/PrepareRefs/CalculateSpeed_2", "depth-2 path");
    Check(All[2].Depth == 2, "depth-2 reported");
    Check(All[3].RootKind.S == "Function", "function root kind");
    Check(All[1].OwningNode == &C1, "owning node recorded");

    FString E;
    auto R = [&](const char* P) { return ResolveBlueprintGraph(&BP, FString(P), E); };

    Check(R("CalculateSpeed_2") == &Calc,                               "bare nested name resolves");
    Check(R("PrepareRefs/CalculateSpeed_2") == &Calc,                   "partial suffix path resolves");
    Check(R("EventGraph/PrepareRefs/CalculateSpeed_2") == &Calc,        "full path resolves");
    Check(R("PrepareRefs") == &Prepare,                                 "bare depth-1 name resolves");
    Check(R("EventGraph") == &Event,                                    "root still resolves (regression)");
    Check(R("UserConstructionScript") == &Ctor,                         "function graph resolves (regression)");
    Check(R("/EventGraph//PrepareRefs/") == &Prepare,                   "stray slashes normalised");
    Check(R("  EventGraph / PrepareRefs  ") == &Prepare,                "segment whitespace trimmed");
    Check(R("preparerefs") == &Prepare,                                 "case-insensitive fallback");
    Check(R("CalculateSpeed_2/PrepareRefs") == nullptr,                 "wrong order does not resolve");
    Check(R("Nope") == nullptr,                                         "unknown name fails");

    // Ambiguity: a second PrepareRefs under the function graph.
    UEdGraph Dup("PrepareRefs");
    FComposite C3; C3.Bound = &Dup; Ctor.Nodes.Add(&C3);
    Check(R("PrepareRefs") == nullptr,                                  "ambiguous bare name refuses to guess");
    Check(E.S.find("ambiguous") != std::string::npos,                   "ambiguity is explained");
    Check(E.S.find("EventGraph/PrepareRefs") != std::string::npos &&
          E.S.find("UserConstructionScript/PrepareRefs") != std::string::npos,
                                                                        "both candidates listed");
    Check(R("EventGraph/PrepareRefs") == &Prepare,                      "longer path disambiguates");
    Check(R("UserConstructionScript/PrepareRefs") == &Dup,              "other candidate reachable too");

    // Cycle safety: a graph that contains itself must not hang.
    UEdGraph Loop("Loop"); FComposite C4; C4.Bound = &Loop; Loop.Nodes.Add(&C4);
    BP.MacroGraphs.Add(TObjectPtr<UEdGraph>(&Loop));
    Check(EnumerateBlueprintGraphs(&BP).Num() == 6, "self-referencing graph terminates");

    printf("\n%s (%d failure(s))\n", Failures ? "FAILED" : "ALL PASSED", Failures);
    return Failures != 0;
}
