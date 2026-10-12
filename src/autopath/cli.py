"""
Command-line interface for autopath — lets shell scripts and other
non-Python tools use the same auto-correcting path logic that Python
projects import directly, so the behavior is identical everywhere.

Usage:
    autopath ensure <path>
    autopath sanitize <raw-string>
    autopath chain <root> <segment> [<segment> ...]
    autopath unique <directory> <desired-name> [--ext .json]
"""

import sys
import argparse

from . import (
    ensure_path, ensure_path_chain, sanitize_component, resolve_unique_path,
    register_path, resolve_alias, list_registered_paths, ensure_under_alias, rebase_path,
    identify_file, discover_file_info, collect_matches, DownloadWatcher,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="autopath",
        description="Auto-correcting filesystem path creation, sanitization, unique naming, custom pathways, and bulk file collection.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ensure = sub.add_parser("ensure", help="Verify/create a directory, with fallback on failure.")
    p_ensure.add_argument("path")

    p_sanitize = sub.add_parser("sanitize", help="Sanitize a raw string into a safe path segment.")
    p_sanitize.add_argument("value")

    p_chain = sub.add_parser("chain", help="Build and ensure a nested path from a root + segments.")
    p_chain.add_argument("root")
    p_chain.add_argument("segments", nargs="+")

    p_unique = sub.add_parser("unique", help="Resolve a collision-safe unique file path in a directory.")
    p_unique.add_argument("directory")
    p_unique.add_argument("name")
    p_unique.add_argument("--ext", default=".json")

    p_register = sub.add_parser("register", help="Register a custom folder path under a short alias.")
    p_register.add_argument("alias")
    p_register.add_argument("path")

    p_resolve = sub.add_parser("resolve", help="Print the path registered to an alias.")
    p_resolve.add_argument("alias")

    sub.add_parser("list-paths", help="List all registered aliases and their paths.")

    p_under = sub.add_parser("under", help="Build and ensure a nested path under a REGISTERED alias.")
    p_under.add_argument("alias")
    p_under.add_argument("segments", nargs="+")

    p_rebase = sub.add_parser(
        "rebase",
        help="Move everything under a registered alias's old location to a new one, and repoint the alias.",
    )
    p_rebase.add_argument("alias")
    p_rebase.add_argument("new_path")
    p_rebase.add_argument("--copy", action="store_true", help="Copy instead of move (old location left intact).")
    p_rebase.add_argument("--dry-run", action="store_true", help="Preview the moves without touching anything.")

    p_identify = sub.add_parser("identify", help="Show basic provenance (modified time, origin URL if available) for a file.")
    p_identify.add_argument("file")

    p_discover = sub.add_parser("discover", help="Show every stdlib-discoverable clue about a file (hash, all xattrs, mime guess, first-line, etc.).")
    p_discover.add_argument("file")

    p_collect = sub.add_parser(
        "collect",
        help="Move/copy every matching file from a source directory into a destination, in one call.",
    )
    p_collect.add_argument("destination", help="Folder to collect matches into (created if needed).")
    p_collect.add_argument("--source", required=True, help="Directory to search (recursively).")
    p_collect.add_argument("--by", choices=["content", "name", "origin-url", "xattr-any", "hash", "omni"], required=True,
                            help="What to match on. 'content'/'name' work on any file. 'omni' searches "
                                 "content + name + all xattrs + mime type at once. 'hash' groups exact "
                                 "duplicates (pass a hex hash or a reference file path). 'origin-url'/"
                                 "'xattr-any' only match files carrying that extended attribute (rare).")
    p_collect.add_argument("--match", required=True, help="The string/regex/hash/path to match, depending on --by.")
    p_collect.add_argument("--regex", action="store_true", help="Treat --match as a regular expression (ignored for --by hash).")
    p_collect.add_argument("--copy", action="store_true", help="Copy instead of move (source files left in place).")
    p_collect.add_argument("--dry-run", action="store_true", help="Show what would happen without touching any files.")

    p_listen = sub.add_parser(
        "listen",
        help="Watch a folder (e.g. Downloads) and redirect every new file into a destination, live, until you stop it.",
    )
    p_listen.add_argument("destination", help="Where new files should be moved to (created if needed).")
    p_listen.add_argument("--source", required=True, help="Folder to watch, e.g. your Downloads directory.")
    p_listen.add_argument("--interval", type=float, default=1.0, help="Seconds between checks for new files (default 1.0).")

    args = parser.parse_args(argv)

    if args.command == "ensure":
        print(ensure_path(args.path))
    elif args.command == "sanitize":
        print(sanitize_component(args.value))
    elif args.command == "chain":
        print(ensure_path_chain(args.root, *args.segments))
    elif args.command == "unique":
        print(resolve_unique_path(args.directory, args.name, extension=args.ext))
    elif args.command == "register":
        print(register_path(args.alias, args.path))
    elif args.command == "resolve":
        result = resolve_alias(args.alias)
        if result is None:
            print(f"no registered path for alias '{args.alias}'", file=sys.stderr)
            return 1
        print(result)
    elif args.command == "list-paths":
        registry = list_registered_paths()
        if not registry:
            print("(no registered paths yet — use `autopath register <alias> <path>`)")
        for alias, path in sorted(registry.items()):
            print(f"{alias}\t{path}")
    elif args.command == "under":
        try:
            print(ensure_under_alias(args.alias, *args.segments))
        except KeyError as e:
            print(str(e), file=sys.stderr)
            return 1
    elif args.command == "rebase":
        try:
            result = rebase_path(args.alias, args.new_path, copy=args.copy, dry_run=args.dry_run)
        except KeyError as e:
            print(str(e), file=sys.stderr)
            return 1
        label = "DRY RUN — " if result["dry_run"] else ""
        print(f"{label}{result['mode'].upper()} alias '{result['alias']}': "
              f"{result['from']} -> {result['to']} ({len(result['moved'])} file(s))")
        for item in result["moved"]:
            print(f"  {item['from']}  ->  {item['to']}")
    elif args.command == "identify":
        info = identify_file(args.file)
        print(f"path:       {info['path']}")
        print(f"modified:   {info['modified']}")
        print(f"origin_url: {info['origin_url'] or '(not available for this file)'}")
    elif args.command == "discover":
        info = discover_file_info(args.file)
        print(f"path:              {info['path']}")
        print(f"size_bytes:        {info['size_bytes']}")
        print(f"modified:          {info['modified']}")
        print(f"accessed:          {info['accessed']}")
        print(f"created_or_ctime:  {info['created_or_ctime']}")
        print(f"sha256:            {info['sha256']}")
        print(f"mime_type_guess:   {info['mime_type_guess'] or '(no useful guess for this extension)'}")
        print(f"first_line_clue:   {info['first_line_clue'] or '(none — binary or empty file)'}")
        print(f"origin_url:        {info['origin_url'] or '(not available for this file)'}")
        if info["all_xattrs"]:
            print("all_xattrs:")
            for k, v in info["all_xattrs"].items():
                print(f"    {k} = {v}")
        else:
            print("all_xattrs:        (none present)")
    elif args.command == "collect":
        result = collect_matches(
            source_dir=args.source, destination_dir=args.destination,
            match_by=args.by, match_value=args.match,
            copy=args.copy, regex=args.regex, dry_run=args.dry_run,
        )
        label = "DRY RUN — " if result["dry_run"] else ""
        print(f"{label}{result['mode'].upper()} {result['matched_count']} file(s) matching "
              f"{result['match_by']}='{result['match_value']}' into {result['destination']}")
        for item in result["moved"]:
            print(f"  {item['from']}  ->  {item['to']}")
    elif args.command == "listen":
        watcher = DownloadWatcher(source_dir=args.source, destination_dir=args.destination,
                                   interval=args.interval)
        watcher.start()
        print(f"Watching {watcher.source_dir} -> {watcher.destination_dir}")
        print("Commands: `path <new-destination>` to redirect, `stop` (or `quit`/`exit`) to end, Ctrl+C also works.")
        try:
            while True:
                try:
                    line = input("> ").strip()
                except EOFError:
                    # No interactive terminal available — stop cleanly
                    # instead of hanging forever waiting for input.
                    print("\n(no interactive input available — stopping)")
                    break

                if not line:
                    continue
                if line in ("stop", "quit", "exit", "done"):
                    break
                if line.startswith("path "):
                    new_dest = line[len("path "):].strip()
                    resolved = watcher.set_destination(new_dest)
                    print(f"Now redirecting new files to: {resolved}")
                else:
                    print("Unrecognized command. Use `path <new-destination>` or `stop`.")
        except KeyboardInterrupt:
            print("\n(stopping)")
        finally:
            watcher.stop()

        moved = watcher.moved_so_far()
        print(f"\nStopped. {len(moved)} file(s) moved this session.")
        for item in moved:
            print(f"  {item['from']}  ->  {item['to']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
