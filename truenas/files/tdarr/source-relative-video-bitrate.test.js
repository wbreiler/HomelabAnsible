const assert = require('node:assert/strict');
const test = require('node:test');

const setSourceRelativeVideoBitrate = require('./source-relative-video-bitrate');

function buildArgs({ audioStream, mediaInfoTracks = [] }) {
  const videoStream = {
    index: 0,
    codec_type: 'video',
    outputArgs: [],
    removed: false,
  };

  return {
    inputFileObj: {
      ffProbeData: {
        format: {
          duration: '2704.203',
          bit_rate: '12116350',
        },
        streams: [videoStream, audioStream],
      },
      mediaInfo: { track: mediaInfoTracks },
    },
    variables: {
      ffmpegCommand: {
        streams: [videoStream, audioStream],
      },
    },
    jobLog: () => {},
  };
}

test('uses MediaInfo bitrate when DTS-HD MA omits FFprobe stream bitrate', async () => {
  const args = buildArgs({
    audioStream: {
      index: 1,
      codec_type: 'audio',
      outputArgs: [],
      removed: false,
    },
    mediaInfoTracks: [{
      '@type': 'Audio',
      StreamOrder: '1',
      BitRate: '3522055',
    }],
  });

  await setSourceRelativeVideoBitrate(args);

  assert.deepEqual(args.variables.ffmpegCommand.streams[0].outputArgs, [
    '-b:v:{outputTypeIndex}',
    '6446k',
  ]);
});

test('uses a conservative allowance when retained audio bitrate is unavailable', async () => {
  const args = buildArgs({
    audioStream: {
      index: 1,
      codec_type: 'audio',
      outputArgs: [],
      removed: false,
    },
  });

  await setSourceRelativeVideoBitrate(args);

  assert.deepEqual(args.variables.ffmpegCommand.streams[0].outputArgs, [
    '-b:v:{outputTypeIndex}',
    '6815k',
  ]);
});

test('does not budget audio streams removed by an earlier flow stage', async () => {
  const args = buildArgs({
    audioStream: {
      index: 1,
      codec_type: 'audio',
      bit_rate: '3522055',
      outputArgs: [],
      removed: true,
    },
  });

  await setSourceRelativeVideoBitrate(args);

  assert.deepEqual(args.variables.ffmpegCommand.streams[0].outputArgs, [
    '-b:v:{outputTypeIndex}',
    '9087k',
  ]);
});
