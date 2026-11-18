import { AWAY_TIMEOUT_MS } from "./constants.js";

export function idleReloadDue(hiddenAt, now, { scanActive = false, autoActive = false } = {}) {
  if (!hiddenAt || scanActive || autoActive) return false;
  return now - hiddenAt >= AWAY_TIMEOUT_MS;
}
