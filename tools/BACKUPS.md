# Verified off-host backups

`pull_verified_backup.py` uses the current project's `emviary.backup_validation`
module. Run with the repo environment:

```sh
/opt/homebrew/bin/uv run --project /Users/lukasz.stepniowski/Development/Emviary python /Users/lukasz.stepniowski/Development/Emviary/tools/pull_verified_backup.py
```

SSH uses the existing key configuration for `lstepnio@one.majjix.com`, batch mode
and a 15-second connection timeout. Remote selection uses the host's standard
Python interpreter and the existing account's readable files under
`/docker/backups/emviary`; it requires neither Docker access nor sudo. It selects
the newest completion record from the current Denver date whose restore
rehearsal passed and whose manifest hash matches. Unreadable/malformed records,
links and future timestamps are skipped. If no current completed backup exists,
the pull fails without changing old copies or the remote success marker. The
server's own scheduler creates nightly backups before the 06:30 Mac pull.

The full file-integrity checks and isolated restore rehearsal run locally after
transfer. Remote selection does not claim to revalidate every payload file.
Existing backups are never replaced or deleted.

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
After success, `/docker/appdata/emviary/data/offhost-backup.json` on the host
(`/data/offhost-backup.json` inside the container) records only verification time, backup
name, manifest digest and the passed restore rehearsal for the owner UI. A failed
pull does not refresh the remote success marker.

`com.majjix.emviary.backup.plist` is a reviewable LaunchAgent template, scheduled
at 06:30 in the Mac's local timezone. Keep the Mac timezone at America/Denver for
the intended schedule. Review the absolute repo and `uv` paths before copying
it to `~/Library/LaunchAgents` and loading it. The LaunchAgent was installed and loaded on October 12, 2026, with a 1 GiB archive/payload limit. Its first actual scheduled-job invocation was tested with `launchctl kickstart` and exited successfully. The Mac must be available for off-host copies; the server continues its own nightly backups independently.
