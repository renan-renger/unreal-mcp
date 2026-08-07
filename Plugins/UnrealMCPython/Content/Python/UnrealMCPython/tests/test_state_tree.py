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
