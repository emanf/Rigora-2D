# Built-in background keying

Rigora's keyer runs in the application process with NumPy, OpenCV and Pillow.
There is no Blender discovery, installation, executable selection or subprocess.
Preview and final artwork share `key_cutout` and reuse the same cached PNG when
the reference image and controls match.

## Source study

Reviewed on 2026-11-02:

- [Blender 4.5.3 Keying implementation](https://github.com/blender/blender/blob/v4.5.3/source/blender/nodes/composite/nodes/node_composite_keying.cc):
  CPU matte calculation, chroma preprocessing, edge-sensitive levels, matte
  cleanup and despill. The source identifies its license as GPL-2.0-or-later.
- [Blender's current Keying implementation](https://github.com/blender/blender/blob/main/source/blender/nodes/composite/nodes/node_composite_keying.cc):
  checked the current node inputs and processing stages against the fixed version.
- [Keying node manual](https://docs.blender.org/manual/en/4.3/compositing/types/keying/keying.html):
  the screen-color and matte workflow.

The runtime is independently authored Python array processing using the reviewed
color-keying mathematics. Blender source, comments, shaders and libraries are not
vendored, translated into a standalone component, or redistributed. Project
licensing is unchanged. This is not Blender embedded in Rigora or a promise of
pixel-identical Blender rendering.

## Processing and controls

1. Validate the encoded size and working dimensions before allocating pixel arrays.
   Existing PNG alpha passes through byte-for-byte, including fractional alpha.
2. Convert opaque sRGB pixels and the picked screen color into linear light.
   Auto samples a common perimeter color and selects colored or neutral keying.
3. Optional chroma blur smooths color residuals while preserving local luminance.
   Chroma derives coverage from the dominant screen channel relative to the other
   channels; Difference measures mean linear RGB distance from a neutral screen.
4. Tolerance removes low-coverage noise. Soft edge adjusts the transition range.
   Chroma retains detail where the local matte varies, using a 7×7 neighborhood.
5. Optional matte blur, elliptical grow/shrink and distance-based feather refine
   the outline. Positive grow/feather expands; negative values contract it.
6. Despill reduces excess screen-channel color in linear light. Key balance and
   Despill balance independently weight the other two channels.
7. Encode straight RGBA pixels. Fully transparent generated pixels have zero RGB;
   partially transparent pixels retain straight color without dark premultiplication.

Controls are immutable worker inputs, and cancellation is checked between native
stages. Buffers cover one reference image, up to 1920×1080 and 16 MiB encoded.
Pixel filters are bounded to 16 pixels. GUI, Python, CLI and MCP use this pipeline.

The implementation supports ordinary 8-bit image references. It does not reproduce
Blender's complete compositor, OCIO/HDR pipeline, GPU implementation, arbitrary
matte-node graphs or exact feather falloff kernels. Solid-screen keying cannot
recover foreground pixels matching the backdrop; complex footage needs prepared
alpha or author cleanup.

## Validation

Tests process actual pixels while prohibiting external process launches. They
check green/blue/neutral screens, foreground RGB, continuous alpha, despill,
cleanup filters, existing alpha, cancellation, malformed inputs and limits.
The offscreen window tests verify the all-bones playback toggle and exact reuse
of reviewed PNG bytes during character creation. Native review uses original
human and quadruped artwork with the installed local pose models.

The broader media/animation/API regression run passed 63 tests; the final
pixel/UI recheck passed 18 tests, including indexed-PNG transparency. Reports:
`build/media-rig-builtin-final.xml` and
`build/media-rig-builtin-alpha-final.xml`. Offscreen window captures confirm the
single all-bones lock is in the playback area and executable controls are absent.

Review: **8.7/10**. Criteria: solid-screen fidelity 9.5 (30%), UI consistency 9.5
(20%), deployment independence 10 (20%), and complex-matte coverage 6.5 (30%).
Complex backgrounds and missing source layers remain the main limitation.
