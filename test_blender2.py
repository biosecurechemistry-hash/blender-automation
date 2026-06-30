import bpy
import json
import sys

# This function reads the JSON payload passed from n8n
def render_from_json(json_string):
    data = json.loads(json_string)
    
    # 1. Update the Text Object (The "Ending Remarks")
    if "content" in data:
        text_obj = bpy.data.objects.get("EndingRemarks")
        if text_obj:
            text_obj.data.body = data["content"]
            
    # 2. Update the Mesh Type (Cylinder, Sphere, etc.)
    if "mesh_type" in data:
        # Code to swap/modify the mesh based on the input
        print(f"Setting geometry to: {data['mesh_type']}")
        
    # 3. Trigger the Animation Seed
    # This ensures your logo animates uniquely every time!
    seed = data.get("id", 0)
    bpy.context.scene.frame_start = 1
    # ... logic to adjust particle randomness based on 'seed'
    
    # Run the render
    bpy.ops.render.render(animation=True)

# Usage: This script will be called by your n8n/MCP client
if __name__ == "__main__":
    payload = sys.argv[1]
    render_from_json(payload)