// Prepare the Shared publisher’s catalog in RAM before a Discord crawler requests it.
const http = require('node:http');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const fs = require('node:fs/promises');
const run = promisify(execFile);
const assert = require('node:assert/strict');
const path = require('node:path');
const { pipeline } = require('node:stream/promises');

function byteRange(header, size) {
  if (!header) return [0, size - 1];
  const match = /^bytes=(\d*)-(\d*)$/.exec(header);
  if (!match || (!match[1] && !match[2])) return null;
  const start = match[1] ? Number(match[1]) : Math.max(0, size - Number(match[2]));
  const end = match[1] && match[2] ? Math.min(size - 1, Number(match[2])) : size - 1;
  return start <= end ? [start, end] : null;
}


const shared = '/srv/zipline-media/Shared';
const ram = '/dev/shm';
const poolBytes = 6 * 1024 * 1024 * 1024;
const maxClipBytes = 32 * 1024 * 1024;
const sourceName = /^(shared-[0-9a-f]{32})\.(mp4|m4v|mov|mkv|webm)$/;
const mediaPath = /^\/discord-media\/(?:v2\/|1080p\/)?(shared-[0-9a-f]{32})\.mp4$/;
const ready = new Map();
const retryAfter = new Map();
let catalog = new Map();
let active;
let scanning = false;

async function readCatalog() {
  const names = JSON.parse(await fs.readFile('/catalog/clips.json', 'utf8'));
  const entries = new Map();
  for (const [name, relative] of Object.entries(names)) {
    const match = sourceName.exec(name);
    if (!match || typeof relative !== 'string' || relative.split('/').some(p => !p || p.startsWith('.')) ||
        path.extname(relative).toLowerCase() !== '.' + match[2]) throw Error('invalid publisher catalog');
    entries.set(match[1], { name, source: path.join(shared, relative),
      format: ['mkv', 'webm'].includes(match[2]) ? 'matroska' : 'mov' });
  }
  return entries;
}

async function duration(input, signal) {
  const probe = await run('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', ...input],
    { timeout: 30000, signal });
  const seconds = Number(probe.stdout.trim());
  if (Number.isFinite(seconds) && seconds > 0) return seconds;
  // Some complete WebM recordings omit duration. Read packet timestamps without decoding.
  const scan = await run('ffmpeg', ['-v', 'error', ...input, '-map', '0:V:0', '-c', 'copy',
    '-progress', 'pipe:1', '-f', 'null', '-'], { timeout: 300000, signal });
  const last = [...scan.stdout.matchAll(/^out_time_us=(\d+)$/gm)].at(-1);
  if (!last || Number(last[1]) <= 0) throw Error('no video duration');
  return Number(last[1]) / 1e6;
}

function rates(seconds, budget) {
  const total = Math.floor(budget * 0.90 * 8 / seconds / 1000);
  const audio = Math.min(160, Math.max(16, Math.floor(total / 10)));
  if (total - audio < 16) throw Error('clip exceeds available RAM at a playable bitrate');
  return { video: Math.min(14000, total - audio), audio };
}

async function prepare(id, entry, budget, signal) {
  const input = ['-protocol_whitelist', 'file', '-f', entry.format, '-i', entry.source];
  const original = await fs.stat(entry.source, { bigint: true });
  const seconds = await duration(input, signal);
  const {video, audio} = rates(seconds, budget);
  const draft = path.join(ram, 'encoding.part.mp4');
  try {
    await run('ffmpeg', ['-nostdin', '-y', '-v', 'error', '-threads', '2', ...input, '-map', '0:V:0',
      '-map', '0:a:0?', '-map_metadata', '-1', '-filter_threads', '2', '-vf',
      'fps=60,scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
      '-threads', '2', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-maxrate', video + 'k',
      '-bufsize', video + 'k', '-g', '120', '-pix_fmt', 'yuv420p', '-ac', '2', '-c:a', 'aac', '-b:a', audio + 'k',
      '-fs', String(budget + 256 * 1024), '-movflags', '+faststart', draft],
      { timeout: Math.min(2147483647, Math.max(240000, seconds * 12000)), killSignal: 'SIGKILL', signal });
    const {size} = await fs.stat(draft);
    if (!size || size > budget) throw Error('encoded preview exceeds RAM allocation');
    const now = await fs.stat(entry.source, { bigint: true });
    if (catalog.get(id)?.name !== entry.name || original.ino !== now.ino ||
        original.size !== now.size || original.mtimeNs !== now.mtimeNs) return;
    await fs.rename(draft, path.join(ram, id + '.mp4'));
    ready.set(id, size);
    console.log('Prepared', id, size, 'bytes');
  } finally {
    await fs.rm(draft, {force: true});
  }
}

async function nextPreview() {
  if (active || !catalog.size) return;
  let selected;
  try {
    const budget = maxClipBytes;
    const candidates = [...catalog.keys()].filter(id => !(retryAfter.get(id) > Date.now()));
    selected = candidates.find(id => !ready.has(id));
    if (!selected) return;
    const used = [...ready.values()].reduce((a, b) => a + b, 0);
    if (used + budget > poolBytes) {
      retryAfter.set(selected, Date.now() + 60000);
      console.error('Preview cache full; waiting for space:', selected);
      return;
    }
    active = {id: selected, controller: new AbortController()};
    await prepare(selected, catalog.get(selected), budget, active.controller.signal);
    retryAfter.delete(selected);
  } catch (error) {
    retryAfter.set(selected, Date.now() + 60000);
    console.error('Preview failed; retrying in one minute:', selected, error.code ?? error.message.split('\n')[0]);
  } finally {
    active = undefined;
  }
}

async function sync() {
  if (scanning) return;
  scanning = true;
  try {
    catalog = await readCatalog();
    if (active && !catalog.has(active.id)) active.controller.abort();
    for (const id of ready.keys()) {
      if (!catalog.has(id)) {
        ready.delete(id);
        await fs.rm(path.join(ram, id + '.mp4'), {force: true});
      }
    }
    for (const id of retryAfter.keys()) if (!catalog.has(id)) retryAfter.delete(id);
    void nextPreview();
  } catch (error) {
    catalog = new Map();
    console.error('Preview catalog unavailable:', error.code ?? error.message);
  } finally {
    scanning = false;
  }
}

const server = http.createServer(async (req, res) => {
  res.setHeader('Cache-Control', 'private, no-store');
  let file;
  try {
    const id = mediaPath.exec(req.url.split('?')[0])?.[1];
    const entry = catalog.get(id);
    if (!['GET', 'HEAD'].includes(req.method) || !entry) { res.writeHead(404).end(); return; }
    const access = await fetch('http://zipline:3000/raw/' + entry.name, { method: 'HEAD', redirect: 'manual',
      signal: AbortSignal.timeout(5000) });
    if (access.status !== 200 || !access.headers.get('content-type')?.startsWith('video/') || !catalog.has(id)) {
      res.writeHead(404).end(); return;
    }
    if (!ready.has(id)) { res.writeHead(503, {'Retry-After': '5'}).end(); return; }
    file = await fs.open(path.join(ram, id + '.mp4'), 'r');
    const {size} = await file.stat();
    const range = req.headers.range;
    const bounds = byteRange(range, size);
    if (!bounds) { res.writeHead(416, { 'Content-Range': 'bytes */' + size }).end(); return; }
    const [start, end] = bounds;
    if (range) res.setHeader('Content-Range', `bytes ${start}-${end}/${size}`);
    res.setHeader('Accept-Ranges', 'bytes');
    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Content-Length', end - start + 1);
    res.writeHead(range ? 206 : 200);
    if (req.method === 'HEAD') res.end();
    else await pipeline(file.createReadStream({start, end, autoClose: false}), res);
  } catch {
    if (!res.headersSent) res.writeHead(503).end();
    else res.destroy();
  } finally {
    await file?.close();
  }
});

async function start() {
  const mounts = await fs.readFile('/proc/self/mountinfo', 'utf8');
  const protectedSource = mounts.split('\n').some(line => {
    const fields = line.split(' ');
    return fields[4] === shared && ['ro', 'nosymfollow'].every(o => fields[5].split(',').includes(o)) &&
      / - nfs4? /.test(line);
  });
  assert(protectedSource && (await fs.statfs(ram)).type === 0x01021994, 'protected source and tmpfs required');
  // A process restart can leave output from its previous generation in this private tmpfs.
  for (const name of await fs.readdir(ram)) {
    if (/^shared-[0-9a-f]{32}\.mp4$/.test(name) || name === 'encoding.part.mp4') await fs.unlink(path.join(ram, name));
  }
  server.maxConnections = 24;
  server.listen(3001);
  await sync();
  setInterval(sync, 5000).unref();
}
if (process.argv.includes('--self-test')) {
  assert.deepEqual(byteRange('bytes=-2', 10), [8, 9]);
  assert.deepEqual(byteRange('bytes=4-20', 10), [4, 9]);
  assert.deepEqual(byteRange('bytes=3-', 10), [3, 9]);
  for (const value of ['bytes=10-', 'bytes=4-2', 'bytes=-0', 'bytes=-', 'bytes=0-1,3-4'])
    assert.equal(byteRange(value, 10), null);
  assert.deepEqual(rates(19.1667, maxClipBytes), {video: 12444, audio: 160});
  assert(rates(120, maxClipBytes).video < rates(20, maxClipBytes).video);
  assert.equal(mediaPath.exec('/discord-media/1080p/shared-' + 'a'.repeat(32) + '.mp4')[1], 'shared-' + 'a'.repeat(32));
  assert.equal(mediaPath.exec('/discord-media/1080p/../../secret.mp4'), null);
  (async () => {
    const budgets = [];
    prepare = async (id, entry, budget) => { budgets.push(budget); ready.set(id, 1); };
    for (const count of [1, 250]) {
      catalog = new Map(Array.from({length: count}, (_, i) => [String(i), {}]));
      ready.clear();
      await nextPreview();
    }
    assert.deepEqual(budgets, [maxClipBytes, maxClipBytes]);
    ready.clear();
    ready.set('full', poolBytes);
    await nextPreview();
    assert.equal(budgets.length, 2);
    assert(retryAfter.size > 0);
    ready.clear();
    retryAfter.clear();
    await nextPreview();
    assert.equal(budgets.length, 3);
  })().catch(error => { console.error(error); process.exitCode = 1; });
  return;
}

start().catch(error => { console.error(error.message); process.exitCode = 1; });
