# NexDeck homepage

The `Start` board is an editable homepage with 44 links in eight categories.
It includes every service from the local DNS setup, related public homelab
services, and everyday bookmarks. The existing `Home` monitoring board remains
available through **Live dashboard** and the board selector.

The current homepage is `https://nexdeck.wbreiler.com/b/start`. It is also the
administrator's default board after sign-in. Set this URL as the browser's
homepage or startup page. Browser preferences are not managed by this change.

## Edit links

Open **Start**, enable **Edit**, and open a bookmark card's settings. Its links
use one line per bookmark:

```text
YouTube | https://www.youtube.com/ | lucide:play
Spoolman | https://spoolman.example.com/ | lucide:layers
```

Use the **Layout** setting to choose a list or icon grid. Existing cards use
lists, native icons, the existing dark theme, and a four-column desktop layout.
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
a new board creates a duplicate. For another installation, adapt
`start-board.yml.example` and import it through NexDeck.

The initial local source is in ignored `proxmox/tmp/nexdeck-start.yml`. It is a
deployment snapshot, not an automatic source of truth. Export the current
board before later work so browser edits are preserved. Do not put actual
deployment URLs, database exports, or credentials in the tracked example.

Creation saved a protected SQLite backup under `/var/lib/nexdeck/backups/`
before adding the board. Native import validation checked the content, and
readback confirmed all 44 links and preservation of the existing monitoring
board. No new integration credentials, authentication changes, or packages
were needed.
