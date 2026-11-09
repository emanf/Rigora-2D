const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {assertOwner, selectRelease, publishAssets} = require('../tools/release_workflow.cjs');

const context = {actor: 'Owner', eventName: 'workflow_dispatch', repo: {owner: 'owner', repo: 'Rigora'}};
const sha = 'a'.repeat(40);
const release = {id: 7, tag_name: 'v0.1.0', draft: false, prerelease: false, immutable: false, html_url: 'https://example.test/release'};
process.env.GITHUB_TRIGGERING_ACTOR = 'Owner';

function fixture() {
  const calls = [];
  const summary = {addHeading() {return this;}, addTable() {return this;}, addLink() {return this;}, addList() {return this;}, async write() {}};
  const core = {summary, setOutput(key, value) {calls.push(['output', key, value]);}, info() {}};
  const repos = {
    async getLatestRelease() {return {data: {...release}};},
    async getRelease() {return {data: {...release}};},
    async getCommit() {return {data: {sha}};},
    async listReleaseAssets() {},
    async deleteReleaseAsset(value) {calls.push(['delete', value.asset_id]);},
    async uploadReleaseAsset(value) {calls.push(['upload', value.name]);},
  };
  return {calls, core, github: {rest: {repos}, async paginate() {return [];}}};
}

test('only the owner can dispatch or rerun publication', () => {
  assert.doesNotThrow(() => assertOwner(context));
  assert.throws(() => assertOwner({...context, actor: 'someone'}));
  assert.throws(() => assertOwner(context, 'someone'));
  assert.throws(() => assertOwner({...context, eventName: 'pull_request'}));
});

test('selection freezes the published tag and peeled source commit', async () => {
  const f = fixture();
  await selectRelease({...f, context});
  assert.deepEqual(f.calls, [['output', 'id', '7'], ['output', 'tag', 'v0.1.0'], ['output', 'sha', sha]]);
  f.github.rest.repos.getLatestRelease = async () => {throw Object.assign(new Error(), {status: 404});};
  await assert.rejects(selectRelease({...f, context}), /No stable release/);
});

test('immutable releases and moved tags stop before remote changes', async () => {
  const f = fixture();
  f.github.rest.repos.getRelease = async () => ({data: {...release, immutable: true}});
  const args = {...f, context, releaseId: 7, tag: release.tag_name, sha, directory: 'unused'};
  await assert.rejects(publishAssets(args), /immutable/);
  f.github.rest.repos.getRelease = async () => ({data: {...release}});
  f.github.rest.repos.getCommit = async () => ({data: {sha: 'b'.repeat(40)}});
  await assert.rejects(publishAssets(args), /tag changed/);
  assert.equal(f.calls.length, 0);
});

test('collisions are preflighted and unrelated release assets survive replacement', async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'rigora-release-'));
  t.after(() => fs.rm(directory, {recursive: true, force: true}));
  const names = ['SHA256SUMS.txt'];
  for (const target of ['windows-x64', 'linux-x64', 'macos-arm64']) {
    for (const extension of ['zip', 'release.json']) names.push(`Rigora-v0.1.0-${target}.${extension}`);
  }
  for (const name of names) await fs.writeFile(path.join(directory, name), 'verified fixture');
  const f = fixture();
  const conflict = names[1];
  f.github.paginate = async () => [{name: conflict, id: 10}, {name: 'unrelated.pdf', id: 99}];
  const args = {...f, context, releaseId: 7, tag: release.tag_name, sha, directory, replace: false};
  await assert.rejects(publishAssets(args), /already exist/);
  assert.equal(f.calls.length, 0);
  await publishAssets({...args, replace: true});
  assert.deepEqual(f.calls.filter(c => c[0] === 'delete'), [['delete', 10]]);
  assert.equal(f.calls.filter(c => c[0] === 'upload').length, 7);
});
