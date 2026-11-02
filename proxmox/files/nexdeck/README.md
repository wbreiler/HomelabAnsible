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

The Live page uses the installed NexDeck widgets and existing integrations:

- A clock, search targets, and an icon grid for everyday favorites.
- Plex streams with backdrop artwork and a moving strip of recent additions.
- **In motion** tabs for SABnzbd, Sonarr, and Radarr queues.
- A Proxmox cluster map, TrueNAS pool capacity, backup activity, and Tdarr workers.

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
