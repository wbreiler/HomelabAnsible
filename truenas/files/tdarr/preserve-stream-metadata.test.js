const assert = require('node:assert/strict');
const test = require('node:test');
const preserve = require('./preserve-stream-metadata');

test('preserves explicit zero and combined flags without modifying removed streams', async () => {
  const streams = [
    { codec_type: 'audio', disposition: { default: 0 }, outputArgs: [] },
    { codec_type: 'subtitle', disposition: { default: 1, forced: 1 }, outputArgs: [] },
    { codec_type: 'audio', removed: true, disposition: { default: 1 }, outputArgs: [] },
    { codec_type: 'video', outputArgs: [] },
  ];
  const args = { variables: { ffmpegCommand: { streams, container: 'mkv' } }, jobLog() {} };
  await preserve(args);
  assert.deepEqual(streams.map((s) => s.outputArgs), [
    ['-disposition:{outputIndex}', '0'],
    ['-disposition:{outputIndex}', 'default+forced'],
    [], [],
  ]);
});

test('permits the MP4 Dolby Vision configuration box only for Dolby Vision MP4', async () => {
  for (const container of ['mp4', 'mkv']) {
    const command = {
      container, overallOuputArguments: [],
      streams: [{ codec_type: 'video', side_data_list: [{ dv_profile: 8 }] }],
    };
    await preserve({ variables: { ffmpegCommand: command }, jobLog() {} });
    assert.deepEqual(command.overallOuputArguments, container === 'mp4' ? ['-strict', 'unofficial'] : []);
  }
});

test('rejects an uninitialized command', async () => {
  await assert.rejects(preserve({ variables: {} }), /has not been initialized/);
});
