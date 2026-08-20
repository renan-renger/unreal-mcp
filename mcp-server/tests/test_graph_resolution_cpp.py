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
Unreal integration.

The compiler is $CXX, else a system g++/clang++/c++, else Unreal's own bundled clang
— a Linux box that builds this plugin usually has no system toolchain at all, and
without that last fallback the gate would skip exactly where it is needed, which
reads as a pass in the summary line.

Run:
    cd mcp-server && uv run --extra dev pytest tests/test_graph_resolution_cpp.py -q
"""

import glob
import os
import platform
import re
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


def _installed_engine_roots() -> list[Path]:
    """Engine install paths Epic records outside the registry (Linux and macOS)."""
    manifests = [
        Path.home() / ".config" / "Epic" / "UnrealEngine" / "Install.ini",
        Path.home() / "Library" / "Application Support" / "Epic" / "UnrealEngine" / "Install.ini",
    ]
    roots = []
    for manifest in manifests:
        if not manifest.is_file():
            continue
        for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            # Entries are "<GUID>=<path>" under an [Installations] header.
            _, sep, path = line.partition("=")
            if sep and path.strip().startswith("/"):
                roots.append(Path(path.strip()))
    return roots


def _toolchain_version(path: str) -> int:
    """Sort key for Unreal's vNN_clang-* toolchain directories, newest first."""
    match = re.search(r"[/\\]v(\d+)_", path)
    return int(match.group(1)) if match else -1


def _bundled_unreal_compiler() -> str | None:
    """Unreal's own clang++, for a box with no system C++ toolchain.

    Unreal ships the toolchain it builds Linux targets with, so a machine that can
    build this plugin at all has a compiler even when g++/clang++ are not installed —
    which is the normal state of a Linux dev box that only ever installed the engine.
    Two shapes are searched: the standalone toolchain drop in ~/UnrealToolchains, and
    the copy inside an engine tree.

    Linux-oriented on purpose: Windows builds against MSVC and macOS has clang from the
    Xcode command line tools, so on those hosts the system lookup above already wins.
    """
    arch = "aarch64-unknown-linux-gnueabi" if platform.machine() == "aarch64" \
        else "x86_64-unknown-linux-gnu"

    roots = [Path(os.environ[var]) for var in ("UE_ENGINE_ROOT", "UNREAL_ENGINE_ROOT", "UE_ROOT")
             if os.environ.get(var)]
    roots.extend(_installed_engine_roots())

    patterns = [str(Path.home() / "UnrealToolchains" / "*" / arch / "bin" / "clang++")]
    patterns += [
        str(root / "Engine" / "Extras" / "ThirdPartyNotUE" / "SDKs" / "HostLinux"
            / "Linux_x64" / "*" / arch / "bin" / "clang++")
        for root in roots
    ]

    for pattern in patterns:
        for found in sorted(glob.glob(pattern), key=_toolchain_version, reverse=True):
            if os.access(found, os.X_OK):
                return found
    return None


def _compiler() -> str | None:
    """$CXX, else a system compiler, else Unreal's bundled clang.

    The fallback matters more than it looks: without it this gate skips on exactly the
    machines that build the plugin, and a skip reads as a pass in the summary line.
    """
    override = os.environ.get("CXX")
    if override:
        return shutil.which(override) or (override if Path(override).is_file() else None)
    for name in ("g++", "clang++", "c++"):
        found = shutil.which(name)
        if found:
            return found
    return _bundled_unreal_compiler()


def test_bundled_compiler_lookup_is_usable():
    """Whatever the lookup returns must actually be a working C++ driver."""
    found = _bundled_unreal_compiler()
    if found is None:
        pytest.skip("no bundled Unreal toolchain on this machine")
    probe = subprocess.run([found, "--version"], capture_output=True, text=True, timeout=60)
    assert probe.returncode == 0, f"{found} is not runnable:\n{probe.stderr}"
    assert "clang" in probe.stdout.lower(), probe.stdout


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
        pytest.skip("no C++ compiler available: no $CXX, no g++/clang++/c++ on PATH, and no "
                    "Unreal toolchain under ~/UnrealToolchains or a recorded engine install")

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
