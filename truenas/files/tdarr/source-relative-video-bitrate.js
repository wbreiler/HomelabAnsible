module.exports = async (args) => {
  const fs = require('fs');

  const format = args.inputFileObj?.ffProbeData?.format || {};
  const streams = args.inputFileObj?.ffProbeData?.streams || [];
  const durationSeconds = Number(format.duration);
  let overallBitsPerSecond = Number(format.bit_rate);

  // FFprobe's container bitrate is normally calculated from the actual file,
  // unlike Matroska BPS tags, which can be stale after a previous remux.
  if (!(overallBitsPerSecond > 0) && durationSeconds > 0) {
    try {
      const bytes = fs.statSync(args.inputFileObj._id).size;
      overallBitsPerSecond = (bytes * 8) / durationSeconds;
    } catch (error) {
      const fileSizeMb = Number(args.inputFileObj.file_size);
      overallBitsPerSecond = (fileSizeMb * 1000000 * 8) / durationSeconds;
    }
  }

  if (!(overallBitsPerSecond > 0)) {
    throw new Error('Unable to calculate bitrate from actual file size and duration');
  }

  const audioBitsPerSecond = streams
    .filter((stream) => stream.codec_type === 'audio')
    .reduce((total, stream) => total + (Number(stream.bit_rate) || 0), 0);
  const sourceVideoBitsPerSecond = Math.max(
    overallBitsPerSecond - audioBitsPerSecond,
    overallBitsPerSecond * 0.5,
  );
  const targetKbps = Math.max(250, Math.round(sourceVideoBitsPerSecond * 0.75 / 1000));

  args.variables.ffmpegCommand.streams.forEach((stream) => {
    if (stream.codec_type === 'video') {
      stream.outputArgs.push('-b:v:{outputTypeIndex}', `${targetKbps}k`);
    }
  });

  args.jobLog(
    `Actual overall bitrate ${Math.round(overallBitsPerSecond / 1000)}k; `
      + `audio bitrate ${Math.round(audioBitsPerSecond / 1000)}k; `
      + `target video bitrate ${targetKbps}k`,
  );

  return {
    outputFileObj: args.inputFileObj,
    outputNumber: 1,
    variables: args.variables,
  };
};
