export const AWAY_TIMEOUT_MS = 15 * 60 * 1000;
export const SCAN_POLL_MS = 1500;
export const SCAN_POLL_ERROR_MS = 3000;
export const FINISH_SCAN_ANIMATION_KEY = "audiobook-stager.finishScanAnimation";

export function finishScanAnimationEnabled() {
  try {
    const value = localStorage.getItem(FINISH_SCAN_ANIMATION_KEY);
    if (value === null) return true;
    return value !== "false";
  } catch {
    return true;
  }
}

export function setFinishScanAnimationEnabled(enabled) {
  try {
    localStorage.setItem(FINISH_SCAN_ANIMATION_KEY, enabled ? "true" : "false");
  } catch {
    /* private mode */
  }
}
