from UnrealMCPython.tests.base import MCPTestCase, TEST_ROOT

_WBP_NAME = "MCP_TestWidget"
_WBP_PATH = f"{TEST_ROOT}/{_WBP_NAME}"
_WBP_FULL = f"{_WBP_PATH}.{_WBP_NAME}"


class TestUMGActions(MCPTestCase):

    def setUp(self):
        self._wbp_path = None
        self.ensure_test_dir()
        r = self.call("umg_actions", "ue_create_widget_blueprint",
                      name=_WBP_NAME, path=TEST_ROOT)
        if r.get("success"):
            self._wbp_path = _WBP_FULL

    def tearDown(self):
        if self._wbp_path:
            self.delete_asset(self._wbp_path)

    def _skip_if_no_wbp(self):
        if not self._wbp_path:
            self.skipTest("WidgetBlueprint not created in setUp")

    # ── create / info ─────────────────────────────────────────────────────────

    def test_create_widget_blueprint(self):
        self.assertIsNotNone(self._wbp_path, "Widget Blueprint was not created in setUp")

    def test_get_widget_blueprint_info_empty(self):
        self._skip_if_no_wbp()
        r = self.call("umg_actions", "ue_get_widget_blueprint_info",
                      asset_path=self._wbp_path)
        self.assertSuccess(r)
        self.assertIn("widget_count", r)

    # ── add widgets ───────────────────────────────────────────────────────────

    def test_add_canvas_panel_root(self):
        self._skip_if_no_wbp()
        r = self.call("umg_actions", "ue_add_widget",
                      asset_path=self._wbp_path,
                      widget_type="CanvasPanel", widget_name="RootCanvas")
        self.assertSuccess(r)
        self.assertTrue(r.get("is_root"))

    def test_add_text_block_under_canvas(self):
        self._skip_if_no_wbp()
        self.call("umg_actions", "ue_add_widget",
                  asset_path=self._wbp_path,
                  widget_type="CanvasPanel", widget_name="RootCanvas")
        r = self.call("umg_actions", "ue_add_widget",
                      asset_path=self._wbp_path,
                      widget_type="TextBlock", widget_name="TitleText",
                      parent_name="RootCanvas")
        self.assertSuccess(r)

    def test_add_and_remove_widget(self):
        self._skip_if_no_wbp()
        self.call("umg_actions", "ue_add_widget",
                  asset_path=self._wbp_path,
                  widget_type="CanvasPanel", widget_name="RootCanvas")
        self.call("umg_actions", "ue_add_widget",
                  asset_path=self._wbp_path,
                  widget_type="Button", widget_name="RemoveBtn",
                  parent_name="RootCanvas")
        r = self.call("umg_actions", "ue_remove_widget",
                      asset_path=self._wbp_path, widget_name="RemoveBtn")
        self.assertSuccess(r)

    # ── properties ────────────────────────────────────────────────────────────

    def test_set_widget_properties(self):
        self._skip_if_no_wbp()
        self.call("umg_actions", "ue_add_widget",
                  asset_path=self._wbp_path,
                  widget_type="CanvasPanel", widget_name="RootCanvas")
        self.call("umg_actions", "ue_add_widget",
                  asset_path=self._wbp_path,
                  widget_type="TextBlock", widget_name="Label",
                  parent_name="RootCanvas")
        r = self.call("umg_actions", "ue_set_widget_properties",
                      asset_path=self._wbp_path, widget_name="Label",
                      properties={"text": "Hello", "font_size": 24,
                                  "slot_position": [100.0, 50.0],
                                  "slot_size": [300.0, 60.0]})
        self.assertSuccess(r)

    def test_set_slot_layout(self):
        self._skip_if_no_wbp()
        self.call("umg_actions", "ue_add_widget",
                  asset_path=self._wbp_path,
                  widget_type="CanvasPanel", widget_name="RootCanvas")
        self.call("umg_actions", "ue_add_widget",
                  asset_path=self._wbp_path,
                  widget_type="Image", widget_name="BgImage",
                  parent_name="RootCanvas")
        r = self.call("umg_actions", "ue_set_slot_layout",
                      asset_path=self._wbp_path, widget_name="BgImage",
                      anchor_min_x=0.0, anchor_min_y=0.0,
                      anchor_max_x=1.0, anchor_max_y=1.0,
                      offset_x=0.0, offset_y=0.0,
                      size_x=800.0, size_y=600.0)
        self.assertSuccess(r)

    # ── compile ───────────────────────────────────────────────────────────────

    def test_compile_widget_blueprint(self):
        self._skip_if_no_wbp()
        self.call("umg_actions", "ue_add_widget",
                  asset_path=self._wbp_path,
                  widget_type="CanvasPanel", widget_name="RootCanvas")
        r = self.call("umg_actions", "ue_compile_widget_blueprint",
                      asset_path=self._wbp_path)
        self.assertSuccess(r)
