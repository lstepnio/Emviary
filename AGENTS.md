

<!-- efficient-project-workflow: start -->
## Efficient project workflow

- This directory is the canonical application checkout. Read `PROJECT_STRUCTURE.md` for paths. `firmware/` is a separate Git submodule; do not merge its history into the service or change its pin incidentally.
- Map: `src/emviary/` service/rendering, `tests/` backend checks, `web-recovery/` recovery source/simulations, `deployment/` hosting examples. Read `RUNBOOK.md` or `DEPLOYMENT.md` when the task involves operations.
- Local verification: `uv run ruff check src tests tools`, `uv run ruff format --check src tests tools`, and targeted `uv run pytest -q` checks. Broaden only for actual changes or unresolved concerns. Recovery/firmware checks belong to their own source directories.
- Preparation, HTTP delivery and authenticated physical display confirmation are distinct evidence. Never label a generated image as displayed solely because it was served. Keep physical recovery, Wi-Fi, battery and overnight acceptance separate from offline tests.
- Read the actual branch/status before edits and preserve unrelated work. `CODEX_HANDOFF.md` is a resume index, not proof of live state. Record tested revision, deployment evidence if any, and remaining physical gaps after material work.
<!-- efficient-project-workflow: end -->
