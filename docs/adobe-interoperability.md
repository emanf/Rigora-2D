# Adobe interoperability review

Reviewed 2026-11-01 against Adobe's published workflows and Rigora's actual import,
rigging, audio and output services. Similar workflows do not imply native project
compatibility.

| Input/workflow | Working Rigora route | Boundary |
| --- | --- | --- |
| Photoshop PSD/PSB | Basic layered pixel/group import, offsets, visibility and retained original source | A rendered subset; masks/effects can be baked. Photoshop's full editable feature set is not reconstructed. |
| Illustrator AI | Explicit PDF-compatible artboard raster approximation, original retained | No private Illustrator layer/vector parser. Use exported SVG for vectors. |
| SVG artwork | Original vectors, independent parts, rigging and output-resolution deformation | No automatic reconstruction of Adobe puppet behaviors/tags. Text needs vector outlines for headless output. |
| Speech/voice | PCM WAV, explicit microphone capture, offline streaming phonemes or local Rhubarb cues | Direct MP3/AIFF decoding is not implemented; convert to PCM WAV first. |
| Performances | Editable keys, Puppet Stage action/replay cards and synchronized audio | Replay cards refer to project-local actions; Adobe take/replay data is not imported. |
| Live output | Transparent local browser-source frames, separate application-audio capture | No NDI, Syphon, Mercury Transmit, Dynamic Link or virtual camera. |
| `.puppet` / `.chproj` | No parser/import route advertised | These are not renamed artwork archives or `.rigora` documents. Rebuild rig/behavior mappings from supported artwork and media. |

Adobe documents `.puppet` as a self-contained puppet-sharing file and explicitly
notes that timeline parameter changes/recorded takes are excluded. Its `.chproj`
workflow imports another Character Animator project's contents and media.
Those are Adobe-to-Adobe workflows; the reviewed pages do not specify an external
conversion API used by Rigora. Rigora therefore does not claim compatibility with
those project formats. See [puppet sharing](https://helpx.adobe.com/in/adobe-character-animator/desktop/creating-and-controlling-puppets/puppet.html)
and [projects/import formats](https://helpx.adobe.com/adobe-character-animator/desktop/introduction/projects.html).

For vector exchange, Illustrator documents SVG export for use in other
applications. Keep the original AI working file and export SVG parts for Rigora;
the PDF-compatible AI route supplies artboard pixels, not native editing data.
See [Illustrator export formats](https://helpx.adobe.com/illustrator/desktop/save-and-export/export-files-to-different-formats/export-artwork-from-illustrator.html).

Adobe's broadcast workflow uses Mercury Transmit and compatible output devices/
plugins. Rigora's loopback Browser Source is a separate implementation; it neither
loads Adobe transmit plugins nor impersonates an NDI sender. See
[Adobe streaming](https://helpx.adobe.com/adobe-character-animator/desktop/export-projects/streaming.html)
and [Rigora local output](local-broadcast.md).

The practical interchange route is PSD layers or SVG parts plus PCM WAV, followed
by Rigora bindings, authored views, face controls and editable action/replay keys.
Use transparent sequences/video for rendered interchange, or validated native
Godot/Unity rigs for supported game integrations. Unreal scene playback remains
blocked until its adapter can be implemented and validated with an installed
engine/SDK; unsupported camera/particle routes remain rejected by preflight.

Review: **8/10** for verified workflow boundaries, retained sources and honest
fallbacks. Full Adobe project/behavior conversion and native Unreal validation
remain actual gaps, not completed features.
