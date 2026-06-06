import unreal
from UnrealMCPython.tests.base import MCPTestCase, TEST_ROOT

_BP_NAME = "MCP_TestBlueprint"
_BP_PATH = f"{TEST_ROOT}/{_BP_NAME}"


class TestBlueprintActions(MCPTestCase):

    def setUp(self):
        self._bp_path = None
        self.ensure_test_dir()
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.BlueprintFactory()
        factory.set_editor_property('parent_class', unreal.Actor)
        bp = tools.create_asset(_BP_NAME, TEST_ROOT, unreal.Blueprint, factory)
        if bp:
            self._bp_path = _BP_PATH
            unreal.EditorAssetLibrary.save_loaded_asset(bp)

    def tearDown(self):
        if self._bp_path:
            self.delete_asset(self._bp_path)

    def _skip_if_no_bp(self):
        if not self._bp_path:
            self.skipTest("Blueprint not created in setUp")

    # ── read ──────────────────────────────────────────────────────────────────

    def test_get_graph_info(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                      asset_path=self._bp_path)
        self.assertSuccess(r)
        self.assertIn("nodes", r)

    def test_list_callable_functions(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_list_callable_functions",
                      asset_path=self._bp_path)
        self.assertSuccess(r)

    def test_list_blueprint_variables(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_list_blueprint_variables",
                      asset_path=self._bp_path)
        self.assertSuccess(r)

    def test_list_blueprint_components(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_list_blueprint_components",
                      asset_path=self._bp_path)
        self.assertSuccess(r)

    # ── write ─────────────────────────────────────────────────────────────────

    def test_add_node_and_compile(self):
        self._skip_if_no_bp()
        # K2_GetActorLocation lives in Actor, which is the parent class;
        # no "target" needed — the code searches the Blueprint's class hierarchy.
        node_json = {
            "type": "CallFunction",
            "function_name": "K2_GetActorLocation"
        }
        r = self.call("blueprint_actions", "ue_add_blueprint_node",
                      asset_path=self._bp_path,
                      graph_name="EventGraph",
                      node_json=node_json)
        self.assertSuccess(r)

        r = self.call("blueprint_actions", "ue_compile_blueprint",
                      asset_path=self._bp_path)
        self.assertSuccess(r)

    def test_add_component(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_add_component_to_blueprint",
                      asset_path=self._bp_path,
                      component_class_path="/Script/Engine.StaticMeshComponent",
                      component_name="TestMeshComp")
        self.assertSuccess(r)

    def test_add_and_remove_component(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_add_component_to_blueprint",
                      asset_path=self._bp_path,
                      component_class_path="/Script/Engine.PointLightComponent",
                      component_name="TestLightComp")
        self.assertSuccess(r)
        r = self.call("blueprint_actions", "ue_remove_component_from_blueprint",
                      asset_path=self._bp_path,
                      component_name="TestLightComp")
        self.assertSuccess(r)

    def test_auto_layout_graph(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_auto_layout_graph",
                      asset_path=self._bp_path, graph_name="EventGraph")
        self.assertSuccess(r)
