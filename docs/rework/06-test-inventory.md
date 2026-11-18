# Test inventory (Audiobook Stager rework)

Evidence is cited as `path:line`. **Observed** = directly seen in repo; **Inference** = reasoned from config or conventions, labeled in the Inference section.

## Commands

### Unit (default)

| Source | Command / config |
|--------|------------------|
| `README.md:34` | `py -3 -m pytest` |
| `pytest.ini:6` | `addopts = -ra -m "not e2e"` |

**Observed:** E2E tests are excluded on a bare `pytest` invocation because `pytest.ini` sets `addopts` to `-m "not e2e"`.

Quoted exclusion line:

```ini
addopts = -ra -m "not e2e"
```

(`pytest.ini:6`)

**Observed:** Root `conftest.py` only adds the repo root to `sys.path` (`conftest.py:12-15`). No `pyproject.toml` pytest section in repo.

**Observed:** E2E extra deps: `tests/requirements-e2e.txt:2-3` (`pytest-playwright`, `playwright`).

### End-to-end

**Observed:** README describes e2e as marked `e2e` and excluded by default (`README.md:37`) but does **not** document an explicit e2e command.

**Inference:** The conventional invocation to run only e2e tests is `py -3 -m pytest -m e2e` (marker defined at `pytest.ini:3`).

**Observed:** All e2e modules set `pytestmark` including `pytest.mark.e2e` (e.g. `tests/e2e/test_a_smoke.py:10`).

### Marker summary (`pytest.ini:2-5`)

| Marker | Purpose |
|--------|---------|
| `e2e` | Playwright browser tests (slow; needs Chromium) |
| `e2e_layout(name)` | Selects `tests/e2e/fixtures_fs.layout_{name}` |
| `e2e_fixture_delay_ms(ms)` | Sets `STAGER_FIXTURE_LOOKUP_DELAY_MS` for cancel UX |

## Module counts

| Kind | Count | Measurement |
|------|-------|-------------|
| Unit test modules (`tests/test_*.py`) | **54** | Glob under `tests/` excluding `tests/e2e/` |
| E2E test modules (`tests/e2e/test_*.py`) | **7** | Glob under `tests/e2e/` |
| E2E support (not counted as test modules) | 3 | `tests/e2e/conftest.py`, `helpers.py`, `fixtures_fs.py` |

## Module inventory

### Unit modules (`tests/`)

#### `tests/test_activity_lock.py`

- **Locks:** Activity lock renew/active state, expiry, default timeout from auto settings.
- **Tests:** `ActivityLockTests.test_renew_makes_lock_active`, `test_lock_expires`, `test_default_timeout_from_settings`.
- **Production:** `app/activity_lock.py`, `app/db.py` (`connect`, `get_auto_settings`, `update_auto_settings`).

#### `tests/test_approve_series_metadata.py`

- **Locks:** Approve stores semantic title (not path suffix) when staging.
- **Tests:** `ApproveSeriesMetadataTests.test_approve_stores_semantic_title_not_path_suffix`.
- **Production:** `app/api.py` (`approve_book`, `holder`), `app/db.py`, `app/scan.py`, `app/session.py`.

#### `tests/test_asin.py`

- **Locks:** ASIN extraction from tags/URLs; trusted field handling.
- **Tests:** `ExtractAsinTests.*`, `TrustedFieldTests.*`.
- **Production:** `stager_core/metadata/tags.py`.

#### `tests/test_author_oeuvre.py`

- **Locks:** Author oeuvre probe/pick/fetch/cache; lookup injects oeuvre candidate (mocked providers).
- **Tests:** `OeuvreProbeTests.*`, `OeuvrePickTests.*`, `OeuvreFetchAndCacheTests.*`, `LookupIntegrationTests.test_resolve_injects_author_oeuvre_candidate` (and related).
- **Production:** `stager_core/metadata/author_oeuvre.py`, `stager_core/metadata/lookup.py`, `stager_core/discovery.py`, scoring/query types.

#### `tests/test_auto_change_feedback.py`

- **Locks:** Auto change feedback recording, dismiss review, revert, paginated `get_auto_feedback`.
- **Tests:** `AutoChangeFeedbackTests.*` (includes feedback list with `limit`/`offset`).
- **Production:** `app/api.py`, `app/db.py`, `app/scan.py`, `app/activity_lock.py`.

#### `tests/test_auto_eligibility.py`

- **Locks:** Rules for auto-stage eligibility (confidence, conflict, partial, missing author, pins, suggested-only).
- **Tests:** `AutoEligibilityTests.test_eligible_high_confidence`, `test_excluded_when_author_pinned`, etc.
- **Production:** `stager_core/auto_eligibility.py`.

#### `tests/test_auto_manual_run.py`

- **Locks:** Manual auto run bypasses activity lock; scheduled run blocked when lock active.
- **Tests:** `AutoManualRunTests.test_manual_run_bypasses_activity_lock`, `test_scheduled_run_blocked_by_activity_lock`.
- **Production:** `app/auto.py`, `app/activity_lock.py`, `app/db.py`, `app/scan.py`.

#### `tests/test_auto_revert.py`

- **Locks:** Unstage removes hardlink; skips foreign inode.
- **Tests:** `AutoRevertTests.test_unstage_removes_hardlink`, `test_unstage_skips_foreign_inode`.
- **Production:** `stager_core/staging.py`, `stager_core/discovery.py`.

#### `tests/test_bulk_approve.py`

- **Locks:** Bulk approve stages multiple pending books via API.
- **Tests:** `BulkApproveTests.test_bulk_approve_stages_multiple_books`.
- **Production:** `app/api.py` (`bulk_approve`), `app/scan.py`, `app/session.py`, `app/auto.py`, `app/db.py`.

#### `tests/test_bulk_revert.py`

- **Locks:** Bulk revert unstages multiple books.
- **Tests:** `BulkRevertTests.test_bulk_revert_unstages_multiple_books`.
- **Production:** Same API/session stack as bulk approve.

#### `tests/test_chosen_pin_migrate.py`

- **Locks:** On `connect()`, staging snapshots are not falsely pinned; `_repair_false_chosen_pins` unpins matching suggested values; divergent pins kept.
- **Tests:** `ChosenPinMigrateTests.test_reconnect_does_not_pin_staging_snapshot`, `test_repair_unpins_chosen_matching_suggested`, `test_repair_keeps_divergent_pins`.
- **Production:** `app/db.py` (`connect`, `_repair_false_chosen_pins`, `schema_flags`).

#### `tests/test_conflict_approve.py`

- **Locks:** Conflict approve with metadata override, save edits on all pending seeds, approve seed over library replace/stage.
- **Tests:** `ConflictApproveApiTests.test_approve_seed_with_metadata_override_stages_new_path`, `test_save_conflict_edits_updates_all_pending_books`, `test_approve_seed_over_library_replaces_and_stages`.
- **Production:** `app/api.py` (`approve_conflict`, `save_conflict_edits`), `stager_core/staging.py`, `app/scan.py`, `app/session.py`.

#### `tests/test_conflicts.py`

- **Locks:** Conflict grouping, library vs seed sides, target keys, merge hints, pinned metadata in conflict rows.
- **Tests:** `ConflictTests.*` (multiple scenarios for grouping and candidate sides).
- **Production:** `stager_core/conflicts.py`, library/inode indexes.

#### `tests/test_decision_log.py`

- **Locks:** Lookup writes decision row; approve/skip/revert/edit outcomes; join by book_id; skipped routine scan writes no decision.
- **Tests:** `LookupDecisionRowTests.*`, `DecisionOutcomeTests.*`, `ScanSkipNoDecisionTests.*`.
- **Production:** `app/api.py`, `app/db.py` (`insert_lookup_decision`), `app/scan.py`, scoring/discovery types.

#### `tests/test_destage_rescan.py`

- **Locks:** Deleting library hardlink returns book to pending on rescan; still-staged stays staged.
- **Tests:** `DestageRescanTests.test_deleted_library_copy_returns_to_pending`, `test_still_staged_book_stays_staged`.
- **Production:** `app/scan.py`, `app/session.py`, `stager_core/discovery.py`, `stager_core/staging.py`.

#### `tests/test_discovery_parallel.py`

- **Locks:** Parallel discovery fingerprints match serial `discover_books`.
- **Tests:** `DiscoveryParallelTests.test_parallel_fingerprint_matches_serial`.
- **Production:** `stager_core/discovery.py`.

#### `tests/test_discovery_parts.py`

- **Locks:** Part detection heuristics; multi-file parts discover as one book.
- **Tests:** `PartDetectionTests.*`, `DiscoverBooksPartGroupingTests.*`.
- **Production:** `stager_core/discovery.py`.

#### `tests/test_duration.py`

- **Locks:** Per-file and library-target duration sums; missing file handling.
- **Tests:** `DurationTests.test_sum_file_durations_totals_seconds`, `test_sum_library_target_durations_sums_files`, etc.
- **Production:** `stager_core/metadata/duration.py`.

#### `tests/test_effective_metadata.py`

- **Locks:** Effective author/title/series from pins vs suggested; series state; `any_chosen_set`.
- **Tests:** `EffectiveMetadataTests.test_suggested_when_not_pinned`, `test_pinned_empty_series_is_confirmed_none`, etc.
- **Production:** `stager_core/metadata/effective.py`.

#### `tests/test_fingerprint.py`

- **Locks:** `book_id_from_paths` order invariance; same content different path; split files; SQLite fingerprint cache hit/invalidate/persist/prune.
- **Tests:** `FingerprintTests.test_order_independence`, `test_same_content_different_path_same_id`, `FingerprintCacheTests.test_cache_hit_skips_file_read`, etc.
- **Production:** `stager_core/fingerprint.py`, `app/fingerprint_cache.py`, `app/db.py`.

#### `tests/test_fixture_providers.py`

- **Locks:** Fixture metadata catalog matching; no cross-title false positives; probe; env gate; lookup delay env.
- **Tests:** `FixtureProvidersTests.test_title_author_hit`, `test_backend_env_gate`, `test_lookup_delay_env`, etc.
- **Production:** `stager_core/metadata/fixture_providers.py`.

#### `tests/test_health.py`

- **Locks:** Health aggregate: DB ok, degraded under DB lock, running scan reported.
- **Tests:** `HealthChecksTests.test_database_check_ok`, `test_database_degraded_when_lock_held`, `test_running_scan_reported`.
- **Production:** `app/api.py` (`_run_health_checks`, `_aggregate_health_status`), `app/scan.py`, `app/session.py`, `app/db.py`.

#### `tests/test_library_cache.py`

- **Locks:** Library index cache reuse; invalidation on filesystem change; inode index copy.
- **Tests:** `LibraryCacheTests.*`.
- **Production:** `stager_core/library_cache.py`.

#### `tests/test_library_names.py`

- **Locks:** Parse library path into author/title parts.
- **Tests:** `LibraryNamesTests.test_splits_author_and_title`, `test_empty_path`, `test_title_only`.
- **Production:** `stager_core` library naming helpers (via imports in module).

#### `tests/test_library_replace.py`

- **Locks:** Replace target unlinks audio, preserves non-audio, noop if missing, hardlink unlink preserves source.
- **Tests:** `LibraryReplaceTests.*`.
- **Production:** `stager_core/staging.py` (`replace_library_target` and related).

#### `tests/test_lvi_lookup.py`

- **Locks:** LVI match/resolve, apply search, library corroboration, MAM entity series chrome, form match, candidate refresh, vocab exclude book id.
- **Tests:** `TestLviLookup.test_resolve_lvi_match_from_id3_hint`, `test_mam_html_entity_series_gets_lvi_chrome`, etc. (class-level pytest style).
- **Production:** `stager_core/metadata/lvi.py`, `library_vocab.py`, normalize/scoring.

#### `tests/test_mam_cookie_rotation.py`

- **Locks:** MAM cookie extract/persist priority; rotation on search (mocked HTTP).
- **Tests:** `ExtractMamCookieTests.*`, `MamRotationOnSearchTests.*`, etc.
- **Production:** `stager_core/metadata/providers.py`, `ratelimit.py`; uses `FakeClient` from `test_providers_search.py`.

#### `tests/test_manual_approve_review.py`

- **Locks:** Approve dismisses auto action; auto run does not queue manually staged book.
- **Tests:** `ManualApproveReviewTests.test_approve_dismisses_existing_auto_action`, `test_auto_run_does_not_queue_manually_staged_book`.
- **Production:** `app/api.py`, `app/auto.py`, `app/scan.py`, `app/db.py`.

#### `tests/test_manual_suggested_ux.py`

- **Locks:** Revert field/all clears or preserves pin flags; save marks manual; revert-then-save stays manual.
- **Tests:** `ManualSuggestedUxTests.test_revert_single_field_uses_suggested`, `test_save_marks_all_fields_manual`, etc.
- **Production:** `app/api.py` (`patch_book` path via DB rows).

#### `tests/test_merge_groups.py`

- **Locks:** Merge group detection; merge API stage; conflict approve clears merge; resolve merged staged names; staging overrides.
- **Tests:** `DetectMergeGroupsTests.*`, `MergeApiTests.*`, `ResolveMergedStagedNamesTests.*`, `StageMergedBooksOverrideTests.*`.
- **Production:** `app/api.py` (`MergeApprove`, `ConflictApprove`, merge endpoints), `stager_core` merge/staging/conflicts.

#### `tests/test_no_research_imports_in_stager.py`

- **Locks:** `app/` and `stager_core/` must not import `research` package.
- **Tests:** `test_no_research_imports_in_stager`.
- **Production:** Static AST scan of production trees.

#### `tests/test_normalize.py`

- **Locks:** Title/author normalization pipelines (indexes, editions, noise, series markers, publishers, subtitles).
- **Tests:** Multiple unittest classes (`StripLeadingIndexTests`, `CleanAuthorTests`, `SubtitleSplitTests`, …).
- **Production:** `stager_core/metadata/normalize.py`.

#### `tests/test_partial_staging.py`

- **Locks:** Partial staging analysis, extra library files, complete partial, collisions, remove extras, unstage partial.
- **Tests:** `PartialStagingTests.test_analyze_partial_book`, `test_complete_partial_stage_links_remaining`, etc.
- **Production:** `stager_core/staging.py` partial-stage helpers.

#### `tests/test_paths.py`

- **Locks:** Seed source path resolution; library target path from target key.
- **Tests:** `PathResolutionTests.test_resolve_seed_source_path_joins_relative_path`, `test_resolve_library_target_path_returns_target_folder`, `test_resolve_library_target_path_invalid_key`.
- **Production:** `stager_core/metadata/paths.py`.

#### `tests/test_provider_registry.py`

- **Locks:** Provider list marks key-gated providers; probe OK / skip unconfigured (mock `FakeProviders`, patched env).
- **Tests:** `ProviderRegistryTests.test_list_marks_key_gated_providers`, `test_probe_skips_unconfigured_google`.
- **Production:** `stager_core/metadata/provider_registry.py`.

#### `tests/test_providers_search.py`

- **Locks:** Audible/Audnexus/MAM/OpenLibrary/Google search behavior with **in-memory fakes** (no live HTTP).
- **Tests:** `AudibleSearchTests.*`, `MamSearchTests.*`, `TitleOnlyWrapperTests.*`, `MamSearchBodyTests.*`.
- **Production:** `stager_core/metadata/providers.py`.

#### `tests/test_scan_books_found.py`

- **Locks:** Discovery progress reports book count; provider list env.
- **Tests:** `ScanBooksFoundTests.test_discovery_on_progress_reports_book_count`, `test_provider_list_env`.
- **Production:** `stager_core/discovery.py` (mocked/patched scan path).

#### `tests/test_scan_cancel.py`

- **Locks:** Scan cancel status/message; API cancel response; cancel during discover/index/library/index build.
- **Tests:** `ScanCancelTests.test_cancel_marks_scan_cancelled`, `ScanCancelApiTests.test_cancel_api_returns_cancelling_message`, `IndexCancelTests.*`, `DiscoveryCancelTests.test_discover_books_raises_when_cancelled_mid_build`.
- **Production:** `app/scan.py`, `app/api.py` (`cancel_scan`), `stager_core/discovery.py`, `stager_core/target_index.py`, `stager_core/conflicts.py`.

#### `tests/test_scan_dedupe.py`

- **Locks:** Prune stale rows; migrate chosen metadata/skip status to successor; fingerprint rescan prunes old staged row.
- **Tests:** `ScanPruneTests.test_prune_migrates_chosen_metadata_to_successor`, `FingerprintRescanPruneTests.test_fingerprint_rescan_prunes_old_staged_row`, etc.
- **Production:** `app/scan.py`, `app/db.py`, `stager_core/discovery.py`, `app/session.py`.

#### `tests/test_scan_manual_hints.py`

- **Locks:** Auto setting passes pinned metadata into lookup; upsert manual flags; no shadowing of `get_auto_settings`.
- **Tests:** `ScanManualHintsTests.test_setting_on_passes_pinned_metadata`, `test_lookup_book_by_id_uses_pins_regardless_of_setting`, etc.
- **Production:** `app/scan.py`, `app/db.py`, `stager_core/metadata/lookup.py`.

#### `tests/test_scan_progress.py`

- **Locks:** Scan progress counters/aliases; skip lookup does not bump metadata; phase and complete counters.
- **Tests:** `ScanProgressTests.test_counters_monotonic_and_aliases`, `test_skip_lookup_does_not_increment_metadata`, `test_scan_sets_phase_and_complete_counters`.
- **Production:** `app/scan.py` (`ScanProgress`, `ScanManager`).

#### `tests/test_scoring.py`

- **Locks:** Membership grade; `pick_winner` behavior.
- **Tests:** `MembershipGradeTests.*`, `PickWinnerTests.*`.
- **Production:** `stager_core/metadata/scoring.py`.

#### `tests/test_search_context.py`

- **Locks:** `build_search_context` from tags/path/manual hints.
- **Tests:** `BuildSearchContextTests.*` (empty manual, title-only, misleading tags, etc.).
- **Production:** `stager_core/metadata/query.py`.

#### `tests/test_search_passes.py`

- **Locks:** Multi-pass metadata search orchestration, dedupe, generic titles, local cap, provider single-field HTTP **stubbed** via fakes.
- **Tests:** `GenericTitleTests.*`, `MultiPassOrchestrationTests.*`, `TheSixRegressionTests.*`, `ProviderSingleFieldTests.*`.
- **Production:** `stager_core/metadata/lookup.py` search passes, providers (mocked).

#### `tests/test_series_patch.py`

- **Locks:** PATCH series fields and pin semantics; candidates expose series; target-key preview; empty series without suggestion does not pin.
- **Tests:** `SeriesPatchTests.test_patch_empty_series_confirms_none`, `test_patch_empty_series_without_suggestion_does_not_pin`, `test_target_key_preview_endpoint`, etc.
- **Production:** `app/api.py` (`patch_book`, `preview_book_target_key`), `app/session.py`, `app/scan.py`.

#### `tests/test_series_scoring.py`

- **Locks:** Series pick/votes/id3/cluster scoring.
- **Tests:** Classes covering `pick_series`, votes, membership (see module).
- **Production:** `stager_core/metadata/series_scoring.py`, `scoring.py`.

#### `tests/test_series_staging.py`

- **Locks:** Target key and folder layout with/without series index.
- **Tests:** `SeriesStagingTests.test_two_level_without_series`, `test_three_level_with_index`, `test_resolve_staging_target_three_level`.
- **Production:** `stager_core/staging.py`.

#### `tests/test_session_persistence.py`

- **Locks:** Staging session persist/hydrate round-trip; hydrate none when empty.
- **Tests:** `SessionPersistenceTests.test_persist_and_hydrate_round_trip`, `test_hydrate_returns_none_when_no_books`.
- **Production:** `app/session.py`, `app/db.py`, `stager_core/staging.py`.

#### `tests/test_session_status.py`

- **Locks:** Session status API reflects DB session meta and scan manager.
- **Tests:** `SessionStatusTests.*` (module exercises `get_session_status`).
- **Production:** `app/api.py`, `app/db.py`, `app/scan.py`, `app/session.py`.

#### `tests/test_staging_confidence.py`

- **Locks:** `fold_staging_confidence` for confirmed-none vs named series.
- **Tests:** `StagingConfidenceTests.test_confirmed_none_uses_book_leg_only`, `test_named_series_uses_min`.
- **Production:** `stager_core/metadata/series_scoring.py`.

#### `tests/test_staging_session.py`

- **Locks:** `apply_stage` updates indexes without rglob; single `rebuild_target_indexes` per scan.
- **Tests:** `StagingSessionTests.test_apply_stage_updates_indexes_without_rglob`, `test_rebuild_target_indexes_called_once_per_scan_not_per_book`.
- **Production:** `app/session.py`, `stager_core/staging.py`, `stager_core/discovery.py`.

#### `tests/test_target_index.py`

- **Locks:** `build_target_indexes` matches legacy library/inode helpers.
- **Tests:** `TargetIndexParityTests.test_build_target_indexes_matches_legacy_helpers`.
- **Production:** `stager_core/target_index.py`, `stager_core/conflicts.py`, `stager_core/staging.py`.

#### `tests/test_title_extraction.py`

- **Locks:** Title extraction presets (conservative/balanced/advanced), config from settings, step validation.
- **Tests:** `test_conservative_prefers_album_over_title`, `test_config_from_settings_advanced_steps`, etc. (pytest functions).
- **Production:** `stager_core/metadata/title_extraction.py`, `cleanup_pipeline.py`.

#### `tests/test_title_first_production.py`

- **Locks:** Title-first candidates and lookup injection via **FakeProviders** (no `MetadataLookupService.__init__` network path).
- **Tests:** `TitleFirstProductionTests.test_fetch_title_first_retags_source`, `test_lookup_includes_title_first_candidates`.
- **Production:** `stager_core/metadata/title_first.py`, `lookup.py`, `scoring.py`.

### E2E modules (`tests/e2e/`)

#### `tests/e2e/test_a_smoke.py`

- **Locks:** Page loads, health OK/degraded, empty scan shows staging/conflicts empty states.
- **Tests:** `test_a_page_loads_and_empty_scan`.
- **Layout:** `smoke` (`fixtures_fs.layout_smoke`).
- **Production (via server):** `app.main`, static UI, `/api/health`, scan bootstrap.

#### `tests/e2e/test_b_scan.py`

- **Locks:** Scan populates staging list; rescan cancel keeps books and seeds on disk.
- **Tests:** `test_b_scan_populates_staging`, `test_b_rescan_cancel_keeps_books_and_seeds` (uses `e2e_fixture_delay_ms(400)`).
- **Layout:** `happy_scan`.
- **Production:** Full stack + Playwright `#booksList`.

#### `tests/e2e/test_c_approve.py`

- **Locks:** Approve hardlinks seed; unstage; skip/unskip no library write; bulk approve hardlinks remainder.
- **Tests:** `test_c_approve_hardlinks_seed_and_leaves_siblings`, `test_c_unstage_returns_to_pending_and_removes_dest`, `test_c_skip_and_unskip_does_not_write_library`, `test_c_bulk_approve_hardlinks_remaining`.
- **Layout:** `happy_scan`.

#### `tests/e2e/test_e_conflicts.py`

- **Locks:** Pick non-suggested conflict winner hardlinks; edit+save leaves conflict; staged conflict keep library.
- **Tests:** `test_e_pick_non_suggested_winner_hardlinks_that_seed`, `test_e_edit_title_save_leaves_conflict`, `test_e_staged_conflict_keep_library`.
- **Layouts:** `conflict_pending`, `conflict_staged`.

#### `tests/e2e/test_f_merge.py`

- **Locks:** Merge split parts stages both seeds into one destination (hardlinks).
- **Tests:** `test_f_merge_and_stage`.
- **Layout:** `merge_parts`.

#### `tests/e2e/test_h_lvi.py`

- **Locks:** LVI gold chrome on detail after staging canonical author.
- **Tests:** `test_h_lvi_gold_chrome_on_detail`.
- **Layout:** `lvi`.

#### `tests/e2e/test_k_toolbar.py`

- **Locks:** Staging toolbar filter/search/sort changes visible order/content.
- **Tests:** `test_k_filter_search_sort`.
- **Layout:** `happy_scan`.

## E2E fixture needs

### `tests/e2e/conftest.py`

| Fixture | Requirement |
|---------|-------------|
| `e2e_env` | **Filesystem:** `tmp_path` subdirs `books`, `library`, `config` (`tests/e2e/conftest.py:45-50`). **Layout:** `e2e_layout` marker → `fixtures_fs.layout_{name}` (`:52-55`). **Env dict** passed to server (`:57-68`): `BOOKS_ROOT`, `AUDIOBOOKS_ROOT`, `STAGING_CONFIG_ROOT`, `STAGER_METADATA_BACKEND=fixture`, rate-limit env zeros/high caps, fixture API keys/ids, `METADATA_CONTACT_EMAIL`. Optional `STAGER_FIXTURE_LOOKUP_DELAY_MS` from `e2e_fixture_delay_ms` (`:69-71`). |
| `stager_server` | **Process:** `uvicorn app.main:app` on ephemeral `127.0.0.1` port (`:82-112`). **Env:** merges `e2e_env["env"]` into `os.environ` (`:85-86`), sets `PYTHONPATH` to repo root (`:88-92`). **Health:** polls `/api/health` via `httpx` (`:28-38`, `:114`). |
| `scanned_page` | **Browser:** pytest-playwright `page` fixture; runs `dismiss_bootstrap_and_scan`, reloads `/`, waits for books/conflicts/empty selectors (`:131-142`). |

### `tests/e2e/fixtures_fs.py`

- **Filesystem builders:** tagged silent MP3 seeds via mutagen (`write_tagged_audio`, `seed_book`, `library_book`).
- **Layouts:** `layout_smoke`, `layout_happy_scan`, `layout_conflict_pending`, `layout_conflict_staged`, `layout_merge_parts`, `layout_lvi` (`fixtures_fs.py:81-185`).

### External tooling

- **Browser:** Playwright `page` (plugin `pytest-playwright`; dependency `tests/requirements-e2e.txt:2-3`).
- **Network:** Server is local only; metadata backend forced to **fixture** in e2e env (`tests/e2e/conftest.py:61`), not live providers.

## Gaps (requested behaviors)

| Behavior | Status | Evidence |
|----------|--------|----------|
| **Migration replay on an old DB** | **Partially tested / gap for full replay** | `tests/test_chosen_pin_migrate.py` exercises `connect()` → `_repair_false_chosen_pins` on hand-built rows (`:71-118`) but no checked-in legacy DB or test that runs full `_migrate_schema` ALTER chain on a pre-pin-flag snapshot (`app/db.py:300-442`). No `*.db` fixtures in repo (glob). |
| **Pin flags: conflict approve vs merge approve vs normal approve** | **Untested (distinction)** | Production: normal approve `_commit_approve_book` updates `chosen_*` **without** `_set` columns (`app/api.py:1849-1856`); conflict/merge set all `_set=1` only when `has_overrides` (`app/api.py:1074-1082`, `1426-1433`). No unit test asserts `chosen_*_set` after `approve_book` / `approve_conflict` / merge approve without overrides (`tests/test_conflict_approve.py`, `tests/test_merge_groups.py`, `tests/test_bulk_approve.py` lack such asserts). |
| **Book-list path stays bounded (limit/pagination)** | **Untested** | API slices with `limit` default 500 (`app/api.py:876-877`, `907`, `916`). E2E `list_books` helper does not pass limit (`tests/e2e/helpers.py:89-91`). No test references `limit`/`offset` on `/api/books`. |
| **Scan cancel** | **Tested** | Unit: `tests/test_scan_cancel.py` (`test_cancel_marks_scan_cancelled`, API and index/discovery cancel). E2E: `tests/e2e/test_b_scan.py:36` `test_b_rescan_cancel_keeps_books_and_seeds`. |
| **Activity lock mutual exclusion** | **Untested (concurrent UX/API)** | Tests cover renew/expiry (`tests/test_activity_lock.py`) and auto-run gating (`tests/test_auto_manual_run.py`). No test for concurrent approve+scan or double-renew exclusion semantics beyond auto scheduler. |
| **Hardlink target stays under library root** | **Untested** | Guard exists: `_assert_target_under_library` (`stager_core/staging.py:649-655`, used at `:614`, `:670`). No test invokes it or asserts failure on escape paths. |
| **Fingerprint identity** | **Tested** | `tests/test_fingerprint.py` (`test_same_content_different_path_same_id`, `test_order_independence`, cache tests). `tests/test_discovery_parallel.py:22` parallels serial fingerprints. |

## Fixture providers vs network (unit suite)

**Observed switch (production):**

```python
if fixture_backend_enabled():
    self.providers = FixtureMetadataProviders()
    ...
else:
    self.providers = MetadataProviders(...)
```

(`stager_core/metadata/lookup.py:100-104`)

`fixture_backend_enabled()` is true when `STAGER_METADATA_BACKEND` equals `fixture` (`stager_core/metadata/fixture_providers.py:118-119`).

**Observed (e2e):** `STAGER_METADATA_BACKEND`: `"fixture"` in `e2e_env` (`tests/e2e/conftest.py:61`).

**Observed (unit):** Default `pytest` does **not** set `STAGER_METADATA_BACKEND` globally. Unit tests avoid network by:

- Injecting `FakeProviders` / `MetadataLookupService.__new__` with fake providers (`tests/test_title_first_production.py:51-53`, `tests/test_author_oeuvre.py:172-177`).
- `MetadataProviders` tests using `FakeClient`/`FakeCache` (`tests/test_providers_search.py`).
- Env gate tested in isolation (`tests/test_fixture_providers.py:33-46`).

**Inference:** A unit test that constructs `MetadataLookupService(conn)` without patching and without `STAGER_METADATA_BACKEND=fixture` would use real `MetadataProviders` and could attempt HTTP (`stager_core/metadata/lookup.py:104-111`). The suite as written largely avoids that constructor path or mocks it.

## Inference

- **E2E command:** `py -3 -m pytest -m e2e` (not written in README; follows marker in `pytest.ini:3`).
- **Playwright `page` fixture:** Provided by `pytest-playwright` when e2e tests run (no `pytest_plugins` line in repo; plugin discovery via installed package).
- **“Mutual exclusion” for activity lock:** Interpreted as cross-operation exclusion (approve vs auto-scan); only scheduler-side blocking is tested, not full API concurrency.

## Unknowns

| Topic | Why unknown | File to inspect |
|-------|-------------|-----------------|
| CI test commands | No `.github/` workflows found in repo | Future CI config or external pipeline |
| Official e2e invoke one-liner | README omits explicit `-m e2e` command | `README.md` (owner doc preference) |
| Whether any integration test hits live metadata APIs | Would require running full suite with network capture | Runtime observation / `tests/test_scan_progress.py` unsampled paths |

---

*Generated for rework documentation. Counts measured 2026-11-17 from workspace `tests/` tree.*