alias Pinchflat.Profiles
alias Pinchflat.Profiles.MediaProfile
alias Pinchflat.Repo

desired = %{
  name: "YouTube Archive",
  output_path_template: "/{{ source_custom_name }}/{{ upload_yyyy_mm_dd }} {{ title }} [{{ id }}].{{ ext }}",
  preferred_resolution: :"4320p",
  media_container: "mkv",
  download_metadata: true,
  embed_metadata: true,
  download_thumbnail: true,
  download_subs: false,
  download_auto_subs: false,
  embed_subs: false,
  sub_langs: "en"
}

current = Repo.get_by(MediaProfile, name: desired.name)
changed = is_nil(current) or Enum.any?(desired, fn {key, value} -> Map.get(current, key) != value end)

if changed and not __ARCHIVE_CHECK__ do
  result = if current, do: Profiles.update_media_profile(current, desired), else: Profiles.create_media_profile(desired)
  {:ok, profile} = result
  true = profile.media_container == "mkv"
end

IO.puts("ARCHIVE_RESULT=" <> Jason.encode!(%{changed: changed}))
