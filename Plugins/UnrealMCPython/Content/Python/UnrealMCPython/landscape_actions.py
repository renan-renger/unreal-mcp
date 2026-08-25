# Copyright (c) 2025 GenOrca. All Rights Reserved.

"""
Landscape / scripted map-building domain.

Ported from MadorasRebirth PR #1511 (Tools/map-build + UMadoraLevelBuildLibrary). Every
rule that looks arbitrary here was measured against that project's hand-authored
reference map (L04-Beach, sampled 41 times per side on 2026-08-18) or against a
counter-example that cost a round of trial and error; the measurement is quoted where
it drives the code.

The C++ side (CreateFlatLandscape, SculptBorderMountains, FindOrCreateLandscapeLayerInfo,
PaintLandscapeBySlope, SpawnHISMScatterActor) lives in MCPythonHelper_Landscape.cpp —
those engine entry points are public C++ but not UFUNCTIONs, so Python cannot reach them
directly. If unreal.MCPythonHelper lacks them, the editor binary predates this domain:
rebuild the editor with it closed (Live Coding does not register new UFUNCTIONs).

Pipeline order is not arbitrary:
  create -> sculpt -> paint -> skeleton -> scatter -> rebuild_navigation
Sculpt heights are ABSOLUTE (sculpting after scattering buries or floats every prop),
and navigation must be rebuilt AFTER scattering (props have collision and carve the
navmesh; navigation does NOT generate on its own in a script-built level).
"""

import json
import math
import random
import traceback

import unreal


# ─── internal helpers (not actions) ──────────────────────────────────────────────

_VALID_QUADS = (7, 15, 31, 63, 127, 255)


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _helper_missing():
    if not hasattr(unreal, "MCPythonHelper") or not hasattr(unreal.MCPythonHelper, "create_flat_landscape"):
        return json.dumps({"success": False, "message":
            "MCPythonHelper landscape functions are missing. The editor binary predates this "
            "domain: close the editor, rebuild it, and reopen (Live Coding does not register "
            "new UFUNCTIONs)."})
    return None


def _find_landscape(landscape_label=None):
    """The level's landscape (by label when given), or (None, error_message)."""
    found = []
    for a in _actors().get_all_level_actors():
        if isinstance(a, unreal.Landscape):
            found.append(a)
    if not found:
        return None, "No Landscape actor in the current level."
    if landscape_label:
        for a in found:
            if a.get_actor_label() == landscape_label:
                return a, None
        return None, f"No Landscape labelled '{landscape_label}' (found: {[a.get_actor_label() for a in found]})."
    if len(found) > 1:
        return None, f"Multiple Landscapes in the level; pass landscape_label (found: {[a.get_actor_label() for a in found]})."
    return found[0], None


_VIS = unreal.TraceTypeQuery.ECC_VISIBILITY
_NODEBUG = unreal.DrawDebugTrace.NONE


def _trace_ground(x, y, top=80000.0, bottom=-80000.0):
    """Height and normal of the TERRAIN at (x, y), or None.

    Two traps handled here:
    - line_trace_single returns None when nothing is hit, not an empty HitResult; calling
      .to_tuple() directly breaks with AttributeError over covered terrain.
    - The trace can hit the canopy of an already-placed prop and hand that point back as
      "ground", leaving the next object floating on top of a tree. Measured: 5% of traces
      on a populated map, instances up to 28 m in the air. Only the landscape counts.

    to_tuple() fields: [0] blocking_hit, [5] impact_point, [7] impact_normal, [9] hit actor.
    """
    hit = unreal.SystemLibrary.line_trace_single(
        _world(), unreal.Vector(x, y, top), unreal.Vector(x, y, bottom),
        _VIS, True, [], _NODEBUG, True)
    if hit is None:
        return None
    r = hit.to_tuple()
    if not r[0] or not isinstance(r[9], unreal.LandscapeProxy):
        return None
    return r[5].z, r[7]


def _slope_degrees(normal):
    return math.degrees(math.acos(max(-1.0, min(1.0, normal.z))))


def _landscape_origin(landscape):
    t = landscape.get_actor_transform().translation
    return t.x, t.y


def _solve(size_uu, quad_size, max_components=64):
    """Closest valid quads/sections/components combination to the requested size.

    The engine only accepts subsections of 7/15/31/63/127/255 quads and 1 or 2 sections
    per component, so a request in metres almost never lands exactly. Always report the
    RESOLVED size, never pretend the request matched: 50000 uu at scale 25 becomes 50400.
    """
    target = size_uu / quad_size
    best = None
    for qps in _VALID_QUADS:
        for spc in (1, 2):
            qpc = qps * spc
            for cc in range(1, max_components + 1):
                key = (abs(cc * qpc - target), cc)  # tie-break: fewer components = less overhead
                if best is None or key < best[0]:
                    best = (key, {
                        "quads_per_section": qps,
                        "sections_per_component": spc,
                        "component_count": cc,
                        "quads_per_axis": cc * qpc,
                        "size_uu": cc * qpc * quad_size,
                        "total_components": cc * cc,
                    })
    return best[1]


def _min_peak_for_angle(angle_degrees, ridge_half_width_uu):
    """Lowest peak that keeps the crest's flank steeper than the given angle.

    Inverts tan(angle) = peak * PI / (2 * half_width). What stops a walking character is
    slope, not height, and it must hold at the LOWEST peak the noise produces, not the mean.
    """
    return math.tan(math.radians(angle_degrees)) * 2.0 * ridge_half_width_uu / math.pi


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, default=str)


# ─── geometry ─────────────────────────────────────────────────────────────────────

def ue_solve_landscape_geometry(size_uu: float = None, quad_size: float = 25.0) -> str:
    """Resolves a requested size to the closest valid landscape geometry (read-only)."""
    if size_uu is None:
        return json.dumps({"success": False, "message": "Required parameter 'size_uu' is missing."})
    try:
        layout = _solve(float(size_uu), float(quad_size))
        return json.dumps({"success": True, **layout,
                           "requested_uu": float(size_uu),
                           "message": f"Requested {float(size_uu):.0f} uu resolves to {layout['size_uu']:.0f} uu."})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_create_flat_landscape(size_uu: float = None, material_path: str = None,
                             scale_x: float = 25.0, scale_y: float = 25.0, scale_z: float = 100.0,
                             location_x: float = 0.0, location_y: float = 0.0, location_z: float = 0.0,
                             quads_per_section: int = None, sections_per_component: int = None,
                             component_count_x: int = None, component_count_y: int = None) -> str:
    """Creates a flat landscape in the open level, resolving size_uu to valid geometry.

    Pass size_uu to let the solver pick the geometry (square), or all four of
    quads_per_section / sections_per_component / component_count_x / component_count_y for
    explicit control. location is the landscape's MINIMUM corner, not its centre (the
    Landscape mode panel differs: it treats its input as the centre). The landscape is born
    flat, with no target layers — a LandscapeLayerBlend material shows nothing until
    paint_by_slope (or manual painting) binds and fills layers.
    """
    missing = _helper_missing()
    if missing:
        return missing
    explicit = [quads_per_section, sections_per_component, component_count_x, component_count_y]
    if size_uu is None and any(v is None for v in explicit):
        return json.dumps({"success": False, "message":
            "Pass 'size_uu', or all four of quads_per_section/sections_per_component/"
            "component_count_x/component_count_y."})
    try:
        if all(v is not None for v in explicit):
            layout = {
                "quads_per_section": int(quads_per_section),
                "sections_per_component": int(sections_per_component),
                "component_count": None,
                "quads_per_axis": None, "size_uu": None, "total_components": None,
            }
            ccx, ccy = int(component_count_x), int(component_count_y)
        else:
            layout = _solve(float(size_uu), float(scale_x))
            ccx = ccy = layout["component_count"]

        material = unreal.load_asset(material_path) if material_path else None
        if material_path and material is None:
            return json.dumps({"success": False, "message": f"Material not found: '{material_path}'."})

        ls, err = unreal.MCPythonHelper.create_flat_landscape(
            _world(),
            unreal.Vector(location_x, location_y, location_z),
            unreal.Vector(scale_x, scale_y, scale_z),
            layout["quads_per_section"], layout["sections_per_component"],
            ccx, ccy, material)
        if err:
            return json.dumps({"success": False, "message": err})

        comps = len(ls.get_components_by_class(unreal.LandscapeComponent))
        extent = ls.get_actor_bounds(False)[1]  # get_actor_bounds returns (origin, box_extent)
        return json.dumps({
            "success": True,
            "landscape_label": ls.get_actor_label(),
            "quads_per_section": layout["quads_per_section"],
            "sections_per_component": layout["sections_per_component"],
            "component_count_x": ccx, "component_count_y": ccy,
            "components": comps,
            "size_x_uu": extent.x * 2.0, "size_y_uu": extent.y * 2.0,
            "requested_uu": float(size_uu) if size_uu is not None else None,
            "message": "Report the RESOLVED size to the user, never the requested one.",
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


# ─── sculpt ───────────────────────────────────────────────────────────────────────

def ue_sculpt_border_mountains(landscape_label: str = None,
                               ridge_distance_uu: float = 1200.0,
                               ridge_half_width_uu: float = 1200.0,
                               peak_height_uu: float = 3500.0,
                               height_variation_uu: float = 4000.0,
                               min_peak_height_uu: float = None,
                               ridge_wander_uu: float = 5000.0,
                               noise_wavelength_uu: float = 3000.0,
                               roughness_uu: float = 400.0,
                               ground_height_uu: float = 100.0,
                               seed: int = 20260818,
                               walkable_floor_angle: float = 44.76,
                               margin_degrees: float = 8.0) -> str:
    """Raises an irregular mountain chain along the landscape's four edges.

    Sculpt BEFORE scattering: heights are absolute and rewrite the interior flat, so props
    placed earlier end up buried or floating. Defaults are calibrated by measurement of a
    hand-authored reference map: ground at 1 m, mean peak 35 m with 9.4 m standard
    deviation, crest ~11 m in from the edge. height_variation_uu is NOT the final
    deviation — the engine's Perlin yields ~0.233 of the parameter, so 4000 produces ~9 m.

    What stops the player is slope, not height: tan(angle) = peak * PI / (2 * half_width)
    against the character's WalkableFloorAngle. min_peak_height_uu is the floor the noise
    may not dig below and is what keeps the chain sealed; left None it is computed to
    guarantee walkable_floor_angle + margin_degrees. Measured without the floor: noise
    dropped peaks to 9.7 m, a 41.6-degree flank, and the escape test found a real route out.
    The floor lifts only the deep troughs — the irregularity survives (measured: deviation
    10.8 -> 10.2 m while the ring's worst angle went 9.3 -> 32.8 degrees).

    Same seed, same mountains. If a gap appears, NARROW the chain before raising it:
    half-width 1600 -> 1200 took one escape to zero without touching height or variation.
    """
    missing = _helper_missing()
    if missing:
        return missing
    if not landscape_label:
        return json.dumps({"success": False, "message":
            "Required parameter 'landscape_label' is missing (the actor label, e.g. from create_flat_landscape)."})
    try:
        ls, err = _find_landscape(landscape_label)
        if err:
            return json.dumps({"success": False, "message": err})

        if min_peak_height_uu is None:
            min_peak_height_uu = _min_peak_for_angle(
                float(walkable_floor_angle) + float(margin_degrees), float(ridge_half_width_uu))

        msg = unreal.MCPythonHelper.sculpt_border_mountains(
            ls, ridge_distance_uu, ridge_half_width_uu, peak_height_uu, height_variation_uu,
            min_peak_height_uu, ridge_wander_uu, noise_wavelength_uu, roughness_uu,
            ground_height_uu, seed)
        if msg:
            return json.dumps({"success": False, "message": msg})

        return json.dumps({
            "success": True,
            "zone_uu": ridge_distance_uu + ridge_wander_uu + ridge_half_width_uu,
            "min_peak_height_uu": round(min_peak_height_uu, 1),
            "guaranteed_min_angle": round(math.degrees(math.atan(
                min_peak_height_uu * math.pi / (2.0 * ridge_half_width_uu))), 1),
            "message": "Sculpted. Run escape_test after rebuild_navigation — mean height proves nothing about a gap.",
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


# ─── paint ────────────────────────────────────────────────────────────────────────

def ue_paint_by_slope(landscape_label: str = None, package_path: str = None,
                      flat_layer_name: str = None, slope_layer_name: str = None,
                      slope_start_degrees: float = 25.0, slope_full_degrees: float = 45.0,
                      save_layer_assets: bool = False) -> str:
    """Creates layer info assets and paints two landscape layers by terrain steepness.

    A LandscapeLayerBlend material shows nothing on a fresh landscape: paint layers are
    only names until each is bound to a ULandscapeLayerInfoObject, and a layer that is not
    registered as a target layer accepts SetAlphaData and silently discards it. Both are
    handled here. Layer names come from the material's LandscapeLayerBlend node, not from
    taste — read them off the material before calling.

    Weights are written to sum to 255 per vertex (weight-blend layers that do not sum full
    render darker, which reads as a lighting bug). With the border mountains' crest past
    60 degrees and a flat floor, 25/45 puts rock on the range and ground everywhere else.

    save_layer_assets=True saves the LI_ assets with only_if_is_dirty=False — the default
    save_asset short-circuits on a package the creation path did not mark dirty, returns
    True, and never writes the file. Painting cost, measured: two layers on a 4033x4033
    terrain took 24 s and grew the .umap 39 -> 113 MB (one weightmap texture per layer per
    component) — warn the caller on big maps.
    """
    missing = _helper_missing()
    if missing:
        return missing
    for name, val in (("landscape_label", landscape_label), ("package_path", package_path),
                      ("flat_layer_name", flat_layer_name), ("slope_layer_name", slope_layer_name)):
        if not val:
            return json.dumps({"success": False, "message": f"Required parameter '{name}' is missing."})
    try:
        ls, err = _find_landscape(landscape_label)
        if err:
            return json.dumps({"success": False, "message": err})

        flat, e1 = unreal.MCPythonHelper.find_or_create_landscape_layer_info(package_path, flat_layer_name)
        if e1:
            return json.dumps({"success": False, "message": f"layer info '{flat_layer_name}': {e1}"})
        slope, e2 = unreal.MCPythonHelper.find_or_create_landscape_layer_info(package_path, slope_layer_name)
        if e2:
            return json.dumps({"success": False, "message": f"layer info '{slope_layer_name}': {e2}"})

        msg = unreal.MCPythonHelper.paint_landscape_by_slope(
            ls, flat, slope, slope_start_degrees, slope_full_degrees)
        if msg:
            return json.dumps({"success": False, "message": msg})

        assets = [f"{package_path}/LI_{flat_layer_name}", f"{package_path}/LI_{slope_layer_name}"]
        saved = []
        if save_layer_assets:
            for a in assets:
                if unreal.EditorAssetLibrary.save_asset(a, False):
                    saved.append(a)

        return json.dumps({
            "success": True,
            "target_layers": [str(n) for n in ls.get_target_layer_names()],
            "layer_assets": assets,
            "saved": saved,
            "message": "Verify with render_weightmap or get_target_layer_names — an empty list means nothing registered.",
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


# ─── level skeleton ───────────────────────────────────────────────────────────────

def ue_build_level_skeleton(size_uu: float = None,
                            origin_x: float = 0.0, origin_y: float = 0.0,
                            game_mode_path: str = None,
                            extra_actor_class_paths: list = None,
                            sun_roll: float = -40.439, sun_pitch: float = -49.709, sun_yaw: float = 132.705,
                            sun_intensity: float = 2.0, sun_temperature: float = 8786.4,
                            sky_intensity: float = 2.0,
                            nav_bounds_margin_uu: float = 4600.0, nav_bounds_height_uu: float = 2000.0,
                            spawn_player_start: bool = True, spawn_post_process: bool = True,
                            spawn_sky: bool = True) -> str:
    """Spawns the structural actors a playable level needs: light, sky, nav bounds, PlayerStart.

    Everything is centred on origin + size_uu/2. Sun/sky defaults are the measured values of
    a hand-authored reference map (Movable, intensity 2.0, use_temperature ON at 8786 K —
    with use_temperature off the temperature property is decorative; the engine default is
    6500 K). Do NOT spawn RecastNavMesh: the navigation system creates it by itself as soon
    as a bounds volume exists.

    game_mode_path (optional) sets WorldSettings' default game mode — pass the generated
    class path with the _C suffix ('/Game/.../GM_Foo.GM_Foo_C'); without _C you load the
    Blueprint asset, not the class. extra_actor_class_paths (optional) spawns one actor of
    each _C class path at the centre (e.g. a project's loot handler).

    The NavMeshBoundsVolume is a brush actor sized through its CubeBuilder: setting x/y/z
    already rebuilds the brush (build() does not exist in Python and is not needed), the
    builder takes the FULL size while the extent read back is the half, and the actor's
    scale is left at (1,1,1) — do not resize by scaling. After building AND after
    scattering, call rebuild_navigation: navigation does not generate on its own in a
    script-built level.
    """
    if size_uu is None:
        return json.dumps({"success": False, "message": "Required parameter 'size_uu' is missing."})
    try:
        asub = _actors()
        cen_x = origin_x + float(size_uu) / 2.0
        cen_y = origin_y + float(size_uu) / 2.0
        spawned = []

        # unreal.Rotator is (roll, pitch, yaw), not (pitch, yaw, roll) — the trap is
        # contained here so callers pass named angles.
        dl = asub.spawn_actor_from_class(unreal.DirectionalLight,
                                         unreal.Vector(cen_x, cen_y, 5000),
                                         unreal.Rotator(sun_roll, sun_pitch, sun_yaw))
        c = dl.get_component_by_class(unreal.DirectionalLightComponent)
        c.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        c.set_editor_property("intensity", sun_intensity)
        if sun_temperature is not None:
            c.set_editor_property("use_temperature", True)
            c.set_editor_property("temperature", sun_temperature)
        spawned.append("DirectionalLight")

        if spawn_sky:
            sl = asub.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(cen_x, cen_y, 5000))
            s = sl.get_component_by_class(unreal.SkyLightComponent)
            s.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
            s.set_editor_property("real_time_capture", True)
            s.set_editor_property("intensity", sky_intensity)
            asub.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(cen_x, cen_y, 0))
            spawned.extend(["SkyLight", "SkyAtmosphere"])

        if spawn_post_process:
            pp = asub.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(cen_x, cen_y, 1000))
            pp.set_editor_property("unbound", True)
            spawned.append("PostProcessVolume")

        if spawn_player_start:
            asub.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(cen_x, cen_y, 300))
            spawned.append("PlayerStart")

        nb = asub.spawn_actor_from_class(unreal.NavMeshBoundsVolume, unreal.Vector(cen_x, cen_y, 0))
        bb = nb.get_editor_property("brush_builder")
        bb.set_editor_property("x", float(size_uu) + nav_bounds_margin_uu)
        bb.set_editor_property("y", float(size_uu) + nav_bounds_margin_uu)
        bb.set_editor_property("z", nav_bounds_height_uu)
        spawned.append("NavMeshBoundsVolume")

        if game_mode_path:
            gm = unreal.load_class(None, game_mode_path)
            if gm is None:
                return json.dumps({"success": False, "spawned": spawned, "message":
                    f"load_class failed for '{game_mode_path}' — Blueprint class paths need the _C suffix."})
            _world().get_world_settings().set_editor_property("default_game_mode", gm)
            spawned.append(f"WorldSettings.default_game_mode={game_mode_path}")

        for path in (extra_actor_class_paths or []):
            cls = unreal.load_class(None, path)
            if cls is None:
                return json.dumps({"success": False, "spawned": spawned, "message":
                    f"load_class failed for '{path}' — Blueprint class paths need the _C suffix."})
            asub.spawn_actor_from_class(cls, unreal.Vector(cen_x, cen_y, 100))
            spawned.append(path)

        ext = nb.get_actor_bounds(False)[1]  # (origin, box_extent)
        return json.dumps({
            "success": True, "spawned": spawned,
            "nav_bounds_extent": {"x": ext.x, "y": ext.y, "z": ext.z},
            "message": "Skeleton built. Call rebuild_navigation (after scattering, if any).",
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_rebuild_navigation() -> str:
    """Rebuilds navigation for the open level (required for script-built levels).

    Navigation does NOT generate on its own when a level is assembled by script. Measured:
    RecastNavMesh extent 494 before the command, 6422 after — covering the whole landscape.
    Run it AFTER scattering: props have collision and carve the navmesh; a rebuild done
    before scattering describes a map that no longer exists. Does not save the level.
    """
    try:
        unreal.SystemLibrary.execute_console_command(_world(), "RebuildNavigation")
        return json.dumps({"success": True, "message":
            "RebuildNavigation issued. Verify with a reachable-point query or escape_test."})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


# ─── scatter ──────────────────────────────────────────────────────────────────────

def ue_scatter_hism(specs: list = None, size_uu: float = None,
                    landscape_label: str = None,
                    margin_uu: float = 1000.0, seed: int = 20260818,
                    max_slope_degrees: float = 20.0,
                    scale_jitter_min: float = 0.85, scale_jitter_max: float = 1.15,
                    tries_per_item: int = 60, replace_existing: bool = True) -> str:
    """Scatters static meshes over the landscape as HISM instances, one actor per species.

    specs: list of {"mesh_path", "count", "base_scale", "radius_uu", "max_slope_degrees"?}
    (or positional lists in that order; the per-species slope limit is optional and
    overrides max_slope_degrees for that species only). Instances, not actors: 2580 objects
    fit in 29 actors, generated in 3.5 s, with collision and navmesh working. For long
    spec lists, call once per batch of species — each call is bounded, which keeps a slow
    scatter inside the MCP socket timeout.

    Four rules that came from measured failures, not taste:
    1. Species are placed in DESCENDING radius order. The big-radius species that comes
       last starves: measured 2-of-11 placed vs 11-of-11 by reordering alone.
    2. Minimum distance is the SUM of the two radii, not the max. With max(), a shrub
       inherits the big tree's radius and the understory vanishes exactly where it should
       be: 258-of-460 vs 460-of-460.
    3. Filter by SLOPE, not by a fat margin. A wide margin leaves an obvious bald ring
       around the mountains. Reference PCG puts trees at 0 degrees and rocks up to 56, so
       start from 20 for trees, 35 for shrubs, 60 for rocks.
    4. The accepted slope is recorded AT PLACEMENT. Measuring afterwards traces down onto
       the props themselves (they have collision) and a landscape-only filter then discards
       everything — a populated map read back as zero valid samples.

    The downward trace only accepts landscape hits, so props never stack on each other's
    canopies (measured: 5% of traces hit vegetation on a populated map, instances up to
    28 m in the air; the symptom is Z max far from Z min on flat terrain).

    replace_existing destroys previous 'Scatter_<mesh>' actors for the same species first,
    making a re-run idempotent per species. Nothing is saved.
    """
    missing = _helper_missing()
    if missing:
        return missing
    if not specs:
        return json.dumps({"success": False, "message": "Required parameter 'specs' is missing."})
    if size_uu is None:
        return json.dumps({"success": False, "message": "Required parameter 'size_uu' is missing."})
    try:
        ls, err = _find_landscape(landscape_label)
        if err:
            return json.dumps({"success": False, "message": err})
        origin_x, origin_y = _landscape_origin(ls)

        normalized = []
        for s in specs:
            if isinstance(s, dict):
                normalized.append((s["mesh_path"], int(s["count"]), float(s.get("base_scale", 1.0)),
                                   float(s["radius_uu"]), float(s.get("max_slope_degrees", max_slope_degrees))))
            else:
                normalized.append((s[0], int(s[1]), float(s[2]), float(s[3]),
                                   float(s[4]) if len(s) > 4 else float(max_slope_degrees)))

        by_radius = sorted(normalized, key=lambda s: -s[3])
        # Cell = 2 * the largest radius in use, so it stays >= the sum of the two largest
        # radii and the 3x3 neighbourhood still covers every possible pair.
        cell = max(s[3] for s in by_radius) * 2.0 or 1.0
        grid = {}
        rng = random.Random(seed)
        rejected_slope = 0
        stats = []
        asub = _actors()

        # Replacement happens ONCE, up front, for every label this call will touch.
        # Doing it per-species inside the loop destroys the instances an earlier spec of
        # the SAME mesh just placed (two specs sharing a mesh is legitimate: same tree at
        # two densities/scales).
        labels = {"Scatter_" + s[0].split("/")[-1].split(".")[0] for s in by_radius}
        if replace_existing:
            for a in list(asub.get_all_level_actors()):
                if a.get_actor_label() in labels:
                    asub.destroy_actor(a)
        created = {}  # label -> HISM component, reused when a mesh repeats in specs

        def fits(x, y, radius):
            cx, cy = int(x // cell), int(y // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for (px, py, pr) in grid.get((cx + dx, cy + dy), ()):
                        r = pr + radius  # SUM of radii — see rule 2 above
                        if (x - px) ** 2 + (y - py) ** 2 < r * r:
                            return False
            return True

        for path, count, base, radius, slope_limit in by_radius:
            name = path.split("/")[-1].split(".")[0]
            mesh = unreal.load_asset(path)
            if not mesh:
                stats.append({"mesh": name, "placed": 0, "requested": count, "error": "mesh did not load"})
                continue

            label = "Scatter_" + name
            comp = created.get(label)
            if comp is None:
                actor, aerr = unreal.MCPythonHelper.spawn_hism_scatter_actor(_world(), label, mesh)
                if aerr:
                    stats.append({"mesh": name, "placed": 0, "requested": count, "error": aerr})
                    continue
                comp = actor.get_component_by_class(unreal.HierarchicalInstancedStaticMeshComponent)
                created[label] = comp

            placed = 0
            tries = 0
            accepted_slopes = []
            limit = count * tries_per_item  # try ceiling: never an endless loop
            while placed < count and tries < limit:
                tries += 1
                x = origin_x + rng.uniform(margin_uu, float(size_uu) - margin_uu)
                y = origin_y + rng.uniform(margin_uu, float(size_uu) - margin_uu)
                if not fits(x, y, radius):
                    continue
                ground = _trace_ground(x, y)
                if ground is None:
                    continue
                z, normal = ground
                slope = _slope_degrees(normal)
                if slope > slope_limit:
                    rejected_slope += 1
                    continue
                sc = base * rng.uniform(scale_jitter_min, scale_jitter_max)
                comp.add_instance(unreal.Transform(unreal.Vector(x, y, z),
                                                   unreal.Rotator(0, 0, rng.uniform(0, 360)),
                                                   unreal.Vector(sc, sc, sc)), False)
                grid.setdefault((int(x // cell), int(y // cell)), []).append((x, y, radius))
                accepted_slopes.append(slope)
                placed += 1

            stats.append({
                "mesh": name, "placed": placed, "requested": count, "tries": tries,
                "slope_limit": slope_limit,
                "max_slope_used": round(max(accepted_slopes), 1) if accepted_slopes else None,
                "mean_slope": round(sum(accepted_slopes) / len(accepted_slopes), 1) if accepted_slopes else None,
            })

        incomplete = [s for s in stats if s.get("placed") != s.get("requested")]
        return json.dumps({
            "success": True,
            "instances": sum(s.get("placed", 0) for s in stats),
            "scatter_actors": len(created),
            "rejected_by_slope": rejected_slope,
            "incomplete": incomplete,
            "stats": stats,
            "message": ("Report per-species placed/requested to the user — placing 2 of 11 in "
                        "silence delivers a wrong map that looks finished. Rebuild navigation next."
                        if incomplete else "All species placed in full. Rebuild navigation next."),
        })
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_get_mesh_footprint(mesh_path: str = None) -> str:
    """Measures a static mesh's canopy radius and height, for scatter spacing (read-only).

    Measure the canopy instead of inventing a radius; in dense forest use ~0.8x the
    measured radius so canopies interlace.
    """
    if not mesh_path:
        return json.dumps({"success": False, "message": "Required parameter 'mesh_path' is missing."})
    try:
        m = unreal.load_asset(mesh_path)
        if not m:
            return json.dumps({"success": False, "message": f"Mesh not found: '{mesh_path}'."})
        b = m.get_bounds().box_extent
        return json.dumps({"success": True, "radius_uu": max(b.x, b.y), "height_uu": b.z * 2.0})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


# ─── verification ─────────────────────────────────────────────────────────────────

def ue_measure_borders(size_uu: float = None, samples_per_side: int = 41,
                       landscape_label: str = None, out_json_path: str = None) -> str:
    """Measures the border mountains: per-side peak mean/deviation/range and interior ground.

    The number that matters most is the DEVIATION: a uniform rim reads as machine-made from
    any angle (the hand-authored reference varies ~27% around its mean, crest wandering
    between 4 and 50 m from the edge). Reference values, measured 41 samples per side:
    ground 1.0 m, peak mean 35.0 m, deviation 9.4 m, range 16-58 m, crest ~11 m in.

    A sampling column that lands entirely on canopy has no valid sample and the position is
    DISCARDED — letting a sentinel into the list poisons mean and deviation (measured:
    'mean peak -4.8 m, deviation 157 m' on a correct map). out_json_path also writes the
    result to disk, for runs that outlive the MCP socket.
    """
    import statistics
    if size_uu is None:
        return json.dumps({"success": False, "message": "Required parameter 'size_uu' is missing."})
    try:
        ls, err = _find_landscape(landscape_label)
        if err:
            return json.dumps({"success": False, "message": err})
        x0, y0 = _landscape_origin(ls)
        size = float(size_uu)
        distances_m = [0, 4, 8, 12, 16, 20, 25, 30, 35, 40, 50, 60, 80]
        step = size / 100.0 / (samples_per_side + 1)

        def point(side, along_m, d_m):
            if side == "west":
                return x0 + d_m * 100.0, y0 + along_m * 100.0
            if side == "east":
                return x0 + size - d_m * 100.0, y0 + along_m * 100.0
            if side == "south":
                return x0 + along_m * 100.0, y0 + d_m * 100.0
            return x0 + along_m * 100.0, y0 + size - d_m * 100.0

        res = {}
        for side in ("west", "east", "south", "north"):
            peaks, crest_pos = [], []
            for i in range(samples_per_side):
                along = step + i * step
                best = None
                for dm in distances_m:
                    ground = _trace_ground(*point(side, along, dm))
                    if ground is None:
                        continue
                    if best is None or ground[0] > best[0]:
                        best = (ground[0], dm)
                if best is None:
                    continue  # covered column: discard, never a sentinel
                peaks.append(round(best[0] / 100.0, 1))
                crest_pos.append(best[1])
            if not peaks:
                res[side] = {"error": "no valid sample"}
                continue
            res[side] = {
                "peak_min_m": min(peaks), "peak_max_m": max(peaks),
                "peak_mean_m": round(statistics.mean(peaks), 1),
                "peak_stdev_m": round(statistics.pstdev(peaks), 1),
                "crest_dist_mean_m": round(statistics.mean(crest_pos), 1),
            }

        interior = []
        for f in (0.4, 0.5, 0.6):
            for g in (0.4, 0.5, 0.6):
                ground = _trace_ground(x0 + size * f, y0 + size * g)
                if ground:
                    interior.append(ground[0] / 100.0)
        res["interior_ground_m"] = round(statistics.mean(interior), 1) if interior else None
        res["success"] = True
        if out_json_path:
            _write_json(out_json_path, res)
            res["written_to"] = out_json_path
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_escape_test(size_uu: float = None, outside_distance_uu: float = 300.0,
                   step_uu: float = 600.0, escape_tolerance_uu: float = 300.0,
                   landscape_label: str = None, out_json_path: str = None) -> str:
    """Answers the question that matters: is there a navigable route out of the map?

    Mean border height proves nothing about a gap. This asks the navigation system for a
    path from the map's centre to points in the OUTER band beyond the mountains; any
    complete path is an escape. Run AFTER rebuild_navigation.

    find_path_to_location_synchronously returns a PARTIAL path to the nearest reachable
    point and still reports is_valid() == True — without comparing the path's endpoint to
    the target, the test cries escape everywhere (measured: 203 false escapes out of 664
    targets; after the endpoint check, 1 real one). Partial paths stopping short are the
    expected outcome: they are walkers hitting the mountain.

    The navmesh's own agent_max_slope is reported alongside so the caller can compare it
    with the character's WalkableFloorAngle — the test is a proxy for the navmesh agent,
    not for the actual character.
    """
    if size_uu is None:
        return json.dumps({"success": False, "message": "Required parameter 'size_uu' is missing."})
    try:
        ls, err = _find_landscape(landscape_label)
        if err:
            return json.dumps({"success": False, "message": err})
        x0, y0 = _landscape_origin(ls)
        size = float(size_uu)
        center = unreal.Vector(x0 + size / 2.0, y0 + size / 2.0, 200.0)

        targets = []
        along = step_uu
        while along < size - step_uu:
            targets.append((x0 + along, y0 + outside_distance_uu))
            targets.append((x0 + along, y0 + size - outside_distance_uu))
            targets.append((x0 + outside_distance_uu, y0 + along))
            targets.append((x0 + size - outside_distance_uu, y0 + along))
            along += step_uu

        escapes, partials, tested = [], 0, 0
        w = _world()
        for x, y in targets:
            ground = _trace_ground(x, y)
            if ground is None:
                continue
            tested += 1
            dest = unreal.Vector(x, y, ground[0] + 100.0)
            path = unreal.NavigationSystemV1.find_path_to_location_synchronously(w, center, dest)
            if path is None:
                continue
            try:
                if not path.is_valid():
                    continue
                points = path.get_editor_property("path_points")
            except Exception:
                continue
            if not points:
                continue
            end = points[-1]
            ev = end if isinstance(end, unreal.Vector) else end.get_editor_property("location")
            d = math.hypot(ev.x - x, ev.y - y)
            if d < escape_tolerance_uu:
                escapes.append({"x": round(x), "y": round(y)})
            else:
                partials += 1

        agent_max_slope = None
        try:
            for a in _actors().get_all_level_actors():
                if isinstance(a, unreal.RecastNavMesh):
                    agent_max_slope = float(a.get_editor_property("agent_max_slope"))
                    break
        except Exception:
            pass

        res = {"success": True, "targets_tested": tested, "escapes": len(escapes),
               "partial_paths": partials, "escape_examples": escapes[:10],
               "agent_max_slope": agent_max_slope,
               "message": ("0 escapes: the ring is sealed for the navmesh agent (not the actual "
                           "character — ask for a PIE lap before shipping)." if not escapes else
                           "ESCAPES FOUND — the ring has a gap. Narrow the chain "
                           "(ridge_half_width) before raising it.")}
        if out_json_path:
            _write_json(out_json_path, res)
            res["written_to"] = out_json_path
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_border_weak_points(size_uu: float = None, step_along_uu: float = 1200.0,
                          step_d_uu: float = 200.0, max_d_uu: float = 6000.0,
                          walkable_floor_angle: float = 44.76,
                          landscape_label: str = None, out_json_path: str = None) -> str:
    """Ranks border profiles by how easy they are to climb (complements escape_test).

    escape_test answers 'can you get out?'; this answers 'where does it almost give?'.
    CAUTION: false positives within ~50 m of a corner — with d = min(dx, dy) a profile
    traced near the corner runs along the outer band and never crosses the crest, showing
    as passable without being a real route. Always confirm with escape_test.
    """
    if size_uu is None:
        return json.dumps({"success": False, "message": "Required parameter 'size_uu' is missing."})
    try:
        ls, err = _find_landscape(landscape_label)
        if err:
            return json.dumps({"success": False, "message": err})
        x0, y0 = _landscape_origin(ls)
        size = float(size_uu)

        def point(side, along, d):
            if side == "west":
                return x0 + d, y0 + along
            if side == "east":
                return x0 + size - d, y0 + along
            if side == "south":
                return x0 + along, y0 + d
            return x0 + along, y0 + size - d

        worst = []
        for side in ("west", "east", "south", "north"):
            along = step_along_uu
            while along < size - step_along_uu:
                max_angle, prev = 0.0, None
                d = 0.0
                while d <= max_d_uu:
                    ground = _trace_ground(*point(side, along, d))
                    z = ground[0] if ground else None
                    if z is not None and prev is not None:
                        max_angle = max(max_angle, math.degrees(math.atan2(abs(z - prev), step_d_uu)))
                    prev = z
                    d += step_d_uu
                worst.append({"angle": round(max_angle, 1), "side": side,
                              "pos_m": round(along / 100.0, 1)})
                along += step_along_uu

        worst.sort(key=lambda p: p["angle"])
        res = {"success": True, "walkable_limit": walkable_floor_angle,
               "profiles": len(worst),
               "passable": sum(1 for p in worst if p["angle"] < walkable_floor_angle),
               "ten_weakest": worst[:10],
               "message": "Confirm any passable profile with escape_test — corner profiles lie."}
        if out_json_path:
            _write_json(out_json_path, res)
            res["written_to"] = out_json_path
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})


def ue_level_budget_report(max_actors: int = 500, max_landscape_components: int = 1024,
                           max_instances: int = 20000) -> str:
    """Counts level actors, landscape components and mesh instances against budget limits.

    Actor count, landscape component count and instance count are what decide loading,
    memory and render cost — worth reporting before delivering a generated map. The limits
    are parameters; the defaults suit a 60 fps / hundreds-of-entities action game.
    """
    try:
        acts = _actors().get_all_level_actors()
        ls, _ = _find_landscape()
        comps = len(ls.get_components_by_class(unreal.LandscapeComponent)) if ls else 0
        inst = 0
        for a in acts:
            for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
                inst += c.get_instance_count()

        counts = {"actors": len(acts), "landscape_components": comps, "instances": inst}
        limits = {"actors": max_actors, "landscape_components": max_landscape_components,
                  "instances": max_instances}
        alerts = [f"{k} = {v}, above the suggested limit of {limits[k]}"
                  for k, v in counts.items() if v > limits[k]]
        return json.dumps({"success": True, **counts, "alerts": alerts})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})
