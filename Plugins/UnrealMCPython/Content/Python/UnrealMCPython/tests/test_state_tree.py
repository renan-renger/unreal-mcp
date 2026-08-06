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
