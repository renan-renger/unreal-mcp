from UnrealMCPython.tests.base import MCPTestCase


class TestLevelActions(MCPTestCase):

    def setUp(self):
        self._gravity_changed = False

    def tearDown(self):
        # Restore default gravity if we changed it
        if self._gravity_changed:
            self.call("level_actions", "ue_set_world_settings", gravity=-980.0)

    def test_list_level_actors(self):
        r = self.call("level_actions", "ue_list_level_actors")
        self.assertSuccess(r)
        self.assertIn("actors", r)
        self.assertIsInstance(r["actors"], list)
        self.assertIn("count", r)

    def test_list_level_actors_with_class_filter(self):
        r = self.call("level_actions", "ue_list_level_actors", class_filter="Light")
        self.assertSuccess(r)
        for actor in r["actors"]:
            self.assertIn("Light", actor["class"])

    def test_set_world_gravity(self):
        self._gravity_changed = True
        r = self.call("level_actions", "ue_set_world_settings", gravity=-500.0)
        self.assertSuccess(r)
        self.assertIn("gravity", r.get("applied", {}))

    def test_set_world_time_dilation(self):
        r = self.call("level_actions", "ue_set_world_settings", time_dilation=1.0)
        self.assertSuccess(r)

    def test_set_world_settings_no_params(self):
        r = self.call("level_actions", "ue_set_world_settings")
        self.assertFalse(r.get("success"))
