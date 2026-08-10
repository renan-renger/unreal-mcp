# Copyright (c) 2025 GenOrca. All Rights Reserved.

"""
Offline behaviour gate for the C++ Blueprint graph resolver.

Blueprint graph resolution (bare name vs slash path, suffix matching, the refuse-
to-guess ambiguity policy, cycle safety) lives in C++, so hosted CI — which has no
Unreal Engine — could not cover it at all. The in-editor suite can, but it only
runs on the manually-dispatched self-hosted runner.

This gate closes that hole: it slices the sentinel-delimited region out of the real
MCPythonHelperInternal.h, compiles it against stubs in tests/cpp/, and runs a
behaviour spec. Because the code under test is extracted from the header at test
time rather than duplicated, the gate cannot go green against a stale copy.

Limits are documented in tests/cpp/ue_stubs.h: this proves the algorithm, not the
Unreal integration. Skips cleanly when no C++ compiler is available.

Run:
    cd mcp-server && uv run --extra dev pytest tests/test_graph_resolution_cpp.py -q
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BEGIN = ">>> MCPYTHON_GRAPH_RESOLUTION_BEGIN"
END = "<<< MCPYTHON_GRAPH_RESOLUTION_END"

_HEADER_REL = (
    Path("Plugins") / "UnrealMCPython" / "Source" / "UnrealMCPython"
    / "Private" / "MCPythonHelperInternal.h"
)

CPP_DIR = Path(__file__).resolve().parent / "cpp"


def _find_header() -> Path | None:
    """Locate the plugin header by walking up (the server may be vendored deeper)."""
    for base in Path(__file__).resolve().parents:
        candidate = base / _HEADER_REL
        if candidate.is_file():
            return candidate
    return None


def _compiler() -> str | None:
    """Prefer $CXX, so a machine whose only C++ compiler is Unreal's bundled clang
    (common on a Linux dev box that never installed a system toolchain) can still
    run this gate: CXX=<engine>/.../bin/clang++ uv run pytest."""
    override = os.environ.get("CXX")
    if override:
        return shutil.which(override) or (override if Path(override).is_file() else None)
    for name in ("g++", "clang++", "c++"):
        found = shutil.which(name)
        if found:
            return found
    return None


def test_header_is_findable():
    """Guard: a layout change must fail loudly, not silently skip the gate."""
    assert _find_header() is not None, f"could not locate {_HEADER_REL} from {__file__}"


def test_sentinels_present():
    """The extraction markers must survive edits to the header."""
    header = _find_header()
    if header is None:
        pytest.skip("plugin header not present in this checkout")
    text = header.read_text(encoding="utf-8")
    assert BEGIN in text, f"missing '{BEGIN}' sentinel in {header}"
    assert END in text, f"missing '{END}' sentinel in {header}"
    assert text.index(BEGIN) < text.index(END), "sentinels are out of order"


def test_graph_resolution_behaviour(tmp_path):
    """Compile the real resolver against stubs and run its behaviour spec."""
    header = _find_header()
    if header is None:
        pytest.skip("plugin header not present in this checkout")
    cxx = _compiler()
    if cxx is None:
        pytest.skip("no C++ compiler available (g++/clang++/c++)")

    text = header.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        pytest.fail("graph-resolution sentinels missing — see test_sentinels_present")

    region = text.split(BEGIN, 1)[1].split(END, 1)[0]
    assert "ResolveBlueprintGraph" in region, "sliced region does not contain the resolver"

    build = tmp_path / "build"
    build.mkdir()
    for name in ("ue_stubs.h", "graph_resolution_harness.cpp"):
        shutil.copy(CPP_DIR / name, build / name)
    (build / "graph_resolution.inc").write_text(region, encoding="utf-8")

    binary = build / "harness"
    compiled = subprocess.run(
        [cxx, "-std=c++17", "-Wall", "-o", str(binary), str(build / "graph_resolution_harness.cpp")],
        cwd=build, capture_output=True, text=True,
    )
    assert compiled.returncode == 0, (
        "graph resolution logic failed to compile:\n"
        f"{compiled.stdout}\n{compiled.stderr}"
    )

    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, f"behaviour spec failed:\n{run.stdout}\n{run.stderr}"
    assert "ALL PASSED" in run.stdout, run.stdout
