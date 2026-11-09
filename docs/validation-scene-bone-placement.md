# Scene bone placement

Validated on 2026-10-29 in the owner's timezone. Source and packaged application
checks use `QT_QPA_PLATFORM=offscreen`, isolated preferences and explicit widget
events. No foreground windows or desktop pointer movement are used.

## Review: 9/10

| Criterion | Score | Evidence |
| --- | --- | --- |
| Requested behavior | 4/4 | Real premade Panda bone silhouettes follow translation, rotation, nonuniform scale, mirroring, committed transforms, saved Object placements and cursor ghosts |
| Solver and edit integrity | 2/2 | Bind-space nodes remain unchanged; meshes are shared rather than deformed twice; live springs, Undo/Redo and Object Editor transitions retain alignment |
| Display integration | 2/2 | Viewport hit geometry, read-only Scene Context, onion previews, motion trails and SVG overlays share the display mapping; subdivision artwork retains its cache |
| Platform coverage | 1/2 | Windows source and packaged executable verified offscreen; native interactive input and Linux/macOS execution were not tested |

Skinned bones intentionally remain in their binding coordinates during engine
evaluation. The skinning stage applies `Object world * inverse(Object binding)`
to place the artwork. The viewport previously drew the unplaced bone matrices.
Each evaluated pose now carries those display placement matrices separately.
`ScenePose.for_display()` applies them once to a display-only snapshot, retaining
the canonical pose for authoring, constraints, deformation and physics. Bare rigs
already placed by the evaluator do not receive a second transform. Reference
poses are resolved before mapping the scene into Object Editor coordinates.

The affected suite passed **61 tests** with exit code 0, including existing bone
editing, springs, creator Objects, source/template placement, pivots and headless
automation/rendering workflows (`build/bone-placement-final.xml`). After the final
cache correction, **3 tests** rechecked actual bone drawing, subdivision caching
and live Spring rendering (`build/bone-placement-recheck.xml`). Ruff lint and
format checks pass; mypy passes for all **212 source modules**.

Packaged-app validation is recorded in
`build/bone-placement-compiled-headless/run-1.json`. The temporary validation
plugin observes real silhouette draw endpoints while exercising the actual
offscreen application. Its checks include the prior 15 Object, scene, binding,
timeline and pivot workflows, plus 5 bone placement and Spring workflows. The
test plugin and copied preference profile are outside the shipped bundle.

`Build_Rigora.bat --no-pause` produced
`dist/windows-amd64-20261028-221809-a3175c/Rigora/Rigora.exe`. All **20 packaged
checks passed**, exit code 0, including the final subdivision-cache assertion.
The reviewed capture is `bone-placement-workspace.png` beside the JSON report.
Keep the entire bundle folder together. The host generates build-folder
timestamps; the validation date above uses the owner's timezone.
