import { PAGE_SIZE } from "./staging.js";

export const GROUP_PAGE_SIZE = PAGE_SIZE;

const KIND = {
  pending: {
    label: "Pending",
    title: "Multiple pending books share the same library target",
  },
  staged: {
    label: "Staged",
    title: "A book is already in the library at this target",
  },
  mixed: {
    label: "Mixed",
    title: "Multiple pending books compete with an existing library folder",
  },
};

const MERGE_DRAFT_PREFIX = "audiobook-stager.mergeDraft.";
const MERGE_STAGED_NAMES_PREFIX = "audiobook-stager.mergeStagedNames.";

export function buildUnifiedGroups(conflicts, merges) {
  const map = new Map();
  for (const conflict of conflicts || []) {
    if (!conflict || !conflict.target_key) continue;
    map.set(conflict.target_key, { target_key: conflict.target_key, conflict, merge: null });
  }
  for (const merge of merges || []) {
    if (!merge || !merge.target_key) continue;
    const existing = map.get(merge.target_key);
    if (existing) existing.merge = merge;
    else map.set(merge.target_key, { target_key: merge.target_key, conflict: null, merge });
  }
  return [...map.values()].sort((a, b) => a.target_key.localeCompare(b.target_key));
}

export function pageSlice(items, offset, pageSize = GROUP_PAGE_SIZE) {
  const list = Array.isArray(items) ? items : [];
  const size = pageSize > 0 ? pageSize : GROUP_PAGE_SIZE;
  const start = Math.max(0, Number(offset) || 0);
  return {
    total: list.length,
    offset: start,
    rows: list.slice(start, start + size),
  };
}

export function clampOffset(offset, total, pageSize = GROUP_PAGE_SIZE) {
  const size = pageSize > 0 ? pageSize : GROUP_PAGE_SIZE;
  if (!total || total <= 0) return 0;
  const max = Math.floor((total - 1) / size) * size;
  return Math.min(Math.max(0, offset || 0), max);
}

export function encodeTargetKey(targetKey) {
  return String(targetKey)
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

export function parseTargetKeyDisplay(targetKey) {
  const parts = String(targetKey || "").split("/").filter(Boolean);
  if (parts.length >= 3) {
    return { author: parts[0], series: parts[1], title: parts.slice(2).join("/"), seriesIndex: "" };
  }
  if (parts.length === 2) return { author: parts[0], title: parts[1], series: "", seriesIndex: "" };
  if (parts.length === 1) return { author: parts[0], title: "—", series: "", seriesIndex: "" };
  return { author: "—", title: "—", series: "", seriesIndex: "" };
}

export function targetSeriesLine(targetKey) {
  const parsed = parseTargetKeyDisplay(targetKey);
  if (!parsed.series) return "";
  return parsed.series;
}

export function canResolveSelect(group) {
  return Boolean(group && group.conflict && (group.conflict.sides || []).length >= 2);
}

export function mergeMembers(group) {
  if (!group) return [];
  if (group.merge) return group.merge.members || [];
  const eligible = new Set(group.conflict?.merge_eligible_seed_ids || []);
  return (group.conflict?.sides || []).filter((side) => side.type === "seed" && eligible.has(side.book_id));
}

export function canResolveMerge(group) {
  return mergeMembers(group).length >= 2;
}

export function defaultResolveMode(group) {
  if (canResolveSelect(group)) return "select";
  if (canResolveMerge(group)) return "merge";
  return "select";
}

export function mergeEndpoints(group) {
  const key = encodeTargetKey(group.target_key);
  if (group.merge) {
    return { preview: `/api/merges/${key}/preview`, approve: `/api/merges/${key}` };
  }
  return {
    preview: `/api/conflicts/${key}/merge/preview`,
    approve: `/api/conflicts/${key}/merge`,
  };
}

export function kindInfo(group) {
  const kind = group && group.conflict && group.conflict.conflict_kind;
  if (kind && KIND[kind]) return KIND[kind];
  if (kind) return { label: kind, title: "" };
  return { label: "Merge", title: "Split audiobook parts at the same target" };
}

export function sidesLabel(group) {
  if (!group) return "—";
  if (group.conflict) return `${(group.conflict.sides || []).length} sides`;
  return `${(group.merge?.members || []).length} parts`;
}

export function readMergeDraft(targetKey) {
  try {
    const raw = sessionStorage.getItem(`${MERGE_DRAFT_PREFIX}${targetKey}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(String) : null;
  } catch {
    return null;
  }
}

export function writeMergeDraft(targetKey, memberIds) {
  try {
    if (!memberIds || !memberIds.length) sessionStorage.removeItem(`${MERGE_DRAFT_PREFIX}${targetKey}`);
    else sessionStorage.setItem(`${MERGE_DRAFT_PREFIX}${targetKey}`, JSON.stringify(memberIds));
  } catch {
    /* private mode */
  }
}

export function readStagedNames(targetKey) {
  try {
    const raw = sessionStorage.getItem(`${MERGE_STAGED_NAMES_PREFIX}${targetKey}`);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).map(([source, name]) => [String(source), String(name)]));
  } catch {
    return {};
  }
}

export function writeStagedNames(targetKey, overrides) {
  try {
    if (!overrides || !Object.keys(overrides).length) {
      sessionStorage.removeItem(`${MERGE_STAGED_NAMES_PREFIX}${targetKey}`);
      return;
    }
    sessionStorage.setItem(`${MERGE_STAGED_NAMES_PREFIX}${targetKey}`, JSON.stringify(overrides));
  } catch {
    /* private mode */
  }
}

export function clearMergeSession(targetKey) {
  writeMergeDraft(targetKey, null);
  writeStagedNames(targetKey, null);
}

export function resolveStatus(group) {
  if (!group) return "—";
  if (group.conflict && group.conflict.winner_side_id) {
    const winner = group.conflict.winner_side_id;
    if (winner === "library") return "Keep library";
    const side = (group.conflict.sides || []).find((item) => item.side_id === winner);
    return side?.source_path || side?.book_id || winner;
  }
  const draft = readMergeDraft(group.target_key);
  if (draft && draft.length >= 2) return `${draft.length} parts selected`;
  return "—";
}

export function formatBytes(value) {
  const size = Number(value) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function invalidStagedNames(rows) {
  const names = (rows || []).map((row) => String(row.staged_name || "").trim());
  if (!names.length) return false;
  if (names.some((name) => !name)) return true;
  return new Set(names).size !== names.length;
}

export function filenameConflicts(preview) {
  return (preview && preview.filename_conflicts) || [];
}

export function partialSummary(book) {
  const staging = (book && book.staging) || {};
  const parts = [`${staging.linked_count ?? 0} linked`];
  if (staging.unlinked_count) parts.push(`${staging.unlinked_count} not linked`);
  if (staging.source_missing_count) parts.push(`${staging.source_missing_count} source missing`);
  const extra = (staging.extra_library_files || []).length;
  if (extra) parts.push(`${extra} extra library file${extra === 1 ? "" : "s"}`);
  return parts.join(", ");
}

export function partialLinkedLabel(book) {
  const staging = book && book.staging;
  if (!staging) return "—";
  return `${staging.linked_count} / ${staging.total}`;
}

export function partialFullyLinked(book) {
  const staging = book && book.staging;
  if (!staging) return false;
  return staging.linked_count === staging.total && staging.unlinked_count === 0 && staging.total > 0;
}

export function canRunCompletePartial(book) {
  if (!book || book.status !== "partial_staged" || !book.staging) return false;
  return book.staging.unlinked_count > 0 || partialFullyLinked(book);
}

export function completePartialLabel(book, { detail = false } = {}) {
  if (partialFullyLinked(book)) return detail ? "Complete staging" : "Complete";
  return detail ? "Link missing files" : "Link missing";
}

export function candidateLine(candidate) {
  if (!candidate || typeof candidate !== "object") return String(candidate ?? "");
  const series = [candidate.series, candidate.series_index].filter(Boolean).join(" #");
  return [candidate.author, candidate.title, series, candidate.source].filter(Boolean).join(" · ");
}
