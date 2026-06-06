import unreal
from UnrealMCPython.tests.base import MCPTestCase

_CLASS_PATH = "/Script/Engine.PointLight"


class TestActorActions(MCPTestCase):

    def setUp(self):
        self._actor_label = None
        r = self.call("actor_actions", "ue_spawn_from_class",
                      class_path=_CLASS_PATH, location=[0, 0, 500])
        if r.get("success"):
            self._actor_label = r["actor_label"]

    def tearDown(self):
        if self._actor_label:
            self.delete_actor_by_label(self._actor_label)

    # ── spawn ──────────────────────────────────────────────────────────────────

    def test_spawn_from_class(self):
        self.assertIsNotNone(self._actor_label, "Actor was not spawned in setUp")

    def test_spawn_missing_class(self):
        r = self.call("actor_actions", "ue_spawn_from_class",
                      class_path="/Script/Engine.NonExistentClass123", location=[0, 0, 0])
        self.assertFalse(r.get("success"))

    # ── list / query ───────────────────────────────────────────────────────────

    def test_list_all_with_locations(self):
        r = self.call("actor_actions", "ue_list_all_with_locations")
        self.assertSuccess(r)
        self.assertIsInstance(r["actors"], list)
        labels = [a["name"] for a in r["actors"]]
        self.assertIn(self._actor_label, labels)

    def test_get_all_details(self):
        r = self.call("actor_actions", "ue_get_all_details")
        self.assertSuccess(r)
        self.assertIsInstance(r["actors"], list)

    def test_get_in_view_frustum(self):
        r = self.call("actor_actions", "ue_get_in_view_frustum")
        self.assertSuccess(r)
        self.assertIn("visible_actors", r)

    # ── transform ─────────────────────────────────────────────────────────────

    def test_set_location(self):
        r = self.call("actor_actions", "ue_set_location",
                      actor_label=self._actor_label, location=[100, 200, 300])
        self.assertSuccess(r)

    def test_set_rotation(self):
        r = self.call("actor_actions", "ue_set_rotation",
                      actor_label=self._actor_label, rotation=[0, 45, 0])
        self.assertSuccess(r)

    def test_set_scale(self):
        r = self.call("actor_actions", "ue_set_scale",
                      actor_label=self._actor_label, scale=[2, 2, 2])
        self.assertSuccess(r)

    def test_set_transform_full(self):
        r = self.call("actor_actions", "ue_set_transform",
                      actor_label=self._actor_label,
                      location=[50, 50, 50], rotation=[0, 0, 0], scale=[1, 1, 1])
        self.assertSuccess(r)

    def test_set_transform_unknown_actor(self):
        r = self.call("actor_actions", "ue_set_transform",
                      actor_label="NonExistentActor_XYZ123", location=[0, 0, 0])
        self.assertFalse(r.get("success"))

    # ── property ──────────────────────────────────────────────────────────────

    def test_get_property(self):
        r = self.call("actor_actions", "ue_get_property",
                      actor_label=self._actor_label, property_name="can_be_damaged")
        self.assertSuccess(r)
        self.assertIn("value", r)

    def test_set_property(self):
        r = self.call("actor_actions", "ue_set_property",
                      actor_label=self._actor_label,
                      property_name="can_be_damaged", value=False)
        self.assertSuccess(r)

    # ── selection ─────────────────────────────────────────────────────────────

    def test_select_all(self):
        r = self.call("actor_actions", "ue_select_all")
        self.assertSuccess(r)

    def test_invert_selection(self):
        self.call("actor_actions", "ue_select_all")
        r = self.call("actor_actions", "ue_invert_selection")
        self.assertSuccess(r)

    # ── delete ────────────────────────────────────────────────────────────────

    def test_delete_by_label(self):
        r = self.call("actor_actions", "ue_spawn_from_class",
                      class_path=_CLASS_PATH, location=[9999, 9999, 9999])
        self.assertSuccess(r)
        extra_label = r["actor_label"]
        r = self.call("actor_actions", "ue_delete_by_label", actor_label=extra_label)
        self.assertSuccess(r)

    # ── raycast ───────────────────────────────────────────────────────────────

    def test_line_trace_no_hit(self):
        r = self.call("actor_actions", "ue_line_trace",
                      ray_start=[0, 0, 100000], ray_end=[0, 0, 200000])
        self.assertSuccess(r)
        self.assertFalse(r.get("hit"))
