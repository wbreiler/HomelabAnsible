alias Pinchflat.Profiles.MediaProfile
alias Pinchflat.Repo
alias Pinchflat.Sources
alias Pinchflat.Sources.Source

url = __ARCHIVE_SOURCE_URL__
profile = Repo.get_by!(MediaProfile, name: "YouTube Archive")
source = Repo.get_by(Source, original_url: url, media_profile_id: profile.id)

if is_nil(source) and not __ARCHIVE_CHECK__ do
  {:ok, _} = Sources.create_source(%{
    original_url: url,
    media_profile_id: profile.id,
    index_frequency_minutes: 1440,
    fast_index: true,
    download_media: true
  })
end

IO.puts("ARCHIVE_RESULT=" <> Jason.encode!(%{changed: is_nil(source), url: url}))
