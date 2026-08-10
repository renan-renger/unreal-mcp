// Copyright (c) 2025 GenOrca. All Rights Reserved.
//
// Minimal shims mirroring the real Unreal signatures that the graph-resolution
// region of MCPythonHelperInternal.h depends on.
//
// SCOPE / LIMITS. This tests the *algorithm* (path splitting, suffix matching,
// ambiguity policy, cycle safety), not Unreal integration. If a shim's signature
// drifts from the engine's, the real build breaks and this harness will not catch
// it — the in-editor suite and the plugin build are what cover that. The payoff is
// that hosted CI, which has no engine, still gets real coverage of the trickiest
// part of the change instead of none.
#pragma once
#include <string>
#include <vector>
#include <set>
#include <algorithm>
#include <cstdio>
#include <utility>

using int32 = int;
#define TEXT(x) x
#define TCHAR char

namespace ESearchCase { enum Type { CaseSensitive, IgnoreCase }; }

struct FString {
    std::string S;
    FString() {}
    FString(const char* p) : S(p ? p : "") {}
    bool IsEmpty() const { return S.empty(); }
    void Reset() { S.clear(); }
    void TrimStartAndEndInline() {
        auto b = S.find_first_not_of(" \t");
        auto e = S.find_last_not_of(" \t");
        S = (b == std::string::npos) ? "" : S.substr(b, e - b + 1);
    }
    bool Equals(const FString& O, ESearchCase::Type C) const {
        if (C == ESearchCase::CaseSensitive) return S == O.S;
        if (S.size() != O.S.size()) return false;
        for (size_t i = 0; i < S.size(); ++i)
            if (tolower(S[i]) != tolower(O.S[i])) return false;
        return true;
    }
    int32 ParseIntoArray(std::vector<FString>& Out, const char* Delim, bool Cull) const;
    const char* operator*() const { return S.c_str(); }
    FString operator+(const FString& O) const { FString R; R.S = S + O.S; return R; }
    template <typename R> static FString Join(const R& Range, const char* Sep) {
        FString Out; bool First = true;
        for (const auto& E : Range) { if (!First) Out.S += Sep; Out.S += E.S; First = false; }
        return Out;
    }
    template <typename... A> static FString Printf(const char* Fmt, A... Args) {
        char Buf[4096]; snprintf(Buf, sizeof(Buf), Fmt, Args...); return FString(Buf);
    }
};

template <typename T> struct TArray : std::vector<T> {
    using Base = std::vector<T>;
    using Base::Base;
    TArray() {}
    TArray(const T* Ptr, int32 Count) : Base(Ptr, Ptr + Count) {}
    int32 Num() const { return (int32)this->size(); }
    void Add(const T& V) { this->push_back(V); }
    template <typename... A> void Emplace(A&&... a) { this->emplace_back(std::forward<A>(a)...); }
    const T* GetData() const { return this->data(); }
    const T& Last() const { return this->back(); }
};

inline int32 FString::ParseIntoArray(std::vector<FString>& Out, const char* Delim, bool Cull) const {
    Out.clear(); size_t pos = 0, next;
    std::string D(Delim);
    while ((next = S.find(D, pos)) != std::string::npos) {
        std::string tok = S.substr(pos, next - pos);
        if (!Cull || !tok.empty()) Out.push_back(FString(tok.c_str()));
        pos = next + D.size();
    }
    std::string tok = S.substr(pos);
    if (!Cull || !tok.empty()) Out.push_back(FString(tok.c_str()));
    return (int32)Out.size();
}

template <typename T> struct TSet : std::set<T> {
    bool Contains(const T& V) const { return this->find(V) != this->end(); }
    void Add(const T& V) { this->insert(V); }
};
template <typename A, typename B> struct TPair {
    A Key; B Value;
    TPair() {}
    TPair(A k, B v) : Key(k), Value(v) {}
};
template <typename T> struct TObjectPtr {
    T* P = nullptr;
    TObjectPtr(T* p = nullptr) : P(p) {}
    operator T*() const { return P; }
};

struct UEdGraph; struct UEdGraphNode;
struct UEdGraphNode {
    virtual TArray<UEdGraph*> GetSubGraphs() const { return TArray<UEdGraph*>(); }
    FString GetName() const { return FString("N"); }
    virtual ~UEdGraphNode() {}
};
struct UEdGraph {
    TArray<UEdGraphNode*> Nodes;
    TArray<TObjectPtr<UEdGraph>> SubGraphs;
    std::string Name;
    UEdGraph(const char* n = "G") : Name(n) {}
    FString GetName() const { return FString(Name.c_str()); }
};
struct UBlueprint {
    TArray<TObjectPtr<UEdGraph>> UbergraphPages, FunctionGraphs, MacroGraphs, DelegateSignatureGraphs;
};
