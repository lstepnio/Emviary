# Container registry

The `Publish container` workflow publishes `ghcr.io/lstepnio/emviary` after the
`Checks` workflow succeeds for a push to `main`. A manual run is also available
on `main` and verifies the same successful checks before publishing.

Each build has a full commit tag, `sha-<40-character-commit>`, and a dated tag,
`YYYYMMDD-<12-character-commit>`. `latest` is promoted only when the checked
source is still current `main`. Deploy by the published digest for an exact
image, rather than relying on a moving tag.

The image targets `linux/amd64`, matching `one`. Publishing uses the workflow's
temporary `GITHUB_TOKEN` with package-write access. No registry password is
stored on the server. Package visibility and access use GitHub's package
settings; publishing does not automatically make a new package public.

```sh
docker pull ghcr.io/lstepnio/emviary:latest
# For a pinned deployment, use the digest from the successful workflow summary:
docker pull ghcr.io/lstepnio/emviary@sha256:<published-digest>
```

Private packages require an authenticated pull with package-read access.
Runtime configuration, credentials, databases and the art library remain
external mounts. This workflow publishes the service image and does not deploy
the server, change frame settings, or publish firmware. Firmware retains its
separate versioned release workflow in `lstepnio/Emviary-firmware`.

Before a server rollout, run `deployment/backup-before-home-rollout.sh`, record
its verified rollback directory, and update only the existing Emviary service.
