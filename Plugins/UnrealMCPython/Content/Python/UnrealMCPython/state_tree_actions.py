# Copyright (c) 2025 GenOrca. All Rights Reserved.

import unreal
import json
import re
import traceback

# UStateTree::EditorData is a bare UPROPERTY(), so Unreal Python refuses it
# ("is protected and cannot be read"). Everything below it — UStateTreeEditorData
# and UStateTreeState — is BlueprintType and reads normally, so one reflection
# hop through MCPythonHelper is enough to reach the whole tree.
_EDITOR_DATA_PROPERTY = "EditorData"

_STATE_TREE_MISSING = ("Requires the StateTree plugin. Enable it in Edit > Plugins "
                       "and restart the editor.")

# Native nodes live in an FInstancedStruct whose type name only shows up in the
# exported text; Blueprint nodes carry a real UObject instead.
_SCRIPT_PATH_RE = re.compile(r"/Script/[A-Za-z0-9_.]+")


def _require_state_tree():
    """Returns an error dict when the StateTree plugin is not loaded, else None."""
    if not hasattr(unreal, "StateTree"):
        return {"success": False, "message": _STATE_TREE_MISSING}
    if not hasattr(unreal.MCPythonHelper, "get_object_property_raw"):
        return {"success": False,
                "message": "MCPythonHelper.get_object_property_raw is missing. "
                           "Rebuild the plugin with the editor closed."}
    return None


def _load_editor_data(asset_path):
    """(state_tree, editor_data, error_dict). Only one of the last two is set."""
    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        return None, None, {"success": False, "message": f"Asset not found: {asset_path}"}

    st = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not isinstance(st, unreal.StateTree):
        got = st.get_class().get_name() if st else "None"
        return None, None, {"success": False,
                            "message": f"Not a StateTree asset: {asset_path} (got {got})"}

    ed = unreal.MCPythonHelper.get_object_property_raw(st, _EDITOR_DATA_PROPERTY)
    if not ed:
        return st, None, {"success": False,
                          "message": f"StateTree has no EditorData: {asset_path}. "
                                     "The asset may be compiled-only or corrupt."}
    return st, ed, None


def _node_name(node):
    """Name of a task/condition/evaluator inside an FStateTreeEditorNode."""
    try:
        instance = node.get_editor_property("InstanceObject")
        if instance:
            return instance.get_class().get_name()
    except Exception:
        pass
    try:
        text = node.get_editor_property("Node").export_text() or ""
    except Exception:
        return "<unreadable>"
    match = _SCRIPT_PATH_RE.search(text)
    return match.group(0) if match else "<empty>"


def _node_params(node):
    """Parameters of a node: exported text for native, editor properties for Blueprint."""
    try:
        instance = node.get_editor_property("InstanceObject")
    except Exception:
        instance = None

    if instance:
        return {"kind": "blueprint", "class": instance.get_class().get_name(),
                "class_path": instance.get_class().get_path_name()}
    try:
        return {"kind": "native", "export": node.get_editor_property("Node").export_text()}
    except Exception as e:
        return {"kind": "unknown", "error": str(e)}


def _enum_name(value):
    """StateTreeStateType.STATE -> 'STATE' (str() renders the whole repr otherwise)."""
    return str(value).split(".")[-1].split(":")[0].strip("<> ")


def _walk(state, path, depth, out):
    name = str(state.get_editor_property("Name"))
    full_path = f"{path}/{name}"
    tasks = state.get_editor_property("Tasks")
    children = state.get_editor_property("Children")
    transitions = state.get_editor_property("Transitions")

    out.append({
        "path": full_path,
        "name": name,
        "depth": depth,
        "type": _enum_name(state.get_editor_property("Type")),
        "selection_behavior": _enum_name(state.get_editor_property("SelectionBehavior")),
        "tasks": [_node_name(t) for t in tasks],
        "enter_conditions": [_node_name(c) for c in state.get_editor_property("EnterConditions")],
        "transition_count": len(transitions),
        "child_count": len(children),
    })
    for child in children:
        _walk(child, full_path, depth + 1, out)


def _all_states(editor_data):
    states = []
    for root in editor_data.get_editor_property("SubTrees"):
        _walk(root, "", 0, states)
    return states


def ue_list_state_trees(path: str = "/Game") -> str:
    """Lists every StateTree asset under a content path (requires the StateTree plugin)."""
    guard = _require_state_tree()
    if guard:
        return json.dumps(guard)
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = registry.get_assets_by_path(path, recursive=True)
        trees = [str(a.package_name) for a in assets
                 if str(a.asset_class_path.asset_name) == "StateTree"]
        return json.dumps({"success": True, "count": len(trees), "state_trees": sorted(trees)})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_get_state_tree_structure(asset_path: str = None) -> str:
    """Dumps a StateTree's full state hierarchy, tasks and transitions (requires the StateTree plugin)."""
    guard = _require_state_tree()
    if guard:
        return json.dumps(guard)
    if asset_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameter 'asset_path' is missing."})
    try:
        _, editor_data, err = _load_editor_data(asset_path)
        if err:
            return json.dumps(err)

        schema = editor_data.get_editor_property("Schema")
        states = _all_states(editor_data)
        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "schema": schema.get_class().get_name() if schema else None,
            "evaluators": [_node_name(e) for e in editor_data.get_editor_property("Evaluators")],
            "global_tasks": [_node_name(t) for t in editor_data.get_editor_property("GlobalTasks")],
            "state_count": len(states),
            "max_depth": max([s["depth"] for s in states], default=0),
            "states": states,
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_get_state_details(asset_path: str = None, state_path: str = None) -> str:
    """Full detail of one state including task parameters (requires the StateTree plugin)."""
    guard = _require_state_tree()
    if guard:
        return json.dumps(guard)
    if asset_path is None or state_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameters: asset_path, state_path."})
    try:
        _, editor_data, err = _load_editor_data(asset_path)
        if err:
            return json.dumps(err)

        found = [None]

        def find(state, path):
            name = str(state.get_editor_property("Name"))
            full = f"{path}/{name}"
            if full == state_path:
                found[0] = state
            for child in state.get_editor_property("Children"):
                find(child, full)

        for root in editor_data.get_editor_property("SubTrees"):
            find(root, "")

        state = found[0]
        if state is None:
            known = [s["path"] for s in _all_states(editor_data)]
            return json.dumps({"success": False,
                               "message": f"State not found: {state_path}",
                               "known_states": known})

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "state_path": state_path,
            "type": _enum_name(state.get_editor_property("Type")),
            "selection_behavior": _enum_name(state.get_editor_property("SelectionBehavior")),
            "tag": str(state.get_editor_property("Tag")),
            "tasks": [_node_params(t) for t in state.get_editor_property("Tasks")],
            "enter_conditions": [_node_params(c)
                                 for c in state.get_editor_property("EnterConditions")],
            "transitions": [t.export_text() for t in state.get_editor_property("Transitions")],
            "children": [str(c.get_editor_property("Name"))
                         for c in state.get_editor_property("Children")],
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_lint_state_tree(asset_path: str = None) -> str:
    """Flags StateTree authoring traps: dead-end empty states, finishing global tasks (requires the StateTree plugin)."""
    guard = _require_state_tree()
    if guard:
        return json.dumps(guard)
    if asset_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameter 'asset_path' is missing."})
    try:
        _, editor_data, err = _load_editor_data(asset_path)
        if err:
            return json.dumps(err)

        findings = []
        states = _all_states(editor_data)

        # A childless state with no task has nothing to call FinishTask, so under
        # scheduled tick the owner parks there indefinitely while the tree still
        # reports RUNNING. A state with children is a pass-through, not a trap.
        for s in states:
            if not s["tasks"] and s["child_count"] == 0:
                findings.append({
                    "rule": "empty_leaf_state",
                    "severity": "error",
                    "state": s["path"],
                    "message": "Leaf state has no task: nothing can complete it, so the "
                               "tree parks here while still reporting RUNNING.",
                })

        # A leaf that has tasks but no outgoing transition can only be left via a
        # parent transition — worth surfacing, not always wrong.
        for s in states:
            if s["tasks"] and s["child_count"] == 0 and s["transition_count"] == 0:
                findings.append({
                    "rule": "leaf_without_transition",
                    "severity": "warning",
                    "state": s["path"],
                    "message": "Leaf state has no outgoing transition; it can only be "
                               "left by a parent transition or task completion.",
                })

        # Global tasks run for the tree's lifetime. One that finishes terminates the
        # whole tree, so any global task at all is worth a look.
        global_tasks = [_node_name(t) for t in editor_data.get_editor_property("GlobalTasks")]
        for name in global_tasks:
            findings.append({
                "rule": "global_task_present",
                "severity": "info",
                "state": "<global>",
                "message": f"Global task '{name}' must never call FinishTask — "
                           "finishing terminates the whole StateTree.",
            })

        if not states:
            findings.append({
                "rule": "no_states",
                "severity": "error",
                "state": "<root>",
                "message": "StateTree has no states; selection cannot enter anything.",
            })

        counts = {"error": 0, "warning": 0, "info": 0}
        for f in findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "state_count": len(states),
            "finding_count": len(findings),
            "counts": counts,
            "findings": findings,
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})
