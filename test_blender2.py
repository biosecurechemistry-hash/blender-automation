import bpy
import json
import sys
import math
import os
import re
import glob
import shutil


# ---------------------------------------------------------------------------
# Output routing — campaign subfolder isolation
# ---------------------------------------------------------------------------
def resolve_campaign_path(cfg):
    """Build the campaign output directory and ensure it exists.

    Resolves campaign_id from the payload (numeric ID like 52580) or falls
    back to a sanitised slug of campaign_title.  Creates the folder tree::

        BlenderAutomationOutputs/
          campaign_52580/          ← all production assets
            frames/                ← PNG frame sequences (instantly scannable)
            _blend/                ← .blend + any .blend1 backups (isolated)
            _audio/                ← generated audio assets
            _cache/                ← transient files, cleaned post-render
    """
    root = cfg.get("output_dir", r"C:\Users\Public\Documents\BlenderAutomationOutputs")

    # 1. Resolve campaign identity
    campaign_id = cfg.get("campaign_id")
    if campaign_id is None:
        # Derive a numeric-ish slug from campaign_title
        title = cfg.get("campaign_title", "dynamic_asset")
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", str(title)).strip("_")[:60]
        campaign_id = slug

    campaign_dir = os.path.join(root, f"campaign_{campaign_id}")

    # 2. Create the tree
    frames_dir = os.path.join(campaign_dir, "frames")
    blend_dir  = os.path.join(campaign_dir, "_blend")
    audio_dir  = os.path.join(campaign_dir, "_audio")
    cache_dir  = os.path.join(campaign_dir, "_cache")

    for d in (frames_dir, blend_dir, audio_dir, cache_dir):
        os.makedirs(d, exist_ok=True)

    print(f"[ROUTE] Campaign output → {campaign_dir}")
    return campaign_dir, frames_dir, blend_dir, audio_dir, cache_dir


def cleanup_backups(campaign_dir: str):
    """Remove .blend1 and other transient files from the campaign tree.

    Called post-render so the user-facing frames/ directory stays clean.
    """
    removed = 0
    for pattern in ("*.blend1", "*.blend@*", "*.tmp"):
        for path in glob.glob(os.path.join(campaign_dir, "**", pattern),
                              recursive=True):
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"[CLEAN] Removed {removed} backup/temp files from {campaign_dir}")


# ---------------------------------------------------------------------------
# Material presets
# ---------------------------------------------------------------------------
MATERIAL_PRESETS = {
    "chrome": {
        "base_color": (0.9, 0.9, 0.9, 1.0),
        "metallic": 1.0,
        "roughness": 0.05,
    },
    "matte": {
        "base_color": (0.85, 0.85, 0.85, 1.0),
        "metallic": 0.0,
        "roughness": 0.7,
    },
    "glass": {
        "base_color": (0.95, 0.95, 0.98, 1.0),
        "metallic": 0.0,
        "roughness": 0.0,
        "transmission": 0.95,
        "ior": 1.45,
    },
    "emissive": {
        "base_color": (1.0, 0.6, 0.1, 1.0),
        "metallic": 0.1,
        "roughness": 0.3,
        "emission": (0.8, 0.4, 0.05),
        "emission_strength": 2.0,
    },
    "gold": {
        "base_color": (0.95, 0.7, 0.2, 1.0),
        "metallic": 1.0,
        "roughness": 0.1,
    },
}

LIGHT_PRESETS = {
    "studio": {"sun_energy": 4.0, "fill_energy": 1500.0, "fill_color": (0.1, 0.3, 1.0)},
    "warm": {"sun_energy": 5.0, "fill_energy": 800.0, "fill_color": (1.0, 0.6, 0.2)},
    "dramatic": {"sun_energy": 8.0, "fill_energy": 300.0, "fill_color": (0.05, 0.05, 0.3)},
    "soft": {"sun_energy": 2.0, "fill_energy": 2000.0, "fill_color": (0.8, 0.85, 1.0)},
}


# ---------------------------------------------------------------------------
# Geometry builders
# ---------------------------------------------------------------------------
def build_helix(molecule_target, cfg):
    """Twisting helix of ico-spheres climbing the Z axis."""
    elements = cfg.get("elements_count", 12)
    radius = cfg.get("cluster_radius", 1.8)
    el_radius = cfg.get("element_radius", 0.45)
    rotations = cfg.get("rotations", 1.5)
    z_height = cfg.get("z_height", 4.0)
    subdivisions = cfg.get("subdivisions", 3)

    for i in range(elements):
        angle = (i / elements) * (2 * math.pi) * rotations
        z_offset = (i / elements) * z_height - (z_height / 2.0)
        loc_x = math.cos(angle) * radius
        loc_y = math.sin(angle) * radius
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=subdivisions, radius=el_radius,
            location=(loc_x, loc_y, z_offset))
        sphere = bpy.context.active_object
        sphere.parent = molecule_target
        sphere.name = f"Node_{i}"


def build_grid(molecule_target, cfg):
    """Flat grid of cubes, evenly spaced."""
    elements = cfg.get("elements_count", 16)
    cols = int(math.ceil(math.sqrt(elements)))
    spacing = cfg.get("grid_spacing", 1.5)
    size = cfg.get("element_size", 0.6)

    for i in range(elements):
        row = i // cols
        col = i % cols
        x = (col - (cols - 1) / 2.0) * spacing
        y = (row - (cols - 1) / 2.0) * spacing
        bpy.ops.mesh.primitive_cube_add(size=size, location=(x, y, 0))
        cube = bpy.context.active_object
        cube.parent = molecule_target
        cube.name = f"Cell_{i}"


def build_sphere_cluster(molecule_target, cfg):
    """Fibonacci sphere distribution — evenly spread points on a sphere."""
    elements = cfg.get("elements_count", 20)
    radius = cfg.get("cluster_radius", 2.0)
    el_radius = cfg.get("element_radius", 0.25)
    subdivisions = cfg.get("subdivisions", 2)
    phi = math.pi * (3.0 - math.sqrt(5.0))

    for i in range(elements):
        y = 1.0 - (i / float(elements - 1)) * 2.0
        radius_at_y = math.sqrt(1.0 - y * y)
        theta = phi * i
        x = math.cos(theta) * radius_at_y
        z = math.sin(theta) * radius_at_y
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=subdivisions, radius=el_radius,
            location=(x * radius, y * radius, z * radius))
        s = bpy.context.active_object
        s.parent = molecule_target
        s.name = f"Point_{i}"


def build_ring(molecule_target, cfg):
    """Concentric rings at varying heights."""
    rings = cfg.get("rings", 3)
    elements_per_ring = cfg.get("elements_per_ring", 12)
    radius = cfg.get("cluster_radius", 2.0)
    el_radius = cfg.get("element_radius", 0.3)

    idx = 0
    for r in range(rings):
        r_height = (r - (rings - 1) / 2.0) * cfg.get("ring_spacing", 1.8)
        for i in range(elements_per_ring):
            angle = (i / elements_per_ring) * 2.0 * math.pi
            x = math.cos(angle) * radius
            y = math.sin(angle) * radius
            bpy.ops.mesh.primitive_ico_sphere_add(
                subdivisions=2, radius=el_radius,
                location=(x, y, r_height))
            s = bpy.context.active_object
            s.parent = molecule_target
            s.name = f"Ring_{r}_Node_{i}"
            idx += 1


GEOMETRY_BUILDERS = {
    "helix": build_helix,
    "grid": build_grid,
    "sphere": build_sphere_cluster,
    "ring": build_ring,
}


# ---------------------------------------------------------------------------
# Master scene builder
# ---------------------------------------------------------------------------
def setup_headless_molecular_scene(cfg):
    """Build a dynamic 3D scene from a configuration dict.

    All values are drawn from `cfg` with sensible defaults, so existing
    payloads continue to work unchanged.
    """
    campaign_title = cfg.get("campaign_title", "Dynamic_Asset")
    prompt_brief = cfg.get("prompt_brief", "")
    geo_type = cfg.get("geometry", "helix")
    material_name = cfg.get("material", "chrome")
    light_name = cfg.get("lighting", "studio")
    frame_start = cfg.get("frame_start", 1)
    frame_end = cfg.get("frame_end", 120)
    camera_lens = cfg.get("camera_lens", 100)
    camera_fstop = cfg.get("camera_fstop", 0.2)
    resolution_x = cfg.get("resolution_x", 1920)
    resolution_y = cfg.get("resolution_y", 1080)
    do_render = cfg.get("render_animation", True)
    do_save = cfg.get("save_blend", True)

    # --- campaign subfolder routing ---
    campaign_dir, frames_dir, blend_dir, audio_dir, cache_dir = \
        resolve_campaign_path(cfg)

    print(f"[CONFIG] geometry={geo_type}  material={material_name}"
          f"  lighting={light_name}  frames={frame_start}-{frame_end}"
          f"  resolution={resolution_x}x{resolution_y}"
          f"  lens={camera_lens}mm  f/{camera_fstop}")
    if prompt_brief:
        print(f"[BRIEF] {prompt_brief[:120]}")

    # 1. Clear everything
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mat in bpy.data.materials:
        bpy.data.materials.remove(mat, do_unlink=True)

    # 2. Anchor
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
    molecule_target = bpy.context.active_object
    molecule_target.name = f"Cluster_{campaign_title}"

    # 3. Build geometry
    builder = GEOMETRY_BUILDERS.get(geo_type, build_helix)
    builder(molecule_target, cfg)
    print(f"[GEO] Built {geo_type} with {len(molecule_target.children)} elements")

    # 4. Material
    preset = MATERIAL_PRESETS.get(material_name, MATERIAL_PRESETS["chrome"])
    mat = bpy.data.materials.new(name=f"Mat_{material_name}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]

    if "base_color" in preset:
        bsdf.inputs['Base Color'].default_value = preset["base_color"]
    if "metallic" in preset:
        bsdf.inputs['Metallic'].default_value = preset["metallic"]
    if "roughness" in preset:
        bsdf.inputs['Roughness'].default_value = preset["roughness"]
    if "transmission" in preset:
        bsdf.inputs['Transmission Weight'].default_value = preset["transmission"]
    if "ior" in preset:
        bsdf.inputs['IOR'].default_value = preset["ior"]
    if "emission" in preset:
        bsdf.inputs['Emission Color'].default_value = preset["emission"]
        bsdf.inputs['Emission Strength'].default_value = preset.get("emission_strength", 1.0)

    # Override base color if explicitly passed
    color_primary = cfg.get("color_primary")
    if color_primary:
        bsdf.inputs['Base Color'].default_value = tuple(color_primary)

    for child in molecule_target.children:
        child.data.materials.append(mat)
    print(f"[MAT] Applied material preset: {material_name}")

    # 5. Lights
    light_preset = LIGHT_PRESETS.get(light_name, LIGHT_PRESETS["studio"])

    bpy.ops.object.light_add(type='SUN', radius=1.0, location=(5, -5, 10))
    sun_light = bpy.context.active_object
    sun_light.name = "PrimarySun"
    sun_light.data.energy = light_preset["sun_energy"]
    sun_light.rotation_euler = (math.radians(75), 0, math.radians(-45))

    bpy.ops.object.light_add(type='AREA', radius=5.0, location=(-6, 6, 2))
    blue_fill = bpy.context.active_object
    blue_fill.name = "FillLight"
    blue_fill.data.energy = light_preset["fill_energy"]
    blue_fill.data.color = light_preset["fill_color"]
    print(f"[LIGHT] Lighting preset: {light_name}")

    # 6. Camera
    cam_distance = cfg.get("camera_distance", 9.0)
    cam_height = cfg.get("camera_height", 2.0)
    bpy.ops.object.camera_add(location=(0, -cam_distance, cam_height))
    cam = bpy.context.active_object
    cam.name = "Cinematic_Cam"
    bpy.context.scene.camera = cam
    cam.data.dof.use_dof = True
    cam.data.dof.focus_object = molecule_target
    cam.data.dof.aperture_fstop = camera_fstop
    cam.data.lens = camera_lens

    track = cam.constraints.new(type='DAMPED_TRACK')
    track.target = molecule_target
    track.track_axis = 'TRACK_NEGATIVE_Z'
    print(f"[CAM] {camera_lens}mm  f/{camera_fstop}")

    # 7. Scene / animation
    scene = bpy.context.scene
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = cfg.get("resolution_percentage", 100)
    scene.render.fps = cfg.get("fps", 24)
    # Route render frames into campaign_<id>/frames/
    scene.render.filepath = os.path.join(frames_dir, f"{campaign_title}_frame_")
    scene.render.image_settings.file_format = 'PNG'

    # Suppress automatic .blend1 backup generation during automated renders
    prefs = bpy.context.preferences
    if hasattr(prefs.filepaths, "save_version"):
        prefs.filepaths.save_version = 0  # 0 = no .blend1 backups

    print(f"[SCENE] {frame_start}-{frame_end} @ {scene.render.fps}fps  "
          f"{resolution_x}x{resolution_y} @ {scene.render.resolution_percentage}%")

    # 8. Render (optional — skip for scene-info-only mode)
    if do_render:
        frame_count = frame_end - frame_start + 1
        print(f"[DISK] Baking {frame_count} frames → {frames_dir}")
        bpy.ops.render.render(animation=True)
        print(f"[DISK] Rendered {frame_count} frames to frames/")

    # 9. Save .blend (optional) — isolated in _blend/ subfolder
    if do_save:
        output_path = os.path.join(blend_dir, f"output_{campaign_title}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=output_path)
        print(f"[DISK] Saved master layout to: {output_path}")

    # 10. Post-render housekeeping
    cleanup_backups(campaign_dir)

    print(f"[SUCCESS] Scene built for campaign: {campaign_title}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            with open(sys.argv[-1], 'r', encoding='utf-8') as f:
                payload = json.load(f)

            # Support both the old positional-call convention and the new
            # fully-dynamic config dict.  Old payloads that only carry
            # {campaign_title, prompt_brief} still work — those fields
            # are just read from the dict inside the builder.
            setup_headless_molecular_scene(payload)

        except Exception as e:
            print(f"Error parsing queue payload: {str(e)}")
