Addon for blender 4.xx or 5.xx
Load DPX and EXR files into the video clip editor for motion tracking and stabilizing.

Sets frame size to match the DPX dimensions.

Creates a node tree in the compositor with the video clip as source and a 2D stabilzation node connected to it. 

Presumes that the file naming is name_framenumber.dpx.

Uses the last 4 digis of the file name for frame start and end in the blender project

Sets the output name with a _stable_ prefix

Color space is set to ADX10, using custom config.ocio

