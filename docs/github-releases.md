# GitHub upload and native release packages

The manual workflow at [`.github/workflows/release.yml`](../.github/workflows/release.yml)
builds the commit named by the repository's latest stable release, packages
native applications, and attaches the verified downloads to that release.
Its structure follows the separate release-selection, platform-build, and
publication jobs used by FrameLine.

Local development remains source-only. Adding this workflow does not compile
the app, upload the repository, or create a release on your behalf.

## 1. Upload the source repository

Create an empty GitHub repository. Before making it public, resolve the source
license and owner-supplied artwork terms described in [provenance](provenance.md).
The existing notices are retained; this cleanup does not choose a license.

If this folder is not already a Git checkout, initialize it in a terminal:

```sh
git init
git add .
git status --short
git diff --cached --stat
```

Review the staged files. Source, tests, canonical assets, examples, documentation,
the lockfile and `.github/` should be included. `build/`, `dist/`, `.venv/`, caches,
private prompts/task notes and credentials should be absent. Then commit and
connect your own repository URL:

```sh
git commit -m "Prepare Rigora source and release workflow"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

For an existing repository, inspect its current branch/remotes and use its normal
commit/push process instead. GitHub Desktop can perform the equivalent steps.

## 2. Publish a release tag

The release tag must point to a commit containing the build scripts, lockfile,
assets, and release packaging tools. Publishing a release for an older commit
will build that older source, even if the workflow itself is newer.

1. Push the prepared source, including the workflow, to the default branch.
2. In GitHub, open **Releases → Draft a new release**.
3. Choose or create a tag for the intended commit, for example `v0.1.0`.
4. Add release notes describing the candidate and any platform limits.
5. Publish it as a normal release, with **Set as a pre-release** unchecked.

The workflow uses GitHub's latest-release API, which excludes drafts and
prereleases. A repository containing only prereleases therefore has no eligible
release. This describes GitHub's release classification, not a production-quality
certification. See the official [release API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).

Immutable releases cannot accept new attachments after publication. If repository
policy makes releases immutable, this particular “attach to an existing release”
workflow must be replaced with a build-before-publication process. It fails clearly
instead of changing that policy or silently creating another release.

## 3. Run the action

1. Sign in as the repository owner.
2. Open **Actions → Build and upload to latest release**.
3. Choose **Run workflow** from the default branch.
4. Leave **Also run source checks and offscreen application verification** off
   for compilation only. Enable it when you want the full source/static gate and
   packaged-application verification as part of the build.
5. Leave **Replace matching Rigora packages** off for a first upload. Enable it
   only when intentionally replacing downloads with the same generated names.
6. Start the workflow and inspect its summary for the selected release and commit.

Only the personal repository owner may dispatch or rerun publication. The helper
checks both the original and triggering actor. Organization repositories need an
explicit maintainer policy before changing this guard.

The workflow uses `GITHUB_TOKEN`; it does not require a personal access token.
Build jobs receive read-only repository access. Only the publication job requests
`contents: write`. Repository/organization policy must allow the required Actions
and token permissions. See [GitHub's token permissions guide](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication).

## 4. Build targets and files

| Download | Runner | Main application |
| --- | --- | --- |
| `Rigora-<tag>-windows-x64.zip` | `windows-2025` | `Rigora/Rigora.exe` |
| `Rigora-<tag>-linux-x64.zip` | `ubuntu-24.04` | `Rigora/Rigora` |
| `Rigora-<tag>-macos-arm64.zip` | `macos-15` | `Rigora.app` |

These targets use Python 3.12 and the locked dependencies, including optional
import/render/tracking integrations. Intel macOS is excluded because the pinned
tracking dependency has no compatible Intel wheel. Windows x86 is also excluded.
The hosted runner labels and architectures follow GitHub's
[runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Each build invokes the existing native builder. It creates a fresh isolated
environment, checks dependency consistency, and runs PyInstaller. Linux installs
missing native GUI/build libraries when needed. No cross-compilation is attempted.
`verify` is optional and defaults to false, matching the local compile-only scripts.

Windows ZIPs retain the complete application directory. Linux's `zip --symlinks`
preserves executable modes and links; macOS uses `ditto` to retain the app bundle's
framework links and metadata. The packaging helper does not modify the compiled
`.app` after signing. These packages are not signed installers or notarized macOS
downloads. See [desktop builds](desktop-builds.md) for OS/runtime requirements.

## 5. Verification before upload

The workflow freezes the release ID, tag and resolved commit before starting
the matrix. Every builder checks out that exact commit. Packaging requires a
passing `build-report.json`, the expected executable, matching architecture, and
the lockfile digest.

Each ZIP has a `.release.json` manifest with its exact tag, source SHA, size,
SHA-256 and compiler report. The publication job downloads only this run's package
artifacts, verifies all three targets and their hashes, and produces
`SHA256SUMS.txt`. A failed or missing platform stops publication; successful jobs
remain downloadable as short-lived Actions artifacts for diagnosis.

Immediately before uploading, the helper verifies that the selected release is
still writable and its tag still points to the same commit. It never switches
to a newer release that appeared during the build. Existing unrelated attachments
remain in place. Matching names cause a failure unless replacement was selected.
Remote uploads are sequential, so a network failure can leave a partial upload;
rerun with replacement after investigating the failure.

Inspect `Rigora-build-log-*` artifacts for the build log, compiler report and any
requested test reports. Actions artifacts expire after seven days. Release
attachments have their normal release lifetime.

## 6. Reruns and common failures

| Failure | Resolution |
| --- | --- |
| Workflow is missing in Actions | Push `.github/workflows/release.yml` to the repository's default branch and enable Actions. |
| No stable release exists | Publish an eligible release, then dispatch again. |
| Immutable release | Use a release process that uploads before publication; this workflow cannot append to it. |
| Release tag moved | Confirm the intended source and start a new workflow run. |
| Build tools are missing at the tag | Create a release tag containing the prepared repository. |
| An OS dependency or wheel is unavailable | Read that platform's build log; do not publish a package with silently removed features. |
| Matching download names exist | Confirm replacement is intended, then rerun with replacement enabled. |
| Upload returns 403 | Check repository/organization Actions policy and the publication job's token permissions. |
| Only one platform finishes | Wait for the whole matrix; publication requires all three. |

## Local checks without compiling

The release helpers can be tested without a native build or GitHub credentials:

```sh
uv run --no-sync pytest tests/test_release_assets.py tests/test_desktop_build.py
node --test tests/release_workflow.test.cjs
```

Python tests use tiny fixture files; JavaScript tests mock GitHub API calls and
check owner guards, missing/immutable releases, moved tags, collision preflight
and preservation of unrelated attachments. Running the real hosted workflow is
still required to validate the first Linux/macOS release build.
