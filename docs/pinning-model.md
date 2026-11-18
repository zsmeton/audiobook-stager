"""Pinning / Manual vs Suggested metadata — operator notes

This documents the current product contract (as of the Playwright e2e work).
It is intentionally descriptive, not a redesign proposal.

## Layers

Per field (`author`, `title`, `series`, `series_index`):

| Storage | Meaning |
|---------|---------|
| `suggested_*` | Last lookup winner. Relookup may overwrite. |
| `chosen_*` + `chosen_*_set` | Operator pin when `_set = 1`. |
| `effective_*` | `_set ? chosen : suggested` |

UI badges (“Manual” / “Suggested”) follow `_set`, **not** whether `chosen_*` is non-empty.

Pinned empty series ⇒ `confirmed_none` (force flat `Author/Title/` with no series folder).

## Staging snapshot ≠ pin

Normal **Approve** / auto-stage copies effective values into `chosen_*` but leaves
`chosen_*_set = 0` unless that field was already pinned. The detail form still
shows Suggested so a later relookup can update suggestions.

Conflict save-edits, conflict approve, and merge approve may also copy effective
values into `chosen_*`. They set `chosen_*_set` only for a field the operator
supplied, using the same rules as Save / revert. Supplying one field does not
pin the other three. A field the operator did not supply keeps its existing flag.

## Save / revert

- `PATCH` with a `chosen_*` field present marks that field Manual (`_set = 1`),
  even if the value equals suggested.
- Revert clears `_set` so effective falls back to suggested.
- Series and series index pin when that field is supplied and the value is
  non-empty, a suggestion exists, or the field was already pinned. An empty
  value with neither a suggestion nor an existing pin stays unpinned (avoids
  accidental `confirmed_none`).
- Conflict save-edits sends author, title, series, and series index together, so
  author and title pin, and series fields follow the empty rule above.
- Conflict approve and merge approve pin only the fields present on the request.

## Relookup policies

- Detail **Re-lookup** always passes pinned fields as `ManualHints`.
- Full **Scan** only does so when Settings → “Use manual metadata as scan hints”
  (`scan_manual_hints`) is on.

## Auto-stage

Any book with `any_chosen_set` is skipped by auto-stage.

## Migration scar

When pin columns were added, a one-time backfill treated non-empty `chosen_*` as
manual (including approve snapshots). `_repair_false_chosen_pins` later unpins
rows where `chosen == suggested`.
