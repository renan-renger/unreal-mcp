# Copyright (c) 2025 GenOrca. All Rights Reserved.

"""
End-to-end tests: MCP server dispatcher -> real TCP -> C++ server -> ue_* -> back.

Unlike test_dispatcher.py (which mocks the TCP layer), these run the FULL chain
with NO mocks. They prove the actual scenario an MCP client triggers:
routing + socket round-trip + C++ dispatch + response unwrapping.

Requires a running Unreal editor with the UnrealMCPython TCP server on :12029.
If the port is not reachable, the whole module is skipped (so CI / offline runs
stay green; run locally with the editor open to exercise these).

Run:
    cd mcp-server && uv run --extra dev pytest tests/test_e2e.py -v
"""

import asyncio
import socket

import pytest

import unreal_mcp.dispatcher as disp

HOST, PORT = "127.0.0.1", 12029


def _editor_reachable() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _editor_reachable(),
    reason=f"Unreal TCP server not reachable on {HOST}:{PORT} (open the editor to run E2E).",
)


def run(coro):
    return asyncio.run(coro)


def test_list_actors_round_trip():
    """A read action proves unwrapping: 'actors' is an INNER field of the action result."""
    r = run(disp._dispatch("actor", "list_all_with_locations", {}))
    assert r.get("success") is True
    assert "actors" in r, f"inner field missing — response not unwrapped: {r}"
    assert isinstance(r["actors"], list)


def test_spawn_and_delete_round_trip():
    spawn = run(disp._dispatch("actor", "spawn_from_class",
                               {"class_path": "/Script/Engine.PointLight",
                                "location": [0, 0, 700]}))
    assert spawn.get("success") is True, spawn
    label = spawn.get("actor_label")
    assert label, f"actor_label missing — not unwrapped: {spawn}"
    # cleanup through the same chain
    deleted = run(disp._dispatch("actor", "delete_by_label", {"actor_label": label}))
    assert deleted.get("success") is True, deleted


def test_inner_action_failure_is_surfaced():
    """Action failure must come back as success=False (not buried in a result string)."""
    r = run(disp._dispatch("actor", "set_transform",
                           {"actor_label": "NoSuchActor_E2E_XYZ", "location": [0, 0, 0]}))
    assert r.get("success") is False
    assert "message" in r


def test_list_actions_offline_path_still_works():
    """list_actions must not touch TCP even when the editor is up."""
    r = run(disp._dispatch("material", "list_actions", {}))
    assert r["success"] is True
    assert r["domain"] == "material"
