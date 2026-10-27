# Emviary continuation notes

Last publication review: October 27, 2026. This is a resume index, not a release or live-health certificate.

## Start here

Read AGENTS.md and the relevant source/setup/quality documentation. Recheck the current branch, working-tree status and task authorization before acting. Existing uncommitted work may belong to another task.

## Current evidence

Reviewed on branch `codex/review-pending-work`, based on main revision
`db612562837dfe91c1332752a5daaeb1daf3be16`. The tested application and test
revision is `a79c1084f08b06a1e75b3c2a15ffe11ffcf953e6`; the publication follow-up
adds only this handoff and project instructions.

Ready source changes: account-free printable recipient guide, stable/seven-day
new-frame firmware defaults, clearer reconnect advice, preserved saved update
preferences, and gallery-index migration/query-plan regression coverage. The
previous path-cleanup documentation is already on main and was not republished.

Verification on the tested revision:

- Ruff lint and formatting pass for `src`, `tests` and `tools`.
- Full Python suite: 423 passed, one existing Starlette/httpx deprecation warning.
- Saved automatic, manual and disabled update policies survive a settings save,
  application restart and authenticated update discovery.
- Hidden-browser guide checks: Print calls `window.print()`, no JavaScript errors,
  no horizontal overflow at 1280/390/320 px, and readable one-page Letter PDF.
- The firmware submodule and release pin are unchanged. Button wording was
  checked against pinned source, not a new hardware test.

Original uncommitted files were copied into an isolated review branch; the
canonical checkout and other local branch histories were preserved during review.

No deployment, firmware update, panel refresh or live policy change was performed.
Destination Wi-Fi, charging kit, battery endurance, overnight operation and
physical recovery remain separate handoff gates. See the dated gift readiness
plan, then gather fresh live evidence before any deployment or physical release.

## Update after material work

- Task and scope, including any pending user decision.
- Exact checkout/branch/revision and relevant PR or artifact.
- What changed and which unrelated work remains.
- Checks actually run, results, and limits of the evidence.
- Deployment/physical observations separately, with date if performed.
- Next concrete step and rollback/approval scope when applicable.

Keep tokens, credentials, customer data and raw diagnostics outside this document.
