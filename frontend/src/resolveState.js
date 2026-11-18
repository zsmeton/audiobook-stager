import { computed, reactive, ref, watch } from "vue";

import { api } from "./api.js";
import { formatDuration } from "./staging.js";
import {
  GROUP_PAGE_SIZE,
  buildUnifiedGroups,
  canResolveMerge,
  canResolveSelect,
  clampOffset,
  clearMergeSession,
  defaultResolveMode,
  encodeTargetKey,
  invalidStagedNames,
  mergeEndpoints,
  mergeMembers,
  pageSlice,
  parseTargetKeyDisplay,
  readMergeDraft,
  readStagedNames,
  writeMergeDraft,
  writeStagedNames,
} from "./groups.js";

export function useResolve(shell, staging) {
  const offset = ref(0);
  const open = ref(false);
  const targetKey = ref("");
  const group = ref(null);
  const mode = ref("select");
  const winner = ref("");
  const busy = ref(false);
  const previewLoading = ref(false);
  const previewError = ref("");
  const preview = ref(null);
  const stagedRows = ref([]);
  const namesDirty = ref(false);
  const drafts = reactive({});
  const selected = reactive({});
  const mergeMeta = reactive({ author: "", title: "", series: "", seriesIndex: "" });

  const groups = computed(() =>
    buildUnifiedGroups(shell.libraryLists.value.conflicts, shell.libraryLists.value.merges),
  );
  const page = computed(() => pageSlice(groups.value, offset.value, GROUP_PAGE_SIZE));
  const pageGroups = computed(() => page.value.rows);
  const total = computed(() => groups.value.length);
  const canPrev = computed(() => offset.value > 0);
  const canNext = computed(() => offset.value + GROUP_PAGE_SIZE < total.value);
  const pageFrom = computed(() => (total.value ? offset.value + 1 : 0));
  const pageTo = computed(() => Math.min(offset.value + pageGroups.value.length, total.value));
  const showTabs = computed(() => canResolveSelect(group.value) && canResolveMerge(group.value));
  const canMerge = computed(() => {
    const count = Object.keys(selected).length;
    return count >= 2 && !previewLoading.value && !invalidStagedNames(stagedRows.value);
  });
  const mergeBlockedReason = computed(() => {
    if (Object.keys(selected).length < 2) return "Select at least two parts to merge";
    if (invalidStagedNames(stagedRows.value)) return "Fix duplicate or empty library filenames";
    return "";
  });
  const hasNext = computed(() => conflictKeys().length > 1);

  watch(total, (count) => {
    offset.value = clampOffset(offset.value, count, GROUP_PAGE_SIZE);
  });

  function conflictKeys() {
    return groups.value.filter((item) => canResolveSelect(item)).map((item) => item.target_key);
  }

  function findGroup(key) {
    return groups.value.find((item) => item.target_key === key) || null;
  }

  function resetDrafts(next) {
    for (const key of Object.keys(drafts)) delete drafts[key];
    Object.assign(drafts, next);
  }

  function resetSelected(ids) {
    for (const key of Object.keys(selected)) delete selected[key];
    for (const id of ids) selected[id] = true;
  }

  function seedDraftsFrom(current) {
    const next = {};
    for (const side of current.conflict?.sides || []) {
      if (side.type !== "seed" || !side.book_id) continue;
      next[side.book_id] = {
        author: side.effective_author || "",
        title: side.effective_title || "",
        series: side.effective_series || "",
        seriesIndex: side.effective_series_index || "",
      };
    }
    resetDrafts(next);
    winner.value = current.conflict?.winner_side_id || "";
  }

  function fillMergeMeta(current) {
    const members = mergeMembers(current).filter((member) => selected[member.book_id]);
    const best = [...members].sort(
      (a, b) => (Number(b.confidence) || 0) - (Number(a.confidence) || 0),
    )[0];
    const target = parseTargetKeyDisplay(current.target_key);
    mergeMeta.author = best?.effective_author || target.author || "";
    mergeMeta.title = best?.effective_title || target.title || "";
    mergeMeta.series = best?.effective_series || target.series || "";
    mergeMeta.seriesIndex = best?.effective_series_index || target.seriesIndex || "";
  }

  function initMergeSelection(current) {
    const members = mergeMembers(current);
    const ids = members.map((member) => String(member.book_id));
    const draft = readMergeDraft(current.target_key);
    const chosen = (draft || []).filter((id) => ids.includes(id));
    resetSelected(chosen.length ? chosen : ids);
    fillMergeMeta(current);
  }

  function ensureMode(current) {
    if (mode.value === "select" && !canResolveSelect(current)) mode.value = "merge";
    if (mode.value === "merge" && !canResolveMerge(current)) mode.value = "select";
    if (!canResolveSelect(current) && canResolveMerge(current)) mode.value = "merge";
  }

  async function fetchUnified(key, fallback) {
    let conflict = null;
    let merge = fallback?.merge || null;
    try {
      conflict = await api(`/api/conflicts/${encodeTargetKey(key)}`);
    } catch (err) {
      if (err.status !== 404) throw err;
    }
    try {
      const fetched = await api(`/api/merges/${encodeTargetKey(key)}`);
      if (fetched) merge = fetched;
    } catch (err) {
      if (err.status !== 404) throw err;
      if (!fallback?.merge) merge = null;
    }
    if (!conflict && !merge) return null;
    return { target_key: key, conflict, merge };
  }

  function applyPreview(data, key) {
    preview.value = data;
    const overrides = readStagedNames(key);
    const serverNames = {};
    stagedRows.value = (data.staged_files || []).map((entry) => {
      serverNames[entry.source] = entry.staged_name || "";
      return {
        source: entry.source,
        basename: entry.basename || entry.source,
        book_id: entry.book_id,
        staged_name: Object.prototype.hasOwnProperty.call(overrides, entry.source)
          ? overrides[entry.source]
          : entry.staged_name || "",
        server_name: entry.staged_name || "",
      };
    });
    namesDirty.value = stagedRows.value.some((row) => row.staged_name !== row.server_name);
  }

  async function loadPreview() {
    const current = group.value;
    if (!current || mode.value !== "merge") return;
    const ids = Object.keys(selected);
    previewError.value = "";
    if (ids.length < 2) {
      preview.value = null;
      stagedRows.value = [];
      previewLoading.value = false;
      return;
    }
    previewLoading.value = true;
    try {
      const data = await api(mergeEndpoints(current).preview, {
        method: "POST",
        body: JSON.stringify({ member_book_ids: ids }),
      });
      if (targetKey.value !== current.target_key) return;
      applyPreview(data, current.target_key);
    } catch (err) {
      preview.value = null;
      stagedRows.value = [];
      previewError.value = err.message || "Could not load merge preview";
    } finally {
      previewLoading.value = false;
    }
  }

  async function openGroup(key) {
    const existing = findGroup(key);
    if (!existing) {
      shell.showToast("Conflict not found.");
      return;
    }
    targetKey.value = key;
    group.value = existing;
    mode.value = defaultResolveMode(existing);
    namesDirty.value = false;
    preview.value = null;
    previewError.value = "";
    stagedRows.value = [];
    const seeded = Boolean(existing.conflict);
    if (existing.conflict) seedDraftsFrom(existing);
    if (canResolveMerge(existing)) initMergeSelection(existing);
    open.value = true;
    try {
      const fresh = await fetchUnified(key, existing);
      if (targetKey.value !== key) return;
      if (!fresh) {
        shell.showToast("Conflict not found.");
        close();
        return;
      }
      group.value = fresh;
      ensureMode(fresh);
      if (fresh.conflict && !seeded) seedDraftsFrom(fresh);
      if (canResolveMerge(fresh)) initMergeSelection(fresh);
      if (mode.value === "merge") await loadPreview();
    } catch (err) {
      shell.showToast(err.message || "Could not open conflict");
    }
  }

  function close() {
    if (!open.value && !targetKey.value) return;
    const key = targetKey.value;
    open.value = false;
    targetKey.value = "";
    group.value = null;
    mode.value = "select";
    preview.value = null;
    previewError.value = "";
    stagedRows.value = [];
    namesDirty.value = false;
    resetDrafts({});
    resetSelected([]);
    if (key) clearMergeSession(key);
  }

  function onDialogClose() {
    if (open.value) close();
  }

  async function setMode(next) {
    const current = group.value;
    if (!current || busy.value) return;
    if (next === "select" && !canResolveSelect(current)) return;
    if (next === "merge" && !canResolveMerge(current)) return;
    mode.value = next;
    if (next === "merge") {
      if (!Object.keys(selected).length) initMergeSelection(current);
      await loadPreview();
    }
  }

  async function run(fn) {
    if (busy.value) return;
    busy.value = true;
    try {
      await fn();
    } catch (err) {
      shell.showToast(err.message || "Request failed");
    } finally {
      busy.value = false;
    }
  }

  async function rebind(key) {
    await staging.afterMutation();
    if (!open.value || targetKey.value !== key) return false;
    const fresh = findGroup(key);
    let resolved = fresh;
    if (!resolved) {
      try {
        resolved = await fetchUnified(key, null);
      } catch (err) {
        if (err.status !== 404) throw err;
        resolved = null;
      }
    }
    if (!resolved || (!resolved.conflict && !resolved.merge)) {
      const next = conflictKeys().find((item) => item !== key) || "";
      if (next) {
        await openGroup(next);
        return false;
      }
      close();
      return false;
    }
    group.value = resolved;
    ensureMode(resolved);
    if (resolved.conflict) seedDraftsFrom(resolved);
    if (mode.value === "merge") {
      initMergeSelection(resolved);
      await loadPreview();
    }
    return true;
  }

  function draftBody(bookId) {
    const draft = drafts[bookId] || {};
    return {
      chosen_author: draft.author ?? "",
      chosen_title: draft.title ?? "",
      chosen_series: draft.series ?? "",
      chosen_series_index: draft.seriesIndex ?? "",
    };
  }

  function saveOne(bookId) {
    return run(async () => {
      const key = targetKey.value;
      await api(`/api/books/${encodeURIComponent(bookId)}`, {
        method: "PATCH",
        body: JSON.stringify(draftBody(bookId)),
      });
      const still = await rebind(key);
      shell.showToast(still ? "Saved" : "Saved. This conflict is resolved.");
    });
  }

  function applyCandidate(bookId, candidate) {
    const draft = drafts[bookId];
    if (!draft || !candidate) return;
    draft.author = candidate.author || "";
    draft.title = candidate.title || "";
    draft.series = candidate.series || "";
    draft.seriesIndex = candidate.series_index || "";
    return saveOne(bookId);
  }

  function saveAll() {
    return run(async () => {
      const current = group.value;
      if (!current?.conflict) return;
      const key = current.target_key;
      const edits = (current.conflict.sides || [])
        .filter((side) => side.type === "seed" && drafts[side.book_id])
        .map((side) => ({ book_id: side.book_id, ...draftBody(side.book_id) }));
      if (!edits.length) return;
      const result = await api(`/api/conflicts/${encodeTargetKey(key)}/save-edits`, {
        method: "POST",
        body: JSON.stringify({ edits }),
      });
      const errors = result?.errors || [];
      const still = await rebind(key);
      if (errors.length) {
        shell.showToast(errors[0]?.error || "Could not save every edit");
        return;
      }
      const saved = result?.saved ?? edits.length;
      shell.showToast(still ? `Saved ${saved} edit${saved === 1 ? "" : "s"}` : "Saved. This conflict is resolved.");
    });
  }

  function skipSeed(bookId) {
    return run(async () => {
      const key = targetKey.value;
      await api(`/api/books/${encodeURIComponent(bookId)}/skip`, { method: "POST" });
      const still = await rebind(key);
      shell.showToast(still ? "Book skipped" : "Book skipped. This conflict is resolved.");
    });
  }

  function approveSelect() {
    return run(async () => {
      const current = group.value;
      if (!current?.conflict) return;
      const winnerId = winner.value;
      if (!winnerId) {
        shell.showToast("Select a winner side first.");
        return;
      }
      const winnerIsSeed = winnerId !== "library";
      if (current.conflict.has_library_side && winnerIsSeed) {
        const ok = await staging.askConfirm({
          title: `Approve seed for “${current.target_key}”?`,
          message: "Existing library files at this path will be removed and replaced by the seed.",
          confirmLabel: "Replace",
          cancelLabel: "Cancel",
          preferenceKey: "conflict-approve-library",
        });
        if (!ok) return;
      }
      const body = { winner_side: winnerId };
      if (winnerIsSeed) Object.assign(body, draftBody(winnerId));
      const key = current.target_key;
      await staging.withScrim("Staging winner…", async () => {
        await api(`/api/conflicts/${encodeTargetKey(key)}/approve`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        await staging.afterMutation();
      });
      shell.showToast("Winner staged");
      if (!open.value || targetKey.value !== key) return;
      const next = conflictKeys().find((item) => item !== key) || "";
      if (next) await openGroup(next);
      else close();
    });
  }

  function advance() {
    const keys = conflictKeys();
    if (keys.length < 2) return;
    const index = keys.indexOf(targetKey.value);
    const next = keys[(index + 1) % keys.length];
    return openGroup(next);
  }

  async function toggleMember(bookId, on, event) {
    const current = group.value;
    if (!current || busy.value) return;
    const id = String(bookId);
    if (namesDirty.value) {
      const ok = await staging.askConfirm({
        title: "Change merge selection?",
        message:
          "Changing which parts are included will reset library filenames to the preview names.",
        confirmLabel: "Change selection",
        cancelLabel: "Cancel",
        preferenceKey: "merge-selection-change",
      });
      if (!ok) {
        if (event && event.target) event.target.checked = !on;
        return;
      }
      writeStagedNames(current.target_key, null);
      namesDirty.value = false;
    }
    if (on) selected[id] = true;
    else delete selected[id];
    writeMergeDraft(current.target_key, Object.keys(selected));
    fillMergeMeta(current);
    await loadPreview();
  }

  function onStagedName(source, value) {
    const current = group.value;
    const row = stagedRows.value.find((item) => item.source === source);
    if (row) row.staged_name = value;
    if (!current) return;
    const overrides = {};
    for (const item of stagedRows.value) {
      if (item.staged_name !== item.server_name) overrides[item.source] = item.staged_name;
    }
    namesDirty.value = Object.keys(overrides).length > 0;
    writeStagedNames(current.target_key, overrides);
  }

  function approveMerge() {
    return run(async () => {
      const current = group.value;
      if (!current) return;
      const ids = Object.keys(selected);
      if (ids.length < 2) {
        shell.showToast("Select at least two parts to merge.");
        return;
      }
      if (invalidStagedNames(stagedRows.value)) {
        shell.showToast("Fix duplicate or empty library filenames before merging.");
        return;
      }
      const stagedNames = {};
      for (const row of stagedRows.value) {
        if (row.source) stagedNames[row.source] = row.staged_name || "";
      }
      await staging.withScrim("Merging and staging…", async () => {
        await api(mergeEndpoints(current).approve, {
          method: "POST",
          body: JSON.stringify({
            member_book_ids: ids,
            chosen_author: mergeMeta.author,
            chosen_title: mergeMeta.title,
            chosen_series: mergeMeta.series,
            chosen_series_index: mergeMeta.seriesIndex,
            staged_names: stagedNames,
          }),
        });
        clearMergeSession(current.target_key);
        await staging.afterMutation();
      });
      close();
      shell.showToast("Merged and staged");
    });
  }

  function prevPage() {
    offset.value = Math.max(0, offset.value - GROUP_PAGE_SIZE);
  }

  function nextPage() {
    if (canNext.value) offset.value += GROUP_PAGE_SIZE;
  }

  const previewDuration = computed(() => formatDuration(preview.value && preview.value.total_duration_seconds));

  return {
    PAGE_SIZE: GROUP_PAGE_SIZE,
    offset,
    open,
    group,
    mode,
    winner,
    busy,
    drafts,
    selected,
    mergeMeta,
    preview,
    previewLoading,
    previewError,
    previewDuration,
    stagedRows,
    pageGroups,
    total,
    pageFrom,
    pageTo,
    canPrev,
    canNext,
    showTabs,
    canMerge,
    mergeBlockedReason,
    hasNext,
    openGroup,
    close,
    onDialogClose,
    setMode,
    saveOne,
    applyCandidate,
    saveAll,
    skipSeed,
    approveSelect,
    advance,
    toggleMember,
    onStagedName,
    approveMerge,
    prevPage,
    nextPage,
  };
}
