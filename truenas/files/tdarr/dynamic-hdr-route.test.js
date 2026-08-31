const assert = require('node:assert/strict');
const test = require('node:test');

const routeDynamicHdr = require('./dynamic-hdr-route');

function buildArgs({ sideData = [], hdrFormat = '', compatibility = '' }) {
  const logs = [];
  return {
    args: {
      inputFileObj: {
        ffProbeData: {
          streams: [{ codec_type: 'video', side_data_list: sideData }],
        },
        mediaInfo: {
          track: [{
            '@type': 'Video',
            HDR_Format: hdrFormat,
            HDR_Format_Compatibility: compatibility,
          }],
        },
      },
      variables: {},
      jobLog: (message) => logs.push(message),
    },
    logs,
  };
}

test('routes Dolby Vision FFprobe side data to remux', async () => {
  const { args, logs } = buildArgs({
    sideData: [{ side_data_type: 'DOVI configuration record', dv_profile: 7 }],
  });
  const result = await routeDynamicHdr(args);
  assert.equal(result.outputNumber, 1);
  assert.match(logs[0], /Dolby Vision/);
});

test('routes HDR10+ MediaInfo metadata to remux', async () => {
  const { args, logs } = buildArgs({
    hdrFormat: 'SMPTE ST 2094 App 4',
    compatibility: 'HDR10+ Profile A',
  });
  const result = await routeDynamicHdr(args);
  assert.equal(result.outputNumber, 1);
  assert.match(logs[0], /HDR10\+/);
});

test('routes combined Dolby Vision and HDR10+ metadata to remux', async () => {
  const { args, logs } = buildArgs({
    hdrFormat: 'Dolby Vision / SMPTE ST 2094 App 4',
    compatibility: 'Blu-ray / HDR10+ Profile A',
  });
  const result = await routeDynamicHdr(args);
  assert.equal(result.outputNumber, 1);
  assert.match(logs[0], /Dolby Vision, HDR10\+/);
});

test('routes ordinary HDR10 to AV1 encoding', async () => {
  const { args, logs } = buildArgs({
    hdrFormat: 'SMPTE ST 2086',
    compatibility: 'HDR10',
  });
  const result = await routeDynamicHdr(args);
  assert.equal(result.outputNumber, 2);
  assert.match(logs[0], /continuing through the AV1 encode path/);
});
