module.exports = async (args) => {
  const streams = args.inputFileObj?.ffProbeData?.streams || [];
  const mediaInfoTracks = args.inputFileObj?.mediaInfo?.track || [];

  const hasDolbyVisionSideData = streams
    .filter((stream) => stream.codec_type === 'video')
    .some((stream) => (stream.side_data_list || []).some((sideData) => {
      const type = String(sideData.side_data_type || '').toLowerCase();
      return type.includes('dovi')
        || type.includes('dolby vision')
        || Number(sideData.dv_profile) > 0;
    }));

  const videoHdrFormats = mediaInfoTracks
    .filter((track) => track['@type'] === 'Video')
    .map((track) => [
      track.HDR_Format,
      track.HDR_Format_Profile,
      track.HDR_Format_Compatibility,
    ].filter(Boolean).join(' '))
    .join(' ')
    .toLowerCase();

  const hasDolbyVision = hasDolbyVisionSideData
    || videoHdrFormats.includes('dolby vision')
    || videoHdrFormats.includes('dvhe.');
  const hasHdr10Plus = videoHdrFormats.includes('hdr10+')
    || videoHdrFormats.includes('smpte st 2094 app 4')
    || videoHdrFormats.includes('smpte2094-40');
  const dynamicFormats = [
    hasDolbyVision ? 'Dolby Vision' : '',
    hasHdr10Plus ? 'HDR10+' : '',
  ].filter(Boolean);

  if (dynamicFormats.length > 0) {
    args.jobLog(
      `Dynamic HDR detected (${dynamicFormats.join(', ')}); `
        + 'copying video and remuxing retained audio/subtitles only',
    );
    return {
      outputFileObj: args.inputFileObj,
      outputNumber: 1,
      variables: args.variables,
    };
  }

  args.jobLog('No dynamic HDR detected; continuing through the AV1 encode path');
  return {
    outputFileObj: args.inputFileObj,
    outputNumber: 2,
    variables: args.variables,
  };
};
