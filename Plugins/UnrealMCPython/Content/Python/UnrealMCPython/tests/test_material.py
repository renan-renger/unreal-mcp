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

        unreal.MaterialEditingLibrary.recompile_material(mat)
        unreal.EditorAssetLibrary.save_loaded_asset(mat)

        try:
            mi_factory = unreal.MaterialInstanceConstantFactoryNew()
            mi_factory.set_editor_property('initial_parent', mat)
            mi = tools.create_asset(_MI_NAME, TEST_ROOT,
                                    unreal.MaterialInstanceConstant, mi_factory)
            if mi:
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
