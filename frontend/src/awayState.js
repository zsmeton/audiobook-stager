import { ref, watch } from "vue";

import { api } from "./api.js";

export function useAway(shell, staging) {
  const items = ref([]);
  const loaded = ref(false);
  const busy = ref(false);
  const errorText = ref("");
  let token = 0;

  async function load() {
    const current = ++token;
    errorText.value = "";
    try {
      const data = await api("/api/auto/review");
      if (current !== token) return;
      items.value = Array.isArray(data && data.items) ? data.items : [];
      loaded.value = true;
    } catch (err) {
      if (current !== token) return;
      errorText.value = err.message || "Could not load auto-stage review";
      shell.showToast(errorText.value);
    }
  }

  async function dismiss(actionId) {
    await api("/api/auto/review/dismiss", {
      method: "POST",
      body: JSON.stringify({ action_ids: [actionId] }),
    });
    await load();
    shell.showToast("Marked okay");
  }

  async function dismissAll() {
    if (busy.value || !items.value.length) return;
    busy.value = true;
    try {
      await api("/api/auto/review/dismiss", {
        method: "POST",
        body: JSON.stringify({ dismiss_all: true }),
      });
      await load();
      shell.showToast("Marked all okay");
    } catch (err) {
      shell.showToast(err.message || "Could not dismiss review");
    } finally {
      busy.value = false;
    }
  }

  async function revert(bookId) {
    const ok = await staging.askConfirm({
      title: "Revert auto-staged book?",
      message: "Library hardlinks will be removed and the book returns to pending.",
      confirmLabel: "Revert",
      cancelLabel: "Keep staged",
      dangerous: true,
      preferenceKey: "away-revert",
    });
    if (!ok) return;
    await staging.withScrim("Reverting auto-stage…", async () => {
      await api(`/api/books/${encodeURIComponent(bookId)}/revert`, { method: "POST" });
      await load();
      await staging.afterMutation();
    });
    shell.showToast("Book reverted to pending");
  }

  async function act(action, item) {
    if (!item || busy.value) return;
    try {
      if (action === "detail") {
        if (item.book_id) await staging.openDetail(item.book_id);
        return;
      }
      busy.value = true;
      if (action === "dismiss" && item.id) await dismiss(item.id);
      else if (action === "revert" && item.book_id) await revert(item.book_id);
    } catch (err) {
      shell.showToast(err.message || "Request failed");
    } finally {
      busy.value = false;
    }
  }

  watch(
    () => shell.mode.value,
    (mode) => {
      if (mode === "home") void load();
    },
  );

  return { items, loaded, busy, errorText, load, dismissAll, act };
}
