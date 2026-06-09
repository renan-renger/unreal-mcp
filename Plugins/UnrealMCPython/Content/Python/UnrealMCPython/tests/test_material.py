import unreal
from UnrealMCPython.tests.base import MCPTestCase, TEST_ROOT

_MAT_NAME = "MCP_TestMaterial"
_MAT_PATH = f"{TEST_ROOT}/{_MAT_NAME}"
_MI_NAME = "MCP_TestMI"
_MI_PATH = f"{TEST_ROOT}/{_MI_NAME}"


class TestMaterialActions(MCPTestCase):

    def setUp(self):
        self._mat_path = None
        self._mi_path = None
        self.ensure_test_dir()
        tools = unreal.AssetToolsHelpers.get_asset_tools()

        mat = tools.create_asset(_MAT_NAME, TEST_ROOT, unreal.Material, unreal.MaterialFactoryNew())
        if not mat:
            return
        self._mat_path = _MAT_PATH

        # Add a ScalarParameter and VectorParameter so the MI has testable params
        scalar = unreal.MaterialEditingLibrary.create_material_expression(
            mat, unreal.MaterialExpressionScalarParameter, 0, 0)
        if scalar:
            scalar.set_editor_property('parameter_name', unreal.Name('TestScalar'))
            scalar.set_editor_property('default_value', 0.5)

        vec = unreal.MaterialEditingLibrary.create_material_expression(
            mat, unreal.MaterialExpressionVectorParameter, 0, 150)
        if vec:
            vec.set_editor_property('parameter_name', unreal.Name('TestVector'))

        sw = unreal.MaterialEditingLibrary.create_material_expression(
            mat, unreal.MaterialExpressionStaticBoolParameter, 0, 300)
        if sw:
            sw.set_editor_property('parameter_name', unreal.Name('TestSwitch'))

        tex = unreal.MaterialEditingLibrary.create_material_expression(
            mat, unreal.MaterialExpressionTextureSampleParameter2D, 0, 450)
        if tex:
            tex.set_editor_property('parameter_name', unreal.Name('TestTexture'))

        unreal.MaterialEditingLibrary.recompile_material(mat)
        unreal.EditorAssetLibrary.save_loaded_asset(mat)

        try:
            mi = tools.create_asset(_MI_NAME, TEST_ROOT,
                                    unreal.MaterialInstanceConstant,
                                    unreal.MaterialInstanceConstantFactoryNew())
            if mi:
                # The factory has no 'initial_parent' in this engine version;
                # set the parent on the instance directly, then refresh it.
                mi.set_editor_property('parent', mat)
                self._mi_path = _MI_PATH
                unreal.MaterialEditingLibrary.update_material_instance(mi)
                unreal.EditorAssetLibrary.save_loaded_asset(mi)
        except Exception:
            pass

    def tearDown(self):
        if self._mi_path:
            self.delete_asset(self._mi_path)
        if self._mat_path:
            self.delete_asset(self._mat_path)

    # ── expressions ───────────────────────────────────────────────────────────

    def test_create_expression(self):
        if not self._mat_path:
            self.skipTest("Material not created in setUp")
        r = self.call("material_actions", "ue_create_expression",
                      material_path=self._mat_path,
                      expression_class_name="Constant", node_pos_x=200, node_pos_y=0)
        self.assertSuccess(r)
        self.assertIn("expression_class", r)

    def test_recompile(self):
        if not self._mat_path:
            self.skipTest("Material not created in setUp")
        r = self.call("material_actions", "ue_recompile",
                      material_path=self._mat_path)
        self.assertSuccess(r)

    def test_create_expression_invalid_class(self):
        if not self._mat_path:
            self.skipTest("Material not created in setUp")
        r = self.call("material_actions", "ue_create_expression",
                      material_path=self._mat_path,
                      expression_class_name="NonExistentExpression999")
        self.assertFalse(r.get("success"))

    # ── MI scalar ─────────────────────────────────────────────────────────────

    def test_set_get_mi_scalar_param(self):
        if not self._mi_path:
            self.skipTest("MaterialInstance not created in setUp")
        r = self.call("material_actions", "ue_set_mi_scalar_param",
                      instance_path=self._mi_path,
                      parameter_name="TestScalar", value=0.75)
        self.assertSuccess(r)
        r = self.call("material_actions", "ue_get_mi_scalar_param",
                      instance_path=self._mi_path, parameter_name="TestScalar")
        self.assertSuccess(r)
        self.assertAlmostEqual(r["value"], 0.75, places=3)

    # ── MI vector ─────────────────────────────────────────────────────────────

    def test_set_get_mi_vector_param(self):
        if not self._mi_path:
            self.skipTest("MaterialInstance not created in setUp")
        color = [1.0, 0.0, 0.5, 1.0]
        r = self.call("material_actions", "ue_set_mi_vector_param",
                      instance_path=self._mi_path,
                      parameter_name="TestVector", value=color)
        self.assertSuccess(r)
        r = self.call("material_actions", "ue_get_mi_vector_param",
                      instance_path=self._mi_path, parameter_name="TestVector")
        self.assertSuccess(r)
        self.assertEqual(len(r["value"]), 4)

    # ── MI static switch ────────────────────────────────────────────────────────

    def test_set_get_mi_static_switch(self):
        if not self._mi_path:
            self.skipTest("MaterialInstance not created in setUp")
        r = self.call("material_actions", "ue_set_mi_static_switch",
                      instance_path=self._mi_path,
                      parameter_name="TestSwitch", value=True)
        self.assertSuccess(r)
        r = self.call("material_actions", "ue_get_mi_static_switch",
                      instance_path=self._mi_path, parameter_name="TestSwitch")
        self.assertSuccess(r)
        self.assertEqual(r["value"], True)

    # ── MI texture ──────────────────────────────────────────────────────────────

    def test_set_get_mi_texture_param(self):
        if not self._mi_path:
            self.skipTest("MaterialInstance not created in setUp")
        r = self.call("material_actions", "ue_set_mi_texture_param",
                      instance_path=self._mi_path, parameter_name="TestTexture",
                      texture_path="/Engine/EngineResources/DefaultTexture")
        self.assertSuccess(r)
        r = self.call("material_actions", "ue_get_mi_texture_param",
                      instance_path=self._mi_path, parameter_name="TestTexture")
        self.assertSuccess(r)

    # ── connect expressions ─────────────────────────────────────────────────────

    def test_connect_expressions(self):
        if not self._mat_path:
            self.skipTest("Material not created in setUp")
        a = self.call("material_actions", "ue_create_expression",
                      material_path=self._mat_path,
                      expression_class_name="Constant", node_pos_x=-600, node_pos_y=0)
        self.assertSuccess(a)
        b = self.call("material_actions", "ue_create_expression",
                      material_path=self._mat_path,
                      expression_class_name="Multiply", node_pos_x=-300, node_pos_y=0)
        self.assertSuccess(b)
        r = self.call("material_actions", "ue_connect_expressions",
                      material_path=self._mat_path,
                      from_expression_identifier=a["expression_name"], from_output_name="",
                      to_expression_identifier=b["expression_name"], to_input_name="A")
        self.assertSuccess(r)
