module.exports = async (args) => {
  const command = args.variables?.ffmpegCommand;
  if (!command?.streams) {
    throw new Error('FFmpeg command has not been initialized');
  }

  command.streams.filter((stream) => !stream.removed).forEach((stream) => {
    if (['audio', 'subtitle'].includes(stream.codec_type)) {
      // Explicit zero prevents FFmpeg from inventing a default track.
      const flags = Object.entries(stream.disposition || {})
        .filter(([, value]) => Number(value) === 1)
        .map(([flag]) => flag).join('+');
      stream.outputArgs.push('-disposition:{outputIndex}', flags || '0');
    }
  });

  const hasDolbyVision = command.streams.some((stream) => !stream.removed
    && stream.codec_type === 'video'
    && (stream.side_data_list || []).some((side) => Number(side.dv_profile) > 0));
  if (command.container === 'mp4' && hasDolbyVision) {
    // FFmpeg otherwise omits the Dolby Vision configuration box in MP4.
    command.overallOuputArguments.push('-strict', 'unofficial');
  }

  args.jobLog('Preserved retained track dispositions and Dolby Vision MP4 signaling');
  return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
};
