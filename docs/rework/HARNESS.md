# Phase 3a characterization harness

Default command, which stays green and does not run Playwright:

```text
py -3 -m pytest
```

`pytest.ini` keeps `addopts = -ra -m "not e2e"`. These tests do not change that, and they do not touch `tests/e2e/`.

The new tests call today's functions and assert today's outputs, including quirks. They use temporary directories and in-memory stand-ins. They do not open the network.

## What the new tests lock

S6 applied D05. Conflict save-edits, conflict approve, and merge approve pin only fields the operator supplied. `tests/test_d05_pin_flags.py` is unskipped and locks that write. `tests/test_pin_flag_writes.py` locks the same behavior. Normal approve still leaves all four `chosen_*_set` flags at 0. The lines below this one that describe "all four flags" are the pre-S6 characterization and are no longer the code.

- `NormalApprovePinFlagTests.test_approve_copies_effective_values_without_setting_pin_flags` — `approve_book` copies effective author, title, series, and series index into `chosen_*` and leaves all four `chosen_*_set` flags at 0.
- `ConflictPinFlagTests.test_save_edits_sets_all_four_pin_flags` — `save_conflict_edits` writes the edited values and sets all four flags.
- `ConflictPinFlagTests.test_approve_with_override_sets_all_four_pin_flags` — `approve_conflict` sets all four flags when the body overrides one field.
- `ConflictPinFlagTests.test_approve_without_override_leaves_pin_flags_unset` — the same approve with no overrides still copies values and leaves the flags at 0.
- `MergeApprovePinFlagTests.test_approve_with_override_sets_all_four_pin_flags_on_primary` — `approve_merge` sets all four flags on the primary book when the body has an override, and does not set them on the member.
- `MergeApprovePinFlagTests.test_approve_without_override_leaves_pin_flags_unset` — merge approve without overrides leaves the flags at 0.

Library-root guard (`tests/test_library_root_guard.py`):

- `LibraryRootGuardTests.test_guard_accepts_path_below_library_and_refuses_root_or_outside` — `_assert_target_under_library` accepts a child of the library, refuses the library root with `target path must be below library root`, and refuses a sibling path.
- `LibraryRootGuardTests.test_remove_extras_refuses_library_root_and_leaves_the_file` — `remove_extra_library_files` aimed at `.` returns `failed` with that same error and does not unlink the extra file.
- `LibraryRootGuardTests.test_replace_collapses_parent_segments_and_stays_inside_library` — `replace_library_target` with author and title `..` is accepted as `untitled/untitled` under the library and does not create a directory outside it.

Activity-lock exclusion (`tests/test_activity_lock_exclusion.py`). This is the check the code actually makes, not a second concurrency model:

- `ActivityLockExclusionTests.test_running_auto_blocks_manual_scan` — `start_scan` returns HTTP 409 `Auto-scan and stage in progress` while an auto-run row is running and its thread is alive, and does not start a scan.
- `ActivityLockExclusionTests.test_live_scan_thread_blocks_auto_run` — `AutoRunManager.start_run` raises `AutoRunBlocked` (`manual scan already in progress`) when the scan thread is alive, including a scheduled run that bypasses the activity lock.
- `ActivityLockExclusionTests.test_scan_row_without_live_thread_does_not_block_auto` — a running scan row whose thread is not alive does not block a manual auto run.

Old database (`tests/test_old_db_migrate.py`):

- `OldDatabaseMigrateTests.test_connect_adds_missing_columns_and_repairs_false_pins_once` — `app.db.connect` on a sqlite file that predates the alter columns adds the book, scan, auto-action, and auto-settings columns, creates `file_fingerprints`, copies `metadata_done` into `books_complete` while leaving `books_discovered` at 0 when `books_found` was added as 0, unpins chosen values that still match suggested, keeps divergent pins, writes `schema_flags.repair_false_chosen_pins_v1`, and does not run that repair again on the next connect.

## Cited instead of duplicated

- Fingerprint identity: `FingerprintTests.test_order_independence`, `FingerprintTests.test_same_content_different_path_same_id`, `FingerprintTests.test_split_files_different_ids` in `tests/test_fingerprint.py`. Cache behavior in that module is separate and was left as-is.
- Scan cancel: `ScanCancelTests.test_cancel_marks_scan_cancelled` and `ScanCancelApiTests.test_cancel_api_returns_cancelling_message` in `tests/test_scan_cancel.py`. Browser cancel stays `test_b_rescan_cancel_keeps_books_and_seeds` in `tests/e2e/test_b_scan.py`. `test_cancel_sets_cancelling_message_before_finish` holds the discovery worker until it has read `Cancelling…`. `cancel_scan` writes that message before it returns, and the worker then replaces it with `Scan cancelled`, so an immediate read was a race.
- Activity lock renew, expiry, and the default timeout: `ActivityLockTests` in `tests/test_activity_lock.py`.
- Scheduled auto blocked while the lock is held: `AutoManualRunTests.test_scheduled_run_blocked_by_activity_lock`. Manual auto bypass: `AutoManualRunTests.test_manual_run_bypasses_activity_lock`. A manual run that does not bypass the lock: `AutoManualRunTests.test_manual_run_without_bypass_blocked_by_lock`. All in `tests/test_auto_manual_run.py`.
- False-pin repair on a database that already has the columns: `ChosenPinMigrateTests` in `tests/test_chosen_pin_migrate.py`.
- In-library replace outcomes: `LibraryReplaceTests` in `tests/test_library_replace.py`.
- In-library extra removal that unlinks: `PartialStagingTests.test_remove_extra_library_files` in `tests/test_partial_staging.py`.

## Skipped until a later slice

`tests/test_d05_pin_flags.py` passed in S6. It is no longer skipped.

`tests/test_d07_bounded_lists.py` is skipped until S2. Its skip reasons start with `D07`. The 50,000-row case inserts SQL rows only. It does not create audio files.

## Deliberately unchanged

No production code, no existing tests, no e2e tests, no README, no Docker, and no `pytest.ini`. Bugs were not fixed. D05's future pin-flag change was not applied. Nothing was committed.

## Phase 3b fitness boundaries

Source scans of `stager_core/` and `app/`. No network. Same AST style as `tests/test_no_research_imports_in_stager.py`. `urllib.parse` is not treated as an HTTP client. Reads, writes, mkdir, and rmdir are not part of the link rule.

- `test_stager_core_imports_app_only_from_library_cache` in `tests/test_fitness_boundaries.py` — after S7, no `stager_core` module imports `app`. `stager_core/library_cache.py` no longer imports `app.api`.
- `test_provider_http_stays_in_providers_and_ratelimit` — `requests`, `httpx`, and `urllib.request` stay in `stager_core/metadata/providers.py` and `stager_core/metadata/ratelimit.py`. Today the client calls (`urllib.request.Request`, `urllib.request.urlopen`) are in `ratelimit.py`. `providers.py` builds URLs with `urllib.parse` and calls `RateLimitedClient.request_json`. `app/api.py` uses `urllib.parse.unquote`. No other file is allowlisted.
- `test_link_and_unlink_stay_in_staging` — `os.link` and `Path.unlink` (`path.unlink`, `dst.unlink`) stay in `stager_core/staging.py`. No `os.unlink` under `stager_core/` or `app/` today. No other file is allowlisted.
