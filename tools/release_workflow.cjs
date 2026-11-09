const fs = require('node:fs/promises');
const path = require('node:path');

/** Restrict release publication to the personal repository owner, including reruns. */
function assertOwner(context, triggeringActor = process.env.GITHUB_TRIGGERING_ACTOR) {
  const owner = context.repo.owner.toLowerCase();
  if (context.eventName !== 'workflow_dispatch' || context.actor.toLowerCase() !== owner ||
      String(triggeringActor).toLowerCase() !== owner) {
    throw new Error('Only the repository owner may start or rerun release builds.');
  }
}

/** Require an existing stable release that still accepts downloadable files. */
function assertWritable(release) {
  if (release.draft || release.prerelease) throw new Error('Publish a stable release first.');
  if (release.immutable) throw new Error('The selected release is immutable and cannot accept assets.');
}

/** Resolve the latest release once and freeze its tagged source commit for every platform. */
async function selectRelease({github, context, core}) {
  assertOwner(context);
  let release;
  try {
    ({data: release} = await github.rest.repos.getLatestRelease(context.repo));
  } catch (error) {
    if (error.status === 404) throw new Error('No stable release exists. Publish one in Releases, then run this workflow.');
    throw error;
  }
  assertWritable(release);
  const {data: commit} = await github.rest.repos.getCommit({...context.repo, ref: `refs/tags/${release.tag_name}`});
  if (!/^[0-9a-f]{40}$/.test(commit.sha)) throw new Error('The release tag did not resolve to a commit.');
  core.setOutput('id', String(release.id));
  core.setOutput('tag', release.tag_name);
  core.setOutput('sha', commit.sha);
  await core.summary.addHeading('Rigora release build').addTable([
    [{data: 'Release', header: true}, {data: 'Source commit', header: true}],
    [release.tag_name, commit.sha],
  ]).write();
}

/** Attach the locally verified package set, rejecting a moved tag before any remote edit. */
async function publishAssets({github, context, core, releaseId, tag, sha, replace, directory}) {
  assertOwner(context);
  const {data: release} = await github.rest.repos.getRelease({...context.repo, release_id: releaseId});
  assertWritable(release);
  const {data: commit} = await github.rest.repos.getCommit({...context.repo, ref: `refs/tags/${tag}`});
  if (release.tag_name !== tag || commit.sha !== sha) {
    throw new Error('The release tag changed while building. Start a new workflow run.');
  }
  const entries = await fs.readdir(directory, {withFileTypes: true});
  const names = entries.map(entry => entry.name).sort();
  if (entries.some(entry => !entry.isFile()) || names.length !== 7 ||
      names.filter(name => name.endsWith('.zip')).length !== 3 ||
      names.filter(name => name.endsWith('.release.json')).length !== 3 ||
      !names.includes('SHA256SUMS.txt') ||
      names.some(name => name !== 'SHA256SUMS.txt' && !/^Rigora-[A-Za-z0-9._-]+\.(zip|release\.json)$/.test(name))) {
    throw new Error('Expected three verified ZIPs, their manifests and SHA256SUMS.txt.');
  }
  const assets = await github.paginate(github.rest.repos.listReleaseAssets,
    {...context.repo, release_id: releaseId, per_page: 100});
  const existing = new Map(assets.map(asset => [asset.name, asset]));
  const collisions = names.filter(name => existing.has(name));
  if (collisions.length && !replace) {
    throw new Error(`Matching assets already exist: ${collisions.join(', ')}. Enable replacement to update them.`);
  }
  for (const name of names) {
    if (existing.has(name)) {
      await github.rest.repos.deleteReleaseAsset({...context.repo, asset_id: existing.get(name).id});
    }
    const data = await fs.readFile(path.join(directory, name));
    await github.rest.repos.uploadReleaseAsset({...context.repo, release_id: releaseId, name, data,
      headers: {'content-type': 'application/octet-stream', 'content-length': String(data.length)}});
    core.info(`Uploaded ${name}`);
  }
  await core.summary.addHeading('Downloads attached').addLink('Open release', release.html_url)
    .addList(names).write();
}

module.exports = {assertOwner, selectRelease, publishAssets};
