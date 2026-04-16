bl_info = {
    "name": "DPX Import + Compositor Setup",
    "description": "Import DPX sequence, match resolution/frame range, and build compositor stabilization chain.",
    "author": "Stable 2.80 → 5.x",
    "version": (12, 0, 0),
    "blender": (2, 80, 0),
    "location": "File > Import > DPX Sequence (Compositor Setup)",
    "category": "Import-Export",
}

import bpy
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty
import os
import re


# ------------------------------------------------------------
# Extract last 4 digits from frame number
# ------------------------------------------------------------
def extract_frame_number(filename):
    match = re.search(r"(\d+)(?=\.dpx$)", filename.lower())
    if not match:
        return None
    return int(match.group(1)) % 10000

# ------------------------------------------------------------
# Add "stable" to the output name
# ------------------------------------------------------------
def make_stable_name(filename):
    match = re.match(r"(.*?)(\d+)(?=\.[^.]+$)", filename)
    if not match:
        # No digits found, just strip extension
        base_name = os.path.splitext(filename)[0]
        output_name = base_name
        return base_name, output_name

    prefix = match.group(1).rstrip("_")   # avoid double underscores
    number_str = match.group(2)

    # Construct new name: prefix + "_stable_" + digits before last 4 + "####"
    base_name = prefix + "_stable_" + number_str[:-4] + "####"
    output_name = base_name
    return base_name, output_name

# ------------------------------------------------------------
# Set compositor tree active in UI
# Not working yet
# ------------------------------------------------------------

def set_active_compositor_tree(context, tree):

    window = context.window
    screen = window.screen

    # Try to find an existing node editor
    for area in screen.areas:
        if area.type == 'NODE_EDITOR':
            for space in area.spaces:
                if space.type == 'NODE_EDITOR':
                    space.tree_type = 'CompositorNodeTree'
                    if hasattr(space, "node_tree"):
                        space.node_tree = tree
                    return

    # If no node editor exists → force one using override
    for area in screen.areas:
        if area.type == 'VIEW_3D':  # hijack a 3D view
            override = {
                "window": window,
                "screen": screen,
                "area": area,
                "region": area.regions[-1],
            }

            try:
                bpy.ops.screen.area_split(override, direction='VERTICAL', factor=0.5)
                new_area = screen.areas[-1]
                new_area.type = 'NODE_EDITOR'

                space = new_area.spaces.active
                space.tree_type = 'CompositorNodeTree'
                if hasattr(space, "node_tree"):
                    space.node_tree = tree

            except Exception:
                pass

            return



# ------------------------------------------------------------
# Get / Create compositor node tree
# ------------------------------------------------------------
def get_compositor_tree(context):

    major = bpy.app.version[0]

    if major >= 5:

        for group in bpy.data.node_groups:
            if group.bl_idname == "CompositorNodeTree":
                return group

        return bpy.data.node_groups.new(
            name="DPX_Compositor",
            type="CompositorNodeTree"
        )

    scene = context.scene
    scene.use_nodes = True
    return scene.node_tree


# ------------------------------------------------------------
# Operator
# ------------------------------------------------------------
class IMPORT_DPX_OT_sequence(bpy.types.Operator, ImportHelper):
    bl_idname = "import_dpx.sequence"
    bl_label = "Import DPX Sequence"
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(
        default="*.dpx",
        options={'HIDDEN'}
    )

    def execute(self, context):

        filepath = self.filepath
        directory = os.path.dirname(filepath)
        filename = os.path.basename(filepath)

        if not os.path.exists(filepath):
            self.report({'ERROR'}, "File does not exist.")
            return {'CANCELLED'}

        dpx_files = sorted(
            f for f in os.listdir(directory)
            if f.lower().endswith(".dpx")
        )

        if not dpx_files:
            self.report({'ERROR'}, "No DPX files found.")
            return {'CANCELLED'}

        frames = []

        for f in dpx_files:
            frame = extract_frame_number(f)
            if frame is not None:
                frames.append(frame)

        if not frames:
            self.report({'ERROR'}, "No valid frame numbers detected.")
            return {'CANCELLED'}

        frame_start = min(frames)
        frame_end = max(frames)

        # Load DPX sequence
        bpy.ops.clip.open(
            directory=directory,
            files=[{"name": filename}],
        )

        movie_clip = bpy.data.movieclips.get(filename)

        if movie_clip is None:
            self.report({'ERROR'}, "Failed to load DPX sequence.")
            return {'CANCELLED'}

        scene = context.scene

        # Resolution
        scene.render.resolution_x = movie_clip.size[0]
        scene.render.resolution_y = movie_clip.size[1]

        # Frame range
        scene.frame_start = frame_start
        scene.frame_end = frame_end
        movie_clip.frame_start = frame_start

        scene.render.fps = 24
        scene.render.fps_base = 1.0

        try:
            movie_clip.colorspace_settings.name = "ADX10"
        except Exception:
            pass


        # Output settings using stable naming
        base_name, output_name = make_stable_name(filename)
        
        scene.render.image_settings.file_format = "DPX"
        scene.render.image_settings.color_depth = "10"
        scene.render.image_settings.use_cineon_log = True
        scene.render.image_settings.linear_colorspace_settings.name = 'ADX10'
        
        scene.render.filepath = os.path.join(directory, output_name)

        output_name = os.path.splitext(base_name)[0]

        self.build_compositor(context, movie_clip)

        self.report({'INFO'}, "DPX imported and compositor created.")
        return {'FINISHED'}

    # ------------------------------------------------------------
    # Build Compositor
    # ------------------------------------------------------------
    def build_compositor(self, context, movie_clip):

        tree = get_compositor_tree(context)

        if tree is None:
            self.report({'ERROR'}, "Compositor system not available.")
            return

        tree.nodes.clear()

        major = bpy.app.version[0]

         # ---------------- Blender 5.x ----------------
        if major >= 5:
        
            # Clear existing interface sockets (important!)
            if hasattr(tree, "interface"):
                tree.interface.clear()
        
                # Create proper Image output socket
                tree.interface.new_socket(
                    name="Image",
                    in_out='OUTPUT',
                    socket_type='NodeSocketColor'
                )
        
            clip_node = tree.nodes.new("CompositorNodeMovieClip")
            clip_node.clip = movie_clip
            clip_node.location = (-400, 0)
        
            stabilize_node = tree.nodes.new("CompositorNodeStabilize")
            stabilize_node.clip = movie_clip
            stabilize_node.location = (0, 0)
        
            output_node = tree.nodes.new("NodeGroupOutput")
            output_node.location = (400, 0)
        
            tree.links.new(
                clip_node.outputs["Image"],
                stabilize_node.inputs["Image"]
            )
        
            # Now this works correctly
            tree.links.new(
                stabilize_node.outputs["Image"],
                output_node.inputs["Image"]
            )
        
            set_active_compositor_tree(context, tree)

        # ---------------- Blender 2.80–4.x ----------------
        else:

            clip_node = tree.nodes.new("CompositorNodeMovieClip")
            clip_node.clip = movie_clip
            clip_node.location = (-400, 0)

            stabilize_node = tree.nodes.new("CompositorNodeStabilize")
            stabilize_node.clip = movie_clip
            stabilize_node.location = (0, 0)

            composite_node = tree.nodes.new("CompositorNodeComposite")
            composite_node.location = (400, 0)

            tree.links.new(
                clip_node.outputs["Image"],
                stabilize_node.inputs["Image"]
            )

            tree.links.new(
                stabilize_node.outputs["Image"],
                composite_node.inputs["Image"]
            )


# ------------------------------------------------------------
# Menu
# ------------------------------------------------------------
def menu_func_import(self, context):
    self.layout.operator(
        IMPORT_DPX_OT_sequence.bl_idname,
        text="DPX Sequence (Compositor Setup)"
    )


def register():
    bpy.utils.register_class(IMPORT_DPX_OT_sequence)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_DPX_OT_sequence)


if __name__ == "__main__":
    register()
