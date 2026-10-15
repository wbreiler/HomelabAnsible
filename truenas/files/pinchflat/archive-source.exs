alias Pinchflat.Profiles.MediaProfile
alias Pinchflat.Repo
alias Pinchflat.Sources
alias Pinchflat.Sources.Source

url = __ARCHIVE_SOURCE_URL__
profile = Repo.get_by!(MediaProfile, name: "YouTube Archive")
source = Repo.get_by(Source, original_url: url, media_profile_id: profile.id)
changed = is_nil(source) or source.max_duration_seconds != 3600

if changed and not __ARCHIVE_CHECK__ do
  result =
    if is_nil(source) do
      Sources.create_source(%{
        original_url: url,
        media_profile_id: profile.id,
        index_frequency_minutes: 1440,
        fast_index: true,
        download_media: true,
        max_duration_seconds: 3600
      })
    else
      Sources.update_source(source, %{max_duration_seconds: 3600})
    end

  {:ok, updated} = result
  true = updated.max_duration_seconds == 3600
end

IO.puts("ARCHIVE_RESULT=" <> Jason.encode!(%{changed: changed, url: url}))
