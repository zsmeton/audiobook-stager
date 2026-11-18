import { computed, onMounted, onUnmounted, ref } from "vue";

import { api } from "./api.js";
import { formatBookStatus, summarizeBooks } from "./books.js";
import { AWAY_TIMEOUT_MS, SCAN_POLL_ERROR_MS, SCAN_POLL_MS, finishScanAnimationEnabled } from "./constants.js";
import { idleReloadDue } from "./idleReload.js";
import { providerChip } from "./providers.js";

const BOOKS_PATH = "/api/books?partitioned=true&status=&q=";

let booksRefreshedListener = null;

export function setBooksRefreshedListener(listener) {
  booksRefreshedListener = listener;
  return () => {
    if (booksRefreshedListener === listener) booksRefreshedListener = null;
  };
}

function wait(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export function useShell() {
  const mode = ref("loading");
  const sessionState = ref("");
  const needsScan = ref(false);
  const scrimTitle = ref("Loading…");
  const scrimMessage = ref("");
  const providers = ref([]);
  const providerPending = ref(false);
  const scan = ref(null);
  const bookSummary = ref(null);
  const libraryLists = ref({ conflicts: [], merges: [], partial: [] });
  const bookRefreshCount = ref(0);
  const pollCount = ref(0);
  const lastPollGapMs = ref(null);
  const finishTail = ref("idle");
  const toast = ref("");
  const cancelBusy = ref(false);
  const autoPollCount = ref(0);
  const lastAutoPollGapMs = ref(null);

  let scanId = null;
  let autoRunId = null;
  let lastAutoPollAt = 0;
  let cancelPending = false;
  let activityGen = 0;
  let scanTimer = null;
  let autoTimer = null;
  let finishTimer = null;
  let lastPollAt = 0;
  let pollToken = 0;
  let hiddenAt = null;
  let toastTimer = null;

  const showScrim = computed(() => mode.value !== "home");
  const sectionsBlocked = computed(() =>
    ["loading", "prescan", "scan", "finishing", "auto"].includes(mode.value),
  );
  const scanButtonDisabled = computed(() =>
    ["loading", "scan", "finishing", "auto"].includes(mode.value),
  );
  const showProviders = computed(() => mode.value === "prescan");
  const showCancel = computed(() => mode.value === "scan" || mode.value === "auto");
  const showStartScan = computed(() => mode.value === "prescan");
  const showReload = computed(() => mode.value === "idle");
  const providerChips = computed(() =>
    providers.value.map((provider) =>
      providerChip(provider.provider, provider.result, { pending: providerPending.value }),
    ),
  );
  const bookStatusText = computed(() => formatBookStatus(bookSummary.value));
  const scanProgressText = computed(() => {
    const row = scan.value;
    if (!row) return "";
    const phase = row.scan_phase || row.status || "";
    const discovered = row.books_discovered ?? row.books_found ?? 0;
    const complete = row.books_complete ?? row.metadata_done ?? 0;
    const total = row.books_total ?? row.total_books ?? 0;
    const message = row.message || "";
    return [phase, message, `discovered ${discovered}`, `${complete}/${total} complete`]
      .filter(Boolean)
      .join(" · ");
  });

  function showToast(message) {
    toast.value = message || "";
    if (toastTimer) clearTimeout(toastTimer);
    if (!message) return;
    toastTimer = setTimeout(() => {
      toast.value = "";
      toastTimer = null;
    }, 4000);
  }

  function clearTimers() {
    if (scanTimer) clearTimeout(scanTimer);
    if (autoTimer) clearTimeout(autoTimer);
    if (finishTimer) clearTimeout(finishTimer);
    scanTimer = null;
    autoTimer = null;
    finishTimer = null;
  }

  function bumpActivity() {
    activityGen += 1;
    clearTimers();
    return activityGen;
  }

  async function refreshBooks() {
    const payload = await api(BOOKS_PATH);
    bookSummary.value = summarizeBooks(payload);
    libraryLists.value = {
      conflicts: Array.isArray(payload && payload.conflicts) ? payload.conflicts : [],
      merges: Array.isArray(payload && payload.merges) ? payload.merges : [],
      partial: Array.isArray(payload && payload.partial) ? payload.partial : [],
    };
    bookRefreshCount.value += 1;
    if (booksRefreshedListener) await booksRefreshedListener();
  }

  async function loadProviders() {
    providerPending.value = false;
    const data = await api("/api/metadata/providers");
    const rows = Array.isArray(data && data.providers) ? data.providers : [];
    providers.value = rows.map((provider) => ({ provider, result: null }));
    providerPending.value = true;
    try {
      const tested = await api("/api/metadata/providers/test", { method: "POST" });
      const results = new Map((tested.results || []).map((result) => [result.id, result]));
      providers.value = rows.map((provider) => ({
        provider,
        result: results.get(provider.id) || null,
      }));
    } catch (err) {
      showToast(err.message || "Could not test metadata providers");
    } finally {
      providerPending.value = false;
    }
  }

  function showPreScan(status) {
    mode.value = "prescan";
    needsScan.value = true;
    scrimTitle.value =
      status && status.state === "stale_scan"
        ? "Your scan is out of date"
        : "Scan your library to get started";
    scrimMessage.value = "Check metadata providers, then start the scan.";
    scan.value = null;
    void loadProviders();
  }

  async function enterHome() {
    mode.value = "home";
    scrimTitle.value = "";
    scrimMessage.value = "";
    scan.value = null;
    try {
      await refreshBooks();
    } catch (err) {
      showToast(err.message || "Could not load book counts");
    }
  }

  function attachScan(nextId) {
    const pendingCancel = cancelPending;
    const gen = bumpActivity();
    scanId = nextId;
    autoRunId = null;
    cancelPending = pendingCancel;
    pollCount.value = 0;
    lastPollAt = 0;
    lastPollGapMs.value = null;
    finishTail.value = "idle";
    mode.value = "scan";
    scrimTitle.value = "Scan in progress";
    scrimMessage.value = "Scan in progress…";
    void pollScan(gen);
    if (pendingCancel) void cancelActivity();
  }

  function attachAuto(nextId) {
    const gen = bumpActivity();
    autoRunId = nextId;
    scanId = null;
    cancelPending = false;
    autoPollCount.value = 0;
    lastAutoPollAt = 0;
    lastAutoPollGapMs.value = null;
    mode.value = "auto";
    scrimTitle.value = "Auto-scan and stage";
    scrimMessage.value = "Please wait…";
    void pollAuto(gen);
  }

  function startAuto(runId) {
    attachAuto(runId || null);
  }

  async function pollScan(gen) {
    const token = ++pollToken;
    if (!scanId || gen !== activityGen) return;
    const id = scanId;
    try {
      const row = await api(`/api/scan/${encodeURIComponent(id)}`);
      if (token !== pollToken || gen !== activityGen || scanId !== id) return;
      if (cancelPending && row.message && !String(row.message).includes("Cancelling")) {
        row.message = "Cancelling…";
      }
      scan.value = row;
      const now = Date.now();
      if (lastPollAt) lastPollGapMs.value = now - lastPollAt;
      lastPollAt = now;
      pollCount.value += 1;
      try {
        await refreshBooks();
      } catch (bookErr) {
        showToast(bookErr.message || "Could not refresh book counts");
      }
      if (token !== pollToken || gen !== activityGen || scanId !== id) return;
      if (row.status === "running") {
        scrimMessage.value = row.message || "Scan in progress…";
        scanTimer = setTimeout(() => {
          if (token === pollToken && gen === activityGen) void pollScan(gen);
        }, SCAN_POLL_MS);
        return;
      }
      cancelPending = false;
      scanId = null;
      if (row.status === "cancelled") showToast("Scan cancelled");
      if (row.status === "cancelled" || row.status === "failed") {
        finishTail.value = "skipped";
        await settleAfterActivity(gen);
        return;
      }
      await runFinishTail(gen, row);
    } catch (err) {
      if (token !== pollToken || gen !== activityGen || !scanId) return;
      scrimMessage.value = err.message || "Scan poll failed. Retrying…";
      scanTimer = setTimeout(() => {
        if (token === pollToken && gen === activityGen) void pollScan(gen);
      }, SCAN_POLL_ERROR_MS);
    }
  }

  async function enterHomeIfCurrent(gen) {
    if (gen !== activityGen) return;
    await enterHome();
  }

  async function runFinishTail(gen, row) {
    const animate = row.status === "completed" && finishScanAnimationEnabled();
    if (!animate) {
      finishTail.value = "skipped";
      await enterHomeIfCurrent(gen);
      return;
    }
    mode.value = "finishing";
    finishTail.value = "waiting";
    scrimTitle.value = "Finishing scan…";
    scrimMessage.value = "Holding the scan view for one poll interval.";
    await wait(SCAN_POLL_MS);
    if (gen !== activityGen) return;
    finishTail.value = "done";
    await enterHomeIfCurrent(gen);
  }

  async function pollAuto(gen) {
    if (gen !== activityGen) return;
    try {
      const run = await api("/api/auto/running");
      if (gen !== activityGen) return;
      if (run && run.status === "running") {
        autoRunId = run.id || autoRunId;
        const now = Date.now();
        if (lastAutoPollAt) lastAutoPollGapMs.value = now - lastAutoPollAt;
        lastAutoPollAt = now;
        autoPollCount.value += 1;
        scrimTitle.value = "Auto-scan and stage";
        scrimMessage.value = run.message || "Please wait…";
        if (run.phase === "scanning" && run.scan_id) {
          try {
            scan.value = await api(`/api/scan/${encodeURIComponent(run.scan_id)}`);
          } catch {
            scan.value = null;
          }
        }
        try {
          await refreshBooks();
        } catch (bookErr) {
          showToast(bookErr.message || "Could not refresh book counts");
        }
        if (gen !== activityGen) return;
        autoTimer = setTimeout(() => {
          void pollAuto(gen);
        }, SCAN_POLL_MS);
        return;
      }
      autoRunId = null;
      showToast(cancelPending ? "Auto-run cancelled" : "Auto-run finished");
      cancelPending = false;
      await settleAfterActivity(gen);
    } catch (err) {
      if (gen !== activityGen) return;
      autoRunId = null;
      showToast(err.message || "Auto-run poll failed");
      await settleAfterActivity(gen);
    }
  }

  async function settleAfterActivity(gen) {
    if (gen !== activityGen) return;
    try {
      const status = await api("/api/session/status");
      if (gen !== activityGen) return;
      await applyStatus(status);
    } catch (err) {
      if (gen !== activityGen) return;
      showToast(err.message || "Could not refresh session");
      await enterHome();
    }
  }

  async function applyStatus(status) {
    sessionState.value = (status && status.state) || "";
    needsScan.value = Boolean(status && status.needs_scan);
    if (status && status.state === "auto_running" && status.auto_run && status.auto_run.id) {
      attachAuto(status.auto_run.id);
      scrimMessage.value = status.auto_run.message || "Please wait…";
      return;
    }
    if (status && status.state === "scan_running" && status.scan && status.scan.id) {
      scan.value = status.scan;
      attachScan(status.scan.id);
      return;
    }
    if (status && (status.state === "no_scan" || status.state === "stale_scan")) {
      showPreScan(status);
      return;
    }
    await enterHome();
  }

  async function bootstrap() {
    const gen = bumpActivity();
    scanId = null;
    autoRunId = null;
    cancelPending = false;
    mode.value = "loading";
    scrimTitle.value = "Loading…";
    scrimMessage.value = "";
    try {
      const status = await api("/api/session/status");
      if (gen !== activityGen) return;
      await applyStatus(status);
    } catch (err) {
      if (gen !== activityGen) return;
      mode.value = "error";
      scrimTitle.value = "Could not load session";
      scrimMessage.value = err.message || "Session request failed";
      showToast(scrimMessage.value);
    }
  }

  async function beginScan() {
    if (scanId || autoRunId) return;
    mode.value = "scan";
    scrimTitle.value = "Scan in progress";
    scrimMessage.value = "Starting scan…";
    scan.value = {
      status: "running",
      scan_phase: "discovering",
      books_discovered: 0,
      books_complete: 0,
      books_total: 0,
    };
    try {
      const started = await api("/api/scan", { method: "POST" });
      attachScan(started.scan_id);
    } catch (err) {
      if (err.status === 409 && err.detail && err.detail.kind === "auto_run") {
        showToast("Auto-scan and stage in progress — please wait");
        if (err.detail.auto_run_id) attachAuto(err.detail.auto_run_id);
        else attachAuto(null);
        return;
      }
      if (err.status === 409 && err.detail && err.detail.scan_id) {
        showToast("Resuming scan already in progress");
        attachScan(err.detail.scan_id);
        return;
      }
      showToast(err.message || "Could not start scan");
      showPreScan({ state: needsScan.value ? sessionState.value : "no_scan" });
    }
  }

  function openPreScan() {
    if (scanId || autoRunId || mode.value === "scan" || mode.value === "finishing" || mode.value === "auto") {
      return;
    }
    showPreScan({ state: sessionState.value === "stale_scan" ? "stale_scan" : "no_scan" });
  }

  async function cancelActivity() {
    if (cancelBusy.value) return;
    if (!scanId && mode.value === "scan") {
      cancelPending = true;
      showToast("Cancelling scan…");
      return;
    }
    if (scanId) {
      const id = scanId;
      cancelBusy.value = true;
      cancelPending = true;
      try {
        const result = await api(`/api/scan/${encodeURIComponent(id)}/cancel`, { method: "POST" });
        showToast("Cancelling scan…");
        const row = await api(`/api/scan/${encodeURIComponent(id)}`);
        if (result && result.message && !(row.message || "").includes("Cancelling")) {
          row.message = result.message;
        }
        scan.value = row;
        const gen = activityGen;
        if (scanTimer) clearTimeout(scanTimer);
        scanTimer = null;
        void pollScan(gen);
      } catch (err) {
        cancelPending = false;
        showToast(err.message || "Could not cancel scan");
      } finally {
        cancelBusy.value = false;
      }
      return;
    }
    if (autoRunId) {
      const id = autoRunId;
      cancelBusy.value = true;
      cancelPending = true;
      try {
        await api(`/api/auto/${encodeURIComponent(id)}/cancel`, { method: "POST" });
        showToast("Auto-run cancelled");
      } catch (err) {
        cancelPending = false;
        showToast(err.message || "Could not cancel auto-run");
      } finally {
        cancelBusy.value = false;
      }
    }
  }

  function reloadAfterAway() {
    window.location.reload();
  }

  function onVisibility() {
    if (document.visibilityState === "hidden") {
      hiddenAt = Date.now();
      return;
    }
    const due = idleReloadDue(hiddenAt, Date.now(), {
      scanActive: Boolean(scanId) || mode.value === "scan" || mode.value === "finishing",
      autoActive: Boolean(autoRunId) || mode.value === "auto",
    });
    hiddenAt = null;
    if (!due) return;
    bumpActivity();
    scanId = null;
    autoRunId = null;
    mode.value = "idle";
    scrimTitle.value = "You've been away for a while";
    scrimMessage.value = "Reload to refresh books and conflicts.";
  }

  function onPageShow(event) {
    if (!event.persisted) return;
    void bootstrap();
  }

  onMounted(() => {
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pageshow", onPageShow);
    void bootstrap();
  });

  onUnmounted(() => {
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("pageshow", onPageShow);
    bumpActivity();
    if (toastTimer) clearTimeout(toastTimer);
  });

  return {
    AWAY_TIMEOUT_MS,
    SCAN_POLL_MS,
    mode,
    sessionState,
    needsScan,
    scrimTitle,
    scrimMessage,
    showScrim,
    sectionsBlocked,
    scanButtonDisabled,
    showProviders,
    showCancel,
    showStartScan,
    showReload,
    providerChips,
    providerPending,
    bookSummary,
    libraryLists,
    bookStatusText,
    bookRefreshCount,
    pollCount,
    lastPollGapMs,
    finishTail,
    scanProgressText,
    toast,
    cancelBusy,
    autoPollCount,
    lastAutoPollGapMs,
    startAuto,
    openPreScan,
    beginScan,
    cancelActivity,
    reloadAfterAway,
    bootstrap,
    showToast,
    refreshBooks,
  };
}
