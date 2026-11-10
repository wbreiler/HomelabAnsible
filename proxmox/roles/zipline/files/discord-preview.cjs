// One public Shared clip, one encoder, and a short-lived buffer in RAM.
const http = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
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
let current;

async function canRead() {
  const response = await fetch(source, { redirect: 'error', headers: { Range: 'bytes=0-0' },
    signal: AbortSignal.timeout(5000) });
  await response.body?.cancel();
  return response.status === 206 && response.headers.get('content-type') === 'video/mp4';
}

function encode() {
  const job = { media: Buffer.alloc(8 * 1024 * 1024), size: 0 };
  const child = spawn('ffmpeg', ['-nostdin', '-v', 'error', '-protocol_whitelist', 'http,tcp',
    '-skip_loop_filter', 'all', '-skip_frame', 'noref', '-threads', '4', '-f', 'mov', '-i', source,
    '-map', '0:v:0', '-map', '0:a:0?', '-map_metadata', '-1', '-vf', 'fps=24,scale=640:-2:flags=fast_bilinear',
    '-threads', '2', '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '1000k', '-maxrate', '1300k',
    '-bufsize', '1800k', '-g', '24', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '80k',
    '-movflags', '+empty_moov+default_base_moof+frag_keyframe', '-flush_packets', '1', '-f', 'mp4', 'pipe:1'],
    { stdio: ['ignore', 'pipe', 'ignore'], timeout: 90000, killSignal: 'SIGKILL' });
  function advance() {
    const previous = job.wake;
    job.next = new Promise(resolve => { job.wake = resolve; });
    previous?.();
  }
  advance();
  child.stdout.on('data', chunk => {
    if (job.size + chunk.length > job.media.length) { child.kill('SIGKILL'); return; }
    chunk.copy(job.media, job.size);
    job.size += chunk.length;
    advance();
  });
  child.on('error', () => { job.failed = true; });
  child.on('close', code => {
    job.finished = true;
    job.failed ||= code !== 0 || !job.size;
    advance();
    if (job.failed) current = undefined;
    else setTimeout(() => {
      if (current === job) current = undefined;
      console.log('Released preview buffer');
    }, 60000).unref();
  });
  return job;
}

const server = http.createServer(async (req, res) => {
  res.setHeader('Cache-Control', 'private, no-store');
  try {
    if (!['GET', 'HEAD'].includes(req.method) || req.url !== '/discord-media/' + clip || !await canRead()) {
      res.writeHead(404).end();
      return;
    }
    const job = current ||= encode();
    const range = req.headers.range;
    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Accept-Ranges', 'bytes');
    // A cold, ordinary GET can play the first fragment while FFmpeg encodes the rest.
    if (!job.finished && req.method === 'GET' && !range) {
      let offset = 0;
      while (!res.destroyed) {
        if (job.failed) throw Error('encoding failed');
        while (offset < job.size) {
          const bytes = job.media.subarray(offset, job.size);
          offset += bytes.length;
          if (!res.write(bytes)) await once(res, 'drain', { signal: AbortSignal.timeout(10000) });
        }
        if (job.finished) break;
        await job.next;
      }
      res.end();
      return;
    }
    while (!job.finished) await job.next;
    if (job.failed) throw Error('encoding failed');
    if (!await canRead()) { res.writeHead(404).end(); return; }
    const bounds = byteRange(range, job.size);
    if (!bounds) { res.writeHead(416, { 'Content-Range': 'bytes */' + job.size }).end(); return; }
    const [start, end] = bounds;
    if (range) res.setHeader('Content-Range', `bytes ${start}-${end}/${job.size}`);
    res.setHeader('Content-Length', end - start + 1);
    res.writeHead(range ? 206 : 200);
    res.end(req.method === 'HEAD' ? undefined : job.media.subarray(start, end + 1));
  } catch {
    if (res.headersSent) res.destroy();
    else res.writeHead(503).end();
  }
});
server.maxConnections = 24;
server.listen(3001);
