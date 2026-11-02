# NexDeck homepage

The `Start` board is an editable homepage with **Live** and **Bookmarks** pages.
Live opens first. Bookmarks contains 43 links in eight categories,
including the local services, related public services, and everyday bookmarks.
The existing `Home` monitoring board remains available through **Live
dashboard** and the board selector.

The current homepage is `https://nexdeck.wbreiler.com/b/start`. It is also the
administrator's default board after sign-in. Set this URL as the browser's
homepage or startup page. Browser preferences are not managed by this change.

## Live activity

The Live page uses NexDeck widgets and existing integrations:

- A clock, search targets, and an icon grid for everyday favorites.
- Plex streams with backdrop artwork and a moving strip of recent additions.
- **In motion** tabs for SABnzbd, Sonarr, and Radarr queues.
- A combined homelab map, TrueNAS pool capacity, backup activity, and Tdarr workers.

**Your homelab, alive** shows Proxmox hosts and guests alongside TrueNAS apps
and pools, plus PBS datastores. TrueNAS apps appear below the TrueNAS host
with their live state. Running apps are green, deployment is amber, crashed
apps are red, and stopped or unknown apps are gray. **Show stopped guests and
apps** controls whether stopped apps appear. PBS remains a datastore view.

Click a host to open its management dashboard. Atlas and Prometheus open
their respective Proxmox summaries. Click an app to open its web UI in a new
tab. Guests without a web dashboard have explicit links to their Proxmox
guest summaries. Keyboard users can focus a node with Tab and open it with
Enter. Both LANCache nodes open the LANCache dashboard. Unconfigured nodes
and storage nodes remain status displays.

Hover over a node for its full name and details. Status
colors come from the existing adapters, including system alerts. A red TrueNAS
node can indicate an open alert while the system remains reachable. An
unreachable system shows **Unavailable** without hiding the other systems.
If only the app query fails, an **Apps · Unavailable** node appears while
the host and pool remain visible. App discovery uses the current TrueNAS
WebSocket API and publishes only app names and states, never app configuration.

The small `homelab.map` adapter lives in `roles/nexdeck/files/homelab.py`.
The NexDeck role installs it after the pinned release and checks that it loads.
It reuses the native topology renderer and connection permissions. A small
`topology-links.patch` adds accessible links to the renderer. The role tests
and builds the frontend separately before replacing the served build. Previous
sources and builds remain under `/opt/nexdeck/frontend-backups/`. The patch
refuses unexpected source changes instead of guessing during an upgrade.
The map adds no credentials, collects read-only data, and exposes no power,
storage, or backup actions.

Cards update through NexDeck's live event stream. Collection intervals range
from 10 seconds for downloads to five minutes for recent library additions.
An empty stream or queue is a real idle state. The page does not generate
activity, start playback, or pause jobs automatically. Native action buttons
remain available where the integration and user permissions allow them.

The bundled stars background and poster strip provide motion. Switch the
background to **None** and the poster card's **View** to **Covers in a grid**
for a still display. Activity tabs change only when selected.

Google is the default search target. Wikipedia, YouTube, and GitHub remain available.
The buttons show their shortcuts, such as `!y` for YouTube. Card title links
use the friendly service URLs. The full bookmark collection remains available
on the **Bookmarks** tab and through the **Everyday favorites** card title.
Discord is excluded from both pages.

Website favicons are stored as native NexDeck icon uploads. This keeps private
service addresses local and lets the LibreSpeed icon load over HTTPS.
Zipline uses its service logo because its favicon was unavailable. The ISO
file index has no favicon, so it uses an archive icon. Uploaded icons are
snapshots; replace them through NexDeck when a website changes its branding.

## Edit links

Open **Start → Bookmarks**, enable **Edit**, and open a bookmark card's settings.
Its links use one line per bookmark:

```text
Reddit | https://www.reddit.com/ | https://www.reddit.com/favicon.ico
Spoolman | https://spoolman.example.com/ | https://spoolman.example.com/favicon.svg
```

Use the **Layout** setting to choose a list or icon grid. Existing cards use
lists, website icons, the existing dark theme, and a four-column desktop layout.
NexDeck stacks the cards in reading order on phones. Links open in new tabs.

The categories are Everyday, Watch & listen, Downloads & archive, Home &
making, Search & AI, Code & tools, Infrastructure, and Network & files.
LibreSpeed keeps its direct HTTP URL, so a proxy cannot distort its results.

For map links, open the map card's settings and edit **Dashboard links**.
Use one key and URL per line:

```text
host/pve1 | https://pve.example.com/#v1:0:=node%2Fpve1:4:5::::::
host/truenas | https://truenas.example.com/
host/pbs | https://pbs.example.com/
guest/101 | https://service.example.com/
plex | https://plex.example.com/web/index.html
tdarr | https://tdarr.example.com/
```

Host keys use the lowercase displayed host name. Proxmox guest keys use the
VM ID, so their links survive migration between hosts and guest renaming.
TrueNAS app keys retain their existing app IDs. For a guest without a web
UI, select its Summary page in Proxmox and copy that page's URL. Add a line
when a new guest or app needs a link. Update the mapping when its VM ID changes.
Only absolute HTTP or HTTPS URLs
without embedded credentials are accepted. Links come from these explicit
settings, not from potentially sensitive portal data in app configuration.

## Export, import, and recovery

The live board is stored in NexDeck's database and stays editable. It is not a
file-provisioned board. Normal application upgrades preserve it with the rest
of `/var/lib/nexdeck`.

Use **Board menu → File → Export** before larger changes. Edit the existing
board through its file editor when updating it; importing the same export as
a new board creates a duplicate. For another installation, configure the
connections named under `integrations` in `start-board.yml.example` first.
Change the example URLs and connection names to match that installation,
then import the file. The example contains no connection credentials.
Deploy the NexDeck role before importing the combined map. In the map's
settings, select the existing Proxmox, TrueNAS, and PBS connections under
**Systems**. These references use installation-specific IDs, so the tracked
example leaves `sources` empty. Re-select them after moving an export to
another installation.
Configure a Google search target with shortcut `g` and URL
`https://www.google.com/search?q={query}` before importing the Live search card.
Search targets are shared application settings and are not part of board exports.

The example uses source favicon URLs because uploaded asset IDs belong to one
installation. For local icon copies, upload the images through NexDeck's media
settings and use the returned icon addresses in the bookmark lines. Include
the uploads directory with the database in application backups.

The `#6`, `#7`, and `#8` references in the activity tabs are zero-based widget
positions within the Live page. Keep these references aligned if the YAML
widget order changes. Normal edits in NexDeck handle the references for you.

The initial local source is in ignored `proxmox/tmp/nexdeck-start.yml`. It is a
deployment snapshot, not an automatic source of truth. The Live update also
saved an export in ignored `proxmox/tmp/nexdeck-start-live-current.yml`.
Export the current board before later work so browser edits are preserved.
Do not put actual deployment URLs, database exports, or credentials in the
tracked example.

Creation and the Live update each saved a protected SQLite backup under
`/var/lib/nexdeck/backups/`. Native import validation checked the content.
API readback confirmed preservation of the existing bookmark cards and Home
board. The only removed bookmark was Discord. The Live update reused existing
service credentials and required no new packages.

The map extension tests run against the installed NexDeck backend and venv:

```bash
PYTHONPATH=/opt/nexdeck/app/backend /opt/nexdeck/venv/bin/python /tmp/test_nexdeck_homelab.py -v
```

Copy `tests/test_nexdeck_homelab.py` into the guest first. The tests cover the
combined tree, source isolation, alert propagation, duplicate sources, invalid
settings, host and app destinations, guest migration, and app states and failures.
Recheck the extension when upgrading
NexDeck's adapter API.

The renderer patch adds link safety and keyboard-focus tests to the upstream
topology tests. The deployment runs them with `npm test --
src/components/TopologyCard.test.tsx` and completes the production build.
