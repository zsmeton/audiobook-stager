export function providerChip(provider, testResult, { pending = false } = {}) {
  let statusClass = "ready";
  if (testResult) {
    if (testResult.status === "ok") statusClass = "ok";
    else if (testResult.status === "error") statusClass = "error";
  }
  if (statusClass === "ready" && provider.requires_key && !provider.configured) {
    statusClass = "missing-key";
  }
  const showPending = pending && statusClass !== "missing-key";
  return {
    id: provider.id,
    label: provider.label || provider.id,
    statusClass: showPending ? "pending" : statusClass,
    title: showPending ? "Checking…" : (testResult && testResult.message) || provider.label || "",
    mark: showPending ? "" : statusClass === "missing-key" ? "key" : "",
  };
}
