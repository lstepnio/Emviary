# Artwork library deletion

> Research and implementation record. Dates, release states, commands and test
> results below belong to the work recorded here; they are not a fresh production
> inspection. For current use, see [RUNBOOK](../RUNBOOK.md),
> [README](../README.md) and the [research index](README.md).

Owner library actions support Delete artwork, Restore artwork and bulk deletion
of entries outside rotation. Outside rotation means `approved` is false or the
owner has excluded that artwork. Special-day art is a separate collection.

Deletion is recoverable: SQLite records deleted IDs and timestamps, and the
service filters those records from the active catalog on startup and immediately
after a change. The source catalog and masters remain read-only recovery data;
files are not erased. Deleted entries no longer appear in public catalog, art
or thumbnail routes and cannot be selected for new compositions. Owners can view
and restore them using Availability > Deleted artwork. Restoring an excluded
artwork preserves its exclusion until the owner explicitly restores rotation.

Rendered history and the currently delivered frame image are preserved. A ready
composition containing deleted artwork is queued for replacement. At least one
usable rotation entry must remain. Actions require owner authentication and
CSRF validation, retain pagination and filters, and use the existing confirmation
prompt for Delete. The data stays in the existing backed-up SQLite database.

Validation: all 126 backend tests and lint passed, including anonymous and CSRF
rejection, persistence through service restart, private deleted thumbnails,
public removal, original file/history preservation, exact bulk membership,
restoration and the final-artwork guard.
