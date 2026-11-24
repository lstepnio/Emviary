# Emviary project structure

Use `~/Development/Emviary` as the local project root and
[Emviary](https://github.com/lstepnio/Emviary) as the application repository.

Emviary is the only application checkout. The former eInkArtifact directory
was a compatibility link to this checkout, not a separate set of files or
application history. That link was retired on October 23, 2026.

```text
~/Development/
└── Emviary/                 canonical project directory
    ├── src/emviary/         service, management pages and rendering
    ├── art/                 artwork, catalog and attribution
    ├── converter/           display image converter dependencies
    ├── web-recovery/        browser recovery source and simulations
    ├── firmware/            Emviary-firmware Git submodule
    ├── firmware.lock.json   published firmware release pin
    ├── deployment/          example configuration and deployment assets
    ├── tools/               operational and backup utilities
    ├── tests/               application tests
    ├── research/            design, investigation and historical reports
    ├── README.md            development entry point
    ├── RUNBOOK.md           owner operations and recovery
    └── DEPLOYMENT.md        hosting and deployment guidance
```

The `firmware/` submodule has its own Git history and remote,
[Emviary-firmware](https://github.com/lstepnio/Emviary-firmware). Keep it as a
submodule rather than merging device firmware into the service repository.
Clone the application with `--recurse-submodules` as shown in README.md.

The local `.venv/`, `dist/`, and `output/` directories contain development
environments or generated files. They are not separate projects. Private state
and provisioning material must remain outside tracked source.

## Canonical local paths

The saved Codex project is named **Emviary**, with
`~/Development/Emviary` as its primary folder. Existing chats were preserved.
The rename migration recreated the Python environment from `uv.lock` and archived
a firmware build cache containing the retired absolute path. New environments
and firmware build directories must be generated for the checkout that owns them;
do not reuse a cache from another path. Documentation or checkout maintenance
does not by itself authorize changing a firmware release pin.

New tools, project entries and automation paths must use the canonical Emviary
directory. The backup LaunchAgent uses this directory too. No compatibility
shortcut is required.

Historical logs, migration reports, archived build files and saved chat records
may still mention the former project name. Those are historical evidence, not
active launchers or configuration. Reopen any old saved editor tabs from the
canonical project if they refer to the retired path.
