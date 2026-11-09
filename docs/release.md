# Development candidate release process

Rigora 0.1.0 is a development candidate. Passing the checks below does not certify
the entire Master Brief or remove the open items in [release-audit.md](release-audit.md).
The local commands below do not publish or upload anything. For the explicitly
dispatched workflow that builds and attaches native downloads to an existing
GitHub release, follow [GitHub releases](github-releases.md).

## Build from locked sources

For a native executable or macOS application, use the checked
[desktop build scripts](desktop-builds.md). The workflow below additionally
produces Python wheel/source distributions for developers.

Use Python 3.12, uv and an unmodified source snapshot. Record the snapshot/archive
hash when Git metadata is unavailable. Keep the lock with the source release.

```powershell
uv sync --locked --extra gui --extra mcp --extra render --extra psd
.\Test_Rigora.bat --no-pause
$env:SOURCE_DATE_EPOCH = '1792281600'
uv build --offline
python -m tools.audit_release --manifest dist/release-manifest.json
```

Build preparation may download dependencies the first time; `--offline` requires
the pinned Hatchling build requirements in the uv cache. `SOURCE_DATE_EPOCH` fixes
build timestamps (2026-10-18 UTC here). Preserve it when rebuilding a candidate.
The wheel and source archive go in `dist/`. The manifest records their SHA-256,
lock hash and available build-environment package versions. It refuses replacing
an existing manifest; archive old candidates separately before rebuilding.
This is a repeatable locked build process, not a claim that arbitrary machines
produce byte-identical archives.

The audit checks every canonical asset and source module byte-for-byte in the
wheel, complete source guides/examples/tools, source docstrings, exclusions and
batch CRLF. Keep ignored build output, personal files and source reference images
out of distributions. Version comes from `src/rigora/__init__.py`; project format,
plugin API and Python API have independent compatibility versions.

## Smoke the installed package

Create a fresh environment, install the built wheel with the selected extras,
and run from the extracted source directory so `tools/` is available:

```powershell
python -m tools.release_smoke --root build/release-smoke-new --mcp --raster
python -m tools.benchmark_release
python tools/benchmark_animation.py --bones 1000 --tracks 1000 --keys 100
python tools/benchmark_deformation.py --frames 31
```

The smoke creates only a fresh destination. It checks original character/content,
bone animation, FFD, undo/redo, exact source/pose reopening, SVG/optional PNG,
generated trusted plugin activation/disable, actual CLI and optional official MCP
stdio. Omit optional switches in a core-only install. It never changes the real
desktop profile. Source-only smoke is useful during development; installed-wheel
smoke additionally checks packaging and optional dependency separation.

`benchmark_release` measures a four-stage dense mesh, a 99,000-frame clip, 128
installed packs and background SVG rendering. Temporary fixtures are removed;
stdout is JSON for comparison. Compare medians and tails on the same host, without
timing assertions in tests. Frame timings exclude fixture construction and UI draw.

## Release checklist

- [ ] Full locked test/static gate passes with all intended extras; record skips.
- [ ] Wheel/sdist and manifest audit pass; archive the exact artifacts and lock.
- [ ] Core-only installed smoke works without Qt/MCP/codecs.
- [ ] Full installed smoke passes, including official MCP stdio and PNG output.
- [ ] Native desktop dark/light, custom chrome, keyboard focus, timeline resizing,
  drag/drop, FFD handles, live bone posing and multi-project save/open checked.
- [ ] Failed save/open/export and missing/incompatible plugin recovery checked.
- [ ] Performance report records hardware, workload sizes and limits.
- [ ] Code license and owner-supplied bone redistribution status resolved.
- [ ] Dependency/asset notices reviewed for the actual shipped bundle.
- [ ] Known limitations, quick start, API/CLI/MCP, SDK and format guides match build.
- [ ] Public target platforms, signing/update/install/uninstall policy agreed and tested.

Do not check boxes solely because this document exists. The dated audit records
what was actually exercised. Standalone packaging/signing and public redistribution
remain separate release work. Use [installation.md](installation.md) for current
wheel installation and [quick-start.md](quick-start.md) for the end-user workflow.
