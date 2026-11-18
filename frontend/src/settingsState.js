import { reactive, ref } from "vue";

import { api } from "./api.js";
import { finishScanAnimationEnabled, setFinishScanAnimationEnabled } from "./constants.js";
import { ADVANCED_DEFAULT_POST, ADVANCED_DEFAULT_PRE, TITLE_STEPS } from "./titleExtraction.js";

function blankSteps() {
  const bag = {};
  for (const step of TITLE_STEPS) bag[step.id] = false;
  return bag;
}

function formatWhen(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return date.toLocaleString();
}

export function useSettings(shell, staging) {
  const open = ref(false);
  const tab = ref("general");
  const busy = ref(false);
  const lastRunText = ref("Last run: —");
  const previewRows = ref([]);
  const previewIds = ref([]);
  const form = reactive({
    enabled: false,
    interval_hours: 2,
    min_confidence: 0.9,
    lock_timeout_minutes: 15,
    scan_manual_hints: false,
    lvi_search: true,
    lvi_boost: true,
    title_extraction_mode: "balanced",
    finish_scan_animation: true,
    pre: blankSteps(),
    post: blankSteps(),
  });
  let previewTimer = null;

  function assignSteps(bag, ids) {
    const selected = new Set(ids || []);
    for (const step of TITLE_STEPS) bag[step.id] = selected.has(step.id);
  }

  function checked(phase) {
    const bag = phase === "pre" ? form.pre : form.post;
    return TITLE_STEPS.filter((step) => bag[step.id]).map((step) => step.id);
  }

  function anyStepChecked() {
    return TITLE_STEPS.some((step) => form.pre[step.id] || form.post[step.id]);
  }

  function renderLastRun(lastRun) {
    if (!lastRun) {
      lastRunText.value = "Last run: —";
      return;
    }
    const parts = [`Last run: ${formatWhen(lastRun.finished_at || lastRun.started_at) || "—"}`];
    if (lastRun.status) parts.push(lastRun.status);
    if (lastRun.books_staged != null) parts.push(`${lastRun.books_staged} staged`);
    if (lastRun.books_failed) parts.push(`${lastRun.books_failed} failed`);
    if (lastRun.message) parts.push(lastRun.message);
    lastRunText.value = parts.join(" · ");
  }

  function apply(payload) {
    const settings = (payload && payload.settings) || {};
    form.enabled = !!settings.enabled;
    form.scan_manual_hints = !!settings.scan_manual_hints;
    form.lvi_search = settings.lvi_search !== false;
    form.lvi_boost = settings.lvi_boost !== false;
    form.interval_hours = settings.interval_hours ?? 2;
    form.min_confidence = settings.min_confidence ?? 0.9;
    form.lock_timeout_minutes = settings.lock_timeout_minutes ?? 15;
    form.title_extraction_mode = settings.title_extraction_mode || "balanced";
    assignSteps(form.pre, settings.title_cleanup_pre);
    assignSteps(form.post, settings.title_cleanup_post);
    if (form.title_extraction_mode === "advanced" && !anyStepChecked()) {
      assignSteps(form.pre, ADVANCED_DEFAULT_PRE);
      assignSteps(form.post, ADVANCED_DEFAULT_POST);
    }
    renderLastRun(payload && payload.last_run);
  }

  async function load() {
    const data = await api("/api/auto/settings");
    apply(data);
    if (form.title_extraction_mode === "advanced") await refreshPreview(true);
  }

  async function openDialog() {
    tab.value = "general";
    form.finish_scan_animation = finishScanAnimationEnabled();
    open.value = true;
    try {
      await load();
    } catch (err) {
      shell.showToast(err.message || "Could not load settings");
    }
  }

  function close() {
    open.value = false;
  }

  function onDialogClose() {
    open.value = false;
  }

  function setTab(next) {
    tab.value = next === "metadata" ? "metadata" : "general";
    if (tab.value === "metadata" && form.title_extraction_mode === "advanced" && !previewIds.value.length) {
      void refreshPreview(true);
    }
  }

  function setMode(mode) {
    form.title_extraction_mode = mode;
    if (mode !== "advanced") return;
    if (!anyStepChecked()) {
      assignSteps(form.pre, ADVANCED_DEFAULT_PRE);
      assignSteps(form.post, ADVANCED_DEFAULT_POST);
    }
    void refreshPreview(!previewIds.value.length);
  }

  function schedulePreview() {
    if (form.title_extraction_mode !== "advanced") return;
    if (previewTimer) clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
      previewTimer = null;
      void refreshPreview(false);
    }, 300);
  }

  async function refreshPreview(resample) {
    if (form.title_extraction_mode !== "advanced") return;
    try {
      const payload = {
        mode: "advanced",
        pre_steps: checked("pre"),
        post_steps: checked("post"),
        limit: 10,
      };
      if (!resample && previewIds.value.length) payload.book_ids = [...previewIds.value];
      const data = await api("/api/settings/title-extraction/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      const samples = Array.isArray(data && data.samples) ? data.samples : [];
      previewIds.value = samples.map((row) => row.book_id).filter(Boolean);
      previewRows.value = samples;
    } catch (err) {
      shell.showToast(err.message || "Preview failed");
    }
  }

  async function save() {
    if (busy.value) return;
    const mode = form.title_extraction_mode;
    const body = {
      enabled: !!form.enabled,
      scan_manual_hints: !!form.scan_manual_hints,
      lvi_search: !!form.lvi_search,
      lvi_boost: !!form.lvi_boost,
      interval_hours: Number(form.interval_hours),
      min_confidence: Number(form.min_confidence),
      lock_timeout_minutes: Number(form.lock_timeout_minutes),
      title_extraction_mode: mode,
    };
    if (mode === "advanced") {
      body.title_cleanup_pre = checked("pre");
      body.title_cleanup_post = checked("post");
    }
    busy.value = true;
    try {
      setFinishScanAnimationEnabled(!!form.finish_scan_animation);
      const data = await api("/api/auto/settings", {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      apply(data);
      shell.showToast("Settings saved");
    } catch (err) {
      shell.showToast(err.message || "Could not save settings");
    } finally {
      busy.value = false;
    }
  }

  async function runNow() {
    if (busy.value || shell.sectionsBlocked.value) {
      shell.showToast("Auto-run already in progress");
      return;
    }
    busy.value = true;
    try {
      const result = await api("/api/auto/run", { method: "POST" });
      open.value = false;
      shell.startAuto(result && result.run_id);
    } catch (err) {
      if (err.status === 409 && err.detail && err.detail.kind === "auto_run") {
        open.value = false;
        shell.startAuto(err.detail.auto_run_id || null);
        shell.showToast("Auto-run already in progress");
        return;
      }
      shell.showToast(err.message || "Could not start auto-run");
    } finally {
      busy.value = false;
    }
  }

  async function clearCache() {
    const ok = await staging.askConfirm({
      title: "Clear metadata cache?",
      message: "Pending books will re-lookup metadata on the next scan.",
      confirmLabel: "Clear cache",
      cancelLabel: "Cancel",
      dangerous: true,
      preferenceKey: "clear-metadata-cache",
    });
    if (!ok) return;
    try {
      await api("/api/auto/cache/clear", { method: "POST" });
      shell.showToast("Metadata cache cleared");
    } catch (err) {
      shell.showToast(err.message || "Could not clear metadata cache");
    }
  }

  return {
    open,
    tab,
    busy,
    form,
    lastRunText,
    previewRows,
    openDialog,
    close,
    onDialogClose,
    setTab,
    setMode,
    schedulePreview,
    refreshPreview,
    save,
    runNow,
    clearCache,
  };
}
