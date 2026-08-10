# Copyright (c) 2025 GenOrca. All Rights Reserved.

"""
Offline contract gates for Blueprint graph addressing (no Unreal needed).

Blueprint graphs form a tree: collapsed graphs (K2Node_Composite) and anim
state-machine sub-graphs hang off nodes inside other graphs and nest arbitrarily
deep. Resolution walks that tree and accepts a slash path, so the LLM-facing
contract has to say so — an action that takes graph_name but documents nothing
about paths reads, to a model, as "top-level graphs only", which is the exact
blind spot this change removes.

The resolution logic itself is C++ (MCPythonHelperInternal.h) and is covered by
the in-editor suite (tests/test_blueprint.py). These gates cover the parts that
can go stale without the editor: the catalog contents and its freshness.

Run:
    cd mcp-server && uv run --extra dev pytest tests/test_graph_paths.py
"""

import subprocess
import sys
from pathlib import Path

import pytest

from unreal_mcp.dispatchers._catalog import CATALOG

MCP_SERVER_DIR = Path(__file__).resolve().parents[1]

# Actions that take a graph_name but address something other than a Blueprint
# graph forest, so the collapsed-graph note would be wrong for them.
_NOT_BLUEPRINT_GRAPHS: set[tuple[str, str]] = set()


def _graph_name_actions() -> list[tuple[str, str]]:
    """Every (domain, action) whose signature takes a graph_name parameter."""
    found = []
    for domain, actions in CATALOG.items():
        for action, info in actions.items():
            params = [p.split("=")[0].strip() for p in info["params"].split(",")]
            if "graph_name" in params:
                found.append((domain, action))
    return found


def test_list_blueprint_graphs_is_exposed():
    """Graph discovery must exist: without it there is no way to learn a nested path."""
    assert "list_blueprint_graphs" in CATALOG["blueprint"]
    entry = CATALOG["blueprint"]["list_blueprint_graphs"]
    assert entry["params"] == "asset_path"
    assert "collapsed" in entry["doc"].lower()


def test_there_are_graph_name_actions():
    """Guard: if the extraction below silently matches nothing, fail loudly."""
    assert _graph_name_actions(), "no graph_name actions found — parser or catalog broke"


@pytest.mark.parametrize("domain,action", _graph_name_actions())
def test_graph_name_actions_document_path_syntax(domain, action):
    """Every graph_name action must tell the model that nested paths are accepted.

    Adding a new graph_name action? Mention the path syntax in its docstring and
    regenerate the catalog — do not weaken this gate.
    """
    if (domain, action) in _NOT_BLUEPRINT_GRAPHS:
        pytest.skip(f"{domain}.{action} does not address a Blueprint graph forest")
    doc = CATALOG[domain][action]["doc"]
    assert "path" in doc.lower(), (
        f"{domain}.{action} takes graph_name but its doc never mentions paths, so an "
        f"LLM cannot know collapsed graphs are addressable. Doc: {doc!r}"
    )


def test_catalog_is_not_stale():
    """The committed catalog must match the plugin's ue_* signatures.

    The dispatcher passes params straight through as ue_func(**params), so a stale
    catalog is a runtime TypeError rather than a docs nit. It also silently reverts
    doc changes, which is how the path-syntax note above would quietly disappear.
    """
    result = subprocess.run(
        [sys.executable, "generate_catalog.py", "--check"],
        cwd=MCP_SERVER_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Catalog is stale — run `python generate_catalog.py`.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
