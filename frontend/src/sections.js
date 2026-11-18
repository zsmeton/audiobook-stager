export const SECTION_COLLAPSE_PREFIX = "stager.sectionCollapsed.";

export const SECTION_IDS = ["awaySection", "conflictsSection", "partialSection", "stagingSection"];

export function readSectionCollapsed(sectionId) {
  try {
    return localStorage.getItem(`${SECTION_COLLAPSE_PREFIX}${sectionId}`) === "1";
  } catch {
    return false;
  }
}

export function writeSectionCollapsed(sectionId, collapsed) {
  if (!sectionId) return;
  try {
    if (collapsed) localStorage.setItem(`${SECTION_COLLAPSE_PREFIX}${sectionId}`, "1");
    else localStorage.removeItem(`${SECTION_COLLAPSE_PREFIX}${sectionId}`);
  } catch {
    /* private mode */
  }
}
