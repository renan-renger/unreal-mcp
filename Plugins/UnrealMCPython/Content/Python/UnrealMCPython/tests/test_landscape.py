import unreal
from UnrealMCPython.tests.base import MCPTestCase, TEST_ROOT

_CUBE = "/Engine/BasicShapes/Cube"

# Small on purpose: 4x4 components of 63 quads at scale 25 -> 6300 uu (63 m), seconds to
# sculpt and paint. The mountain zone (300+600+300=1200) must stay under the half-span
# (3150) or SculptBorderMountains refuses.
_SCULPT = dict(ridge_distance_uu=300.0, ridge_half_width_uu=300.0, peak_height_uu=800.0,
               height_variation_uu=600.0, ridge_wander_uu=600.0, noise_wavelength_uu=800.0,
               roughness_uu=100.0, ground_height_uu=50.0, seed=20260818)


class TestLandscapeActions(MCPTestCase):
    """Runs the whole map-build pipeline in the OPEN level (never switches levels — see
    the note in test_level.py: replacing the open level destabilizes the shared suite).
    Everything spawned is destroyed by actor-set diff, assets are deleted, nothing is
    saved."""

    def setUp(self):
        if not hasattr(unreal, "MCPythonHelper") or \
                not hasattr(unreal.MCPythonHelper, "create_flat_landscape"):
            self.skipTest("MCPythonHelper landscape functions missing (editor binary predates the domain)")
        self.ensure_test_dir()
        self._sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self._before = set(a.get_path_name() for a in self._sub.get_all_level_actors())

    def tearDown(self):
        for a in list(self._sub.get_all_level_actors()):
            if a.get_path_name() not in self._before:
                try:
                    self._sub.destroy_actor(a)
                except Exception:
                    pass
        for layer in ("TestFlat", "TestSlope"):
            self.delete_asset(f"{TEST_ROOT}/LI_{layer}")

    # ── parameter guards (also what the E2E empty-param sweep exercises) ─────────

    def test_missing_param_guards(self):
        self.assertFalse(self.call("landscape_actions", "ue_solve_landscape_geometry").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_create_flat_landscape").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_sculpt_border_mountains").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_paint_by_slope").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_build_level_skeleton").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_scatter_hism").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_get_mesh_footprint").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_measure_borders").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_escape_test").get("success"))
        self.assertFalse(self.call("landscape_actions", "ue_border_weak_points").get("success"))

    def test_solve_reports_resolved_size(self):
        r = self.call("landscape_actions", "ue_solve_landscape_geometry", size_uu=50000.0)
        self.assertSuccess(r)
        # 50000 uu at scale 25 cannot land exactly; the closest legal grid is 2016 quads.
        self.assertEqual(r["size_uu"], 50400.0)
        self.assertIn(r["quads_per_section"], (7, 15, 31, 63, 127, 255))

    def test_mesh_footprint(self):
        r = self.call("landscape_actions", "ue_get_mesh_footprint", mesh_path=_CUBE)
        self.assertSuccess(r)
        self.assertGreater(r["radius_uu"], 0)
        self.assertGreater(r["height_uu"], 0)

    def test_budget_report_runs_read_only(self):
        r = self.call("landscape_actions", "ue_level_budget_report")
        self.assertSuccess(r)
        self.assertIn("actors", r)
        self.assertIn("alerts", r)

    # ── the pipeline, in its one valid order ─────────────────────────────────────

    def test_full_pipeline(self):
        r = self.call("landscape_actions", "ue_create_flat_landscape",
                      quads_per_section=63, sections_per_component=1,
                      component_count_x=4, component_count_y=4,
                      location_x=200000.0, location_y=200000.0)
        if not r.get("success") and "grid-based" in r.get("message", ""):
            self.skipTest("open level is World Partition; CreateFlatLandscape only supports non-partitioned levels")
        self.assertSuccess(r)
        label = r["landscape_label"]
        size = r["size_x_uu"]
        self.assertEqual(r["components"], 16)
        self.assertAlmostEqual(size, 6300.0, delta=1.0)

        r = self.call("landscape_actions", "ue_sculpt_border_mountains",
                      landscape_label=label, **_SCULPT)
        self.assertSuccess(r)
        self.assertGreater(r["min_peak_height_uu"], 0)
        self.assertGreater(r["guaranteed_min_angle"], 44.76)

        # Floor above the mean must be refused - it would erase the noise entirely.
        r = self.call("landscape_actions", "ue_sculpt_border_mountains",
                      landscape_label=label, **dict(_SCULPT, min_peak_height_uu=2000.0))
        self.assertFalse(r.get("success"))

        # Unknown side names are refused; a partial ring reports its open sides.
        r = self.call("landscape_actions", "ue_sculpt_border_mountains",
                      landscape_label=label, sides="north,upward", **_SCULPT)
        self.assertFalse(r.get("success"))
        r = self.call("landscape_actions", "ue_sculpt_border_mountains",
                      landscape_label=label, sides="north,east,west", **_SCULPT)
        self.assertSuccess(r)
        self.assertEqual(r["open_sides"], ["south"])
        # restore the full ring for the measurements below (heights are absolute)
        r = self.call("landscape_actions", "ue_sculpt_border_mountains",
                      landscape_label=label, **_SCULPT)
        self.assertSuccess(r)

        r = self.call("landscape_actions", "ue_paint_by_slope",
                      landscape_label=label, package_path=TEST_ROOT,
                      flat_layer_name="TestFlat", slope_layer_name="TestSlope",
                      slope_start_degrees=20.0, slope_full_degrees=40.0)
        self.assertSuccess(r)
        self.assertIn("TestFlat", r["target_layers"])
        self.assertIn("TestSlope", r["target_layers"])

        r = self.call("landscape_actions", "ue_build_level_skeleton",
                      size_uu=size, origin_x=200000.0, origin_y=200000.0)
        self.assertSuccess(r)
        self.assertIn("DirectionalLight", r["spawned"])
        self.assertIn("NavMeshBoundsVolume", r["spawned"])
        # Builder takes the FULL size; the extent read back is the half.
        self.assertAlmostEqual(r["nav_bounds_extent"]["x"], (size + 4600.0) / 2.0, delta=1.0)

        r = self.call("landscape_actions", "ue_scatter_hism",
                      landscape_label=label, size_uu=size, margin_uu=400.0,
                      specs=[{"mesh_path": _CUBE, "count": 12, "base_scale": 1.0,
                              "radius_uu": 200.0, "max_slope_degrees": 60.0},
                             {"mesh_path": _CUBE, "count": 8, "base_scale": 0.5,
                              "radius_uu": 400.0}])
        self.assertSuccess(r)
        self.assertGreater(r["instances"], 0)
        self.assertEqual(r["scatter_actors"], 1)  # same mesh -> same label -> replaced
        for s in r["stats"]:
            self.assertLessEqual(s["placed"], s["requested"])

        r = self.call("landscape_actions", "ue_rebuild_navigation")
        self.assertSuccess(r)

        r = self.call("landscape_actions", "ue_measure_borders",
                      landscape_label=label, size_uu=size, samples_per_side=5)
        self.assertSuccess(r)
        self.assertIsNotNone(r.get("interior_ground_m"))
        for side in ("west", "east", "south", "north"):
            self.assertIn("peak_mean_m", r[side], f"side {side} had no valid samples: {r[side]}")
            # The crest must rise above the interior floor.
            self.assertGreater(r[side]["peak_mean_m"], r["interior_ground_m"])

        r = self.call("landscape_actions", "ue_border_weak_points",
                      landscape_label=label, size_uu=size,
                      step_along_uu=1500.0, step_d_uu=300.0, max_d_uu=1500.0)
        self.assertSuccess(r)
        self.assertGreater(r["profiles"], 0)

        # Plumbing assertion only: navigation builds asynchronously, so escape counts are
        # not asserted here - the action must round-trip and classify targets.
        r = self.call("landscape_actions", "ue_escape_test",
                      landscape_label=label, size_uu=size, step_uu=1500.0)
        self.assertSuccess(r)
        self.assertIn("escapes", r)
        self.assertIn("partial_paths", r)
