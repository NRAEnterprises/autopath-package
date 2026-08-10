"""
autopath — core auto-correcting filesystem organization logic.

This is deliberately dependency-free (stdlib only) and framework-agnostic
so it can be dropped into ANY project — compute farm tooling, unrelated
scripts, future projects — as the one shared implementation of "how do we
create, verify, and name paths on disk" rather than reimplementing this
per-project.

Three responsibilities, each usable independently:

  1. ensure_path(path)        — verify/create a directory, with a safe
                                 writability fallback chain if it can't be
                                 used as given (permissions, wrong owner,
                                 path collision with an existing file).

  2. sanitize_component(s)    — turn any raw string (user-typed or
                                 machine-derived) into a single safe,
                                 consistent path segment.

  3. resolve_unique_path(dir, name, ext) — given a desired file name in a
                                 directory, auto-correct on collision by
                                 appending a numeric suffix rather than
                                 overwriting existing data.

Import these three into any project that writes files to disk in an
organized tree, instead of re-deriving this logic locally each time.
"""

import os
import re
import json
import shutil
import hashlib
import mimetypes
import threading
import time
from pathlib import Path
from datetime import datetime


# =======================================================================
# 1. Path verification / creation with fallback chain
# =======================================================================

def ensure_path(path: str | Path, fallback_root: Path | None = None,
                 last_resort: Path = Path("/tmp/autopath_fallback")) -> Path:
    """
    Verifies a target directory, handling all three states a path can be
    in, in order:

      1. Doesn't exist yet (in whole or in part) -> create the full
         parent chain.
      2. Exists and is writable -> use as-is, no redundant work.
      3. Exists but ISN'T writable by the current user/process (common
         when a directory was created by a different user/UID on a
         previous run, or under root vs. non-root) -> fall back rather
         than crashing or silently failing. Tries fallback_root first
         (defaults to the caller's home directory), then last_resort.

    Always returns a path that has been confirmed writable — never
    returns a path without having tested it can actually be written to,
    since a directory "existing" is not the same as being usable.
    """
    path = Path(path).expanduser()
    fallback_root = fallback_root or (Path.home() / "autopath_fallback")

    def _try_create_and_verify(candidate: Path) -> Path | None:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError, NotADirectoryError):
            return None

        probe = candidate / ".autopath_write_test"
        try:
            probe.write_text("ok")
            probe.unlink()
        except (PermissionError, OSError):
            return None
        return candidate

    result = _try_create_and_verify(path)
    if result is not None:
        return result

    print(f"warning: could not create/use '{path}' — falling back to '{fallback_root}'")
    result = _try_create_and_verify(fallback_root)
    if result is not None:
        return result

    print(f"warning: fallback '{fallback_root}' also unusable — using last resort '{last_resort}'")
    result = _try_create_and_verify(last_resort)
    if result is not None:
        return result

    # If even /tmp is unusable, the environment itself is broken beyond
    # what path fallback can fix — raise rather than pretend to succeed.
    raise OSError(
        f"autopath: unable to create a writable directory at '{path}', "
        f"'{fallback_root}', or last-resort '{last_resort}'"
    )


def ensure_path_chain(root: str | Path, *segments: str) -> Path:
    """
    Convenience wrapper: build a full nested path from root + ordered
    segments (each sanitized automatically) and ensure the whole chain
    exists and is writable in one call.

        ensure_path_chain("/home/Documents/persist_logs",
                           "acme", "widget-pro", "unit-1")
        -> creates/verifies .../acme/widget-pro/unit-1 and returns it
    """
    path = Path(root).expanduser()
    for segment in segments:
        path = path / sanitize_component(segment)
    return ensure_path(path)


# =======================================================================
# 2. Component sanitization
# =======================================================================

def sanitize_component(value: str, fallback: str = "unknown") -> str:
    """
    Turns any raw string — user-typed or machine-derived — into a single
    filesystem-safe path segment: strips whitespace, removes anything
    that isn't alphanumeric/space/dash/underscore/dot, collapses
    remaining whitespace into single dashes, trims stray leading/trailing
    dashes. Returns `fallback` if the result would be empty, so a blank
    or fully-invalid input never produces an unusable/empty path segment.

    Use this on EVERY path/file segment in a project — both
    automatically-derived ones (device model names, category labels) and
    user-typed ones (a prompted file name) — so the whole tree stays
    consistent regardless of where a given segment came from.
    """
    value = (value or "").strip()
    value = re.sub(r"[^A-Za-z0-9 _.\-]", "", value)
    value = re.sub(r"\s+", "-", value).strip("-")
    return value or fallback


# =======================================================================
# 3. Collision-safe unique file naming
# =======================================================================

def resolve_unique_path(directory: str | Path, desired_name: str,
                          extension: str = ".json") -> Path:
    """
    Given a desired base file name inside `directory`, returns a path
    that's guaranteed not to collide with an existing file — auto-
    correcting by appending "-2", "-3", etc. rather than ever silently
    overwriting existing data. This is the core rule for anything
    writing named files into an auto-organized tree: NEVER clobber,
    ALWAYS auto-correct the name instead.

        resolve_unique_path("/archive/acme/widget-pro", "unit-1")
        -> .../unit-1.json                         (if free)
        -> .../unit-1-2.json                        (if unit-1.json exists)
        -> .../unit-1-3.json                        (if -2 also exists)
    """
    directory = Path(directory)
    if extension and not extension.startswith("."):
        extension = f".{extension}"

    base = sanitize_component(desired_name)
    candidate = directory / f"{base}{extension}"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = directory / f"{base}-{counter}{extension}"
        if not candidate.exists():
            return candidate
        counter += 1


# =======================================================================
# 4. Custom path registry — user-defined "recognized pathways"
# =======================================================================
#
# Lets you name a folder once (e.g. "downloads", "code-projects") and
# have every autopath command that accepts an alias resolve it, instead
# of retyping/hardcoding the full path everywhere. Per-user, stored at
# ~/.config/autopath/paths.json — this is real per-user preference data
# (unlike e.g. a system-wide device archive), so tying it to $HOME is
# correct here even on a system with multiple users.

_REGISTRY_DIR = Path.home() / ".config" / "autopath"
_REGISTRY_PATH = _REGISTRY_DIR / "paths.json"


def _load_registry() -> dict:
    if not _REGISTRY_PATH.exists():
        return {}
    try:
        return json.loads(_REGISTRY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_registry(registry: dict) -> None:
    ensure_path(_REGISTRY_DIR)
    _REGISTRY_PATH.write_text(json.dumps(registry, indent=2, sort_keys=True))


def register_path(alias: str, path: str | Path) -> Path:
    """
    Registers `path` under `alias` for this user, creating/verifying it
    immediately via ensure_path so a freshly registered alias is always
    usable right away.

        register_path("downloads", "~/Downloads")
        register_path("code-drops", "~/Downloads/code-drops")
    """
    alias = sanitize_component(alias)
    resolved = ensure_path(Path(path).expanduser())
    registry = _load_registry()
    registry[alias] = str(resolved)
    _save_registry(registry)
    return resolved


def resolve_alias(alias: str) -> Path | None:
    """Returns the registered path for an alias, or None if it isn't
    registered — callers should treat None as 'not registered yet',
    not silently fall back to something else."""
    registry = _load_registry()
    raw = registry.get(sanitize_component(alias))
    return Path(raw) if raw else None


def list_registered_paths() -> dict:
    return _load_registry()


def ensure_under_alias(alias: str, *segments: str) -> Path:
    """
    Builds and ensures a nested path under a REGISTERED alias, rather
    than a literal root — the alias-based equivalent of
    ensure_path_chain(). Raises KeyError with a clear message if the
    alias was never registered, instead of silently creating something
    under the current directory.

        register_path("downloads", "~/Downloads")
        ensure_under_alias("downloads", "vibe-coding", "project-x")
        -> ~/Downloads/vibe-coding/project-x
    """
    base = resolve_alias(alias)
    if base is None:
        raise KeyError(
            f"no registered path for alias '{alias}' — register it first with "
            f"`autopath register {alias} <path>`"
        )
    return ensure_path_chain(base, *segments)


_MIGRATIONS_LOG_PATH = _REGISTRY_DIR / "migrations.log"


def _log_migration(entry: str) -> None:
    ensure_path(_REGISTRY_DIR)
    timestamp = datetime.now().isoformat()
    with _MIGRATIONS_LOG_PATH.open("a") as f:
        f.write(f"{timestamp}\t{entry}\n")


def rebase_path(alias: str, new_path: str | Path, copy: bool = False,
                 dry_run: bool = False) -> dict:
    """
    Moves everything already organized under a registered alias's OLD
    location to a NEW location, then repoints the alias — for when the
    underlying storage moved (new device, new mount point, a storage
    path that changed) but the folder structure you built under that
    alias should carry over intact rather than starting over.

    This is the alias system doing the work a "device profile" would
    otherwise need vendor/model-specific knowledge to do: since
    everything was already organized under an alias rather than a
    literal path, moving it is just "point the alias somewhere else and
    bring the contents along" — no awareness of what device or vendor
    either location belongs to is required.

    Every file that would collide with something already at the new
    location is renamed via resolve_unique_path rather than overwritten.
    dry_run=True previews the full set of moves without touching
    anything or updating the registry. Every real (non-dry-run) rebase
    is appended to ~/.config/autopath/migrations.log for an audit trail.

    Raises KeyError if the alias was never registered.
    """
    old_path = resolve_alias(alias)
    if old_path is None:
        raise KeyError(
            f"no registered path for alias '{alias}' — nothing to rebase. "
            f"Register it first with `autopath register {alias} <path>`"
        )

    new_path = Path(new_path).expanduser()
    moves = []

    if old_path.exists():
        for item in sorted(old_path.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(old_path)
            target_dir = new_path / rel.parent
            if not dry_run:
                ensure_path(target_dir)
            target = resolve_unique_path(target_dir, item.stem, extension=item.suffix) \
                if not dry_run else (target_dir / item.name)
            moves.append({"from": str(item), "to": str(target)})
            if not dry_run:
                if copy:
                    shutil.copy2(item, target)
                else:
                    shutil.move(str(item), str(target))

    if not dry_run:
        ensure_path(new_path)
        registry = _load_registry()
        registry[sanitize_component(alias)] = str(new_path)
        _save_registry(registry)
        _log_migration(
            f"rebase alias={alias} from={old_path} to={new_path} "
            f"files_moved={len(moves)} mode={'copy' if copy else 'move'}"
        )

    return {
        "alias": alias,
        "from": str(old_path),
        "to": str(new_path),
        "moved": moves,
        "mode": "copy" if copy else "move",
        "dry_run": dry_run,
    }


# =======================================================================
# 5. File discovery — every stdlib-available clue about a file's
#    identity, origin, and relatedness to other files
# =======================================================================
#
# discover_file_info() pulls together everything the standard library
# can tell you about a single file, in one call. Reliability varies a
# lot by field — this is stated explicitly per field rather than
# implied, since "deeper info" is only useful if you know how much to
# trust it:
#
#   ALWAYS available (from the filesystem itself):
#     size_bytes, modified/accessed/created-or-ctime, sha256
#
#   OFTEN available for text files, no special conditions needed:
#     first_line_clue — the first line of the file. For scripts this
#     is frequently a shebang or a header comment that names the
#     project/language even when the filename itself is generic.
#
#   SOMETIMES available, extension-dependent only (not content-sniffed):
#     mime_type_guess — via the stdlib `mimetypes` module, which
#     guesses purely from the file extension. A renamed or
#     extensionless file gets no useful guess here; this project
#     deliberately has no dependency on a magic-byte sniffing library.
#
#   RARELY available, platform/tool-dependent:
#     all_xattrs / origin_url — extended filesystem attributes. Only
#     present if something that wrote the file explicitly set them
#     (some desktop browsers do, for origin URL specifically), AND
#     only on a filesystem that supports xattrs at all (ext4: yes;
#     FAT/exFAT, common on Android external storage: no). curl, wget,
#     git clone, and most Termux download flows set none of this.
#
# sha256 is the one field worth calling out separately: it's the most
# reliable way to find files that are ACTUALLY related (exact
# duplicates saved twice, or copied between folders) — two files with
# the same hash are the same file, full stop, regardless of what
# either one is named.

def _read_all_xattrs(path: Path) -> dict:
    """Every extended attribute actually present on this file, not
    just the origin-URL ones — some tools stash other clues under
    different keys, and this surfaces all of them rather than guessing
    which key to look for."""
    result = {}
    if not hasattr(os, "listxattr"):
        return result
    try:
        keys = os.listxattr(str(path))
    except OSError:
        return result
    for key in keys:
        try:
            raw = os.getxattr(str(path), key)
            result[key] = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
    return result


def _sha256_of(path: Path, chunk_size: int = 1 << 20) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _first_line_clue(path: Path, max_chars: int = 200) -> str | None:
    try:
        with path.open("r", errors="ignore") as f:
            first = f.readline().strip()
        return first[:max_chars] if first else None
    except (OSError, UnicodeDecodeError):
        return None


def discover_file_info(path: str | Path) -> dict:
    """
    The full picture for one file — see reliability notes above for
    which fields to actually trust. Nothing here is guaranteed present
    except size and the three timestamps; everything else degrades to
    None/empty rather than guessing.
    """
    path = Path(path)
    st = path.stat()

    xattrs = _read_all_xattrs(path)
    origin_url = xattrs.get("user.xdg.origin.url") or xattrs.get("user.xdg.referrer.url")
    mime_type, _ = mimetypes.guess_type(str(path))

    return {
        "path": str(path),
        "size_bytes": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
        "accessed": datetime.fromtimestamp(st.st_atime).isoformat(),
        "created_or_ctime": datetime.fromtimestamp(st.st_ctime).isoformat(),
        "origin_url": origin_url,
        "all_xattrs": xattrs,
        "sha256": _sha256_of(path),
        "mime_type_guess": mime_type,
        "first_line_clue": _first_line_clue(path),
    }


def identify_file(path: str | Path) -> dict:
    """
    Kept as the original lightweight provenance check (modified time +
    origin URL only) for backward compatibility with existing callers.
    For the full picture — hash, all xattrs, mime guess, first-line
    clue — use discover_file_info() instead.
    """
    path = Path(path)
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime).isoformat()

    origin_url = None
    if hasattr(os, "getxattr"):
        for key in ("user.xdg.origin.url", "user.xdg.referrer.url"):
            try:
                raw = os.getxattr(str(path), key)
                origin_url = raw.decode("utf-8", errors="replace")
                break
            except OSError:
                continue

    return {"path": str(path), "modified": modified, "origin_url": origin_url}


# =======================================================================
# 6. Bulk collect — replaces repeated `mv $(grep -lir '...' dir/*) dest/`
# =======================================================================
#
# match_by modes, from narrowest to broadest signal:
#   "content"    — string/regex found in the file's text content
#   "name"       — string/regex found in the filename
#   "origin-url" — exact match against the origin-URL xattr (rare, see above)
#   "xattr-any"  — string/regex found in ANY extended attribute value
#   "hash"       — exact sha256 match, either against a literal hex
#                  hash string or against a reference file's hash
#                  (pass a path that exists and its hash is used) —
#                  the reliable way to group true duplicates/copies
#   "omni"       — combines content + name + all xattr values + mime
#                  type guess: matches if the string/regex is found in
#                  ANY of them. This is "search everything you can
#                  possibly discover about the file, all at once."

def _content_matches(path: Path, value: str, regex: bool) -> bool:
    try:
        text = path.read_text(errors="ignore")
    except (OSError, UnicodeDecodeError):
        return False
    return re.search(value, text) is not None if regex else value in text


def _name_matches(path: Path, value: str, regex: bool) -> bool:
    return re.search(value, path.name) is not None if regex else value in path.name


def _xattr_any_matches(path: Path, value: str, regex: bool) -> bool:
    for xval in _read_all_xattrs(path).values():
        if (re.search(value, xval) is not None) if regex else (value in xval):
            return True
    return False


def _omni_matches(path: Path, value: str, regex: bool) -> bool:
    if _name_matches(path, value, regex) or _content_matches(path, value, regex):
        return True
    if _xattr_any_matches(path, value, regex):
        return True
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type and ((re.search(value, mime_type) is not None) if regex else (value in mime_type)):
        return True
    return False


def _hash_matches(path: Path, value: str) -> bool:
    target_hash = value
    ref_path = Path(value).expanduser()
    if ref_path.exists() and ref_path.is_file():
        target_hash = _sha256_of(ref_path)
    return _sha256_of(path) == target_hash


_MATCHERS = {
    "content": lambda p, v, r: _content_matches(p, v, r),
    "name": lambda p, v, r: _name_matches(p, v, r),
    "origin-url": lambda p, v, r: identify_file(p)["origin_url"] == v,
    "xattr-any": lambda p, v, r: _xattr_any_matches(p, v, r),
    "hash": lambda p, v, r: _hash_matches(p, v),
    "omni": lambda p, v, r: _omni_matches(p, v, r),
}


def collect_matches(source_dir: str | Path, destination_dir: str | Path,
                     match_by: str, match_value: str,
                     copy: bool = False, regex: bool = False,
                     dry_run: bool = False) -> dict:
    """
    Finds every file under source_dir matching by the chosen mode (see
    match_by options above), then moves (or copies, with copy=True)
    each match into destination_dir — created automatically if it
    doesn't exist yet — using resolve_unique_path so an existing file
    there is never overwritten. This is the direct replacement for
    running `mv $(grep -lir 'string' dir/*) dest/` by hand once per
    group, now able to search everything discoverable about a file at
    once via match_by="omni", not just its content.

    Returns a summary dict including every from/to path actually
    touched, so you can see (or, with dry_run=True, preview) exactly
    what happened rather than trusting it blindly.
    """
    if match_by not in _MATCHERS:
        raise ValueError(f"unknown match_by: '{match_by}' (expected one of {sorted(_MATCHERS)})")

    source_dir = Path(source_dir).expanduser()
    dest_dir = ensure_path(Path(destination_dir).expanduser())
    matcher = _MATCHERS[match_by]

    matched = [
        candidate for candidate in sorted(source_dir.rglob("*"))
        if candidate.is_file() and matcher(candidate, match_value, regex)
    ]

    moved = []
    for src_file in matched:
        target = resolve_unique_path(dest_dir, src_file.stem, extension=src_file.suffix)
        if not dry_run:
            if copy:
                shutil.copy2(src_file, target)
            else:
                shutil.move(str(src_file), str(target))
        moved.append({"from": str(src_file), "to": str(target)})

    return {
        "destination": str(dest_dir),
        "match_by": match_by,
        "match_value": match_value,
        "matched_count": len(matched),
        "moved": moved,
        "mode": "copy" if copy else "move",
        "dry_run": dry_run,
    }


# =======================================================================
# 7. Live watch — redirect a folder's incoming downloads in real time
# =======================================================================
#
# Built for the case where Android's "choose download location" picker
# silently fails, or you're pulling several files from several
# different places one after another and don't want to manually move
# each one as it lands. Points at a source folder (typically
# Downloads), moves every NEW file that appears there — once it looks
# fully written, not mid-download — into a destination you control,
# and lets you redirect that destination or stop the whole thing while
# it's running, without restarting anything.
#
# Runs in the foreground on purpose, not as a background daemon: Android
# frequently suspends background processes for apps (including Termux)
# that lose focus, so a true background daemon here would be unreliable
# without something like termux-wake-lock. A foreground session that
# you actively drive — start it, download your batch, redirect or stop
# — matches how this workflow actually happens and doesn't depend on
# anything beyond the standard library.

def _is_file_stable(path: Path, wait: float) -> bool:
    """A file is treated as 'done downloading' only if its size is
    unchanged across two checks `wait` seconds apart. This is what
    keeps the watcher from grabbing a file that's still being written
    to and moving a truncated copy."""
    try:
        size1 = path.stat().st_size
    except OSError:
        return False
    time.sleep(wait)
    try:
        size2 = path.stat().st_size
    except OSError:
        return False
    return size1 == size2


class DownloadWatcher:
    """
    Watches source_dir for new files and moves each stable one into a
    destination that can be redirected live via set_destination(),
    without stopping the watch loop. Runs its polling in a background
    thread; start()/stop() control that thread from your own code (the
    CLI `listen` command wraps this with an interactive stdin loop).
    """

    def __init__(self, source_dir: str | Path, destination_dir: str | Path,
                 interval: float = 1.0, stability_wait: float = 0.5):
        self.source_dir = Path(source_dir).expanduser()
        self.destination_dir = ensure_path(Path(destination_dir).expanduser())
        self.interval = interval
        self.stability_wait = stability_wait

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._moved: list[dict] = []
        # Snapshot what's already there so only genuinely NEW files
        # trigger a move — pre-existing files in the folder are left
        # alone.
        self._seen = {p for p in self.source_dir.glob("*") if p.is_file()}

    def set_destination(self, new_destination: str | Path) -> Path:
        with self._lock:
            self.destination_dir = ensure_path(Path(new_destination).expanduser())
        return self.destination_dir

    def moved_so_far(self) -> list[dict]:
        with self._lock:
            return list(self._moved)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                current_files = {p for p in self.source_dir.glob("*") if p.is_file()}
            except OSError:
                current_files = set()

            for f in current_files - self._seen:
                if not _is_file_stable(f, wait=self.stability_wait):
                    # Still being written — leave it unmarked so the
                    # next poll cycle checks it again.
                    continue
                self._seen.add(f)
                with self._lock:
                    dest = self.destination_dir
                try:
                    target = resolve_unique_path(dest, f.stem, extension=f.suffix)
                    shutil.move(str(f), str(target))
                    with self._lock:
                        self._moved.append({"from": str(f), "to": str(target)})
                    print(f"  moved: {f.name}  ->  {target}")
                except OSError as e:
                    print(f"  warning: could not move {f}: {e}")

            self._stop_event.wait(self.interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval * 2 + 2)
