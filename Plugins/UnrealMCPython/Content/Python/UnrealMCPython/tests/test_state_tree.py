import unittest

import unreal
from UnrealMCPython.tests.base import MCPTestCase, TEST_ROOT

_ST_PATH = f"{TEST_ROOT}/MCP_TestST"


class TestStateTreeActions(MCPTestCase):
    """The StateTree plugin is optional, so every test skips when it is absent.

    Asset creation needs the factory's schema class, which is script-protected —
    hence set_class_property_raw rather than set_editor_property.

    Fixture is class-scoped, not per-test: each create/delete cycle raises a modal
    dialog on the game thread, and a modal that ever stops auto-dismissing hangs the
    whole unattended suite. One cycle per class keeps that exposure at one.
    """

    _st_path = None

    @classmethod
    def setUpClass(cls):
        cls._st_path = None
        if not hasattr(unreal, "StateTree"):
            raise unittest.SkipTest("StateTree plugin not enabled")
        if not hasattr(unreal, "StateTreeComponentSchema"):
            raise unittest.SkipTest("GameplayStateTree plugin not enabled")
        unreal.EditorAssetLibrary.make_directory(TEST_ROOT)

        # Reuse a leftover asset rather than recreating it. create_asset over an
        # existing object opens a modal "Overwrite?" dialog, which blocks the game
        # thread until a human clicks — fatal for an unattended suite. A StateTree
        # also stays rooted after it has been read, so delete_asset can legitimately
        # fail with "asset is in use" and leave the object in place.
        if unreal.EditorAssetLibrary.does_asset_exist(_ST_PATH):
            existing = unreal.EditorAssetLibrary.load_asset(_ST_PATH)
            if isinstance(existing, unreal.StateTree):
                cls._st_path = _ST_PATH
                return
            raise unittest.SkipTest(f"{_ST_PATH} exists but is not a StateTree")

        factory = unreal.StateTreeFactory()
        if not unreal.MCPythonHelper.set_class_property_raw(
                factory, "StateTreeSchemaClass", unreal.StateTreeComponentSchema):
            raise unittest.SkipTest("Could not set the factory schema class")

        tools = unreal.AssetToolsHelpers.get_asset_tools()
        asset = tools.create_asset("MCP_TestST", TEST_ROOT, unreal.StateTree, factory)
        if asset:
            cls._st_path = _ST_PATH

    @classmethod
    def tearDownClass(cls):
        # Best effort: a rooted StateTree refuses deletion, and that is fine — the
        # next run reuses it instead of prompting.
        if cls._st_path:
            cls.delete_asset(cls._st_path)
        # Same for the Blueprint task fixture, which only some tests create.
        cls.delete_asset(f"{TEST_ROOT}/MCP_TestSTTask")

    def _skip_if_no_st(self):
        if not self._st_path:
            self.skipTest("StateTree asset not created in setUp")

    # ── list ──────────────────────────────────────────────────────────────────

    def test_list_state_trees(self):
        r = self.call("state_tree_actions", "ue_list_state_trees", path=TEST_ROOT)
        self.assertSuccess(r)
        self.assertIn("state_trees", r)

    # ── structure ─────────────────────────────────────────────────────────────

    def test_get_state_tree_structure(self):
        self._skip_if_no_st()
        r = self.call("state_tree_actions", "ue_get_state_tree_structure",
                      asset_path=self._st_path)
        self.assertSuccess(r)
        self.assertGreaterEqual(r["state_count"], 1)
        self.assertEqual(r["states"][0]["depth"], 0)

    def test_get_state_tree_structure_missing_param(self):
        r = self.call("state_tree_actions", "ue_get_state_tree_structure")
        self.assertFalse(r.get("success"))

    def test_get_state_tree_structure_unknown_asset(self):
        r = self.call("state_tree_actions", "ue_get_state_tree_structure",
                      asset_path=f"{TEST_ROOT}/NoSuchST_XYZ")
        self.assertFalse(r.get("success"))

    def test_get_state_tree_structure_wrong_asset_type(self):
        self._skip_if_no_st()
        r = self.call("state_tree_actions", "ue_get_state_tree_structure",
                      asset_path="/Engine/BasicShapes/Cube")
        self.assertFalse(r.get("success"))

    # ── state details ─────────────────────────────────────────────────────────

    def test_get_state_details(self):
        self._skip_if_no_st()
        structure = self.call("state_tree_actions", "ue_get_state_tree_structure",
                              asset_path=self._st_path)
        root_path = structure["states"][0]["path"]
        r = self.call("state_tree_actions", "ue_get_state_details",
                      asset_path=self._st_path, state_path=root_path)
        self.assertSuccess(r)
        self.assertEqual(r["state_path"], root_path)

    def test_get_state_details_missing_param(self):
        r = self.call("state_tree_actions", "ue_get_state_details",
                      asset_path=_ST_PATH)
        self.assertFalse(r.get("success"))

    def test_get_state_details_unknown_state(self):
        self._skip_if_no_st()
        r = self.call("state_tree_actions", "ue_get_state_details",
                      asset_path=self._st_path, state_path="/Nope/Nowhere")
        self.assertFalse(r.get("success"))
        self.assertIn("known_states", r)

    # ── lint ──────────────────────────────────────────────────────────────────

    def test_lint_state_tree(self):
        self._skip_if_no_st()
        r = self.call("state_tree_actions", "ue_lint_state_tree",
                      asset_path=self._st_path)
        self.assertSuccess(r)
        self.assertIn("findings", r)
        self.assertIn("counts", r)

    def test_lint_state_tree_flags_empty_leaf(self):
        """A freshly created tree is a single taskless root — the exact trap the rule targets."""
        self._skip_if_no_st()
        r = self.call("state_tree_actions", "ue_lint_state_tree",
                      asset_path=self._st_path)
        self.assertSuccess(r)
        rules = [f["rule"] for f in r["findings"]]
        self.assertIn("empty_leaf_state", rules)

    def test_lint_state_tree_missing_param(self):
        r = self.call("state_tree_actions", "ue_lint_state_tree")
        self.assertFalse(r.get("success"))

    # ── authoring (UnrealMCPythonStateTree plugin) ─────────────────────────────

    def _skip_if_no_helper(self):
        self._skip_if_no_st()
        if not hasattr(unreal, "MCPythonStateTreeHelper"):
            self.skipTest("UnrealMCPythonStateTree plugin not enabled")

    def _root_path(self):
        structure = self.call("state_tree_actions", "ue_get_state_tree_structure",
                              asset_path=self._st_path)
        return structure["states"][0]["path"]

    def _state_paths(self):
        structure = self.call("state_tree_actions", "ue_get_state_tree_structure",
                              asset_path=self._st_path)
        return [s["path"] for s in structure["states"]]

    # ── compile / validate ────────────────────────────────────────────────────

    def test_compile_state_tree(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_compile_state_tree",
                      asset_path=self._st_path)
        self.assertSuccess(r)
        self.assertIsInstance(r["messages"], list)
        self.assertEqual(r["error_count"], 0)

    def test_compile_state_tree_missing_param(self):
        r = self.call("state_tree_actions", "ue_compile_state_tree")
        self.assertFalse(r.get("success"))

    def test_compile_state_tree_unknown_asset(self):
        r = self.call("state_tree_actions", "ue_compile_state_tree",
                      asset_path=f"{TEST_ROOT}/NoSuchST_XYZ")
        self.assertFalse(r.get("success"))

    def test_validate_state_tree(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_validate_state_tree",
                      asset_path=self._st_path)
        self.assertSuccess(r)
        self.assertIn("needs_recompile", r)

    def test_validate_state_tree_missing_param(self):
        r = self.call("state_tree_actions", "ue_validate_state_tree")
        self.assertFalse(r.get("success"))

    # ── structure edits ───────────────────────────────────────────────────────

    def test_add_and_remove_child_state(self):
        """Add then remove, so the shared fixture is the same size after as before."""
        self._skip_if_no_helper()
        root = self._root_path()
        before = len(self._state_paths())

        added = self.call("state_tree_actions", "ue_add_child_state",
                          asset_path=self._st_path, parent_state_path=root,
                          name="MCP_Child")
        self.assertSuccess(added)
        self.assertEqual(added["state_path"], f"{root}/MCP_Child")
        self.assertIn(added["state_path"], self._state_paths())

        removed = self.call("state_tree_actions", "ue_remove_state",
                            asset_path=self._st_path, state_path=added["state_path"])
        self.assertSuccess(removed)
        self.assertEqual(removed["removed_state_count"], 1)
        self.assertEqual(len(self._state_paths()), before)

    def test_add_and_remove_subtree(self):
        """An empty parent path means a new subtree root rather than a child."""
        self._skip_if_no_helper()
        before = len(self._state_paths())

        added = self.call("state_tree_actions", "ue_add_child_state",
                          asset_path=self._st_path, name="MCP_Subtree",
                          state_type="Group")
        self.assertSuccess(added)
        self.assertEqual(added["state_path"], "/MCP_Subtree")

        removed = self.call("state_tree_actions", "ue_remove_state",
                            asset_path=self._st_path, state_path="/MCP_Subtree")
        self.assertSuccess(removed)
        self.assertEqual(len(self._state_paths()), before)

    def test_add_child_state_missing_param(self):
        r = self.call("state_tree_actions", "ue_add_child_state",
                      asset_path=_ST_PATH)
        self.assertFalse(r.get("success"))

    def test_add_child_state_unknown_parent(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_child_state",
                      asset_path=self._st_path, parent_state_path="/Nope/Nowhere",
                      name="MCP_Orphan")
        self.assertFalse(r.get("success"))
        self.assertIn("known_states", r)

    def test_add_child_state_unknown_type(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_child_state",
                      asset_path=self._st_path, parent_state_path=self._root_path(),
                      name="MCP_BadType", state_type="NotAStateType")
        self.assertFalse(r.get("success"))

    def test_remove_state_missing_param(self):
        r = self.call("state_tree_actions", "ue_remove_state", asset_path=_ST_PATH)
        self.assertFalse(r.get("success"))

    def test_remove_state_unknown_state(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_remove_state",
                      asset_path=self._st_path, state_path="/Nope/Nowhere")
        self.assertFalse(r.get("success"))
        self.assertIn("known_states", r)

    # ── node edits ────────────────────────────────────────────────────────────

    # A task that ships with StateTreeModule. Its header is private, so nothing can
    # name the type at compile time — it is resolved by reflection name, which is the
    # whole point of taking node_struct as a string.
    _DELAY_TASK = "StateTreeDelayTask"

    def _add_host_state(self, name):
        """Adds a state to hang nodes off, and returns its path."""
        added = self.call("state_tree_actions", "ue_add_child_state",
                          asset_path=self._st_path, parent_state_path=self._root_path(),
                          name=name)
        self.assertSuccess(added)
        return added["state_path"]

    def _drop_state(self, state_path):
        self.call("state_tree_actions", "ue_remove_state",
                  asset_path=self._st_path, state_path=state_path)

    def test_list_state_tree_node_types(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_list_state_tree_node_types",
                      node_kind="task")
        self.assertSuccess(r)
        self.assertEqual(r["count"], len(r["node_types"]))
        # The engine's own delay task must be discoverable, or nothing downstream
        # can name a type to add.
        self.assertIn(self._DELAY_TASK, [t["struct"] for t in r["node_types"]])
        # Kind filtering means every result derives from that kind's base.
        self.assertEqual({t["base"] for t in r["node_types"]}, {"StateTreeTaskBase"})

    def test_list_state_tree_node_types_unknown_kind(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_list_state_tree_node_types",
                      node_kind="not_a_kind")
        self.assertFalse(r.get("success"))

    def test_add_and_remove_state_tree_node(self):
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_NodeHost")
        try:
            added = self.call("state_tree_actions", "ue_add_state_tree_node",
                              asset_path=self._st_path, state_path=host,
                              node_kind="task", node_struct=self._DELAY_TASK)
            self.assertSuccess(added)
            self.assertEqual(added["node_struct"], self._DELAY_TASK)
            self.assertTrue(added["struct_id"])

            # The node must show up as bindable, which is what makes it a binding target.
            structs = self.call("state_tree_actions", "ue_get_state_tree_bindable_structs",
                                asset_path=self._st_path)
            self.assertSuccess(structs)
            mine = [s for s in structs["structs"] if s["struct_id"] == added["struct_id"]]
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]["role"], "task")
            self.assertEqual(mine[0]["owner"], host)

            removed = self.call("state_tree_actions", "ue_remove_state_tree_node",
                                asset_path=self._st_path, state_path=host,
                                node_kind="task", struct_id=added["struct_id"])
            self.assertSuccess(removed)
            self.assertEqual(removed["removed_count"], 1)

            after = self.call("state_tree_actions", "ue_get_state_tree_bindable_structs",
                              asset_path=self._st_path)
            self.assertNotIn(added["struct_id"], [s["struct_id"] for s in after["structs"]])
        finally:
            self._drop_state(host)

    def test_add_state_tree_node_wrong_kind_for_struct(self):
        """A task struct cannot be added as a condition."""
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_WrongKind")
        try:
            r = self.call("state_tree_actions", "ue_add_state_tree_node",
                          asset_path=self._st_path, state_path=host,
                          node_kind="enter_condition", node_struct=self._DELAY_TASK)
            self.assertFalse(r.get("success"))
        finally:
            self._drop_state(host)

    def test_add_state_tree_node_unknown_struct(self):
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_UnknownStruct")
        try:
            r = self.call("state_tree_actions", "ue_add_state_tree_node",
                          asset_path=self._st_path, state_path=host,
                          node_kind="task", node_struct="NoSuchTaskXYZ")
            self.assertFalse(r.get("success"))
        finally:
            self._drop_state(host)

    def test_add_state_tree_node_unknown_kind(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_state_tree_node",
                      asset_path=self._st_path, state_path=self._root_path(),
                      node_kind="not_a_kind", node_struct=self._DELAY_TASK)
        self.assertFalse(r.get("success"))

    def test_add_state_tree_node_unknown_state(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_state_tree_node",
                      asset_path=self._st_path, state_path="/Nope/Nowhere",
                      node_kind="task", node_struct=self._DELAY_TASK)
        self.assertFalse(r.get("success"))
        self.assertIn("known_states", r)

    def test_add_state_tree_node_missing_param(self):
        r = self.call("state_tree_actions", "ue_add_state_tree_node",
                      asset_path=_ST_PATH)
        self.assertFalse(r.get("success"))

    def test_remove_state_tree_node_unknown_id(self):
        """An ID that is not in the slot is an error, not a silent no-op."""
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_RemoveUnknown")
        try:
            r = self.call("state_tree_actions", "ue_remove_state_tree_node",
                          asset_path=self._st_path, state_path=host, node_kind="task",
                          struct_id="00000000-0000-0000-0000-000000000001")
            self.assertFalse(r.get("success"))
        finally:
            self._drop_state(host)

    def test_remove_state_tree_node_missing_param(self):
        r = self.call("state_tree_actions", "ue_remove_state_tree_node",
                      asset_path=_ST_PATH)
        self.assertFalse(r.get("success"))

    # ── bindings ──────────────────────────────────────────────────────────────

    def test_get_state_tree_bindable_structs(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_get_state_tree_bindable_structs",
                      asset_path=self._st_path)
        self.assertSuccess(r)
        self.assertIsInstance(r["structs"], list)
        self.assertEqual(r["count"], len(r["structs"]))

    def test_get_state_tree_bindable_structs_bad_id(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_get_state_tree_bindable_structs",
                      asset_path=self._st_path, target_struct_id="not-a-guid")
        self.assertFalse(r.get("success"))

    def test_get_state_tree_bindable_structs_missing_param(self):
        r = self.call("state_tree_actions", "ue_get_state_tree_bindable_structs")
        self.assertFalse(r.get("success"))

    def test_get_state_tree_bindings(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_get_state_tree_bindings",
                      asset_path=self._st_path)
        self.assertSuccess(r)
        self.assertIsInstance(r["bindings"], list)
        self.assertEqual(r["count"], len(r["bindings"]))

    def test_get_state_tree_bindings_missing_param(self):
        r = self.call("state_tree_actions", "ue_get_state_tree_bindings")
        self.assertFalse(r.get("success"))

    def test_add_state_tree_binding_missing_param(self):
        r = self.call("state_tree_actions", "ue_add_state_tree_binding",
                      asset_path=_ST_PATH)
        self.assertFalse(r.get("success"))

    def test_add_state_tree_binding_bad_id(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_state_tree_binding",
                      asset_path=self._st_path,
                      source_struct_id="not-a-guid", source_path="Foo",
                      target_struct_id="not-a-guid", target_path="Bar")
        self.assertFalse(r.get("success"))

    def test_remove_state_tree_binding_missing_param(self):
        r = self.call("state_tree_actions", "ue_remove_state_tree_binding",
                      asset_path=_ST_PATH)
        self.assertFalse(r.get("success"))

    def test_binding_round_trip(self):
        """Author a binding end to end and read it back.

        The guard tests below prove the parameter checks; this is the only test that
        proves a binding can actually be written. It needs two nodes because a binding
        needs both ends, and until add_state_tree_node existed a tree built through
        this domain had none at all.
        """
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_BindHost")
        try:
            source = self.call("state_tree_actions", "ue_add_state_tree_node",
                               asset_path=self._st_path, state_path=host,
                               node_kind="task", node_struct=self._DELAY_TASK)
            self.assertSuccess(source)
            target = self.call("state_tree_actions", "ue_add_state_tree_node",
                               asset_path=self._st_path, state_path=host,
                               node_kind="task", node_struct=self._DELAY_TASK)
            self.assertSuccess(target)

            before = self.call("state_tree_actions", "ue_get_state_tree_bindings",
                               asset_path=self._st_path)["count"]

            bound = self.call("state_tree_actions", "ue_add_state_tree_binding",
                              asset_path=self._st_path,
                              source_struct_id=source["struct_id"], source_path="Duration",
                              target_struct_id=target["struct_id"], target_path="Duration")
            self.assertSuccess(bound)

            listed = self.call("state_tree_actions", "ue_get_state_tree_bindings",
                               asset_path=self._st_path)
            self.assertSuccess(listed)
            self.assertEqual(listed["count"], before + 1)
            # Assert on content, not just on the count: a binding that lists with the
            # wrong endpoints would satisfy a length check. resolved=True is the part
            # that matters — it means the engine matched the path to a real property,
            # not that a string was stored.
            mine = [b for b in listed["bindings"]
                    if b["target"]["struct_id"].lower() == target["struct_id"].lower()]
            self.assertEqual(len(mine), 1, listed["bindings"])
            self.assertEqual(mine[0]["target"]["path"], "Duration")
            self.assertTrue(mine[0]["target"]["resolved"])
            self.assertEqual(mine[0]["source"]["struct_id"].lower(),
                             source["struct_id"].lower())
            self.assertEqual(mine[0]["source"]["path"], "Duration")

            removed = self.call("state_tree_actions", "ue_remove_state_tree_binding",
                                asset_path=self._st_path,
                                target_struct_id=target["struct_id"], target_path="Duration")
            self.assertSuccess(removed)
            self.assertEqual(removed["removed_count"], 1)
            self.assertEqual(
                self.call("state_tree_actions", "ue_get_state_tree_bindings",
                          asset_path=self._st_path)["count"], before)
        finally:
            self._drop_state(host)

    def test_remove_state_tree_binding_bad_id(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_remove_state_tree_binding",
                      asset_path=self._st_path,
                      target_struct_id="not-a-guid", target_path="Bar")
        self.assertFalse(r.get("success"))

    # ── transitions ───────────────────────────────────────────────────────────

    def test_transition_round_trip(self):
        """Author a transition end to end and read it back.

        Like the binding round trip, this is the only test that proves a transition
        can actually be written; the guards below only prove the parameter checks.
        It needs two states because a GotoState transition needs somewhere to go.
        """
        self._skip_if_no_helper()
        source = self._add_host_state("MCP_TransFrom")
        target = self._add_host_state("MCP_TransTo")
        try:
            before = self.call("state_tree_actions", "ue_get_state_tree_transitions",
                               asset_path=self._st_path, state_path=source)
            self.assertSuccess(before)

            added = self.call("state_tree_actions", "ue_add_state_tree_transition",
                              asset_path=self._st_path, state_path=source,
                              trigger="OnStateCompleted", transition_type="GotoState",
                              target_state_path=target, priority="High")
            self.assertSuccess(added)

            listed = self.call("state_tree_actions", "ue_get_state_tree_transitions",
                               asset_path=self._st_path, state_path=source)
            self.assertSuccess(listed)
            self.assertEqual(listed["count"], before["count"] + 1)
            # Assert on content, not just the count: a transition stored with the
            # wrong trigger or a target that never resolved would still satisfy a
            # length check.
            mine = listed["transitions"][added["index"]]
            self.assertEqual(mine["trigger"], "OnStateCompleted")
            self.assertEqual(mine["transition_type"], "GotoState")
            self.assertEqual(mine["priority"], "High")
            self.assertEqual(mine["target_state"], target.rsplit("/", 1)[-1])

            removed = self.call("state_tree_actions", "ue_remove_state_tree_transition",
                                asset_path=self._st_path, state_path=source,
                                index=added["index"])
            self.assertSuccess(removed)
            self.assertEqual(removed["count"], before["count"])
        finally:
            self._drop_state(source)
            self._drop_state(target)

    def test_add_state_tree_transition_delay(self):
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_TransDelay")
        try:
            r = self.call("state_tree_actions", "ue_add_state_tree_transition",
                          asset_path=self._st_path, state_path=host,
                          transition_type="Succeeded", delay_duration=2.5)
            self.assertSuccess(r)
            self.assertTrue(r["delay_transition"])
            self.assertAlmostEqual(r["delay_duration"], 2.5, places=3)
        finally:
            self._drop_state(host)

    def test_add_state_tree_transition_rejects_target_without_goto(self):
        """A target path on a non-GotoState transition would be silently dropped."""
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_TransBadTarget")
        try:
            r = self.call("state_tree_actions", "ue_add_state_tree_transition",
                          asset_path=self._st_path, state_path=host,
                          transition_type="Succeeded", target_state_path=self._root_path())
            self.assertFalse(r.get("success"))
        finally:
            self._drop_state(host)

    def test_add_state_tree_transition_goto_needs_target(self):
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_TransNoTarget")
        try:
            r = self.call("state_tree_actions", "ue_add_state_tree_transition",
                          asset_path=self._st_path, state_path=host,
                          transition_type="GotoState")
            self.assertFalse(r.get("success"))
        finally:
            self._drop_state(host)

    def test_add_state_tree_transition_unknown_trigger(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_state_tree_transition",
                      asset_path=self._st_path, state_path=self._root_path(),
                      trigger="OnBananas", transition_type="Succeeded")
        self.assertFalse(r.get("success"))

    def test_add_state_tree_transition_missing_param(self):
        r = self.call("state_tree_actions", "ue_add_state_tree_transition")
        self.assertFalse(r.get("success"))

    def test_get_state_tree_transitions_missing_param(self):
        r = self.call("state_tree_actions", "ue_get_state_tree_transitions")
        self.assertFalse(r.get("success"))

    def test_get_state_tree_transitions_unknown_state(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_get_state_tree_transitions",
                      asset_path=self._st_path, state_path="/NoSuchState")
        self.assertFalse(r.get("success"))

    def test_remove_state_tree_transition_out_of_range(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_remove_state_tree_transition",
                      asset_path=self._st_path, state_path=self._root_path(), index=9999)
        self.assertFalse(r.get("success"))

    def test_remove_state_tree_transition_missing_param(self):
        r = self.call("state_tree_actions", "ue_remove_state_tree_transition")
        self.assertFalse(r.get("success"))

    # ── selection behaviour ───────────────────────────────────────────────────

    def test_set_state_selection_behavior_round_trip(self):
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_SelBehavior")
        try:
            r = self.call("state_tree_actions", "ue_set_state_selection_behavior",
                          asset_path=self._st_path, state_path=host,
                          behavior="TrySelectChildrenWithHighestUtility")
            self.assertSuccess(r)
            self.assertEqual(r["selection_behavior"], "TrySelectChildrenWithHighestUtility")
            self.assertEqual(r["previous_behavior"], "TrySelectChildrenInOrder")
            # Read it back through the structure reader, not just the write's own echo.
            details = self.call("state_tree_actions", "ue_get_state_details",
                                asset_path=self._st_path, state_path=host)
            self.assertSuccess(details)
            self.assertEqual(details["selection_behavior"], "TRY_SELECT_CHILDREN_WITH_HIGHEST_UTILITY")
        finally:
            self._drop_state(host)

    def test_set_state_selection_behavior_unknown(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_set_state_selection_behavior",
                      asset_path=self._st_path, state_path=self._root_path(),
                      behavior="TrySelectChildrenTelepathically")
        self.assertFalse(r.get("success"))

    def test_set_state_selection_behavior_missing_param(self):
        r = self.call("state_tree_actions", "ue_set_state_selection_behavior")
        self.assertFalse(r.get("success"))

    # ── Blueprint nodes ───────────────────────────────────────────────────────

    _BP_TASK_PATH = TEST_ROOT + "/MCP_TestSTTask"

    def _ensure_bp_task(self):
        """Authors a Blueprint task class to add, or skips when that is impossible.

        The sample project ships no Blueprint tasks, so the round trip has to make
        its own. Reused across tests rather than recreated: create_asset over an
        existing object opens a blocking modal, same trap as the tree fixture.
        """
        if not hasattr(unreal, "StateTreeTaskBlueprintBase"):
            self.skipTest("StateTreeTaskBlueprintBase is not exposed to Python")
        if unreal.EditorAssetLibrary.does_asset_exist(self._BP_TASK_PATH):
            return self._BP_TASK_PATH
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", unreal.StateTreeTaskBlueprintBase)
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "MCP_TestSTTask", TEST_ROOT, unreal.Blueprint, factory)
        if not asset:
            self.skipTest("Could not create a Blueprint task asset")
        return self._BP_TASK_PATH

    def test_list_state_tree_blueprint_nodes(self):
        self._skip_if_no_helper()
        self._ensure_bp_task()
        r = self.call("state_tree_actions", "ue_list_state_tree_blueprint_nodes",
                      node_kind="task")
        self.assertSuccess(r)
        self.assertEqual(r["count"], len(r["blueprint_nodes"]))
        self.assertEqual(r["blueprint_base"], "StateTreeTaskBlueprintBase")
        # The task we just authored must be discoverable, or nothing downstream
        # can reference it.
        names = [n["name"] for n in r["blueprint_nodes"]]
        self.assertIn("MCP_TestSTTask_C", names)

    def test_list_state_tree_blueprint_nodes_unknown_kind(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_list_state_tree_blueprint_nodes",
                      node_kind="nonsense")
        self.assertFalse(r.get("success"))

    def test_blueprint_node_round_trip(self):
        """Add a Blueprint task by class path and read it back off the state.

        This is the action that closes StateTree authoring end to end: without it a
        tree built through MCP could only ever use engine-native tasks.
        """
        self._skip_if_no_helper()
        bp = self._ensure_bp_task()
        host = self._add_host_state("MCP_BPNodeHost")
        try:
            added = self.call("state_tree_actions", "ue_add_state_tree_blueprint_node",
                              asset_path=self._st_path, state_path=host,
                              node_kind="task", blueprint_class=bp)
            self.assertSuccess(added)
            self.assertTrue(added["blueprint_class"].endswith("MCP_TestSTTask_C"))

            # Read back through the structure reader: the write's own echo would pass
            # even if the wrapper never took the class.
            details = self.call("state_tree_actions", "ue_get_state_details",
                                asset_path=self._st_path, state_path=host)
            self.assertSuccess(details)
            blueprint_tasks = [t for t in details["tasks"] if t.get("kind") == "blueprint"]
            self.assertEqual(len(blueprint_tasks), 1, details["tasks"])
            self.assertEqual(blueprint_tasks[0]["class"], "MCP_TestSTTask_C")

            removed = self.call("state_tree_actions", "ue_remove_state_tree_node",
                                asset_path=self._st_path, state_path=host,
                                node_kind="task", struct_id=added["struct_id"])
            self.assertSuccess(removed)
        finally:
            self._drop_state(host)

    def test_add_state_tree_blueprint_node_accepts_generated_class_path(self):
        """Both /Game/X and /Game/X.X_C must resolve, since callers have either."""
        self._skip_if_no_helper()
        bp = self._ensure_bp_task()
        host = self._add_host_state("MCP_BPNodePathForm")
        try:
            generated = f"{bp}.{bp.rsplit('/', 1)[-1]}_C"
            r = self.call("state_tree_actions", "ue_add_state_tree_blueprint_node",
                          asset_path=self._st_path, state_path=host,
                          node_kind="task", blueprint_class=generated)
            self.assertSuccess(r)
        finally:
            self._drop_state(host)

    def test_add_state_tree_blueprint_node_wrong_base(self):
        """A Blueprint task is not a condition; adding it as one must fail."""
        self._skip_if_no_helper()
        bp = self._ensure_bp_task()
        host = self._add_host_state("MCP_BPNodeWrongBase")
        try:
            r = self.call("state_tree_actions", "ue_add_state_tree_blueprint_node",
                          asset_path=self._st_path, state_path=host,
                          node_kind="enter_condition", blueprint_class=bp)
            self.assertFalse(r.get("success"))
        finally:
            self._drop_state(host)

    def test_add_state_tree_blueprint_node_unknown_class(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_state_tree_blueprint_node",
                      asset_path=self._st_path, state_path=self._root_path(),
                      node_kind="task", blueprint_class="/Game/Nope/DoesNotExist")
        self.assertFalse(r.get("success"))

    def test_add_state_tree_blueprint_node_missing_param(self):
        r = self.call("state_tree_actions", "ue_add_state_tree_blueprint_node")
        self.assertFalse(r.get("success"))

    # ── crash guards ──────────────────────────────────────────────────────────

    def test_list_state_tree_blueprint_nodes_excludes_compiler_artefacts(self):
        """SKEL_/REINST_/TRASHCLASS_ classes are registered but unusable as nodes.

        Listing them doubled the result in a real project and every one of them
        fails on add, so the list has to filter them.
        """
        self._skip_if_no_helper()
        self._ensure_bp_task()
        r = self.call("state_tree_actions", "ue_list_state_tree_blueprint_nodes",
                      node_kind="task")
        self.assertSuccess(r)
        names = [n["name"] for n in r["blueprint_nodes"]]
        self.assertIn("MCP_TestSTTask_C", names)
        bad = [n for n in names
               if n.startswith(("SKEL_", "REINST_", "TRASHCLASS_"))]
        self.assertEqual(bad, [], f"compiler artefacts leaked into the list: {bad}")

    def test_add_state_tree_binding_rejects_struct_root_into_property_ref(self):
        """A PropertyRef bound to a struct root crashes the compiler, so refuse it.

        Regression test for a hard editor crash: the binding was accepted and
        reported resolved=True, then compile_state_tree died on
        `Assertion failed: (Index >= 0) & (Index < ArrayNum)` inside
        IsPropertyAccessibleForPropertyRef. Guarding at bind time is the only place
        the caller can still be told something useful.

        This project ships no node carrying a PropertyRef, and one cannot be authored
        from here — `add_variable` has no PropertyRef type. So the test skips rather
        than asserting something it did not exercise. The guard was verified by hand
        against the original crash repro in a project that does have such tasks
        (MadorasRebirth: STT_SelectSlot.Slot, STT_Cooldown.CooldownPropRef).
        """
        self._skip_if_no_helper()
        self.skipTest("no PropertyRef-bearing node available in this project to bind against")

    def test_add_state_tree_binding_still_allows_struct_root_for_plain_targets(self):
        """The guard must not block ordinary struct-root bindings, which are valid."""
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_PlainRootBind")
        try:
            src = self.call("state_tree_actions", "ue_add_state_tree_node",
                            asset_path=self._st_path, state_path=host,
                            node_kind="task", node_struct=self._DELAY_TASK)
            self.assertSuccess(src)
            tgt = self.call("state_tree_actions", "ue_add_state_tree_node",
                            asset_path=self._st_path, state_path=host,
                            node_kind="task", node_struct=self._DELAY_TASK)
            self.assertSuccess(tgt)
            # Duration is a plain float, not a PropertyRef: a normal binding, unaffected.
            r = self.call("state_tree_actions", "ue_add_state_tree_binding",
                          asset_path=self._st_path,
                          source_struct_id=src["struct_id"], source_path="Duration",
                          target_struct_id=tgt["struct_id"], target_path="Duration")
            self.assertSuccess(r)
        finally:
            self._drop_state(host)

    # ── parameters ────────────────────────────────────────────────────────────

    def test_parameter_round_trip_root(self):
        """Add a root parameter, read it back, remove it.

        Root parameters are the thing a property reference binds to; without them
        a tree using any PropertyRef-bearing task cannot be compiled at all.
        """
        self._skip_if_no_helper()
        before = self.call("state_tree_actions", "ue_list_state_tree_parameters",
                           asset_path=self._st_path)
        self.assertSuccess(before)
        try:
            added = self.call("state_tree_actions", "ue_add_state_tree_parameter",
                              asset_path=self._st_path, name="MCP_Quota", param_type="Int32")
            self.assertSuccess(added)
            self.assertEqual(added["type"], "Int32")
            # The struct_id is what a binding needs as its source; without it the
            # parameter is unreachable even though it exists.
            self.assertTrue(added["struct_id"])

            listed = self.call("state_tree_actions", "ue_list_state_tree_parameters",
                               asset_path=self._st_path)
            self.assertSuccess(listed)
            self.assertEqual(listed["count"], before["count"] + 1)
            mine = [p for p in listed["parameters"] if p["name"] == "MCP_Quota"]
            self.assertEqual(len(mine), 1, listed["parameters"])
            self.assertEqual(mine[0]["type"], "Int32")
        finally:
            self.call("state_tree_actions", "ue_remove_state_tree_parameter",
                      asset_path=self._st_path, name="MCP_Quota")
        after = self.call("state_tree_actions", "ue_list_state_tree_parameters",
                          asset_path=self._st_path)
        self.assertEqual(after["count"], before["count"])

    def test_parameter_on_a_state(self):
        self._skip_if_no_helper()
        host = self._add_host_state("MCP_ParamState")
        try:
            r = self.call("state_tree_actions", "ue_add_state_tree_parameter",
                          asset_path=self._st_path, state_path=host,
                          name="MCP_StateParam", param_type="Float")
            self.assertSuccess(r)
            listed = self.call("state_tree_actions", "ue_list_state_tree_parameters",
                               asset_path=self._st_path, state_path=host)
            self.assertSuccess(listed)
            self.assertEqual([p["name"] for p in listed["parameters"]], ["MCP_StateParam"])
            # A state parameter must not leak into the root bag.
            root = self.call("state_tree_actions", "ue_list_state_tree_parameters",
                             asset_path=self._st_path)
            self.assertNotIn("MCP_StateParam", [p["name"] for p in root["parameters"]])
        finally:
            self._drop_state(host)

    def test_add_state_tree_parameter_rejects_duplicate(self):
        """Overwriting would silently break every binding pointing at the old one."""
        self._skip_if_no_helper()
        self.call("state_tree_actions", "ue_add_state_tree_parameter",
                  asset_path=self._st_path, name="MCP_Dup", param_type="Bool")
        try:
            again = self.call("state_tree_actions", "ue_add_state_tree_parameter",
                              asset_path=self._st_path, name="MCP_Dup", param_type="Bool")
            self.assertFalse(again.get("success"))
        finally:
            self.call("state_tree_actions", "ue_remove_state_tree_parameter",
                      asset_path=self._st_path, name="MCP_Dup")

    def test_add_state_tree_parameter_struct_needs_value_type_object(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_state_tree_parameter",
                      asset_path=self._st_path, name="MCP_NoStruct", param_type="Struct")
        self.assertFalse(r.get("success"))

    def test_add_state_tree_parameter_scalar_rejects_value_type_object(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_state_tree_parameter",
                      asset_path=self._st_path, name="MCP_BadScalar", param_type="Int32",
                      value_type_object="/Script/CoreUObject.Vector")
        self.assertFalse(r.get("success"))

    def test_add_state_tree_parameter_unknown_type(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_add_state_tree_parameter",
                      asset_path=self._st_path, name="MCP_BadType", param_type="Quaternion")
        self.assertFalse(r.get("success"))

    def test_add_state_tree_parameter_missing_param(self):
        r = self.call("state_tree_actions", "ue_add_state_tree_parameter")
        self.assertFalse(r.get("success"))

    def test_remove_state_tree_parameter_unknown(self):
        self._skip_if_no_helper()
        r = self.call("state_tree_actions", "ue_remove_state_tree_parameter",
                      asset_path=self._st_path, name="MCP_NeverExisted")
        self.assertFalse(r.get("success"))

    def test_list_state_tree_parameters_missing_param(self):
        r = self.call("state_tree_actions", "ue_list_state_tree_parameters")
        self.assertFalse(r.get("success"))
