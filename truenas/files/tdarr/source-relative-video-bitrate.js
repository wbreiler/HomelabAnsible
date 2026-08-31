module.exports = async (args) => {
  const fs = require('fs');

  const format = args.inputFileObj?.ffProbeData?.format || {};
  const mediaInfoTracks = args.inputFileObj?.mediaInfo?.track || [];
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

  const retainedAudioStreams = args.variables.ffmpegCommand.streams
    .filter((stream) => stream.codec_type === 'audio' && !stream.removed);
  let missingAudioBitrateCount = 0;
  const audioBitsPerSecond = retainedAudioStreams.reduce((total, stream) => {
    let streamBitsPerSecond = Number(stream.bit_rate);

    // Lossless formats such as DTS-HD MA commonly omit FFprobe's stream
    // bit_rate. MediaInfo still reports the measured per-track bitrate.
    if (!(streamBitsPerSecond > 0)) {
      const mediaInfoTrack = mediaInfoTracks.find(
        (track) => track['@type'] === 'Audio'
          && Number(track.StreamOrder) === Number(stream.index),
      );
      streamBitsPerSecond = Number(mediaInfoTrack?.BitRate);
    }

    if (!(streamBitsPerSecond > 0)) {
      missingAudioBitrateCount += 1;
      return total;
    }

    return total + streamBitsPerSecond;
  }, 0);

  // When neither scanner exposes a retained audio bitrate, reserve 25% of the
  // source container bitrate for copied audio instead of treating it as zero.
  const estimatedAudioBitsPerSecond = missingAudioBitrateCount > 0
    ? Math.max(audioBitsPerSecond, overallBitsPerSecond * 0.25)
    : audioBitsPerSecond;
  const sourceVideoBitsPerSecond = Math.max(
    overallBitsPerSecond - estimatedAudioBitsPerSecond,
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
      + `audio bitrate ${Math.round(estimatedAudioBitsPerSecond / 1000)}k`
      + `${missingAudioBitrateCount > 0 ? ' (includes fallback estimate)' : ''}; `
      + `target video bitrate ${targetKbps}k`,
  );

  return {
    outputFileObj: args.inputFileObj,
    outputNumber: 1,
    variables: args.variables,
  };
};
