# Verified off-host backups

`pull_verified_backup.py` uses the current project's `emviary.backup_validation`
module. Run with the repo environment:

```sh
/opt/homebrew/bin/uv run --project /Users/lukasz.stepniowski/Development/Emviary python /Users/lukasz.stepniowski/Development/Emviary/tools/pull_verified_backup.py
```

SSH uses the existing key configuration for `lstepnio@one.majjix.com`, batch mode
and a 15-second connection timeout. The remote container `emviary` verifies its
most recent complete backup from the current Denver date under `/backups`, mounted from
`/docker/backups/emviary`. If none passes, it creates `offhost-YYYY-MM-DD` and
verifies it. Existing backups are never replaced or deleted.

The local destination defaults to
`~/Library/Application Support/Emviary/backups`. Each download is extracted into
private staging, checked against the remote manifest digest, and subjected to
an isolated offline restore rehearsal. Only then is the directory published
atomically. Matching existing copies are verified and reused. Changed content
under an existing backup name fails without replacement. Links, devices,
absolute paths, traversal and duplicate archive members are rejected.
Directories use mode 0700 and files use 0600.

`--destination` selects another private directory. Optional `--max-bytes` bounds
both archive download and extracted payload size; allow additional free space
for staging and the temporary restore rehearsal. There is no automatic retention
or deletion. `.last-pull.json` records the latest local outcome without secrets.
After success, `/data/offhost-backup.json` records only verification time, backup
name, manifest digest and the passed restore rehearsal for the owner UI. A failed
pull does not refresh the remote success marker.

`com.majjix.emviary.backup.plist` is a reviewable LaunchAgent template, scheduled
at 06:30 in the Mac's local timezone. Keep the Mac timezone at America/Denver for
the intended schedule. Review the absolute repo and `uv` paths before copying
it to `~/Library/LaunchAgents` and loading it. The LaunchAgent was installed and loaded on October 12, 2026, with a 1 GiB archive/payload limit. Its first actual scheduled-job invocation was tested with `launchctl kickstart` and exited successfully. The Mac must be available for off-host copies; the server continues its own nightly backups independently.
