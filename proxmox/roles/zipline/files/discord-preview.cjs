// Prepare one public Shared clip in RAM before a Discord crawler requests it.
const http = require('node:http');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const fs = require('node:fs/promises');
const run = promisify(execFile);
const assert = require('node:assert/strict');

function byteRange(header, size) {
  if (!header) return [0, size - 1];
  const match = /^bytes=(\d*)-(\d*)$/.exec(header);
  if (!match || (!match[1] && !match[2])) return null;
  const start = match[1] ? Number(match[1]) : Math.max(0, size - Number(match[2]));
  const end = match[1] && match[2] ? Math.min(size - 1, Number(match[2])) : size - 1;
  return start <= end ? [start, end] : null;
}

if (process.argv.includes('--self-test')) {
  assert.deepEqual(byteRange('bytes=-2', 10), [8, 9]);
  assert.deepEqual(byteRange('bytes=4-20', 10), [4, 9]);
  assert.deepEqual(byteRange('bytes=3-', 10), [3, 9]);
  for (const value of ['bytes=10-', 'bytes=4-2', 'bytes=-0', 'bytes=-', 'bytes=0-1,3-4'])
    assert.equal(byteRange(value, 10), null);
  return;
}

const clip = process.env.PREVIEW_CLIP;
assert.match(clip, /^shared-[0-9a-f]{32}\.mp4$/);
const source = 'http://zipline:3000/raw/' + clip;
const viewer = 'http://zipline:3000/view/' + clip;
let media;
let refreshing = false;
let revision = 0;

function withdraw() {
  revision++;
  if (media) console.log('Released unpublished preview');
  media = undefined;
}

async function published() {
  // The viewer exposes the public video tag without consuming a Zipline view.
  const page = await fetch(viewer, { redirect: 'manual', signal: AbortSignal.timeout(5000) });
  if (!page.ok) { await page.body?.cancel(); return false; }
  return (await page.text()).includes('property="og:video:url" content="https://zipline:3000/raw/' + clip + '"');
}

async function encode() {
  const dir = await fs.mkdtemp('/dev/shm/discord-preview-');
  const file = dir + '/clip.mp4';
  try {
    await run('ffmpeg', ['-nostdin', '-v', 'error', '-protocol_whitelist', 'http,tcp',
      '-skip_loop_filter', 'all', '-skip_frame', 'noref', '-threads', '4', '-f', 'mov', '-i', source,
      '-map', '0:v:0', '-map', '0:a:0?', '-map_metadata', '-1', '-vf', 'fps=24,scale=640:-2:flags=fast_bilinear',
      '-threads', '2', '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '1000k', '-maxrate', '1300k',
      '-bufsize', '1800k', '-g', '24', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '80k',
      '-fs', '9M', '-movflags', '+faststart', file], { timeout: 90000, killSignal: 'SIGKILL' });
    const { size } = await fs.stat(file);
    if (!size || size > 8 * 1024 * 1024) throw Error('preview size limit');
    return await fs.readFile(file);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    if (!await published()) { withdraw(); return; }
    if (media) return;
    const started = revision;
    const bytes = await encode();
    if (await published() && started === revision) {
      media = bytes;
      console.log('Prepared fast-start MP4 in RAM');
    }
  } catch {
    withdraw();
    console.error('Preview unavailable; retrying on the next publication check');
  } finally {
    refreshing = false;
  }
}

const paths = ['/discord-media/' + clip, '/discord-media/v2/' + clip];
const server = http.createServer(async (req, res) => {
  res.setHeader('Cache-Control', 'private, no-store');
  try {
    if (!['GET', 'HEAD'].includes(req.method) || !paths.includes(req.url)) {
      res.writeHead(404).end();
      return;
    }
    const access = await fetch(source, { method: 'HEAD', redirect: 'manual', signal: AbortSignal.timeout(5000) });
    if (access.status !== 200 || access.headers.get('content-type') !== 'video/mp4') {
      withdraw();
      res.writeHead(404).end();
      return;
    }
    if (!media) {
      void refresh();
      res.writeHead(503, { 'Retry-After': '5' }).end();
      return;
    }
    const range = req.headers.range;
    const bounds = byteRange(range, media.length);
    if (!bounds) { res.writeHead(416, { 'Content-Range': 'bytes */' + media.length }).end(); return; }
    const [start, end] = bounds;
    if (range) res.setHeader('Content-Range', `bytes ${start}-${end}/${media.length}`);
    res.setHeader('Accept-Ranges', 'bytes');
    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Content-Length', end - start + 1);
    res.writeHead(range ? 206 : 200);
    res.end(req.method === 'HEAD' ? undefined : media.subarray(start, end + 1));
  } catch {
    res.writeHead(503).end();
  }
});
server.maxConnections = 24;
server.listen(3001);
void refresh();
setInterval(refresh, 30000).unref();
