# Design notes — device-agnostic path migration and registry

Purpose
- Capture design suggestions for making autopath device-agnostic: allow the tool to recognize and migrate device-default path fragments (vendor, model, system defaults) while preserving user-registered custom paths.
- Provide a clear, reviewable plan so the maintainer can implement or apply changes intentionally.

Goals
- Automatically correct path fragments that reflect historical device defaults to match the current device's defaults.
- Never overwrite or remove user-registered custom paths; treat them as authoritative.
- Keep the default behavior dependency-free and explicit (dry-runable migrations and user confirmation).

Key concepts
- Device profile: a named set of canonical fragments and defaults for a platform/device family (e.g., android/samsung/Galaxy, linux/generic, windows/generic, apple/macos).
- Device registry: per-user JSON registry (in ~/.config/autopath/) that stores profiles and a "current" profile choice.
- Migration: the act of mapping a path that contains fragments from one profile into the equivalent path using another profile's fragments.
- User-registered aliases: existing register_path(alias, path) entries that must be preserved and excluded from mass-migration rules.

File locations and formats (proposal)
- Device profiles (per-user):
  - Path: ~/.config/autopath/devices.json
  - Schema (example):

```json
{
  "profiles": {
    "android-samsung": {
      "vendor": "samsung",
      "device_model": "Galaxy",
      "downloads": "~/storage/downloads",
      "persist_dir": "~/persist_logs",
      "other_fragments": ["DCIM", "Pictures"]
    },
    "linux-generic": {
      "vendor": "generic",
      "device_model": "LinuxHost",
      "downloads": "~/Downloads",
      "persist_dir": "~/persist_logs"
    }
  },
  "current": "linux-generic"
}
```

- Registry of user aliases (existing): ~/.config/autopath/paths.json (already used by the project).

Behavioral rules for migration
- Only rewrite path segments that match *known* device-default fragments from a source profile. Do not attempt fuzzy replacements on arbitrary segments.
- Preserve any directory segment that appears in the user alias registry. If a path includes a segment that equals a registered alias value, skip replacement for that subtree.
- Migration should be explicit and dry-run by default. The CLI should provide a `--apply` switch to perform changes.

Example migration algorithm (high level)
1. Load device profiles and the user alias registry.
2. Build two fragment maps: from_profile_fragments and to_profile_fragments.
   - e.g., {"samsung": "vendor", "Galaxy": "device_model", "Downloads": "downloads"}
3. Walk the input path's segments left-to-right and, for each segment:
   - If segment matches a registered alias value -> mark subtree as protected and stop replacing under it.
   - Else if segment matches a value in from_profile_fragments, replace it with the corresponding value in to_profile_fragments (if present).
   - Otherwise leave the segment unchanged.
4. Return the migrated path.

Edge cases and constraints
- Profiles may not have perfect one-to-one mappings. If a fragment in the source profile has no mapping in the target, leave it as-is and log a warning.
- Case sensitivity: default to exact matching, but allow a `--case-insensitive` option for platforms where that is appropriate.
- Filesystems and separators: use pathlib.Path to rebuild paths safely for the running OS when presenting results; migration should not assume a single path style if the purpose is to produce portable documentation or suggestions.

CLI additions (suggested)
- autopath device add <name> --vendor <v> --model <m> [--downloads <path>] [--persist <path>]
- autopath device list
- autopath device set-current <name>
- autopath device get-current
- autopath migrate --from <profile> --to <profile> <target-root> [--dry-run] [--apply] [--protect-registered]
  - `--dry-run` default; `--apply` performs moves/renames.
  - `--protect-registered` (default true) ensures registered aliases are never altered.

API additions (suggested functions)
- load_device_profiles(path: Path | None = None) -> dict
- save_device_profiles(profiles: dict, path: Path | None = None) -> None
- detect_profile_candidates(path: Path) -> list[str]
  - heuristics to guess which profile(s) a given path likely belongs to
- migrate_path(path: Path, from_profile: str, to_profile: str, protect_registered: bool = True) -> Path
- bulk_migrate(root: Path, from_profile: str, to_profile: str, dry_run: bool = True) -> dict
  - returns a report of proposed changes (from->to list)

Preserving user customizations
- Use the existing register_path/resolve_alias registry to mark protected roots.
- When migrating, if a candidate replacement would change a path that is or contains a registered alias path, skip that candidate and note it in the report.

Safety and UX
- Always produce a clear, human-readable report for dry runs and require explicit `--apply` to perform filesystem changes.
- For `--apply`, perform atomic moves where possible (shutil.move) and ensure resolve_unique_path is used on the target to avoid clobbering files.
- Log every move with a timestamped entry in the user's config directory (e.g., ~/.config/autopath/migrations.log) so changes can be audited and optionally reverted.

Testing and validation
- Unit tests for migrate_path covering:
  - direct mapping replacements
  - protected registered aliases
  - missing mappings (no-op for unmapped fragments)
  - paths with mixed user-created and device-default fragments
- Integration test for bulk_migrate using a temporary directory containing example legacy paths.

Examples (documentation-friendly, device-agnostic)
- Before (device-specific example to be replaced):
  - autopath sanitize "Galaxy S25 Ultra!!"  # -> Galaxy-S25-Ultra

- After (device-agnostic example):
  - autopath sanitize "Example Device 123!!"  # -> Example-Device-123
  - autopath chain /home/persist_logs vendor DeviceModel "Example Device"
    # -> /home/persist_logs/vendor/DeviceModel/Example-Device

Notes for maintainers
- Do not auto-rewrite user alias registry entries; those are authoritative user preferences.
- Keep device profiles per-user by default (avoid system-wide defaults unless explicitly desired).
- Keep the migration operation interactive/dry-run by default to avoid accidental mass-moves.

Next steps (for you to apply manually)
- Review these notes and, if you agree, I can produce patch files for the following docs changes (no code changes unless you request them):
  - Replace device-specific examples in README.md, install.sh, and docstrings in __init__.py with the generic "Example Device" placeholders.
  - Add this design-notes.md (already created) to the repo (so you can edit or extend it).
- If you want code/CLI changes implemented, tell me whether to produce patches (for your review) or to push directly.

