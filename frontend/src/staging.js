export const PAGE_SIZE = 50;
export const SEARCH_DEBOUNCE_MS = 250;
export const PREVIEW_DEBOUNCE_MS = 300;
export const STAGING_SORT_KEY = "audiobook-stager.stagingSort";
export const CONFIRM_SKIP_PREFIX = "stager.confirmSkip.";

const SORT_KEYS = new Set(["source_path", "metadata", "confidence"]);

export const METADATA_FIELDS = [
  {
    key: "author",
    label: "Author",
    draft: "author",
    chosen: "chosen_author",
    set: "chosen_author_set",
    suggested: "suggested_author",
    effective: "effective_author",
  },
  {
    key: "title",
    label: "Title",
    draft: "title",
    chosen: "chosen_title",
    set: "chosen_title_set",
    suggested: "suggested_title",
    effective: "effective_title",
  },
  {
    key: "series",
    label: "Series",
    draft: "series",
    chosen: "chosen_series",
    set: "chosen_series_set",
    suggested: "suggested_series",
    effective: "effective_series",
  },
  {
    key: "series_index",
    label: "Series #",
    draft: "seriesIndex",
    chosen: "chosen_series_index",
    set: "chosen_series_index_set",
    suggested: "suggested_series_index",
    effective: "effective_series_index",
  },
];

export const BULK_BY_FILTER = {
  pending: {
    label: "Approve Selected",
    empty: "Select pending books to approve",
    path: "/api/books/bulk-approve",
    scrim: "Staging selected books…",
    confirm: false,
  },
  staged: {
    label: "Unstage Selected",
    empty: "Select staged books to unstage",
    path: "/api/books/bulk-revert",
    scrim: "Unstaging selected books…",
    confirm: true,
  },
  skipped: {
    label: "Unskip Selected",
    empty: "Select skipped books to unskip",
    path: "/api/books/bulk-unskip",
    scrim: "",
    confirm: false,
  },
};

export function buildBooksSearch({ status, q, limit, offset }) {
  const params = new URLSearchParams();
  params.set("partitioned", "true");
  params.set("status", status || "pending");
  params.set("q", q || "");
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return params;
}

export function loadStagingSort() {
  try {
    const raw = localStorage.getItem(STAGING_SORT_KEY);
    if (!raw) return { key: "source_path", dir: "asc" };
    const parsed = JSON.parse(raw);
    if (!SORT_KEYS.has(parsed.key)) return { key: "source_path", dir: "asc" };
    return { key: parsed.key, dir: parsed.dir === "desc" ? "desc" : "asc" };
  } catch {
    return { key: "source_path", dir: "asc" };
  }
}

export function saveStagingSort(sort) {
  try {
    localStorage.setItem(STAGING_SORT_KEY, JSON.stringify(sort));
  } catch {
    /* private mode */
  }
}

function displayAuthor(book) {
  return (book.effective_author || book.chosen_author || book.suggested_author || "").trim().toLowerCase();
}

function displayTitle(book) {
  return (book.effective_title || book.chosen_title || book.suggested_title || book.flatten_name || "")
    .trim()
    .toLowerCase();
}

export function isMetadataOverridden(book) {
  if (!book) return false;
  if (book.any_chosen_set) return true;
  return Boolean(
    book.chosen_author_set || book.chosen_title_set || book.chosen_series_set || book.chosen_series_index_set,
  );
}

function sortConfidence(book) {
  if (isMetadataOverridden(book)) return 1;
  const value = Number(book.staging_confidence ?? book.confidence);
  return Number.isFinite(value) ? value : 0;
}

export function sortStagingBooks(books, sort) {
  const dir = sort && sort.dir === "desc" ? -1 : 1;
  const key = sort && sort.key;
  return [...(books || [])].sort((a, b) => {
    let cmp = 0;
    if (key === "metadata") {
      cmp = displayAuthor(a).localeCompare(displayAuthor(b));
      if (cmp === 0) cmp = displayTitle(a).localeCompare(displayTitle(b));
    } else if (key === "confidence") {
      cmp = sortConfidence(a) - sortConfidence(b);
    } else {
      cmp = (a.source_path || "").localeCompare(b.source_path || "", undefined, { sensitivity: "base" });
    }
    if (cmp !== 0) return cmp * dir;
    return (a.source_path || "").localeCompare(b.source_path || "", undefined, { sensitivity: "base" });
  });
}

export function confidenceLabel(book) {
  if (isMetadataOverridden(book)) return "Manual";
  const value = Number(book.staging_confidence ?? book.confidence);
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(2);
}

export function collectMergeIds(merges) {
  const ids = new Set();
  for (const group of merges || []) {
    for (const id of group.member_book_ids || []) ids.add(String(id));
    for (const member of group.members || []) {
      if (member && member.book_id) ids.add(String(member.book_id));
      if (member && member.id) ids.add(String(member.id));
    }
  }
  return ids;
}

export function isRowSelectable(book, status, mergeIds) {
  if (!book || book.status !== status) return false;
  if (status === "pending" && (book.in_conflict || (mergeIds && mergeIds.has(String(book.id))))) return false;
  return true;
}

export function emptyStagingMessage(status, q) {
  if ((q || "").trim()) return "No books match your search.";
  if (status === "pending") return "All books staged.";
  if (status === "staged") return "No staged books.";
  if (status === "skipped") return "No skipped books.";
  return "No books match this filter.";
}

export function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
  if (!seconds) return "0m";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remain = seconds % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes > 0) return remain > 0 ? `${minutes}m ${remain}s` : `${minutes}m`;
  return `${remain}s`;
}

export function seriesLine(book) {
  const series = String(book.effective_series || "").trim();
  const index = String(book.effective_series_index || "").trim();
  if (!series && !index) return "";
  if (series && index) return `${series} #${index}`;
  return series || `#${index}`;
}

export function confirmSkipped(preferenceKey) {
  if (!preferenceKey) return false;
  try {
    return localStorage.getItem(`${CONFIRM_SKIP_PREFIX}${preferenceKey}`) === "1";
  } catch {
    return false;
  }
}

export function rememberConfirmSkip(preferenceKey) {
  if (!preferenceKey) return;
  try {
    localStorage.setItem(`${CONFIRM_SKIP_PREFIX}${preferenceKey}`, "1");
  } catch {
    /* private mode */
  }
}
