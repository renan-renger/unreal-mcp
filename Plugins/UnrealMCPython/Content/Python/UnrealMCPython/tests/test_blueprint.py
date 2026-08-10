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

    # ── graph enumeration & path resolution ───────────────────────────────────
    #
    # These cover the graph forest walk: a Blueprint's graphs are a tree, not a
    # flat list, and collapsed graphs (K2Node_Composite) used to be unreachable
    # by every action that takes graph_name.
    #
    # A collapsed graph cannot be authored from Python (K2Node_Composite::BoundGraph
    # is not editor-exposed and there is no collapse API), so the nested cases below
    # build the fixture reflectively and skip when the engine refuses. The real
    # nesting check is a manual one against an asset that already has a collapsed
    # graph — see test_nested_graph_resolution's docstring.

    def _graphs(self):
        r = self.call("blueprint_actions", "ue_list_blueprint_graphs",
                      asset_path=self._bp_path)
        self.assertSuccess(r)
        return r

    def test_list_blueprint_graphs(self):
        self._skip_if_no_bp()
        r = self._graphs()
        self.assertEqual(r["graph_count"], len(r["graphs"]))
        self.assertGreater(r["graph_count"], 0, "a Blueprint always has at least one graph")

        for g in r["graphs"]:
            for key in ("path", "name", "root_kind", "depth", "node_count", "name_is_unique"):
                self.assertIn(key, g, f"missing '{key}' in {g}")
            # A root graph's path is just its name; a nested one is parent/child.
            if g["depth"] == 0:
                self.assertEqual(g["path"], g["name"])
            else:
                self.assertTrue(g["path"].endswith("/" + g["name"]))
            self.assertEqual(g["path"].count("/"), g["depth"])

    def test_list_blueprint_graphs_includes_event_graph(self):
        self._skip_if_no_bp()
        r = self._graphs()
        ubergraphs = [g for g in r["graphs"] if g["root_kind"] == "Ubergraph"]
        self.assertTrue(ubergraphs, f"expected at least one Ubergraph: {r['graphs']}")

    def test_list_blueprint_graphs_missing_param(self):
        r = self.call("blueprint_actions", "ue_list_blueprint_graphs")
        self.assertFalse(r.get("success"))

    def test_list_blueprint_graphs_unknown_asset(self):
        r = self.call("blueprint_actions", "ue_list_blueprint_graphs",
                      asset_path=f"{TEST_ROOT}/MCP_NoSuchBlueprint")
        self.assertFalse(r.get("success"))

    def test_every_listed_graph_resolves_by_full_path(self):
        """Whatever list_blueprint_graphs advertises must be addressable as-is."""
        self._skip_if_no_bp()
        for g in self._graphs()["graphs"]:
            r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                          asset_path=self._bp_path, graph_name=g["path"])
            self.assertSuccess(r, f"full path '{g['path']}' did not resolve: {r}")

    def test_unique_graph_resolves_by_bare_name(self):
        """A leaf name that occurs once is addressable without any path."""
        self._skip_if_no_bp()
        unique = [g for g in self._graphs()["graphs"] if g["name_is_unique"]]
        if not unique:
            self.skipTest("no uniquely-named graph in this Blueprint")
        for g in unique:
            r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                          asset_path=self._bp_path, graph_name=g["name"])
            self.assertSuccess(r, f"bare name '{g['name']}' did not resolve: {r}")

    def test_function_graph_resolves(self):
        """Regression: function graphs stay reachable after the resolver rewrite."""
        self._skip_if_no_bp()
        funcs = [g for g in self._graphs()["graphs"] if g["root_kind"] == "Function"]
        if not funcs:
            self.skipTest("Blueprint has no function graph")
        r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                      asset_path=self._bp_path, graph_name=funcs[0]["path"])
        self.assertSuccess(r)

    def test_unknown_graph_error_lists_available_graphs(self):
        """The failure must be actionable, not a dead end.

        The old message was just "Graph 'X' not found in Blueprint." with no way to
        discover real names — the gap that made collapsed graphs undebuggable.
        """
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                      asset_path=self._bp_path, graph_name="NoSuchGraph_XYZ")
        self.assertFalse(r.get("success"))
        msg = r.get("message", "")
        self.assertIn("Available graphs", msg, f"error is not actionable: {msg}")
        some_real_graph = self._graphs()["graphs"][0]["name"]
        self.assertIn(some_real_graph, msg)

    def test_empty_graph_name_is_rejected(self):
        self._skip_if_no_bp()
        r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                      asset_path=self._bp_path, graph_name="   ")
        self.assertFalse(r.get("success"))

    def test_path_separators_are_normalised(self):
        """Stray/duplicated slashes must not change resolution."""
        self._skip_if_no_bp()
        target = self._graphs()["graphs"][0]["path"]
        for variant in (f"/{target}", f"{target}/", f"//{target}//"):
            r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                          asset_path=self._bp_path, graph_name=variant)
            self.assertSuccess(r, f"variant '{variant}' did not resolve: {r}")

    # ── nested (collapsed) graphs ─────────────────────────────────────────────

    def _try_make_collapsed_graph(self, name):
        """Build a minimal K2Node_Composite + BoundGraph, or return None.

        Only BoundGraph needs to be set: the resolver finds children through the
        base-class virtual UEdGraphNode::GetSubGraphs(), which K2Node_Composite
        overrides to return exactly that graph. Tunnel nodes and a compilable
        interior are irrelevant to *resolution*, so the fixture stays minimal.
        """
        try:
            bp = unreal.EditorAssetLibrary.load_asset(self._bp_path)
            event_graph = bp.get_editor_property("uber_graph_pages")[0]
            bound = unreal.new_object(unreal.EdGraph, outer=bp, name=name)
            composite = unreal.new_object(unreal.K2Node_Composite, outer=event_graph)
            composite.set_editor_property("bound_graph", bound)
            event_graph.get_editor_property("nodes").append(composite)
            return bound
        except Exception:
            return None

    def test_nested_graph_resolution(self):
        """Collapsed graphs resolve by bare name and by path.

        Skips when the fixture cannot be built from Python. The authoritative
        manual check, against a Blueprint that really has one:
            blueprint list_blueprint_graphs {"asset_path": "<BP>"}
            blueprint get_blueprint_graph_info {"asset_path": "<BP>",
                                                "graph_name": "EventGraph/<Collapsed>"}
        """
        self._skip_if_no_bp()
        before = self._graphs()["graph_count"]
        if self._try_make_collapsed_graph("MCP_Collapsed") is None:
            self.skipTest("cannot author a K2Node_Composite from Python")

        after = self._graphs()
        self.assertEqual(after["graph_count"], before + 1,
                         "collapsed graph was not enumerated")

        nested = [g for g in after["graphs"] if g["name"] == "MCP_Collapsed"]
        self.assertEqual(len(nested), 1)
        self.assertEqual(nested[0]["depth"], 1)
        self.assertIn("/", nested[0]["path"])
        self.assertEqual(nested[0]["owning_node_class"], "K2Node_Composite")

        # Reachable by bare name and by full path — the whole point of the change.
        for graph_name in ("MCP_Collapsed", nested[0]["path"]):
            r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                          asset_path=self._bp_path, graph_name=graph_name)
            self.assertSuccess(r, f"'{graph_name}' did not resolve: {r}")

    def test_ambiguous_bare_name_is_an_error(self):
        """Two graphs sharing a leaf name must never silently pick one."""
        self._skip_if_no_bp()
        if self._try_make_collapsed_graph("MCP_Dup") is None:
            self.skipTest("cannot author a K2Node_Composite from Python")
        if self._try_make_collapsed_graph("MCP_Dup") is None:
            self.skipTest("cannot author a second K2Node_Composite from Python")

        dups = [g for g in self._graphs()["graphs"] if g["name"].startswith("MCP_Dup")]
        if len({g["name"] for g in dups}) != 1 or len(dups) < 2:
            self.skipTest("engine renamed the duplicate; cannot force a collision")

        r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                      asset_path=self._bp_path, graph_name="MCP_Dup")
        self.assertFalse(r.get("success"), "ambiguous name must not resolve")
        self.assertIn("ambiguous", r.get("message", "").lower())
        # The error has to name the candidates, or it is not actionable.
        for g in dups:
            self.assertIn(g["path"], r["message"])

    def test_edit_inside_collapsed_graph(self):
        """Edit actions — not just reads — must reach a collapsed graph."""
        self._skip_if_no_bp()
        if self._try_make_collapsed_graph("MCP_Editable") is None:
            self.skipTest("cannot author a K2Node_Composite from Python")

        r = self.call("blueprint_actions", "ue_add_blueprint_node",
                      asset_path=self._bp_path, graph_name="MCP_Editable",
                      node_json={"type": "CallFunction", "function_name": "K2_GetActorLocation"})
        self.assertSuccess(r, f"could not add a node inside the collapsed graph: {r}")
        added = r["node_name"]

        info = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                         asset_path=self._bp_path, graph_name="MCP_Editable")
        self.assertSuccess(info)
        self.assertIn(added, [n["node_name"] for n in info["nodes"]],
                      "node was added to the wrong graph")

        r = self.call("blueprint_actions", "ue_remove_blueprint_node",
                      asset_path=self._bp_path, graph_name="MCP_Editable", node_name=added)
        self.assertSuccess(r)

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
