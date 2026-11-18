D01: B, 2026-11-17, Python domain and FastAPI stay. SQLite repositories with real pagination. Vue after the API contract is frozen. Current page stays until the parity list in 05-ui-workflows.md is green.
D02: credentialed providers stay optional and are skipped when unset; keyless providers stay on; Google Books and MyAnonaMouse stay in the tree, 2026-11-17, signed before this rework. Blank METADATA_CONTACT_EMAIL does not disable Open Library.
D03: keep, 2026-11-17, library layout stays Author/Series/Title, with flat Author/Title when series is empty or pinned empty.
D04: keep, 2026-11-17, auto-stage stays, including the timer, Run now, eligibility, and the away queue.
D05: fix, 2026-11-17, pinning stays as the pinning doc. Conflict and merge approve must not set all pin flags; they follow normal approve.
D06: audiobook-only plus a light media-kind seam, 2026-11-17, no epub or mobi parser. Owner: stay audiobook-only, but do not lock the code so hard that a later format cannot plug in.
D07: yes, 2026-11-17, scale bar about 50,000 books and on the order of 500,000 audio files. UI must page. List and conflict reads must not be full-table. Provider rate limits stay as they are. Owner confirmed the same day: designing for that size is fine, and the UI may change to support it. The 50,000 figure is a design bar, not a count of the current library.
D08: yes, 2026-11-17, one operator per instance, no authentication. Other people clone and run their own copy.
D09: yes, 2026-11-17, HTTP routes stay compatible until the Vue parity list is green. Unused routes may be deleted in the UI slice after that.
License: GPL-3.0-only, 2026-11-17, owner selected GPL-3.0. The file is the official GNU GPL version 3 text.
