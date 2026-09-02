const assert = require('assert');

const ensureMatroskaCompatibility = require('./matroska-stream-compatibility');

const makeArgs = (streams) => ({
  inputFileObj: { _id: '/media/test.mp4' },
  variables: { ffmpegCommand: { streams } },
  logs: [],
  jobLog(message) {
    this.logs.push(message);
  },
});

(async () => {
  const args = makeArgs([
    { codec_type: 'video', codec_name: 'hevc', removed: false, outputArgs: [] },
    { codec_type: 'subtitle', codec_name: 'mov_text', removed: false, outputArgs: [] },
    { codec_type: 'subtitle', codec_name: 'subrip', removed: false, outputArgs: [] },
    { codec_type: 'subtitle', codec_name: 'mov_text', removed: true, outputArgs: [] },
    { codec_type: 'data', codec_name: 'bin_data', removed: false, outputArgs: [] },
    { codec_type: 'attachment', codec_name: 'mjpeg', removed: false, outputArgs: [] },
  ]);

  const result = await ensureMatroskaCompatibility(args);

  assert.deepStrictEqual(
    result.variables.ffmpegCommand.streams[1].outputArgs,
    ['-c:{outputIndex}', 'srt'],
  );
  assert.deepStrictEqual(result.variables.ffmpegCommand.streams[2].outputArgs, []);
  assert.deepStrictEqual(result.variables.ffmpegCommand.streams[3].outputArgs, []);
  assert.strictEqual(result.variables.ffmpegCommand.streams[4].removed, true);
  assert.strictEqual(result.variables.ffmpegCommand.streams[5].removed, false);
  assert.match(args.logs[0], /converting 1 mov_text.*removing 1 data/s);

  await assert.rejects(
    ensureMatroskaCompatibility({ variables: {}, jobLog() {} }),
    /has not been initialized/,
  );
})();
