import { computed, ref, watch } from "vue";

import { api } from "./api.js";
import { GROUP_PAGE_SIZE, canRunCompletePartial, clampOffset, pageSlice } from "./groups.js";

export function usePartial(shell, staging) {
  const offset = ref(0);
  const busyId = ref("");

  const all = computed(() => shell.libraryLists.value.partial || []);
  const page = computed(() => pageSlice(all.value, offset.value, GROUP_PAGE_SIZE));
  const rows = computed(() => page.value.rows);
  const total = computed(() => all.value.length);
  const canPrev = computed(() => offset.value > 0);
  const canNext = computed(() => offset.value + GROUP_PAGE_SIZE < total.value);
  const pageFrom = computed(() => (total.value ? offset.value + 1 : 0));
  const pageTo = computed(() => Math.min(offset.value + rows.value.length, total.value));

  watch(total, (count) => {
    offset.value = clampOffset(offset.value, count, GROUP_PAGE_SIZE);
  });

  function prevPage() {
    offset.value = Math.max(0, offset.value - GROUP_PAGE_SIZE);
  }

  function nextPage() {
    if (canNext.value) offset.value += GROUP_PAGE_SIZE;
  }

  async function openDetail(bookId) {
    try {
      await staging.openDetail(bookId);
    } catch (err) {
      shell.showToast(err.message || "Could not open book");
    }
  }

  function rememberDetail(bookId, book) {
    if (staging.detailBook && staging.detailBook.id === bookId) staging.detailBook = book;
  }

  async function complete(bookId) {
    if (!bookId || busyId.value) return;
    busyId.value = bookId;
    try {
      let result = null;
      await staging.withScrim("Linking missing files…", async () => {
        result = await api(`/api/books/${encodeURIComponent(bookId)}/complete-partial`, { method: "POST" });
        rememberDetail(bookId, result);
        await staging.afterMutation();
      });
      if (result && result.status === "staged") shell.showToast("Book fully staged");
      else if (result && result.status === "partial_staged" && result.staging) {
        shell.showToast(`Linked files; ${result.staging.linked_count} / ${result.staging.total} in library`);
      } else shell.showToast("Missing files linked");
    } catch (err) {
      shell.showToast(err.message ? `Could not link missing files. ${err.message}` : "Could not link missing files");
    } finally {
      busyId.value = "";
    }
  }

  async function removeExtras(book) {
    const bookId = book && book.id;
    const extras = (book && book.staging && book.staging.extra_library_files) || [];
    if (!bookId || busyId.value || !extras.length) return;
    const ok = await staging.askConfirm({
      title: "Remove extra library files?",
      message: `${extras.length} audio file${extras.length === 1 ? "" : "s"} in the library folder will be deleted. Source files are not affected.`,
      confirmLabel: "Remove extras",
      cancelLabel: "Cancel",
      dangerous: true,
      preferenceKey: "partial-remove-extras",
    });
    if (!ok) return;
    busyId.value = bookId;
    try {
      let result = null;
      await staging.withScrim("Removing extra files…", async () => {
        result = await api(`/api/books/${encodeURIComponent(bookId)}/remove-extras`, { method: "POST" });
        rememberDetail(bookId, result);
        await staging.afterMutation();
      });
      shell.showToast("Extra library files removed");
      return result;
    } catch (err) {
      shell.showToast(err.message || "Could not remove extra files");
    } finally {
      busyId.value = "";
    }
  }

  return {
    PAGE_SIZE: GROUP_PAGE_SIZE,
    offset,
    rows,
    total,
    pageFrom,
    pageTo,
    canPrev,
    canNext,
    busyId,
    canRunCompletePartial,
    openDetail,
    complete,
    removeExtras,
    prevPage,
    nextPage,
  };
}
