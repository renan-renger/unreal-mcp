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

# Authoring needs C++ the read path did not: the StateTree editor API is not
# script-exposed, so it lives in a separate optional plugin rather than in
# UnrealMCPython itself — a hard dependency there would force StateTree on every
# consumer project and take the whole MCP server down when it is disabled.
_HELPER_MISSING = ("Requires the UnrealMCPythonStateTree plugin. Enable it in "
                   "Edit > Plugins, then rebuild the editor with it closed.")

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


def _require_helper():
    """Returns an error dict when the authoring plugin is not loaded, else None."""
    guard = _require_state_tree()
    if guard:
        return guard
    if not hasattr(unreal, "MCPythonStateTreeHelper"):
        return {"success": False, "message": _HELPER_MISSING}
    return None


def _load_state_tree(asset_path):
    """(state_tree, error_dict). Only one is set."""
    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        return None, {"success": False, "message": f"Asset not found: {asset_path}"}

    st = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not isinstance(st, unreal.StateTree):
        got = st.get_class().get_name() if st else "None"
        return None, {"success": False,
                      "message": f"Not a StateTree asset: {asset_path} (got {got})"}
    return st, None


def _finish(payload, asset_path, save):
    """Normalises the C++ payload and, when asked, saves.

    The helper reports asset_path as an object path ("/Game/X.X"); the read actions
    report the content path the caller passed in. Overwrite so both halves of the
    domain speak the same dialect. A failed action never saves.
    """
    result = json.loads(payload)
    result["asset_path"] = asset_path
    if save and result.get("success"):
        result["saved"] = bool(unreal.EditorAssetLibrary.save_asset(asset_path))
    return json.dumps(result)


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


# ── Authoring (needs the UnrealMCPythonStateTree plugin) ──────────────────────


def ue_compile_state_tree(asset_path: str = None, save: bool = False) -> str:
    """Compiles a StateTree and returns the compiler log (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameter 'asset_path' is missing."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        return _finish(unreal.MCPythonStateTreeHelper.compile_state_tree(st), asset_path, save)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_validate_state_tree(asset_path: str = None, save: bool = False) -> str:
    """Applies schema rules and fixes up a StateTree's editor data — this WRITES (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameter 'asset_path' is missing."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        return _finish(unreal.MCPythonStateTreeHelper.validate_state_tree(st), asset_path, save)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_add_child_state(asset_path: str = None, parent_state_path: str = None,
                       name: str = None, state_type: str = "State",
                       save: bool = False) -> str:
    """Adds a state under parent_state_path, or a new subtree when it is empty (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None or name is None:
        return json.dumps({"success": False,
                           "message": "Required parameters: asset_path, name."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        # An omitted parent means "new subtree root", which the helper spells as "".
        payload = unreal.MCPythonStateTreeHelper.add_child_state(
            st, parent_state_path or "", name, state_type)
        return _finish(payload, asset_path, save)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_remove_state(asset_path: str = None, state_path: str = None,
                    save: bool = False) -> str:
    """Removes a state and everything under it (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None or state_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameters: asset_path, state_path."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        return _finish(unreal.MCPythonStateTreeHelper.remove_state(st, state_path),
                       asset_path, save)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_list_state_tree_node_types(node_kind: str = "") -> str:
    """Lists the task/condition/consideration/evaluator types a state tree can use (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    try:
        # No asset needed: this reads the reflection registry, not a tree. The helper
        # already returns a JSON string, and there is no asset_path to normalise.
        return unreal.MCPythonStateTreeHelper.list_state_tree_node_types(node_kind or "")
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_add_state_tree_node(asset_path: str = None, state_path: str = None,
                           node_kind: str = "task", node_struct: str = None,
                           save: bool = False) -> str:
    """Adds a task, condition, consideration or evaluator and returns its struct_id (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None or node_struct is None:
        return json.dumps({"success": False,
                           "message": "Required parameters: asset_path, node_struct."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        # The global kinds live on the tree, not on a state, so an omitted state_path is
        # legitimate for those and rejected by the helper for the rest.
        payload = unreal.MCPythonStateTreeHelper.add_state_tree_node(
            st, state_path or "", node_kind, node_struct)
        return _finish(payload, asset_path, save)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_remove_state_tree_node(asset_path: str = None, state_path: str = None,
                              node_kind: str = "task", struct_id: str = None,
                              save: bool = False) -> str:
    """Removes a task/condition/consideration/evaluator by struct_id (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None or struct_id is None:
        return json.dumps({"success": False,
                           "message": "Required parameters: asset_path, struct_id."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        payload = unreal.MCPythonStateTreeHelper.remove_state_tree_node(
            st, state_path or "", node_kind, struct_id)
        return _finish(payload, asset_path, save)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_get_state_tree_bindable_structs(asset_path: str = None,
                                       target_struct_id: str = "") -> str:
    """Lists the struct IDs a binding can use; with target_struct_id, what may bind into it (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameter 'asset_path' is missing."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        payload = unreal.MCPythonStateTreeHelper.get_state_tree_bindable_structs(
            st, target_struct_id or "")
        return _finish(payload, asset_path, False)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_get_state_tree_bindings(asset_path: str = None) -> str:
    """Lists a StateTree's existing property bindings (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameter 'asset_path' is missing."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        return _finish(unreal.MCPythonStateTreeHelper.get_state_tree_bindings(st),
                       asset_path, False)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_add_state_tree_binding(asset_path: str = None,
                              source_struct_id: str = None, source_path: str = None,
                              target_struct_id: str = None, target_path: str = None,
                              save: bool = False) -> str:
    """Binds one StateTree property to another; IDs come from get_state_tree_bindable_structs (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    missing = [n for n, v in (("asset_path", asset_path),
                              ("source_struct_id", source_struct_id),
                              ("source_path", source_path),
                              ("target_struct_id", target_struct_id),
                              ("target_path", target_path)) if v is None]
    if missing:
        return json.dumps({"success": False,
                           "message": f"Required parameters missing: {', '.join(missing)}."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        payload = unreal.MCPythonStateTreeHelper.add_state_tree_binding(
            st, source_struct_id, source_path, target_struct_id, target_path)
        return _finish(payload, asset_path, save)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})


def ue_remove_state_tree_binding(asset_path: str = None, target_struct_id: str = None,
                                 target_path: str = None, save: bool = False) -> str:
    """Removes whatever is bound into a StateTree property path (requires the UnrealMCPythonStateTree plugin)."""
    guard = _require_helper()
    if guard:
        return json.dumps(guard)
    if asset_path is None or target_struct_id is None or target_path is None:
        return json.dumps({"success": False,
                           "message": "Required parameters: asset_path, target_struct_id, "
                                      "target_path."})
    try:
        st, err = _load_state_tree(asset_path)
        if err:
            return json.dumps(err)
        payload = unreal.MCPythonStateTreeHelper.remove_state_tree_binding(
            st, target_struct_id, target_path)
        return _finish(payload, asset_path, save)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e),
                           "traceback": traceback.format_exc()})
