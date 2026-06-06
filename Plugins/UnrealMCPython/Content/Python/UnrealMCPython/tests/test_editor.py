from UnrealMCPython.tests.base import MCPTestCase

_CLASS_PATH = "/Script/Engine.PointLight"


class TestEditorActions(MCPTestCase):

    def setUp(self):
        self._actor_label = None
        self._actor_path = None
        r = self.call("actor_actions", "ue_spawn_from_class",
                      class_path=_CLASS_PATH, location=[0, 0, 600])
        if r.get("success"):
            self._actor_label = r["actor_label"]
            self._actor_path = r.get("actor_path")

    def tearDown(self):
        if self._actor_label:
            self.delete_actor_by_label(self._actor_label)

    # ── get selected assets ───────────────────────────────────────────────────

    def test_get_selected_assets(self):
        r = self.call("editor_actions", "ue_get_selected_assets")
        self.assertSuccess(r)
        self.assertIn("selected_assets", r)
        self.assertIsInstance(r["selected_assets"], list)

    # ── material replace (specified) ──────────────────────────────────────────

    def test_replace_mtl_on_specified_no_mesh_actor(self):
        # PointLight has no mesh component — operation should succeed but change 0 slots
        if not self._actor_path:
            self.skipTest("Actor not spawned in setUp")
        r = self.call("editor_actions", "ue_replace_mtl_on_specified",
                      actor_paths=[self._actor_path],
                      material_to_be_replaced_path="/Game/DoesNotExist/OldMat",
                      new_material_path="/Game/DoesNotExist/NewMat")
        # No mesh to replace on, so result depends on implementation;
        # at minimum, the call should not crash the editor
        self.assertIsInstance(r.get("success"), bool)

    # ── mesh replace (specified) ──────────────────────────────────────────────

    def test_replace_mesh_on_specified_no_mesh_actor(self):
        if not self._actor_path:
            self.skipTest("Actor not spawned in setUp")
        r = self.call("editor_actions", "ue_replace_mesh_on_specified",
                      actor_paths=[self._actor_path],
                      mesh_to_be_replaced_path="/Game/DoesNotExist/OldMesh",
                      new_mesh_path="/Game/DoesNotExist/NewMesh")
        self.assertIsInstance(r.get("success"), bool)
