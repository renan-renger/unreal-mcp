import unreal
from UnrealMCPython.tests.base import MCPTestCase, TEST_ROOT

_BP_NAME = "MCP_TestBlueprint"
_BP_PATH = f"{TEST_ROOT}/{_BP_NAME}"

# Same-named sibling graphs cannot be forced with composites (the engine uniquifies a
# composite's bound graph against its parent), so that case is covered with an anim
# state machine, whose transition graphs are all named "Transition".
_SKELETON = "/Engine/Tutorial/SubEditors/TutorialAssets/Character/TutorialTPP_Skeleton"
_IDLE_ANIM = "/Engine/Tutorial/SubEditors/TutorialAssets/Character/Tutorial_Idle"
_WALK_ANIM = "/Engine/Tutorial/SubEditors/TutorialAssets/Character/Tutorial_Walk_Fwd"
_ABP_PATH = f"{TEST_ROOT}/MCP_TestGraphPathsABP"


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
    # Collapsed graphs are authored through the "Composite" node type, so these run
    # against a real K2Node_Composite rather than a reflective stand-in.

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

    def _make_collapsed_graph(self, name, parent="EventGraph"):
        """Author a real collapsed graph and return its list_blueprint_graphs row.

        UK2Node_Composite::PostPlacedNewNode builds the bound graph, its entry/exit
        tunnels and the parent's SubGraphs entry, so nothing here has to fake them.
        The engine uniquifies the graph name against its siblings, so the name that
        comes back can differ from the one requested — read it from the enumeration
        instead of assuming.
        """
        before = {g["path"] for g in self._graphs()["graphs"]}
        r = self.call("blueprint_actions", "ue_add_blueprint_node",
                      asset_path=self._bp_path, graph_name=parent,
                      node_json={"type": "Composite", "graph_name": name})
        self.assertSuccess(r, f"could not author a collapsed graph: {r}")

        new = [g for g in self._graphs()["graphs"] if g["path"] not in before]
        self.assertEqual(len(new), 1,
                         f"expected exactly one new graph, got {[g['path'] for g in new]}")
        return new[0]

    def test_nested_graph_resolution(self):
        """Collapsed graphs resolve by bare name and by path."""
        self._skip_if_no_bp()
        before = self._graphs()["graph_count"]
        nested = self._make_collapsed_graph("MCP_Collapsed")

        self.assertEqual(self._graphs()["graph_count"], before + 1,
                         "collapsed graph was not enumerated")
        self.assertEqual(nested["depth"], 1)
        self.assertIn("/", nested["path"])
        self.assertEqual(nested["owning_node_class"], "K2Node_Composite")

        # Reachable by bare name and by full path — the whole point of the change.
        for graph_name in (nested["name"], nested["path"]):
            r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                          asset_path=self._bp_path, graph_name=graph_name)
            self.assertSuccess(r, f"'{graph_name}' did not resolve: {r}")

    def test_ambiguous_bare_name_is_an_error(self):
        """Two graphs sharing a leaf name must never silently pick one."""
        self._skip_if_no_bp()
        # One per parent graph: UK2Node_Composite::IsCompositeNameAvailable only checks
        # the parent's own SubGraphs, so composites under different parents keep the
        # same name and collide on the bare name while holding distinct paths.
        self._make_collapsed_graph("MCP_Dup", parent="EventGraph")
        self._make_collapsed_graph("MCP_Dup", parent="UserConstructionScript")

        dups = [g for g in self._graphs()["graphs"] if g["name"] == "MCP_Dup"]
        self.assertEqual(len(dups), 2, f"expected two graphs named MCP_Dup: {self._graphs()}")

        r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                      asset_path=self._bp_path, graph_name="MCP_Dup")
        self.assertFalse(r.get("success"), "ambiguous name must not resolve")
        self.assertIn("ambiguous", r.get("message", "").lower())
        # The error has to name the candidates, or it is not actionable.
        for g in dups:
            self.assertIn(g["path"], r["message"])
            info = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                             asset_path=self._bp_path, graph_name=g["path"])
            self.assertSuccess(info, f"offered path '{g['path']}' did not resolve: {info}")

    def test_same_named_siblings_stay_addressable(self):
        """Siblings sharing a name must each keep a path that works.

        A bound graph is outered to the node that owns it, so UObject naming does not
        separate siblings: every transition graph of a state machine is named
        "Transition". Undisambiguated they collapse onto one identical path, which
        leaves them unreachable while the error advises a longer path that cannot exist.
        """
        for asset in (_SKELETON, _IDLE_ANIM, _WALK_ANIM):
            if not unreal.EditorAssetLibrary.does_asset_exist(asset):
                self.skipTest(f"Engine tutorial asset not available: {asset}")

        self.delete_asset(_ABP_PATH)
        self.addCleanup(self.delete_asset, _ABP_PATH)
        self.assertSuccess(self.call("anim_blueprint_actions", "ue_create_anim_blueprint",
                                     asset_path=_ABP_PATH, skeleton_path=_SKELETON))
        self.assertSuccess(self.call(
            "anim_blueprint_actions", "ue_build_anim_state_machine", asset_path=_ABP_PATH,
            spec={"states": [{"name": "Idle", "anim": _IDLE_ANIM},
                             {"name": "Walk", "anim": _WALK_ANIM}],
                  "transitions": [{"from": "Idle", "to": "Walk"},
                                  {"from": "Walk", "to": "Idle"}]}))

        graphs = self.call("blueprint_actions", "ue_list_blueprint_graphs", asset_path=_ABP_PATH)
        self.assertSuccess(graphs)
        paths = [g["path"] for g in graphs["graphs"]]
        self.assertEqual(len(paths), len(set(paths)), f"paths are not unique: {paths}")

        transitions = [g for g in graphs["graphs"] if g["name"] == "Transition"]
        self.assertGreaterEqual(len(transitions), 2,
                                f"expected same-named transition graphs: {paths}")

        # Each colliding sibling is reachable by its own path...
        for g in transitions:
            info = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                             asset_path=_ABP_PATH, graph_name=g["path"])
            self.assertSuccess(info, f"'{g['path']}' did not resolve: {info}")

        # ...and the bare name still refuses to guess, offering paths that work.
        r = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                      asset_path=_ABP_PATH, graph_name="Transition")
        self.assertFalse(r.get("success"), "ambiguous name must not resolve")
        message = r.get("message", "")
        self.assertIn("ambiguous", message.lower())
        for g in transitions:
            self.assertIn(g["path"], message)
        self.assertNotIn("longer path", message,
                         "siblings differing only by owning node have no longer path")

    def test_edit_inside_collapsed_graph(self):
        """Edit actions — not just reads — must reach a collapsed graph."""
        self._skip_if_no_bp()
        nested = self._make_collapsed_graph("MCP_Editable")

        r = self.call("blueprint_actions", "ue_add_blueprint_node",
                      asset_path=self._bp_path, graph_name=nested["path"],
                      node_json={"type": "CallFunction", "function_name": "K2_GetActorLocation"})
        self.assertSuccess(r, f"could not add a node inside the collapsed graph: {r}")
        added = r["node_name"]

        info = self.call("blueprint_actions", "ue_get_blueprint_graph_info",
                         asset_path=self._bp_path, graph_name=nested["path"])
        self.assertSuccess(info)
        self.assertIn(added, [n["node_name"] for n in info["nodes"]],
                      "node was added to the wrong graph")

        r = self.call("blueprint_actions", "ue_remove_blueprint_node",
                      asset_path=self._bp_path, graph_name=nested["path"], node_name=added)
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
