import bpy
import json
import sys
import math

def setup_headless_molecular_scene(campaign_title, prompt_brief):
    # 1. Force clear EVERYTHING in the scene database to completely eliminate defaults
    for obj in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    
    # Remove default collections/materials to prevent pollution
    for mat in bpy.data.materials:
        bpy.data.materials.remove(mat, do_unlink=True)
        
    # 2. Procedural Geometry: Build a twisting structure instead of just a basic sphere
    # Create an anchor container
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
    molecule_target = bpy.context.active_object
    molecule_target.name = f"Cluster_{campaign_title}"
    
    # Generate a procedural twisting chain string using an array pattern
    elements_count = 12
    for i in range(elements_count):
        angle = (i / elements_count) * (2 * math.pi) * 1.5  # 1.5 rotations
        z_offset = (i / elements_count) * 4.0 - 2.0         # Climb up Z axis
        radius = 1.8
        
        loc_x = math.cos(angle) * radius
        loc_y = math.sin(angle) * radius
        
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.45, location=(loc_x, loc_y, loc_z_offset := z_offset))
        sphere = bpy.context.active_object
        sphere.parent = molecule_target
        sphere.name = f"Node_{i}"
    
    # 3. Create Polished Chrome Material (Fixed spelling with double 'l')
    mat = bpy.data.materials.new(name="ChromeMaterial")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs['Base Color'].default_value = (0.9, 0.9, 0.9, 1.0)
    bsdf.inputs['Metallic'].default_value = 1.0     # <-- Fixed double 'l' typo
    bsdf.inputs['Roughness'].default_value = 0.05   # Mirror finish
    
    # Link material to all child elements
    for child in molecule_target.children:
        child.data.materials.append(mat)
    
    # 4. Re-create the lighting rig (Key Sun + Blue Shadow Fill array)
    bpy.ops.object.light_add(type='SUN', radius=1.0, location=(5, -5, 10))
    sun_light = bpy.context.active_object
    sun_light.name = "PrimarySun"
    sun_light.data.energy = 4.0
    sun_light.rotation_euler = (math.radians(75), 0, math.radians(-45))
    
    # Add deep blue secondary fill light for dual-toned colored shadow bands
    bpy.ops.object.light_add(type='AREA', radius=5.0, location=(-6, 6, 2))
    blue_fill = bpy.context.active_object
    blue_fill.name = "BlueFill"
    blue_fill.data.energy = 1500.0
    blue_fill.data.color = (0.1, 0.3, 1.0)
    
    # 5. Re-create the cinematic camera
    bpy.ops.object.camera_add(location=(0, -9, 2))
    cam = bpy.context.active_object
    cam.name = "Cinematic_Micro_Cam"
    bpy.context.scene.camera = cam
    
    # 6. Set microscopic shallow focus configurations
    cam.data.dof.use_dof = True
    cam.data.dof.focus_object = molecule_target
    cam.data.dof.aperture_fstop = 0.2  # Ultra ultra-shallow micro focus
    cam.data.lens = 100                 # Crisp macro zoom lens
    
    # 7. Lock camera focus target using a tracking constraint
    track_constraint = cam.constraints.new(type='DAMPED_TRACK')
    track_constraint.target = molecule_target
    track_constraint.track_axis = 'TRACK_NEGATIVE_Z'
    
    # 8. Set scene animation parameters
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 120
    print(f"[SUCCESS] Scene built for campaign: {campaign_title}")
    
    # 9. Set Output File Path & Bake the Render
    # Prefixing with campaign title stops cross-campaign file overwriting
    scene.render.filepath = f"C:\\Users\\Public\\Documents\\BlenderAutomationOutputs\\{campaign_title}_frame_"
    scene.render.image_settings.file_format = 'PNG'
    
    print(f"[DISK] Baking {campaign_title} frames to disk...")
    bpy.ops.render.render(animation=True)
    
    # 10. Save master scene layout
    output_path = f"C:\\Users\\Public\\Documents\\BlenderAutomationOutputs\\output_{campaign_title}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=output_path)
    print(f"[DISK] Saved master layout to: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            with open(sys.argv[-1], 'r') as f:
                payload = json.load(f)
            
            campaign_title = payload.get("campaign_title", "Dynamic_Asset")
            prompt_brief = payload.get("prompt_brief", "")
            
            setup_headless_molecular_scene(campaign_title, prompt_brief)
            
        except Exception as e:
            print(f"Error parsing queue payload: {str(e)}")