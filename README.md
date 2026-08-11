# Calibre plugin for Xteink X3 (stock firmware)

A Calibre plugin to send EPUBs wirelessly to a **Xteink X3** running its
**stock manufacturer firmware**, and to browse/delete files already stored
on the device — all over the local network, no cable or SD card swap
required.

> **Running CrossPoint instead?** This plugin is for the stock firmware
> only. If you've flashed
> [CrossPoint](https://github.com/crosspoint-reader/crosspoint-reader),
> use [`crosspoint-reader/calibre-plugins`](https://github.com/crosspoint-reader/calibre-plugins)
> instead — it talks to CrossPoint's own (documented) WebSocket protocol.

## Disclaimer

This plugin was built with heavy AI assistance ("vibe coding") rather
than written line-by-line by hand. It works for me, on my own X3, and
has had a human pass reviewing and fixing the logic — but it hasn't
been battle-tested across different firmware versions, network setups,
or edge cases.

In particular, before trusting it with books or files you care about:

- Read `network.py` yourself, especially `upload()` and `delete_file()`
  — the delete path is recursive and there's no "are you sure, really"
  beyond the one confirmation dialog in Calibre.
- Test on a device / library where a mistake costs you nothing, first.
- Don't assume error handling covers every failure mode the real
  hardware can produce; the stock firmware's API isn't documented, so
  some behavior here is best-effort guesswork.

Issues and PRs — including "this assumption is wrong" ones — are
welcome.

## Features

- Send one or several EPUBs from your Calibre library straight to the
  reader over Wi-Fi.
- Auto-discovery: scans the local `/24` network for a Xteink X3, or lets
  you enter/save an IP address manually.
- Browse the files and folders stored on the device, and delete them
  (recursively for folders) — a small file-manager dialog inside Calibre.
- French translation included (`fr.mo`); UI strings are in English by
  default via `gettext`.

New in v1.1.0

- "Empty Xteink X3" button: clears the device in one click (protects the XTCache system folder)
- Automatic conversion to EPUB for books lacking this format (MOBI, AZW3, PDF, etc.)
- Real progress bar during transfer + duplicate detection before transfer
- Calibre toolbar icon
- "Explore Xteink X3 filesystem (debug)": browse and preview internal files
- "Reading progress (X3)": displays reading progress per book (experimental — based on undocumented internal files)

New n v1.2.0

- Add support for multiple named Xteink X3 devices (save, rename,
  delete), with automatic migration from the old single-IP format
- Fix save_ip() silently overwriting the entire config file on every
  call, which would have wiped the named devices list
- Add optional target folder selection when sending books (existing
  folders only — folder creation via /edit was tested and confirmed
  broken on this firmware, option removed)
- Add post-upload verification: the firmware can return HTTP 200 on
  /edit without actually writing the file (observed with a
  non-existent target folder), so uploads are now confirmed by
  relisting the target directory rather than trusting the HTTP
  response alone
- Warn explicitly in the UI when a "successful" upload can't be
  verified on the device, instead of silently reporting success

## About the `bofi.xteink.com` request

Before the plugin can talk to the reader over the LAN, the stock Xteink
firmware needs a single `GET` request sent to
`http://bofi.xteink.com/index.html`. This isn't something this plugin
adds on top — it's how the manufacturer firmware itself works: without
that request, the device's local HTTP API (`/Read_info`, `/edit`,
`/list`) simply doesn't respond to anything on the LAN.

To be explicit about what that request does and doesn't do:

- It's a plain `GET` to the domain's front page — no reader identifier,
  no book data, no personal information is sent.
- It happens before every scan and before every upload/list/delete
  operation (see `initialize_xteink()` in `network.py`).
- If you have no internet access at the time, this step — and therefore
  the whole plugin — won't work, even though everything else happens
  purely on your LAN.

This is undocumented, reverse-engineered behavior of the stock firmware.
If anyone understands *why* the device needs this or finds a way around
it, contributions are very welcome.

## Installation

```bash
python build.py          # produces Xteink_X3.zip
```

In Calibre: **Preferences → Plugins → Load plugin from file**, select
`Xteink_X3.zip`, then restart Calibre. The action appears in the
toolbar under **X3 reader management** (`Ctrl+Shift+X`).

## Usage

1. Put the Xteink X3 in **"PC Transfer" mode** (Wi-Fi file transfer mode
   in the device's own menu).
2. From Calibre, select one or more books and click **Send to Xteink
   X3** — or use **Manage books on X3** to browse/delete existing files.
3. On first use the plugin scans the local network for the reader; the
   IP address found is saved for next time (editable manually if
   needed).

## Protocol notes (reverse-engineered, stock firmware)

None of this is officially documented by Xteink — it was worked out by
observation. It may break on firmware updates.

| Call | Method | Purpose |
|---|---|---|
| `http://bofi.xteink.com/index.html` | GET | Unlocks the device's local HTTP API (see above) |
| `http://<ip>/Read_info` | GET | Returns a raw text blob with `Version`, `ID`, `STA-MAC`, `AP-MAC` fields, no separators between them |
| `http://<ip>/edit` | POST (multipart) | Uploads a file (`data` field) |
| `http://<ip>/list?dir=<path>` | GET | Returns a JSON array describing the contents of `<path>`; returns something else (non-JSON) if `<path>` is a file rather than a directory |
| `http://<ip>/edit` | DELETE (form body: `path=<path>`) | Deletes a file. Deleting a non-empty directory fails — its contents must be deleted first |

## Known limitations

- Assumes a `/24` LAN and scans up to 254 addresses; unusual subnet
  masks aren't detected.
- No authentication on the device's local API — anyone on the LAN can
  talk to it while "PC Transfer" mode is active. This is a property of
  the stock firmware, not something the plugin controls.
- Stock firmware only, as noted above.

## License

MIT — see [`LICENSE`](LICENSE).
