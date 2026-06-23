Addon for blender 4.xx or 5.xx

Imports DPX and EXR files into the video clip editor for motion tracking and stabilizing.

Sets blender project frame size to match the DPX dimensions and sets start and end frames to match the clip start and end.

Color space is set to ADX10 for dpx files and ACEScg for EXR files using custom config.ocio.

Creates a node tree in the compositor with the video clip as source and a 2D stabilzation node connected to it. 

Presumes that the file naming is name_framenumber.dpx.

The last 4 digis of the original file name are used for frame start and end in the blender project,

Ouput is set to EXR format using PIZ compression and ACEScg color space.

Sets the output name with a _stable_ prefix.
