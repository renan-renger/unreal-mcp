from UnrealMCPython.tests.base import MCPTestCase


class TestAssetActions(MCPTestCase):

    def test_find_by_type(self):
        r = self.call("asset_actions", "ue_find_by_query", asset_type="StaticMesh")
        self.assertSuccess(r)
        self.assertIsInstance(r["assets"], list)

    def test_find_by_name(self):
        r = self.call("asset_actions", "ue_find_by_query", name="Cube")
        self.assertSuccess(r)
        self.assertIsInstance(r["assets"], list)

    def test_find_by_name_and_type(self):
        r = self.call("asset_actions", "ue_find_by_query",
                      name="Cube", asset_type="StaticMesh")
        self.assertSuccess(r)

    def test_find_missing_params_fails(self):
        r = self.call("asset_actions", "ue_find_by_query")
        self.assertFalse(r.get("success"))

    def test_get_static_mesh_details_invalid(self):
        r = self.call("asset_actions", "ue_get_static_mesh_details",
                      asset_path="/Game/DoesNotExist/FakeMesh")
        self.assertFalse(r.get("success"))
