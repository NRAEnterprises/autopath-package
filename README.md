# autopath

Auto-correcting filesystem path creation, sanitization, unique naming, custom
pathways, deep file discovery, bulk collection, and live folder watching.

Pure Python standard library — zero dependencies, zero compiled extensions.
Installs and behaves identically on Linux and Termux (Android), with nothing
to compile and nothing that can fail to build.

Standalone. Does not depend on any other package (including `cloud-restore`
or `farmctl`), and nothing else depends on it to function — any project can
adopt it independently.

## Install

```sh
curl -LsSf https://raw.githubusercontent.com/NRAEnterprises/autopath/main/install.sh | sh
```

Or manually:

```sh
git clone https://github.com/NRAEnterprises/autopath.git
pip install --user ./autopath
```

If the `autopath` command isn't found afterward, add pip's user bin
directory to `PATH` — find it with `python3 -m site --user-base`, then add
`<that path>/bin`.

## Why this exists

Every project that writes files to disk ends up reimplementing the same
handful of things: "make sure this directory exists," "turn this string
into a safe filename," "don't overwrite an existing file by accident."
`autopath` is that logic written once, correctly, with real fallback
behavior when the obvious path doesn't work — so it doesn't need
reinventing per project.

## Commands

### Path creation

```sh
autopath ensure <path>
```
Creates `<path>` if it doesn't exist. If it exists but isn't writable
(common when a directory was created by a different user/UID on an
earlier run), falls back to `~/persist_logs`, then `/tmp/persist_logs`
as a last resort — always prints a warning when it falls back, never
fails silently.

```sh
autopath chain <root> <segment> [<segment> ...]
```
Builds and ensures a nested path in one call:
```sh
autopath chain /home/Documents/persist_logs samsung Galaxy "S25 Ultra"
# -> /home/Documents/persist_logs/samsung/Galaxy/S25-Ultra
```

### Sanitization and unique naming

```sh
autopath sanitize "Galaxy S25 Ultra!!"
# -> Galaxy-S25-Ultra
```

```sh
autopath unique <directory> <name> [--ext .json]
```
Returns a collision-safe path in `<directory>` — if `<name>.json` already
exists, returns `<name>-2.json`, then `-3`, and so on. Never overwrites.

### Custom recognized pathways

Register a folder once under a short alias, per-user (stored at
`~/.config/autopath/paths.json`):

```sh
autopath register downloads ~/Downloads
autopath resolve downloads
autopath list-paths
autopath under downloads vibe-coding project-x
# -> ensures and prints ~/Downloads/vibe-coding/project-x
```

### File discovery

```sh
autopath identify <file>
```
Basic provenance: modified time (always available) and origin URL, if
present. Origin URL is a real but *rare* signal — only set by some desktop
browsers as an extended filesystem attribute (`user.xdg.origin.url`), and
only on filesystems that support xattrs (ext4: yes; FAT/exFAT, common on
Android external storage: no). `curl`, `wget`, `git clone`, and most Termux
downloads will show nothing here — that's expected, not a bug.

```sh
autopath discover <file>
```
Everything stdlib can tell you about a file in one call: size, three
timestamps, sha256 hash, guessed MIME type (extension-based), first-line
text snippet, and *every* extended attribute actually present (not just
origin URL). The sha256 hash is the reliable way to find true duplicates —
two files with the same hash are the same file, regardless of name.

### Bulk collect

Replaces running `mv $(grep -lir '...' dir/*) dest/` by hand, once per
group:

```sh
autopath collect <destination> --source <dir> --by content --match "some-string" [--dry-run]
```

`--by` modes:
| mode | matches on |
|---|---|
| `content` | string/regex found in the file's text |
| `name` | string/regex found in the filename |
| `xattr-any` | string/regex found in any extended attribute value |
| `hash` | exact sha256 match — pass a hex hash, or a path to a reference file |
| `origin-url` | exact match against the origin-URL xattr (rare — see above) |
| `omni` | content + name + all xattrs + MIME type, all at once |

Add `--regex` to treat `--match` as a regular expression, `--copy` to copy
instead of move, `--dry-run` to preview without touching anything.

### Live folder watching

```sh
autopath listen <destination> --source ~/Downloads [--interval 1.0]
```

Watches a folder and moves every *new* file into `<destination>` as it
finishes downloading (checked by size-stability across two polls, so a
file mid-download is never grabbed and moved half-written). Built for two
real situations: Android's "choose download location" picker silently
failing, and downloading several files from several different sources one
after another without manually sorting each one.

While running:
- `path <new-destination>` — redirect new files to a different folder,
  live, without restarting
- `stop` / `quit` / `exit` / Ctrl+C — end the session and print a summary

Runs in the foreground on purpose, not as a background daemon — Android
routinely suspends backgrounded Termux processes, which would make a true
daemon unreliable without `termux-wake-lock`. A session you actively drive
matches how this workflow actually happens.

## Using it as a library

```python
from autopath import ensure_path, ensure_path_chain, sanitize_component, resolve_unique_path
from autopath import register_path, resolve_alias, ensure_under_alias
from autopath import discover_file_info, collect_matches, DownloadWatcher
```

Every CLI command is a thin wrapper over one of these — call them directly
for tighter integration into your own project.

## License

MIT (or your choice — update this section before publishing).
