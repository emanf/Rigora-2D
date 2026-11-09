# Raster color and orientation

New raster imports interpret untagged pixels as sRGB. Tagged imports use Pillow's
LittleCMS binding to convert an embedded ICC profile to sRGB and apply EXIF
orientation before creating mesh dimensions. Alpha is retained independently of
the color transform. Corrected artwork is stored as a derived PNG; its asset
metadata points to an opaque source asset containing the exact original bytes.
Both assets travel with the project, and one Undo removes the whole import.
Ordinary untagged images retain their original bytes and media type.

This policy applies to new `MeshService.register_image_bytes` imports and the
image route through `AssetPipeline`. Opening an existing project does not
rewrite its artwork. Invalid profiles fail before document mutation. Correction
requires the `render` extra; bounded inputs are limited to 8192 pixels per axis,
16 megapixels and a 4 MiB embedded profile.

The working interpretation is sRGB. Monitor profiling, HDR/linear-light
compositing, OCIO and complete PSD/Illustrator color-space preservation are not
implemented by this change. Export codecs can introduce their own chroma and
compression changes; use PNG or FFV1 when exact RGBA output matters.

Regression coverage uses actual oriented RGBA and LAB-profiled images, checks
pixel/alpha results, preserves original source bytes through save/reopen and
checks that malformed profiles leave the project unchanged.
