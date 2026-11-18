# UI workflows map (current static client)

**Source files (line counts measured 2026-11-17):**

| File | Lines |
|------|------:|
| `static/app.js` | 5951 |
| `static/style.css` | 2587 |
| `static/index.html` | 392 |

**Delivery:** one HTML document served at `/` (`app/main.py:80`), scripts `static/app.js`, styles `static/style.css`, API under `/api/*` (`app/api.py` router).

**Router:** **None observed.** No `location.hash`, `history.pushState`, or path-based client routing in `static/app.js` / `static/index.html`. Navigation is a single scrollable main page plus native `<dialog>` modals (`#detailDialog`, `#settingsDialog`, `#confirmDialog`, `#conflictDialog`) and the full-screen `#bootstrapScrim`.

---

## Observed behavior

### Page layout (`static/index.html`)

| Region | DOM id / class | Role |
|--------|----------------|------|
| Toolbar | `#scanBtn`, `#settingsBtn` | Manual scan; auto-stage / metadata settings |
| Stats | `#stats` | Status chips from `GET /api/books` → `stats` |
| While you were away | `#awaySection` | Auto-staged since last visit |
| Conflicts | `#conflictsSection` | Target collisions + merge groups (unified list) |
| Partial staged | `#partialSection` | `partial_staged` books |
| Staging | `#stagingSection` | Filter (`#statusFilter`), search (`#searchBox`), sort, bulk approve |
| Bootstrap scrim | `#bootstrapScrim` | Loading, pre-scan providers, scan progress canvas |
| Staging scrim | `#stagingScrim` | Blocks UI during approve / revert / merge |
| Mobile bulk | `#mobileBulkBar` | Mirror of staging bulk on small viewports |

Section headers collapse; state persisted (see localStorage).

---

### Session bootstrap

**Operator:** opens `/`; sees loading scrim, then one of: pre-scan modal, active scan/auto scrim, or home lists.

**Functions:** `bootstrapApp`, `handleBootstrapStatus`, `returnToPreScanIfNeeded`, `completeBootstrapHome`, `finishBootstrapIdle`, `resumeRunningScan`, `resumeRunningAuto`, `showBootstrapPreScanModal`, `showBootstrapScrim`, `hideBootstrapScrim` (`static/app.js:5818–5950`, `5739–5882`, `4964–4976`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/session/status` | Initial load (`5895`); stale pre-scan check (`5741`) |
| GET | `/api/scan/running` | Resume manual scan (`4967`) |
| GET | `/api/auto/running` | Resume auto run (`4472`, `4402`) |
| GET | `/api/scan/{scan_id}` | Attached scan during bootstrap auto phase (`4408`) |

**Session states used:** `no_scan`, `stale_scan`, `scan_running`, `auto_running`, else → `completeBootstrapHome` (`5849–5882`).

**Away reload prompt:** `visibilitychange` → if hidden ≥ `AWAY_TIMEOUT_MS` (15 min) and no scan/auto running, scrim offers Reload (`5922–5940`) → full `location.reload()`.

**E2E:** `tests/e2e/test_a_smoke.py` (page + empty staging after scan helper); `tests/e2e/helpers.py:dismiss_bootstrap_and_scan` drives provider scrim → Start Scan (used by most fixtures).

---

### Scan (manual)

**Operator:** `#scanBtn` → pre-scan scrim (providers) → Start Scan → stack viz; Cancel during run; sections blocked until complete/cancel.

**Functions:** `startScan` → `openScanModal` → `showBootstrapPreScanModal` / `beginScan` → `attachToScan` → `pollScan`; `cancelActiveScan`; `scanProgressAnimator` (drip UI between polls); `loadMetadataProviders`, `testMetadataProviders`, `loadAndTestMetadataProviders`, `renderProviderList` (`969–973`, `954–967`, `878–899`, `4885–4962`, `901–919`, `271–449`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/metadata/providers` | Pre-scan panel (`879`) |
| POST | `/api/metadata/providers/test` | Provider probe (`885`) |
| POST | `/api/scan` | Start (`4990`) |
| GET | `/api/scan/{scan_id}` | Poll while `currentScanId` set (`4901`) |
| POST | `/api/scan/{scan_id}/cancel` | Cancel (`908`) |
| GET | `/api/books?...` | Every successful scan poll (`4906` via `loadBooks`) |

**409 handling:** auto run in progress → `attachToAutoRun`; scan already running → `attachToScan` (`4993–5006`).

**E2E:** `tests/e2e/test_b_scan.py` (`test_b_scan_populates_staging`, `test_b_rescan_cancel_keeps_books_and_seeds`); bootstrap path in `test_h_lvi.py` (rescan).

---

### Auto-stage (scheduled / run now)

**Operator:** Settings → enable interval, min confidence, lock timeout, run now; during run, main sections blocked and bootstrap scrim may show; cancel from scrim.

**Functions:** `openSettingsDialog`, `saveSettings`, `runAutoNow`, `attachToAutoRun`, `pollAutoRun`, `cancelActiveAutoRun`, `applyAutoStatus`, `refreshAutoSettingsSummary` (`4714–4772`, `4386–4468`, `931–943`, `4669–4712`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/auto/settings` | Settings dialog + post-auto (`4670`, `4434`) |
| PATCH | `/api/auto/settings` | Save settings (`4751`) |
| POST | `/api/auto/run` | Run now (`4768`) |
| GET | `/api/auto/running` | Poll (`4402`) |
| POST | `/api/auto/{run_id}/cancel` | Cancel (`936`) |
| POST | `/api/auto/cache/clear` | Clear metadata cache (`4784`) |
| GET | `/api/scan/{scan_id}` | When auto phase is `scanning` (`4408`) |

**E2E:** **None** dedicated to settings UI or auto-run scrim (would need `app/auto.py` + API-only tests).

---

### Staging list (toolbar + bulk)

**Operator:** Filter pending / staged / skipped; search; sort by path, metadata, confidence (desktop headers + mobile `#stagingSortSelect`); row actions; select-all + bulk button (label changes per filter).

**Functions:** `loadBooks`, `renderBooksPayload`, `renderBooks`, `renderBookItem`, `sortStagingBooks`, `handleBookAction`, `runStagingBulkAction`, `wireStagingSortControls`, `wireStagingListControls`, `updateStagingBulkBtn`, `optimisticSkipRow` (`4788–4801`, `4178–4235`, `2744+`, `5212–5335`, `1970+`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/books?partitioned=true&status={pending\|staged\|skipped}&q={optional}` | List refresh (`4791–4795`) |
| POST | `/api/books/{id}/approve` | Row approve (`5221`) |
| POST | `/api/books/{id}/skip` | Row skip (`5236`) |
| POST | `/api/books/{id}/unskip` | Row unskip (`5247`) |
| POST | `/api/books/{id}/revert` | Unstage (`5266`) |
| POST | `/api/books/bulk-approve` | Bulk pending (`5302`) |
| POST | `/api/books/bulk-unskip` | Bulk skipped (`5310`) |
| POST | `/api/books/bulk-revert` | Bulk staged (`5318`) |

**Query params sent by UI (`4791–4795`):** `partitioned=true`, `status`, optional `q`. **Not sent:** `limit`, `offset`, `section`, `low_confidence`.

**Server note:** with `partitioned=true`, `staging` array is sliced `staging[offset:offset+limit]` default `limit=500`, `offset=0` (`app/api.py:869–908`). UI never passes `limit`/`offset`.

**E2E:** `tests/e2e/test_c_approve.py` (approve, unstage, skip/unskip, bulk); `tests/e2e/test_k_toolbar.py` (search, sort, filter).

---

### Book detail (modal)

**Operator:** Detail → edit author/title/series/#, live target preview, save, per-field revert, apply lookup candidate, re-lookup, duration load, partial actions if applicable.

**Functions:** `showDetail`, `renderDetailContent`, `saveBookMetadata`, `revertMetadataFields`, `refreshDetailTargetPreview`, `wireDetailMetadataPreview`, `wireDetailMetadataRevert`, `renderDetailCandidates`, `attachDetailStagingActions`, `runCompletePartial`, `runRemoveExtras`, `loadBookDuration` (`5018–5112`, `4803–4862`, `1594–1688`, `1627–1658`, `3234–3245`, `5114–5209`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/books/{book_id}` | Open detail (`5021`) |
| PATCH | `/api/books/{book_id}` | Save chosen metadata / revert (`4828`, `1596`) |
| POST | `/api/books/{book_id}/target-key-preview` | Typing preview (`1630`) |
| POST | `/api/books/{book_id}/lookup` | Re-lookup (`5443`) |
| GET | `/api/books/{book_id}/duration` | On demand (`2464`, `2490`) |
| POST | `/api/books/{book_id}/complete-partial` | Link missing (`5124`) |
| POST | `/api/books/{book_id}/remove-extras` | Delete extra library files (`5157`) |
| POST | `/api/books/{book_id}/revert` | Unstage from detail (`5196`) |

**Rendering:** `els.detailContent.innerHTML = ...` template (`5034`); file lists via `renderFileList` / `renderStagingFileList` (`2218–2270`).

**E2E:** `tests/e2e/test_h_lvi.py` opens detail for LVI chrome; no e2e focused on PATCH metadata / revert / lookup alone.

---

### Metadata “pins” (chosen fields + candidates)

There is **no separate “pin” API** in the UI. Operator “pins” metadata by setting **chosen_*** fields (manual mode) via save, or by **Apply** on a lookup candidate.

**Functions:** `METADATA_EDIT_FIELDS`, `saveBookMetadata`, `renderMetadataModeBadge`, `renderMetadataRevertBtn`, `revertMetadataFields`, candidate **Apply** handlers in detail (`5078–5103`) and conflict dialog (`5516–5541`).

**API:** same as detail PATCH with body `{ chosen_author, chosen_title, chosen_series, chosen_series_index }` (`4820–4830`); PATCH revert `{ revert_fields }` or `{ revert_all: true }` (`1595–1598`).

**E2E:** Conflict candidate/edit paths partially in `tests/e2e/test_e_conflicts.py`; detail pin/revert **not** locked in e2e.

---

### Approve / skip / revert (staging + away)

Covered above for staging list. **Away** revert uses same `POST /api/books/{id}/revert` (`1164`).

**Confirm dialogs** with optional “Don’t show again” → `stager.confirmSkip.*` localStorage (`982–998`, `1235–1265`).

**E2E:** `test_c_*`; away revert **no** e2e.

---

### Conflicts (select winner)

**Operator:** Conflicts section → Resolve → `#conflictDialog` Select tab: pick library vs seed radio, edit seed metadata, save per-side or Save all, skip seed, next conflict, Select (approve).

**Functions:** `renderUnifiedConflicts`, `openResolvePanel`, `renderResolvePanelContent`, `renderConflictSideCard`, `approveConflict`, `saveAllConflictEdits`, `reconcileConflictSession`, `advanceToNextConflict`, `fetchConflictGroup` (`3140–3177`, `3851–3900`, `3970–4014`, `4080–4176`, `4016–4024`).

**Data source:** conflict groups embedded in `GET /api/books` partitioned payload (`4181–4182`); detail fetch `GET /api/conflicts/{target_key}` (`4018`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/conflicts/{target_key}` | Open / refresh group (`4018`) |
| POST | `/api/conflicts/{target_key}/save-edits` | Save all seed edits (`4148–4161`) |
| POST | `/api/conflicts/{target_key}/approve` | Winner staged (`4135`) |
| PATCH + POST approve | `/api/books/{winner}` | Fallback when group dissolved (`4099–4109`) |
| POST | `/api/books/{id}/skip` | Skip seed in dialog (`5550`) |
| GET | `/api/conflicts/{target_key}/duration` | Side duration (`2470`) |

**E2E:** `tests/e2e/test_e_conflicts.py` (winner pick, edit+save dissolves conflict, keep library).

---

### Merges (combine parts)

**Operator:** Same dialog, Merge tab when group is merge-eligible: select members, edit merged metadata, staged filename overrides, preview accordion, Merge & stage.

**Functions:** `getMergeEndpoints`, `loadMergePreview`, `refreshMergePreview`, `approveMerge`, `wireMergePanelInteractions`, sessionStorage drafts (`2838–2927`, `3570–3578`, `3931–3968`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/merges/{target_key}` | Fetch merge group (`3563`) |
| POST | `/api/merges/{target_key}/preview` or `/api/conflicts/{target_key}/merge/preview` | Preview (`3576–3578`, `3171–3183`) |
| POST | `/api/merges/{target_key}` or `.../merge` | Approve merge (`3951`) |

**UI does not call** `DELETE /api/merges/{primary_book_id}` (`app/api.py:1553`) — unmerge not exposed in client.

**E2E:** `tests/e2e/test_f_merge.py`.

---

### Partial stage

**Operator:** Partial section rows; Detail shows staging file matrix, complete partial, remove extras, unstage.

**Functions:** `renderPartialItem`, `renderPartialStagingBlock`, `runCompletePartial`, `runRemoveExtras` (partial list in `renderBooks` `4230–4233`).

**API:** `POST .../complete-partial`, `POST .../remove-extras`; list from partitioned `partial` array (no separate GET).

**E2E:** **None** in `tests/e2e/` (behavior may be covered in `tests/test_partial_staging.py` unit/API).

---

### While you were away (auto review)

**Operator:** Review auto-staged items; Okay / Okay all / Revert / Detail.

**Functions:** `loadAwayReview`, `renderAwaySection`, `awayListClickHandler` (`4298–4305`, `4268–4296`, `1135–1172`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/auto/review` | Load list (`4300`) |
| POST | `/api/auto/review/dismiss` | `{ action_ids: [...] }` or `{ dismiss_all: true }` (`1145`, `5395`) |

Loaded on `completeBootstrapHome` (`5827`); not refreshed on every `loadBooks`.

**E2E:** **None**.

---

### Provider status (bootstrap)

**Operator:** Before first scan, sees provider chips with ok/error/missing-key/pending states; no settings-page provider UI.

**Functions:** `showBootstrapProvidersPanel`, `renderProviderList`, `providerStatusClass` (`946–952`, `858–876`, `849–856`).

**API:** `GET /api/metadata/providers`, `POST /api/metadata/providers/test`.

**E2E:** Implicit in `dismiss_bootstrap_and_scan` (expects Start Scan visible, does not assert chip states).

---

### Settings

**Operator:** `#settingsDialog` tabs General (auto-stage, finish-scan animation) and Metadata (scan manual hints, LVI toggles, title extraction mode, advanced cleanup table, preview table).

**Functions:** `openSettingsDialog`, `saveSettings`, `populateSettingsForm`, `buildTitleCleanupStepsTable`, `refreshTitleExtractionPreview`, `clearMetadataCache` (`4714–4786`, `4524–4667`).

**API:**

| Method | Path | When |
|--------|------|------|
| GET | `/api/auto/settings` | Load (`4670`) |
| PATCH | `/api/auto/settings` | Save (`4751`) |
| POST | `/api/settings/title-extraction/preview` | Advanced preview, `limit: 10` in body (`4658`) |
| POST | `/api/auto/cache/clear` | Clear cache (`4784`) |

Finish-scan animation preference stored in **localStorage** on save (`4750`), not only server.

**E2E:** **None**.

---

### Polling summary

| Timer | Interval | Endpoint(s) | Start | Stop |
|-------|----------|-------------|-------|------|
| `pollScan` | **1500 ms** (`SCAN_POLL_MS` `32`) | `GET /api/scan/{id}`; each tick also `loadBooks` | `attachToScan` (`4895`) | Scan not `running` (`4907–4913`); on error retry **3000 ms** (`4947`) |
| `pollAutoRun` | **1500 ms** (`4425`) | `GET /api/auto/running`; optional `GET /api/scan/{scan_id}`; `loadBooks` | `attachToAutoRun` (`4394`) | Run not `running` (`4428+`) |
| `scanProgressAnimator` drip | `max(16ms, floor(1500/behind))` (`384`) | N/A (local between polls) | `onPoll` during bootstrap scan | `reset` / scan complete |
| Finish animation tail | **1500 ms** once (`431`) | N/A | Scan completed + animation on | Before `completeBootstrapHome` |
| Search debounce | **250 ms** (`5413`) | `GET /api/books?...` | `#searchBox` input | — |
| Target key preview debounce | **300 ms** (`1649`) | `POST .../target-key-preview` | Detail field input | — |

**Observed:** scan progress polling is **1.5 s**, confirming the suspected interval (`static/app.js:32`, `4908`, `4425`).

---

### List rendering

| List | Mechanism | Container |
|------|-----------|-----------|
| Staging rows | `innerHTML` = `map(renderBookItem).join()` | `#booksList` (`4225–4227`) |
| Partial rows | `innerHTML` | `#partialList` (`4231–4233`) |
| Conflicts | `innerHTML` | `#conflictsList` (`3164`) |
| Away | `innerHTML` | `#awayList` (`4294`) |
| Stats chips | `innerHTML` | `#stats` (`2506`) |
| Providers | `innerHTML` | `#bootstrapProviderList` (`861`) |
| Detail / conflict bodies | `innerHTML` large templates | `#detailContent`, `#conflictDialogContent` |
| Settings title cleanup / preview | `createElement` + `appendChild` / `replaceChildren` | `#titleCleanupStepsBody`, `#titleExtractionPreviewBody` (`4529+`, `4626+`) |
| Section shells while blocked | `innerHTML` placeholder paragraphs | `restoreSectionShells` (`1042+`) |

**Selection state:** in-memory `selectionByFilter` per status filter (`40–44`), not persisted.

---

### localStorage keys

| Key pattern | Stores |
|-------------|--------|
| `audiobook-stager.stagingSort` | JSON `{ key, dir }` for staging sort (`20`, `1978–1989`) |
| `audiobook-stager.finishScanAnimation` | `"true"` / `"false"` — keep scan scrim one poll after complete (`34`, `286–296`, settings checkbox sync `4695–4697`) |
| `stager.confirmSkip.{preferenceKey}` | `"1"` if user checked “Don’t show again” on confirm dialog (`975–995`). Keys include: `away-revert`, `merge-selection-change`, `conflict-approve-library`, `clear-metadata-cache`, `partial-remove-extras`, `staging-unstage`, `staging-unstage-bulk` |
| `stager.sectionCollapsed.{sectionId}` | `"1"` when section collapsed (`976`, `5661–5677`). Section ids: `awaySection`, `conflictsSection`, `partialSection`, `stagingSection` |

---

### sessionStorage keys (merge conflict UI only)

| Key pattern | Stores |
|-------------|--------|
| `audiobook-stager.mergeDraft.{targetKey}` | JSON array of selected member book ids (`17`, `2838–2858`) |
| `audiobook-stager.mergeStagedNames.{targetKey}` | JSON map of staged filename overrides (`18`, `2865–2891`) |
| `audiobook-stager.mergeSortMode.{targetKey}` | String sort mode for merge file list (`19`, `2904–2927`) |

---

## Parity checklist

Later UI should match current behavior (evidence-backed):

- [ ] Single-page layout: four stacked sections (away, conflicts, partial, staging) plus toolbar stats and scrims (`static/index.html`).
- [ ] Bootstrap via `GET /api/session/status` branching into pre-scan, resume scan/auto, or load lists (`5888–5896`).
- [ ] Pre-scan flow: load/test metadata providers, Start Scan → `POST /api/scan`, block sections during scan (`954–967`, `4885–4895`).
- [ ] Scan poll **1500 ms** on `GET /api/scan/{id}` + refresh books each tick (`4901–4908`).
- [ ] Optional finish-scan animation: extra **1500 ms** tail after completed scan (`425–431`, settings `settingsFinishScanAnimation`).
- [ ] Manual scan cancel → `POST /api/scan/{id}/cancel`; resync poll (`901–919`).
- [ ] Auto-run: settings PATCH/GET, run now POST, poll `GET /api/auto/running` at **1500 ms**, cancel POST (`4386–4468`).
- [ ] `GET /api/books?partitioned=true&status=&q=` drives staging, partial, conflicts, merges, stats; **no client limit/offset** (`4788–4795`, `app/api.py:894–908`).
- [ ] Staging filter pending/staged/skipped; server-side search `q`; client sort on current staging slice (`1970+`, `5411–5414`).
- [ ] Row actions: detail, approve, skip, unskip, unstage with staging scrim / confirm patterns (`5212–5271`).
- [ ] Bulk actions per filter: approve selected, unskip selected, unstage selected with bulk API endpoints (`5277–5334`).
- [ ] Detail modal: PATCH chosen metadata, target-key preview, revert fields, lookup POST, duration lazy load (`5018–5467`).
- [ ] Conflicts list unified conflicts+merges; resolve dialog Select vs Merge tabs (`3140–3164`, `3813–3848`).
- [ ] Conflict approve: `POST /api/conflicts/.../approve` or library/seed flows with replace-library confirm (`4080–4141`).
- [ ] Merge: preview POST, approve POST with member ids + staged_names (`3931–3967`).
- [ ] Partial: complete-partial and remove-extras from detail (`5114–5168`).
- [ ] Away review: `GET /api/auto/review`, dismiss single/all, revert with confirm (`4298–4305`, `1135–1172`).
- [ ] 15-minute tab-away reload prompt when idle (`5922–5940`).
- [ ] Confirm-dialog “don’t show again” persistence keys (`982–998`).
- [ ] Section collapse persistence per section id (`5654–5677`).

---

## Unbounded lists

These UIs render **all items returned** in one HTML string (no virtualisation, no client pagination):

| Group | What grows | Render site | Server bound |
|-------|------------|-------------|--------------|
| Staging list | Books in current filter | `#booksList` `innerHTML` | **Capped:** default `limit=500` on `staging` only (`app/api.py:907`); UI does not send `limit` |
| Partial list | All `partial_staged` matching `q` | `#partialList` | **Unbounded** in partitioned response (full `partial` array) |
| Conflicts list | All conflict + merge groups | `#conflictsList` | **Unbounded** (`conflicts`, `merges` arrays in same response) |
| Away list | All pending auto-review actions | `#awayList` | **Unbounded** (`GET /api/auto/review` — see `app/api.py:2467+`) |
| Detail: source files | `book.files` | `renderFileList` in template | Per book |
| Detail: candidates | `book.candidates` | `renderDetailCandidates` | Per book |
| Conflict dialog | Sides, files per side, candidates | `renderConflictSideCard` etc. | Per group |
| Merge dialog | Members, staged file rows | merge panel templates | Per group |
| Stats chips | One per status key | `#stats` | Small fixed set |
| Provider chips | Provider count | `#bootstrapProviderList` | Small fixed set |

**Fetch evidence for books list:**

```4788:4795:static/app.js
async function loadBooks() {
  const status = getActiveFilter();
  const q = els.searchBox.value.trim();
  const params = new URLSearchParams({ partitioned: "true", status });
  if (q) params.set("q", q);

  try {
    const data = await api(`/api/books?${params.toString()}`);
```

Conflict/merge **list** data: same `loadBooks` response — UI does **not** call `GET /api/conflicts` or `GET /api/merges` for the section list.

---

## Inference (labeled)

- **Inference:** With >500 books in one staging filter, rows beyond 500 never appear until server default changes or UI sends `offset`/`limit` — UI has no “load more” (`app/api.py:876–907`, `static/app.js:4791–4795`).
- **Inference:** “Pins” in product language map to **chosen_*** manual metadata and candidate Apply, not a distinct REST resource (`docs/pinning-model.md` not read for this doc).
- **Inference:** Scheduled auto-stage runs without operator opening settings; UI only reflects state via bootstrap and `pollAutoRun` (`4327–4344`).
- **Inference:** Activity lock (server) renews on mutations mentioned in settings copy (`static/index.html:263–264`); exact renew sites are server-side beyond this UI pass.

---

## Tests that lock this

| Workflow | Playwright file |
|----------|-----------------|
| Page load, empty staging, bootstrap scan helper | `tests/e2e/test_a_smoke.py` |
| Scan populates list; cancel rescan retains books | `tests/e2e/test_b_scan.py` |
| Approve, unstage, skip/unskip, bulk approve | `tests/e2e/test_c_approve.py` |
| Conflict winner, edit dissolves, keep library side | `tests/e2e/test_e_conflicts.py` |
| Merge parts dialog | `tests/e2e/test_f_merge.py` |
| LVI gold chrome on detail after stage+rescan | `tests/e2e/test_h_lvi.py` |
| Toolbar search, sort, filter | `tests/e2e/test_k_toolbar.py` |

**Gaps (no e2e in `tests/e2e/`):** partial staging UI, away review, settings/auto-stage dialog, provider chip states, detail metadata PATCH/revert/lookup, auto-run cancel, away reload scrim, bulk unstage/unskip.

---

## Single-operator assumptions

- One human uses one browser tab; `selectionByFilter` and dialog state are global in `app.js` (`7–44`).
- Settings copy states scheduled auto-stage is skipped while the stager is **actively in use**, with lock renewed on approve, skip, edit, scan, etc. (`static/index.html:263–264`) — implies single concurrent operator session, not multi-user UI.
- `POST /api/scan` conflicts with running auto-run (`4993–5000`); one scan or auto pipeline at a time from the client perspective.
- Away reload suggests operator may leave one tab open for >15 minutes and expect a full reload for fresh data (`5922–5940`).
- No auth UI; server treated as trusted local operator (`fetch` without credentials in `api()` `1268–1293`).

---

## Unknowns

| Topic | Why unknown | File to confirm |
|-------|-------------|-----------------|
| Max size of `GET /api/auto/review` items list | Did not trace handler pagination | `app/api.py` near `2467` |
| Whether `staging` 500 cap is hit in real libraries | No production metrics | Operator / DB |
| Unmerge/admin flows | No UI call to DELETE merges | `app/api.py:1553` |
| `GET /api/auto/feedback` usage | Not referenced in `static/app.js` | `app/api.py:2547` |
| Partial-stage e2e coverage | No playwright file | `tests/test_partial_staging.py` |
| Exact activity-lock renew list from UI actions | Only settings note cited | `app/activity_lock.py`, API handlers |