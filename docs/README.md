# Rigora documentation

## Workflows

| Topic | Guide |
| --- | --- |
| Installation and optional dependencies | [Install Rigora](installation.md) |
| First rigged character | [Quick start](quick-start.md) |
| Modular parts, clothing, expressions and presets | [Character Creator](character-wizard.md) |
| Object Editor, views and private actions | [Object and character workflow](object-character-workflow.md) |
| Linked Objects across scenes | [Linked Objects](linked-objects.md) |
| Artwork, bones and skin binding | [Rigging guide](rigging-guide.md), [mesh and spring design](mesh-and-spring-design.md) |
| FFD, lattices and mesh deformation | [Deformation](deformation.md) |
| Clips, curves and character action rows | [Animation editing](animation-editing.md), [timeline](timeline.md) |
| Spring groups and mouse performance recording | [Spring Dynamics and Motion Pilot](spring-and-motion-pilot.md), [editor design](spring-editor-design.md) |
| Facial controls, audio and mouth cues | [Facial animation](facial-animation.md) |
| Offline streaming phonemes and editable speech takes | [Live lip-sync](live-speech.md) |
| Transparent local browser-source output | [Local broadcast](local-broadcast.md) |
| Adobe workflow compatibility and limits | [Adobe interoperability](adobe-interoperability.md) |
| Optional local tracking | [Camera performance](camera-performance.md) |
| Scene cameras and camera cuts | [Cameras](cameras.md) |
| Retargeting between compatible rigs | [Motion retargeting](retargeting.md) |
| Draggable motions, rigs, FFD, springs, SVG props and animated effects | [Creative Templates](creative-templates.md), [source research](creative-library-research.md) |
| Images, sequences and video to editable human/quadruped rigs | [Media to Rig](video-to-rig.md), [17-project research](video-rig-research.md), [built-in keying](keying-source-review.md) |
| Import formats and rendered output | [Asset pipeline](asset-pipeline.md) |
| Unity, Godot and Unreal adapters | [Game engine export](game-engine-export.md) |
| Recovery, diagnostics, contacts, layers, audio, events, particles and state machines | [Production workflows](production-workflows.md) |

## Extensions and automation

Start with [Build a Rigora plugin](plugin-development.md), then use the
[SDK callback reference](plugin-sdk.md) and [Extension API 2](extensions.md).
The tutorial includes a complete source package and covers development loading,
trust, menus, toolbars, context menus, panels, testing, ZIP installation, native
dependencies, hooks, dynamic presets and cleanup.

For other integrations, read [Python API](python-api.md),
[CLI reference](cli-reference.md), [automation](automation.md), and
[MCP setup](mcp-setup.md). These adapters share the application services.

## Development and releases

- [Contributing and repository layout](contributing.md)
- [Development setup and checks](development.md)
- [Native desktop builds](desktop-builds.md)
- [GitHub upload and automated releases](github-releases.md)
- [Package audits and release checks](release.md)
- [Architecture](architecture/0001-foundation.md)
- [Project format](project-format.md)
- [Asset and dependency provenance](provenance.md)
- [Known limitations](limitations.md)

`validation-*.md` files are dated engineering records. They describe the source
and tests at that time, not a promise that every historical screenshot or local
build log ships in the repository. Generated evidence belongs in ignored
`build/`; current tests and benchmark tools reproduce the workflows. Older
milestone audits are retained as history and may predate later features.
