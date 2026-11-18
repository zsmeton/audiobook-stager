function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function summarizeBooks(payload) {
  const stats = payload && payload.stats ? payload.stats : {};
  return {
    pending: num(stats.pending),
    staged: num(stats.staged),
    skipped: num(stats.skipped),
    partial: Array.isArray(payload && payload.partial)
      ? payload.partial.length
      : num(stats.partial_staged),
    conflicts: Array.isArray(payload && payload.conflicts)
      ? payload.conflicts.length
      : num(stats.conflicts),
    staging: Array.isArray(payload && payload.staging) ? payload.staging.length : 0,
  };
}

export function formatBookStatus(summary) {
  if (!summary) return "Books not loaded";
  return `pending ${summary.pending} · staged ${summary.staged} · skipped ${summary.skipped} · partial ${summary.partial} · conflicts ${summary.conflicts} · staging ${summary.staging}`;
}
