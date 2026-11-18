import { computed, onUnmounted, reactive, ref } from "vue";

import { api } from "./api.js";
import { setBooksRefreshedListener } from "./shellState.js";
import {
  BULK_BY_FILTER,
  PAGE_SIZE,
  SEARCH_DEBOUNCE_MS,
  buildBooksSearch,
  collectMergeIds,
  confirmSkipped,
  emptyStagingMessage,
  isRowSelectable,
  loadStagingSort,
  rememberConfirmSkip,
  saveStagingSort,
  sortStagingBooks,
} from "./staging.js";

export function useStaging(shell) {
  const status = ref("pending");
  const query = ref("");
  const offset = ref(0);
  const rows = ref([]);
  const mergeIds = ref(new Set());
  const sort = ref(loadStagingSort());
  const loading = ref(false);
  const loaded = ref(false);
  const errorText = ref("");
  const busy = ref(false);
  const scrimMessage = ref("");
  const detailBook = ref(null);
  const confirmState = ref(null);
  const selection = reactive({ pending: {}, staged: {}, skipped: {} });
  const requestText = ref(
    buildBooksSearch({ status: "pending", q: "", limit: PAGE_SIZE, offset: 0 }).toString(),
  );

  let loadToken = 0;
  let searchTimer = null;

  const sortedRows = computed(() => sortStagingBooks(rows.value, sort.value));
  const selectedIds = computed(() => Object.keys(selection[status.value] || {}));
  const bulkConfig = computed(() => BULK_BY_FILTER[status.value] || BULK_BY_FILTER.pending);
  const bulkLabel = computed(() => bulkConfig.value.label);
  const emptyMessage = computed(() => emptyStagingMessage(status.value, query.value));
  const canPrev = computed(() => offset.value > 0 && !loading.value);
  const canNext = computed(() => rows.value.length === PAGE_SIZE && !loading.value);
  const selectableIds = computed(() =>
    sortedRows.value.filter((book) => isRowSelectable(book, status.value, mergeIds.value)).map((book) => book.id),
  );
  const allPageSelected = computed(
    () => selectableIds.value.length > 0 && selectableIds.value.every((id) => selection[status.value][id]),
  );

  async function loadBooks() {
    const token = ++loadToken;
    const params = buildBooksSearch({
      status: status.value,
      q: query.value.trim(),
      limit: PAGE_SIZE,
      offset: offset.value,
    });
    requestText.value = params.toString();
    loading.value = true;
    errorText.value = "";
    try {
      const data = await api(`/api/books?${params.toString()}`);
      if (token !== loadToken) return;
      rows.value = Array.isArray(data && data.staging) ? data.staging : [];
      mergeIds.value = collectMergeIds(data && data.merges);
      loaded.value = true;
    } catch (err) {
      if (token !== loadToken) return;
      rows.value = [];
      errorText.value = err.message || "Could not load staging";
      shell.showToast(errorText.value);
    } finally {
      if (token === loadToken) loading.value = false;
    }
  }

  async function refreshAfterChange() {
    await shell.refreshBooks();
    if (rows.value.length === 0 && offset.value > 0) {
      offset.value = Math.max(0, offset.value - PAGE_SIZE);
      await loadBooks();
    }
  }

  function setStatus(next) {
    if (!BULK_BY_FILTER[next] || next === status.value) return;
    status.value = next;
    offset.value = 0;
    void loadBooks();
  }

  function onSearch(value) {
    query.value = value;
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      searchTimer = null;
      offset.value = 0;
      void loadBooks();
    }, SEARCH_DEBOUNCE_MS);
  }

  function applySort(next) {
    sort.value = next;
    saveStagingSort(next);
  }

  function toggleSort(key) {
    if (!["source_path", "metadata", "confidence"].includes(key)) return;
    if (sort.value.key === key) applySort({ key, dir: sort.value.dir === "asc" ? "desc" : "asc" });
    else applySort({ key, dir: "asc" });
  }

  function setSortValue(value) {
    const [key, dir] = String(value || "").split(":");
    if (!["source_path", "metadata", "confidence"].includes(key)) return;
    applySort({ key, dir: dir === "desc" ? "desc" : "asc" });
  }

  function rowSelected(id) {
    return Boolean(selection[status.value][id]);
  }

  function toggleRow(id, on) {
    const bag = selection[status.value];
    if (on) bag[id] = true;
    else delete bag[id];
  }

  function togglePage(on) {
    for (const id of selectableIds.value) toggleRow(id, on);
  }

  function forgetSelected(filter, ids) {
    const bag = selection[filter];
    for (const id of ids) delete bag[id];
  }

  function askConfirm(options) {
    if (confirmSkipped(options.preferenceKey)) return Promise.resolve(true);
    return new Promise((resolve) => {
      confirmState.value = { ...options, dontAgain: false, resolve };
    });
  }

  function settleConfirm(ok) {
    const state = confirmState.value;
    if (!state) return;
    confirmState.value = null;
    if (ok && state.dontAgain && state.preferenceKey) rememberConfirmSkip(state.preferenceKey);
    state.resolve(Boolean(ok));
  }

  function onConfirmDialogClose() {
    if (confirmState.value) settleConfirm(false);
  }

  async function withScrim(message, fn) {
    scrimMessage.value = message;
    try {
      return await fn();
    } finally {
      scrimMessage.value = "";
    }
  }

  async function openDetail(id) {
    const book = await api(`/api/books/${encodeURIComponent(id)}`);
    detailBook.value = book;
  }

  function closeDetail() {
    detailBook.value = null;
  }

  function onDetailSaved(book) {
    detailBook.value = book;
    void loadBooks();
  }

  async function approve(id) {
    await withScrim("Staging book…", async () => {
      await api(`/api/books/${encodeURIComponent(id)}/approve`, { method: "POST" });
      forgetSelected("pending", [id]);
      await refreshAfterChange();
    });
    shell.showToast("Book staged");
  }

  async function skip(id) {
    await api(`/api/books/${encodeURIComponent(id)}/skip`, { method: "POST" });
    forgetSelected("pending", [id]);
    await refreshAfterChange();
    shell.showToast("Book skipped");
  }

  async function unskip(id) {
    await api(`/api/books/${encodeURIComponent(id)}/unskip`, { method: "POST" });
    forgetSelected("skipped", [id]);
    await refreshAfterChange();
    shell.showToast("Book unskipped");
  }

  async function unstage(id) {
    const ok = await askConfirm({
      title: "Unstage book?",
      message: "Library hardlinks will be removed and the book returns to pending.",
      confirmLabel: "Unstage",
      cancelLabel: "Cancel",
      dangerous: true,
      preferenceKey: "staging-unstage",
    });
    if (!ok) return;
    await withScrim("Unstaging book…", async () => {
      await api(`/api/books/${encodeURIComponent(id)}/revert`, { method: "POST" });
      forgetSelected("staged", [id]);
      await refreshAfterChange();
    });
    if (detailBook.value && detailBook.value.id === id) detailBook.value = null;
    shell.showToast("Book unstaged");
  }

  async function runRow(action, book) {
    if (!book || busy.value || shell.sectionsBlocked.value) return;
    busy.value = true;
    try {
      if (action === "detail") await openDetail(book.id);
      else if (action === "approve") await approve(book.id);
      else if (action === "skip") await skip(book.id);
      else if (action === "unskip") await unskip(book.id);
      else if (action === "unstage") await unstage(book.id);
    } catch (err) {
      shell.showToast(err.message || "Request failed");
    } finally {
      busy.value = false;
    }
  }

  async function unstageFromDetail() {
    const book = detailBook.value;
    if (!book) return;
    await runRow("unstage", book);
  }

  async function runBulk() {
    if (busy.value || shell.sectionsBlocked.value) return;
    const filter = status.value;
    const config = BULK_BY_FILTER[filter] || BULK_BY_FILTER.pending;
    const ids = Object.keys(selection[filter]);
    if (!ids.length) {
      shell.showToast(config.empty);
      return;
    }
    if (config.confirm) {
      const ok = await askConfirm({
        title: `Unstage ${ids.length} book${ids.length === 1 ? "" : "s"}?`,
        message: "Library hardlinks will be removed and selected books return to pending.",
        confirmLabel: "Unstage",
        cancelLabel: "Cancel",
        dangerous: true,
        preferenceKey: "staging-unstage-bulk",
      });
      if (!ok) return;
    }
    busy.value = true;
    try {
      const execute = async () => {
        const result = await api(config.path, {
          method: "POST",
          body: JSON.stringify({ book_ids: ids }),
        });
        forgetSelected(filter, ids);
        await refreshAfterChange();
        const errors = result && Array.isArray(result.errors) ? result.errors : [];
        if (errors.length) shell.showToast(`${errors.length} error(s) during ${config.label.toLowerCase()}`);
        else shell.showToast(config.label.replace(" Selected", ""));
      };
      if (config.scrim) await withScrim(config.scrim, execute);
      else await execute();
    } catch (err) {
      shell.showToast(err.message || "Bulk action failed");
    } finally {
      busy.value = false;
    }
  }

  function nextPage() {
    if (!canNext.value) return;
    offset.value += PAGE_SIZE;
    void loadBooks();
  }

  function prevPage() {
    if (!canPrev.value) return;
    offset.value = Math.max(0, offset.value - PAGE_SIZE);
    void loadBooks();
  }

  const stopListener = setBooksRefreshedListener(() => loadBooks());
  onUnmounted(() => {
    stopListener();
    if (searchTimer) clearTimeout(searchTimer);
  });

  return {
    PAGE_SIZE,
    status,
    query,
    offset,
    requestText,
    loading,
    loaded,
    errorText,
    busy,
    scrimMessage,
    detailBook,
    confirmState,
    sort,
    sortedRows,
    selectedIds,
    bulkLabel,
    emptyMessage,
    canPrev,
    canNext,
    allPageSelected,
    mergeIds,
    setStatus,
    onSearch,
    toggleSort,
    setSortValue,
    rowSelected,
    toggleRow,
    togglePage,
    runRow,
    runBulk,
    nextPage,
    prevPage,
    closeDetail,
    openDetail,
    onDetailSaved,
    unstageFromDetail,
    askConfirm,
    withScrim,
    afterMutation: refreshAfterChange,
    settleConfirm,
    onConfirmDialogClose,
    isRowSelectable: (book) => isRowSelectable(book, status.value, mergeIds.value),
  };
}
