module.exports = async (args) => {
  const command = args.variables?.ffmpegCommand;

  if (!command?.streams) {
    throw new Error('FFmpeg command has not been initialized');
  }

  let convertedSubtitleCount = 0;
  let removedDataCount = 0;

  command.streams.forEach((stream) => {
    if (stream.removed) {
      return;
    }

    if (stream.codec_type === 'subtitle' && stream.codec_name === 'mov_text') {
      stream.outputArgs.push('-c:{outputIndex}', 'srt');
      convertedSubtitleCount += 1;
    }

    if (stream.codec_type === 'data') {
      stream.removed = true;
      removedDataCount += 1;
    }
  });

  args.jobLog(
    `Matroska compatibility: converting ${convertedSubtitleCount} mov_text `
      + `subtitle stream(s) to SubRip; removing ${removedDataCount} data stream(s)`,
  );

  return {
    outputFileObj: args.inputFileObj,
    outputNumber: 1,
    variables: args.variables,
  };
};
