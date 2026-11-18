# Metadata pipeline (as implemented)

Descriptive map for the Audiobook Stager rework. No redesign proposals.

---

## Call order: audio tags → suggestion

**Observed behavior** — entry from scan / re-lookup:

| Step | Function(s) | Location |
|------|-------------|----------|
| 1. Serialize lookup | `MetadataLookupService.resolve_book` → `_resolve_book_locked` under `threading.Lock` | `stager_core/metadata/lookup.py:140-149` |
| 2. Read tags | `read_book_tags` → per-file `read_tags` (mutagen) | `stager_core/metadata/tags.py:121-139`, `84-118` |
| 3. Search context | `build_search_context` | `stager_core/metadata/query.py:9-63` |
| 4. LVI match (pre-search) | `resolve_lvi_match` → `apply_lvi_search` | `stager_core/metadata/lvi.py:304-373`, `lookup.py:258-259` |
| 5. Title for queries | Pinned manual title **or** `extract_title` → `normalize_title` | `lookup.py:261-266`, `title_extraction.py:117-131` |
| 6. Author for queries | `normalize_author(context["author"])` | `lookup.py:267` |
| 7. Provider passes (order) | ASIN: `audnexus_book`; title-first: `title_first_candidates`; combined: `_external_candidates`; oeuvre: `author_oeuvre_candidate`; local: `_local_candidates` | `lookup.py:271-279` |
| 8. Filter | Drop `audnexus_author`, empty titles | `lookup.py:281` |
| 9. LVI on candidates | `annotate_candidates_lvi` | `lookup.py:283`, `lvi.py:376-398` |
| 10. Book-level scoring | `Evidence` + `pick_winner` + `annotate_candidates` | `lookup.py:285-299`, `scoring.py:329+` |
| 11. Suggested author/title | Winner or `book.flatten_name` fallback | `lookup.py:301-312` |
| 12. Series | `pick_series_votes_from_cluster`, `id3_series_vote`, `lvi_series_vote`, `pick_series`, `annotate_series_membership`, `fold_staging_confidence` | `lookup.py:314-326`, `series_scoring.py` |
| 13. Series fallback | `primary_candidate_series_from_candidates` if pick_series empty | `lookup.py:344-349`, `effective.py:22-47` |
| 14. Sort candidates | LVI tier + cluster/medoid keys | `lookup.py:336-342` |
| 15. Persist (scan) | `suggested_*`, `candidates_json`, `lvi_match_json`, etc. | `app/scan.py:655-780` |

**Observed behavior** — `_external_candidates` provider loop (combined title+author only, sequential):

1. `MetadataProviders.audible_search`
2. `MetadataProviders.mam_search`
3. `MetadataProviders.google_books_search`
4. `MetadataProviders.openlibrary_search`

`stager_core/metadata/lookup.py:210-220`

**Observed behavior** — `title_first_candidates` runs four title-only wrappers in order: Audible, MAM, Open Library, Google Books (`stager_core/metadata/title_first.py:24-29`).

**Observed behavior** — `AudibleSearch` often chains `audnexus_book(asin)` after catalog hit (`stager_core/metadata/providers.py:342-348`).

**Observed behavior** — `author_oeuvre_candidate` pools `audible_author_catalog` then `mam_search("", author)` (`stager_core/metadata/author_oeuvre.py:68-71`).

**Observed behavior** — `pick_suggestion` exists for UI/history use; scan path uses `resolution.suggested_*` from `pick_winner`, not `pick_suggestion` (`stager_core/metadata/lookup.py:413-420`).

**Inference** — Title cleanup runs inside `extract_title` (conservative/balanced/advanced) before provider queries; provider responses use `normalize_title` / `provider_text` in `MetadataProviders`, not the full fuzzy-subset pipeline.

---

## Providers and configuration

| Provider ID | HTTP / role | Credential / key | Env var(s) | Lookup skips when unset? |
|-------------|-------------|-------------------|------------|---------------------------|
| **audnexus** | `GET api.audnex.us/books/{asin}`; optional `authors` verify API exists but **not** called from `resolve_book` | No API key | `AUDNEXUS_REGION` (default `us`, `lookup.py:107`); rate: `AUDNEXUS_MIN_INTERVAL_MS` (`lookup.py:85`) | No — runs when `context["asin"]` non-empty (`lookup.py:271-272`) |
| **audible** | `GET api.audible.com/1.0/catalog/products` (+ author catalog for oeuvre) | No key | Rate: default via `RateLimitedClient` (`audible_min_ms` default 1000, `ratelimit.py:53-54`; not overridden in `lookup.py`) | No — empty title+author returns `[]` (`providers.py:318-319`) |
| **openlibrary** | `GET openlibrary.org/search.json` | No key | Rate: `OPENLIBRARY_MIN_INTERVAL_MS` (`lookup.py:86`) | No — empty title+author returns `[]` (`providers.py:658-659`). **`METADATA_CONTACT_EMAIL` does not gate OL** — only built into User-Agent (`lookup.py:82-88`; OL requests unchanged in `providers.py:652-685`) |
| **google_books** | `GET googleapis.com/books/v1/volumes` | API key | `GOOGLE_BOOKS_API_KEY` (`lookup.py:108`) | **Yes** — `if not self.google_api_key: return []` (`providers.py:718-720`) |
| **mam** (MyAnonaMouse) | `POST myanonamouse.net/.../loadSearchJSONbasic.php` | Session cookie (`mam_id`) | `STAGER_MAM_ID` (registry label); resolution: `resolve_mam_id()` also reads cookie file paths, `MAM_ID`, `MAM_COOKIE_FILE`, `CONFIG_ROOT` (`providers.py:117-161`, `provider_registry.py:11`) | **Yes** — `if not self.mam_id: return []` (`providers.py:490-492`) |
| **Fixture backend** | No network | N/A | `STAGER_METADATA_BACKEND=fixture`, optional `STAGER_METADATA_FIXTURES`, `STAGER_FIXTURE_LOOKUP_DELAY_MS` | Replaces `MetadataProviders` entirely (`lookup.py:100-101`, `fixture_providers.py:118-119`) |

**Observed behavior** — `provider_registry.list_provider_status` marks Google/MAM `enabled=false` when env/cookie missing (`provider_registry.py:29-45`). That status is **informational**; lookup uses inline guards in `MetadataProviders`, not `list_provider_status`.

**Observed behavior** — `provider_registry` probe skips Google/MAM without credentials (`provider_registry.py:53-59`); live providers use `MetadataProviders.probe_connectivity` (`providers.py:849-913`).

**Observed behavior** — Local candidate sources (not registry entries): `id3` (`tag_candidate`), `folder`, `filename` (`lookup.py:151-186`). Scoring families also include `author_oeuvre`, `title_first`, `library` (LVI corroboration).

**Inference** — `mam_exact` appears in `FAMILY_PRIORS` (`scoring.py:39`) but **no producer** found in repo grep beyond tests; treat as reserved/Phase 2 (unknown producer — would need wider `stager_core/` search for infohash wiring).

---

## Fixture providers and `provider_registry.py`

**Observed behavior** — When `STAGER_METADATA_BACKEND=fixture`, `MetadataLookupService` uses `FixtureMetadataProviders` (`lookup.py:95-101`). Methods mirror live providers; matches catalog JSON by normalized title/author (`fixture_providers.py:138-220`).

**Observed behavior** — Unit tests inject `FakeCache` + `FakeClient` into `MetadataProviders` (`tests/test_providers_search.py:9-40`) or patch `resolve_book` (`tests/test_scan_progress.py`).

**Observed behavior** — E2E sets fixture backend in `tests/e2e/conftest.py` (env `STAGER_METADATA_BACKEND`, `METADATA_CONTACT_EMAIL` for UA only).

---

## Failure caching (`ApiCache` + provider TTLs)

**Observed behavior** — SQLite table `api_cache` via `ApiCache.get` / `put` / `put_permanent` (`stager_core/metadata/cache.py:13-63`). Expired rows ignored (`cache.py:31-32`).

**Observed behavior** — Success: mostly `put_permanent` (no expiry).

**Observed behavior** — Failure / throttle caching:

| Provider | Condition | TTL / behavior |
|----------|-----------|----------------|
| audnexus | 429 | 60s (`providers.py:274-275`) |
| audnexus | 404 | 7d (`providers.py:276-277`) |
| audible | 429 | 300s (`providers.py:339-340`, `379-380`) |
| mam | 200 | 86400s (`providers.py:519`) |
| mam | 429 | 300s (`providers.py:523-525`) |
| mam | cached non-200 | Returns `[]`, no retry (`providers.py:506-511`) |
| openlibrary | 429 | 60s (`providers.py:681-682`) |
| openlibrary | 404 | 7d (`providers.py:683-684`) |
| google_books | 429 | 3600s (`providers.py:748-749`) |

**Observed behavior** — On cache hit with non-200, several search methods return `[]` without HTTP (e.g. openlibrary `providers.py:670-674`, google `733-737`).

---

## Rate limiter and lookup lock

**Observed behavior** — All provider HTTP goes through `RateLimitedClient.request_json`: per-provider min interval, 429 backoff, MAM leaky bucket (`MAM_REQUESTS_PER_MINUTE`, `lookup.py:87`, `ratelimit.py:46-218`).

**Observed behavior** — `MetadataLookupService._lock`: one in-flight `resolve_book` per service instance (`lookup.py:116-117`, `148-149`).

**Observed behavior** — Within a single lookup, provider calls are **sequential** (loops in `_external_candidates`, `title_first`, oeuvre catalog, plus nested audnexus after audible). No parallel provider HTTP in `lookup.py`.

**Observed behavior** — Separate from metadata: `DB_LOCK` in `app/scan.py` / `app/api.py` for SQLite writes (not serializing HTTP).

**Inference** — Multiple worker threads could each hold a `MetadataLookupService` with separate locks unless the app shares one instance (scan manager holds one service — `app/scan.py:206`).

---

## Pinning vs `docs/pinning-model.md`

**Observed behavior** — Model in `docs/pinning-model.md`: `suggested_*` = lookup winner; `chosen_*` + `chosen_*_set` = manual pin; `effective_*` = set ? chosen : suggested (`stager_core/metadata/effective.py:73-141`).

**Observed behavior** — Normal **Approve** / `_commit_approve_book`: copies effective values into `chosen_*` **without** setting `chosen_*_set` (`app/api.py:1851-1855`; pinning doc lines 22-24).

**Observed behavior** — **PATCH** book metadata: presence of `chosen_*` fields sets corresponding `_set = 1` (`app/api.py:1711-1724`).

**Observed behavior** — Scan re-lookup: `chosen_*` preserved when `_set = 1` via SQL `CASE` (`app/scan.py:715-729`); manual re-lookup updates **only** `suggested_*` and JSON blobs (`app/scan.py:927-934`).

**Observed behavior** — **Mismatch with pinning doc** (doc lines 24-25, 36-39):

| Path | Sets `chosen_*_set = 1`? | Citation |
|------|-------------------------|----------|
| `save_conflict_edits` | All four fields | `app/api.py:996-997` |
| `approve_conflict` when body overrides | All four | `app/api.py:1081-1082` |
| `approve_merge` / `_perform_merge` when `has_overrides` | All four | `app/api.py:1432-1433` |
| `approve_conflict` after stage (no override branch) | Does **not** set `_set` | `app/api.py:1110-1115` |
| Normal `approve_book` | Does **not** set `_set` | `app/api.py:1851-1855` |

**Observed behavior** — `_manual_hints_from_row` passes pinned **author/title only** into re-lookup when `_set` (`app/scan.py:48-57`); series pins are not in `ManualHints` from this helper (series fields exist on `ManualHints` type but unused here — `stager_core/metadata/types.py:7-11`).

**Observed behavior** — Auto-stage skips any book with any `chosen_*_set` (`stager_core/auto_eligibility.py:27-32`; pinning doc line 43).

**Observed behavior** — One-time `_repair_false_chosen_pins` on DB connect unpins when `chosen == suggested` (`app/db.py:469-493`).

---

## LVI (operator language)

**Observed behavior** — LVI built from **staged** books in DB (`build_lvi_from_db`, `lvi.py:136-144`). Excludes current book on lookup (`lvi_for_book`, `lvi.py:147-155`).

**What the operator sees** (UI wiring in `static/app.js`):

- Settings toggles **LVI search** and **LVI boost** (`static/app.js:4682-4683`, `4739-4740`) → `auto_settings.lvi_search` / `lvi_boost` → scan (`app/scan.py:401-402`, `648-652`).
- Detail: `lvi_form_match` chrome on author/series fields (`app/api.py:248-256`, `static/app.js:1537`, `1591`).
- Candidate list: `lvi_author_matched`, `lvi_series_matched`, `lvi_in_library` (`static/app.js:3215-3216`).

**What LVI changes when enabled**:

| Flag | Effect |
|------|--------|
| `lvi_search` | Replaces search `context["author"]` with LVI canonical author when hit; stores `lvi_resolved_series` (`lvi.py:369-373`) |
| `lvi_boost` | Adds `library_corroboration_evidence`; `lvi_series_vote`; sorts candidates with library tier first (`lookup.py:295-296`, `318-320`, `337-342`) |

**What LVI does not change**:

- Does not set `suggested_*` directly (winner still from `pick_winner`).
- Does not pin `chosen_*`.
- `annotate_candidates_lvi` only sets match flags/scores on candidates (`lvi.py:376-398`).

---

## Tests that lock this

| Area | Module(s) |
|------|-----------|
| Scoring / book winner | `tests/test_scoring.py` |
| Series scoring | `tests/test_series_scoring.py` |
| Title extraction / cleanup steps | `tests/test_title_extraction.py`, `tests/test_normalize.py` |
| Effective / pinning helpers | `tests/test_effective_metadata.py` |
| Author oeuvre | `tests/test_author_oeuvre.py` |
| Title-first pass | `tests/test_title_first_production.py`, `tests/test_search_passes.py` |
| Provider HTTP shapes | `tests/test_providers_search.py` |
| Fixture backend | `tests/test_fixture_providers.py` |
| Provider registry | `tests/test_provider_registry.py` |
| LVI lookup | `tests/test_lvi_lookup.py` |
| Scan manual hints | `tests/test_scan_manual_hints.py` |
| Conflict approve / pins | `tests/test_conflict_approve.py` |
| Approve staging metadata | `tests/test_approve_series_metadata.py` |
| Auto-stage eligibility | `tests/test_auto_eligibility.py` |
| Search context | `tests/test_search_context.py` |

---

## Single-operator assumptions

- One running Stager app with one `ScanManager` / `MetadataLookupService` instance sharing one rate limiter and lookup mutex (`app/scan.py:206`, `lookup.py:116-149`).
- One SQLite DB holds `api_cache` and book rows; concurrent scans use `DB_LOCK` for writes.
- Operator uses UI/API on that instance; no multi-tenant isolation in metadata code.

---

## Unknowns

| Topic | Status | Where to verify |
|-------|--------|-----------------|
| `mam_exact` evidence emission | No non-test producer found | `stager_core/metadata/scoring.py:39`; full-repo search for `mam_exact` |
| Whether series manual pins affect lookup hints on scan | `_manual_hints_from_row` omits series | `app/scan.py:48-57` vs `build_search_context` / oeuvre probes |
| Google Books `audible_min_ms` env exposure | Not passed from `lookup.py` | `ratelimit.py:52-54` |

---

## Heuristic piles that must not be retuned

Without updating characterization tests, do not change:

| Pile | Location | Tests |
|------|----------|-------|
| Book cluster thresholds, family priors, caps | `stager_core/metadata/scoring.py` CONFIG (`24-63`, `329+`) | `tests/test_scoring.py` |
| Series family priors, caps, pick logic | `stager_core/metadata/series_scoring.py` CONFIG (`35-56`) | `tests/test_series_scoring.py` |
| Title cleanup step order / advanced UI steps | `stager_core/metadata/cleanup_pipeline.py`, `title_cleanup.py` | `tests/test_title_extraction.py`, `tests/test_normalize.py` |
| Title extraction modes (conservative/balanced/advanced) | `stager_core/metadata/title_extraction.py` | `tests/test_title_extraction.py` |
| Author oeuvre disambiguation (title/series probe scoring) | `stager_core/metadata/author_oeuvre.py` | `tests/test_author_oeuvre.py` |
| Audible ASIN pick overlap weights | `providers.py:399-421` (`_overlap_score` 0.5 author term) | `tests/test_providers_search.py` (partial) |
| LVI match floors | `library_vocab.py` `DEFAULT_*_FLOOR` (used `lvi.py:309-310`) | `tests/test_lvi_lookup.py` |

---

*Document generated from repo state on branch rework exploration; paths relative to repository root.*