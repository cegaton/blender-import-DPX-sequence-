bl_info = {
    "name": "DPX / EXR Import + Compositor Setup",
    "description": "Import DPX or EXR image sequences, match resolution/frame range, and build compositor stabilization chain.",
    "author": "Stable 2.80 → 5.x, modified for DPX + EXR",
    "version": (8, 3, 0),
    "blender": (2, 80, 0),
    "location": "File > Import > DPX / EXR Sequence (Compositor Setup)",
    "category": "Import-Export",
}

import bpy
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty
import os
import re


# ------------------------------------------------------------
# Supported sequence types
# ------------------------------------------------------------
SEQUENCE_SETTINGS = {
    ".dpx": {
        "label": "DPX",
        "input_colorspace": "ADX10",
    },
    ".exr": {
        "label": "EXR",
        "input_colorspace": "ACEScg",
    },
}


# ------------------------------------------------------------
# Extract last 4 digits from frame number before extension
# ------------------------------------------------------------
def extract_frame_number(filename, extension=None):
    lower_name = filename.lower()

    if extension is not None and not lower_name.endswith(extension.lower()):
        return None

    match = re.search(r"(\d+)(?=\.[^.]+$)", lower_name)
    if not match:
        return None

    return int(match.group(1)) % 10000


# ------------------------------------------------------------
# Set Movie Clip input colorspace safely
# ------------------------------------------------------------
def set_clip_colorspace(movie_clip, target_name):
    try:
        movie_clip.colorspace_settings.name = target_name
        return True, target_name
    except Exception:
        pass

    try:
        enum_items = movie_clip.colorspace_settings.bl_rna.properties["name"].enum_items
        target_lower = target_name.lower()
        for item in enum_items:
            if item.identifier.lower() == target_lower or item.name.lower() == target_lower:
                movie_clip.colorspace_settings.name = item.identifier
                return True, item.identifier
    except Exception:
        pass

    return False, target_name


# ------------------------------------------------------------
# Get compositor node tree
#
# Blender 2.80–4.x:
#   scene.use_nodes = True  →  scene.node_tree
#
# Blender 5.x (verified via diagnostics on 5.1.1):
#   scene.node_tree was REMOVED (AttributeError).
#   scene.use_nodes is deprecated (gone in 6.0).
#   The compositor is now a CompositorNodeTree node group
#   created with bpy.data.node_groups.new() and assigned to
#   scene.compositing_node_group.
# ------------------------------------------------------------
def get_compositor_tree(context):
    scene = context.scene
    major = bpy.app.version[0]

    if major >= 5:
        # Return the existing compositor node group if already set.
        if scene.compositing_node_group is not None:
            return scene.compositing_node_group

        # Create a new CompositorNodeTree and assign it to the scene.
        ng = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
        scene.compositing_node_group = ng
        return ng

    else:
        # Blender 2.80–4.x
        scene.use_nodes = True
        return scene.node_tree


# ------------------------------------------------------------
# Operator
# ------------------------------------------------------------
class IMPORT_DPX_EXR_OT_sequence(bpy.types.Operator, ImportHelper):
    bl_idname = "import_dpx_exr.sequence"
    bl_label = "Import DPX / EXR Sequence"
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(
        default="*.dpx;*.exr",
        options={'HIDDEN'}
    )

    def execute(self, context):

        filepath = self.filepath
        directory = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        extension = os.path.splitext(filename)[1].lower()

        if not os.path.exists(filepath):
            self.report({'ERROR'}, "File does not exist.")
            return {'CANCELLED'}

        if extension not in SEQUENCE_SETTINGS:
            self.report({'ERROR'}, "Please choose a DPX or EXR file.")
            return {'CANCELLED'}

        sequence_label = SEQUENCE_SETTINGS[extension]["label"]
        input_colorspace = SEQUENCE_SETTINGS[extension]["input_colorspace"]

        sequence_files = sorted(
            f for f in os.listdir(directory)
            if f.lower().endswith(extension)
        )

        if not sequence_files:
            self.report({'ERROR'}, f"No {sequence_label} files found.")
            return {'CANCELLED'}

        frames = []
        for f in sequence_files:
            frame = extract_frame_number(f, extension)
            if frame is not None:
                frames.append(frame)

        if not frames:
            self.report({'ERROR'}, f"No valid {sequence_label} frame numbers detected.")
            return {'CANCELLED'}

        frame_start = min(frames)
        frame_end = max(frames)

        bpy.ops.clip.open(
            directory=directory,
            files=[{"name": filename}],
        )

        movie_clip = bpy.data.movieclips.get(filename)

        if movie_clip is None:
            self.report({'ERROR'}, f"Failed to load {sequence_label} sequence.")
            return {'CANCELLED'}

        scene = context.scene

        scene.render.resolution_x = movie_clip.size[0]
        scene.render.resolution_y = movie_clip.size[1]

        scene.frame_start = frame_start
        scene.frame_end = frame_end
        movie_clip.frame_start = frame_start

        scene.render.fps = 24
        scene.render.fps_base = 1.0

        colorspace_ok, applied_colorspace = set_clip_colorspace(movie_clip, input_colorspace)
        if not colorspace_ok:
            self.report(
                {'WARNING'},
                f"Could not set input colorspace to {input_colorspace}. "
                "Check that your Blender OCIO config includes it."
            )

        base_name = re.sub(r"\d{4}(?=\.[^.]+$)", "####", filename)
        output_name = os.path.splitext(base_name)[0]

        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_depth = "16"
        scene.render.image_settings.exr_codec = "PIZ"
        scene.render.filepath = os.path.join(directory, output_name)

        self.build_compositor(context, movie_clip)

        if colorspace_ok:
            self.report(
                {'INFO'},
                f"{sequence_label} imported, colorspace set to {applied_colorspace}, and compositor created."
            )
        else:
            self.report(
                {'INFO'},
                f"{sequence_label} imported and compositor created."
            )

        return {'FINISHED'}

    # ------------------------------------------------------------
    # Build Compositor
    #
    # Blender 5.x API changes (confirmed by diagnostics on 5.1.1):
    #
    #   - CompositorNodeComposite is UNDEFINED in a CompositorNodeTree
    #     node group. The output node is NodeGroupOutput instead.
    #
    #   - NodeGroupOutput requires an output socket to be registered
    #     on the group's interface first via tree.interface.new_socket().
    #     Without this the node has no inputs to connect to.
    #
    #   - The compositor renders the socket named "Image" on the
    #     NodeGroupOutput as the final composite result.
    #
    # Blender 2.80–4.x uses the classic CompositorNodeComposite node
    # on scene.node_tree unchanged.
    # ------------------------------------------------------------
    def build_compositor(self, context, movie_clip):

        tree = get_compositor_tree(context)

        if tree is None:
            self.report({'ERROR'}, "Compositor node tree unavailable.")
            return

        tree.nodes.clear()
        major = bpy.app.version[0]

        # ── Blender 5.x ─────────────────────────────────────────
        if major >= 5:

            # Clear any existing interface sockets so we start fresh.
            for item in list(tree.interface.items_tree):
                tree.interface.remove(item)

            # Register one output socket on the group interface.
            # This creates the "Image" input on NodeGroupOutput that
            # the compositor reads as the final rendered image.
            tree.interface.new_socket(
                name="Image",
                in_out='OUTPUT',
                socket_type='NodeSocketColor',
            )

            clip_node = tree.nodes.new("CompositorNodeMovieClip")
            clip_node.clip = movie_clip
            clip_node.location = (-400, 0)

            stabilize_node = tree.nodes.new("CompositorNodeStabilize")
            stabilize_node.clip = movie_clip
            stabilize_node.location = (0, 0)

            # NodeGroupOutput replaces CompositorNodeComposite in 5.x.
            output_node = tree.nodes.new("NodeGroupOutput")
            output_node.location = (400, 0)

            tree.links.new(
                clip_node.outputs["Image"],
                stabilize_node.inputs["Image"],
            )
            tree.links.new(
                stabilize_node.outputs["Image"],
                output_node.inputs["Image"],
            )

        # ── Blender 2.80–4.x ────────────────────────────────────
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
                stabilize_node.inputs["Image"],
            )
            tree.links.new(
                stabilize_node.outputs["Image"],
                composite_node.inputs["Image"],
            )


# ------------------------------------------------------------
# Menu
# ------------------------------------------------------------
def menu_func_import(self, context):
    self.layout.operator(
        IMPORT_DPX_EXR_OT_sequence.bl_idname,
        text="DPX / EXR Sequence (Compositor Setup)"
    )


def register():
    bpy.utils.register_class(IMPORT_DPX_EXR_OT_sequence)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_DPX_EXR_OT_sequence)


if __name__ == "__main__":
    register()
