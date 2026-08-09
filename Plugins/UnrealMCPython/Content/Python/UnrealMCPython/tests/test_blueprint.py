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

    # ── selection queries ───────────────────────────────────────────────────────

    def test_get_selected_bp_nodes(self):
        r = self.call("blueprint_actions", "ue_get_selected_bp_nodes")
        self.assertSuccess(r)
        self.assertIn("selected_nodes", r)

    def test_get_selected_bp_node_infos(self):
        r = self.call("blueprint_actions", "ue_get_selected_bp_node_infos")
        self.assertSuccess(r)
        self.assertIn("nodes", r)

    # ── node position / remove ──────────────────────────────────────────────────

    def _add_node(self, **node_json):
        r = self.call("blueprint_actions", "ue_add_blueprint_node",
                      asset_path=self._bp_path, graph_name="EventGraph",
                      node_json=node_json)
        self.assertSuccess(r)
        return r["node_name"]

    def test_set_blueprint_node_position(self):
        self._skip_if_no_bp()
        node = self._add_node(type="CallFunction", function_name="K2_GetActorLocation")
        r = self.call("blueprint_actions", "ue_set_blueprint_node_position",
                      asset_path=self._bp_path, graph_name="EventGraph",
                      node_name=node, pos_x=320.0, pos_y=128.0)
        self.assertSuccess(r)

    def test_remove_blueprint_node(self):
        self._skip_if_no_bp()
        node = self._add_node(type="CallFunction", function_name="K2_GetActorLocation")
        r = self.call("blueprint_actions", "ue_remove_blueprint_node",
                      asset_path=self._bp_path, graph_name="EventGraph",
                      node_name=node)
        self.assertSuccess(r)

    # ── event dispatchers ───────────────────────────────────────────────────────

    def _add_node_raw(self, **node_json):
        return self.call("blueprint_actions", "ue_add_blueprint_node",
                         asset_path=self._bp_path, graph_name="EventGraph",
                         node_json=node_json)

    def test_add_delegate_node_on_self(self):
        self._skip_if_no_bp()
        # OnDestroyed comes from Actor, the parent class, so the Blueprint's own class owns it
        self._add_node(type="AddDelegate", delegate_name="OnDestroyed")
        r = self.call("blueprint_actions", "ue_compile_blueprint", asset_path=self._bp_path)
        self.assertSuccess(r)

    def test_add_delegate_node_on_external_class(self):
        self._skip_if_no_bp()
        r = self._add_node_raw(type="AddDelegate", delegate_name="OnClicked",
                               delegate_class="/Script/UMG.Button")
        self.assertSuccess(r)

    def test_call_delegate_node(self):
        self._skip_if_no_bp()
        r = self._add_node_raw(type="CallDelegate", delegate_name="OnDestroyed")
        self.assertSuccess(r)

    def test_delegate_node_unknown_name_rejected(self):
        self._skip_if_no_bp()
        r = self._add_node_raw(type="AddDelegate", delegate_name="OnNope_XYZ")
        self.assertFalse(r.get("success"))

    def test_delegate_node_unknown_class_rejected(self):
        self._skip_if_no_bp()
        r = self._add_node_raw(type="AddDelegate", delegate_name="OnClicked",
                               delegate_class="/Script/UMG.NotAClass_XYZ")
        self.assertFalse(r.get("success"))

    def test_delegate_node_missing_name(self):
        self._skip_if_no_bp()
        r = self._add_node_raw(type="AddDelegate")
        self.assertFalse(r.get("success"))

    def test_custom_event_takes_delegate_signature(self):
        self._skip_if_no_bp()
        # Without a signature the handler has no parameters and silently drops what the
        # dispatcher passes; OnTakeAnyDamage carries Damage among others.
        r = self._add_node_raw(type="CustomEvent", event_name="HandleDamage",
                               delegate_signature="OnTakeAnyDamage")
        self.assertSuccess(r)
        pin_names = [p.get("pin_name") for p in r.get("pins", [])]
        self.assertIn("Damage", pin_names)

    def test_custom_event_unknown_delegate_signature_rejected(self):
        self._skip_if_no_bp()
        r = self._add_node_raw(type="CustomEvent", event_name="HandleNothing",
                               delegate_signature="OnNope_XYZ")
        self.assertFalse(r.get("success"))

    def test_custom_event_without_signature_still_works(self):
        self._skip_if_no_bp()
        r = self._add_node_raw(type="CustomEvent", event_name="PlainEvent")
        self.assertSuccess(r)

    # ── connect pins ────────────────────────────────────────────────────────────

    def test_connect_blueprint_pins(self):
        self._skip_if_no_bp()
        event = self._add_node(type="Event", event_name="ReceiveBeginPlay")
        setter = self._add_node(type="CallFunction", function_name="K2_SetActorLocation")
        r = self.call("blueprint_actions", "ue_connect_blueprint_pins",
                      asset_path=self._bp_path, graph_name="EventGraph",
                      source_node=event, source_pin="then",
                      target_node=setter, target_pin="execute")
        self.assertSuccess(r)

    def _pin_type(self, node_name, pin_name):
        r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                      asset_path=self._bp_path, graph_name="EventGraph")
        self.assertSuccess(r)
        for node in r.get("nodes", []):
            if node.get("node_name") != node_name:
                continue
            for pin in node.get("pins", []):
                if pin.get("pin_name") == pin_name:
                    return pin.get("type")
        return None

    def test_connect_resolves_a_wildcard_pin(self):
        self._skip_if_no_bp()
        # A wildcard only resolves inside PinConnectionListChanged, which MakeLinkTo
        # does not call: without the notification Array_Add keeps NewItem as a wildcard
        # and the graph fails to compile while looking correctly wired.
        # ForEachLoop takes a wildcard array and derives Array Element from it;
        # GetAllActorsOfClass hands back an Actor array to resolve it against.
        loop = self._add_node(type="MacroInstance", macro_name="ForEachLoop")
        source = self._add_node(type="CallFunction", function_name="GetAllActorsOfClass",
                                target="GameplayStatics")
        self.assertEqual(self._pin_type(loop, "Array Element"), "wildcard")
        r = self.call("blueprint_actions", "ue_connect_blueprint_pins",
                      asset_path=self._bp_path, graph_name="EventGraph",
                      source_node=source, source_pin="OutActors",
                      target_node=loop, target_pin="Array")
        self.assertSuccess(r)
        self.assertEqual(self._pin_type(loop, "Array Element"), "object")

    # ── build whole graph ───────────────────────────────────────────────────────

    def test_build_blueprint_graph(self):
        self._skip_if_no_bp()
        structure = {
            "nodes": [
                {"id": "evt", "type": "Event", "event_name": "ReceiveBeginPlay"},
                {"id": "loc", "type": "CallFunction", "function_name": "K2_GetActorLocation"},
            ],
            "connections": [],
        }
        r = self.call("blueprint_actions", "ue_build_blueprint_graph",
                      asset_path=self._bp_path, graph_name="EventGraph",
                      graph_structure=structure)
        self.assertSuccess(r)

    # ── component property ──────────────────────────────────────────────────────

    def test_set_component_property(self):
        self._skip_if_no_bp()
        self.call("blueprint_actions", "ue_add_component_to_blueprint",
                  asset_path=self._bp_path,
                  component_class_path="/Script/Engine.PointLightComponent",
                  component_name="PropLightComp")
        r = self.call("blueprint_actions", "ue_set_component_property",
                      asset_path=self._bp_path, component_name="PropLightComp",
                      property_name="Intensity", value="5000.0")
        self.assertSuccess(r)

    def test_create_blueprint(self):
        import unreal
        from UnrealMCPython.tests.base import TEST_ROOT
        path = f"{TEST_ROOT}/MCP_CreatedBP"
        self.delete_asset(path)
        try:
            r = self.call("blueprint_actions", "ue_create_blueprint",
                          asset_path=path, parent_class_path="/Script/Engine.Actor")
            self.assertSuccess(r)
            self.assertTrue(unreal.EditorAssetLibrary.does_asset_exist(path))
        finally:
            self.delete_asset(path)

    def test_create_blueprint_bad_parent(self):
        from UnrealMCPython.tests.base import TEST_ROOT
        r = self.call("blueprint_actions", "ue_create_blueprint",
                      asset_path=f"{TEST_ROOT}/MCP_BadBP", parent_class_path="/Script/Engine.NopeXYZ")
        self.assertFalse(r.get("success"))

    def test_add_variable(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_add_variable",
                      asset_path=self._bp_path, variable_name="MyFloatVar", variable_type="float")
        self.assertSuccess(r)
        variables = self.call("blueprint_actions", "ue_list_blueprint_variables",
                              asset_path=self._bp_path)
        self.assertSuccess(variables)

    def test_add_variable_bad_type(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_add_variable",
                      asset_path=self._bp_path, variable_name="X", variable_type="notatype")
        self.assertFalse(r.get("success"))

    def test_set_variable_flags(self):
        self._skip_if_no_bp()
        self.call("blueprint_actions", "ue_add_variable",
                  asset_path=self._bp_path, variable_name="FlagVar", variable_type="bool")
        r = self.call("blueprint_actions", "ue_set_variable_flags",
                      asset_path=self._bp_path, variable_name="FlagVar",
                      instance_editable=True, expose_on_spawn=True)
        self.assertSuccess(r)
        self.assertTrue(r["applied"]["instance_editable"])

    def test_set_variable_flags_none(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_set_variable_flags",
                      asset_path=self._bp_path, variable_name="X")
        self.assertFalse(r.get("success"))
