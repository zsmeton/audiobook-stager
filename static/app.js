let currentScanId = null;
let pollTimer = null;
let currentAutoRunId = null;
let autoPollTimer = null;
let sectionsBlocked = false;
let sectionsBlockedKind = null;
let selectedBookId = null;
let currentConflictKey = null;
let conflictQueue = [];
let conflictSessionBookIds = new Set();
let lastConflicts = [];
let lastMerges = [];
let mergeBookIds = new Set();
let currentResolveKey = null;
let currentResolveMode = "select";
let mergePreviewCache = null;
const MERGE_DRAFT_PREFIX = "audiobook-stager.mergeDraft.";
const MERGE_STAGED_NAMES_PREFIX = "audiobook-stager.mergeStagedNames.";
const MERGE_SORT_MODE_PREFIX = "audiobook-stager.mergeSortMode.";
const STAGING_SORT_KEY = "audiobook-stager.stagingSort";
const STAGING_SORT_KEYS = new Set(["source_path", "metadata", "confidence"]);
let mergeSelectionSnapshot = null;
let stagingSort = { key: "source_path", dir: "asc" };
let cachedBooksPayload = null;
let stagingScrimDepth = 0;
let awayHiddenAt = null;
let bootstrapActionHandler = null;
let bootstrapScanActive = false;
let autoMinConfidence = 0.9;

const AWAY_TIMEOUT_MS = 15 * 60 * 1000;
const SCAN_POLL_MS = 1500;
const SCAN_DRIP_MIN_TICK_MS = 16;
const FINISH_SCAN_ANIMATION_KEY = "audiobook-stager.finishScanAnimation";
const SCORE_RGB_RED = { r: 232, g: 93, b: 93 };
const SCORE_RGB_YELLOW = { r: 240, g: 180, b: 41 };
const SCORE_RGB_GREEN = { r: 62, g: 207, b: 142 };
const SCORE_RGB_GREEN_BRIGHT = { r: 130, g: 245, b: 185 };
const DURATION_PLACEHOLDER = "—";
const selectionByFilter = {
  pending: new Set(),
  staged: new Set(),
  skipped: new Set(),
};

const STAGING_BULK_CONFIG = {
  pending: {
    label: "Approve Selected",
    emptyTitle: "Select pending books to approve",
    scrim: "Staging selected books…",
  },
  staged: {
    label: "Unstage Selected",
    emptyTitle: "Select staged books to unstage",
    scrim: "Unstaging selected books…",
    confirm: true,
  },
  skipped: {
    label: "Unskip Selected",
    emptyTitle: "Select skipped books to unskip",
    scrim: null,
  },
};
const durationSkeletonHtml =
  '<span class="skeleton skeleton-text" aria-label="Loading duration"></span>';

const els = {
  scanBtn: document.getElementById("scanBtn"),
  statusFilter: document.getElementById("statusFilter"),
  searchBox: document.getElementById("searchBox"),
  stagingBulkBtn: document.getElementById("stagingBulkBtn"),
  stagingSortSelect: document.getElementById("stagingSortSelect"),
  mobileBulkBar: document.getElementById("mobileBulkBar"),
  mobileBulkBtn: document.getElementById("mobileBulkBtn"),
  mobileBulkCount: document.getElementById("mobileBulkCount"),
  selectAll: document.getElementById("selectAll"),
  booksList: document.getElementById("booksList"),
  booksListWrap: document.getElementById("booksListWrap"),
  partialList: document.getElementById("partialList"),
  partialListWrap: document.getElementById("partialListWrap"),
  conflictsListWrap: document.getElementById("conflictsListWrap"),
  conflictsList: document.getElementById("conflictsList"),
  stats: document.getElementById("stats"),
  detailDialog: document.getElementById("detailDialog"),
  detailContent: document.getElementById("detailContent"),
  detailLookup: document.getElementById("detailLookup"),
  conflictDialog: document.getElementById("conflictDialog"),
  conflictDialogTitle: document.getElementById("conflictDialogTitle"),
  conflictDialogContent: document.getElementById("conflictDialogContent"),
  conflictApproveBtn: document.getElementById("conflictApproveBtn"),
  conflictNextBtn: document.getElementById("conflictNextBtn"),
  conflictSaveAllBtn: document.getElementById("conflictSaveAllBtn"),
  conflictApprovePreview: document.getElementById("conflictApprovePreview"),
  mergeApproveBtn: document.getElementById("mergeApproveBtn"),
  mergeApprovePreview: document.getElementById("mergeApprovePreview"),
  toast: document.getElementById("toast"),
  stagingScrim: document.getElementById("stagingScrim"),
  stagingScrimMessage: document.getElementById("stagingScrimMessage"),
  settingsBtn: document.getElementById("settingsBtn"),
  settingsDialog: document.getElementById("settingsDialog"),
  settingsContent: document.getElementById("settingsContent"),
  settingsEnabled: document.getElementById("settingsEnabled"),
  settingsScanManualHints: document.getElementById("settingsScanManualHints"),
  settingsLviSearch: document.getElementById("settingsLviSearch"),
  settingsLviBoost: document.getElementById("settingsLviBoost"),
  settingsInterval: document.getElementById("settingsInterval"),
  settingsConfidence: document.getElementById("settingsConfidence"),
  settingsLockTimeout: document.getElementById("settingsLockTimeout"),
  settingsFinishScanAnimation: document.getElementById("settingsFinishScanAnimation"),
  settingsLastRun: document.getElementById("settingsLastRun"),
  settingsSaveBtn: document.getElementById("settingsSaveBtn"),
  settingsRunNowBtn: document.getElementById("settingsRunNowBtn"),
  settingsClearCacheBtn: document.getElementById("settingsClearCacheBtn"),
  titleExtractionAdvancedPanel: document.getElementById("titleExtractionAdvancedPanel"),
  titleCleanupStepsBody: document.getElementById("titleCleanupStepsBody"),
  titleExtractionPreviewBtn: document.getElementById("titleExtractionPreviewBtn"),
  titleExtractionPreviewBody: document.getElementById("titleExtractionPreviewBody"),
  titleExtractionPreviewEmpty: document.getElementById("titleExtractionPreviewEmpty"),
  titleExtractionPreviewTable: document.getElementById("titleExtractionPreviewTable"),
  awaySection: document.getElementById("awaySection"),
  awayCount: document.getElementById("awayCount"),
  awayEmpty: document.getElementById("awayEmpty"),
  awayListWrap: document.getElementById("awayListWrap"),
  awayList: document.getElementById("awayList"),
  awayContent: document.getElementById("awayContent"),
  dismissAllAwayBtn: document.getElementById("dismissAllAwayBtn"),
  conflictsSection: document.getElementById("conflictsSection"),
  conflictsCount: document.getElementById("conflictsCount"),
  conflictsEmpty: document.getElementById("conflictsEmpty"),
  conflictsContent: document.getElementById("conflictsContent"),
  partialSection: document.getElementById("partialSection"),
  partialCount: document.getElementById("partialCount"),
  partialEmpty: document.getElementById("partialEmpty"),
  partialContent: document.getElementById("partialContent"),
  stagingSection: document.getElementById("stagingSection"),
  stagingCount: document.getElementById("stagingCount"),
  stagingEmpty: document.getElementById("stagingEmpty"),
  stagingContent: document.getElementById("stagingContent"),
  confirmDialog: document.getElementById("confirmDialog"),
  confirmTitle: document.getElementById("confirmTitle"),
  confirmMessage: document.getElementById("confirmMessage"),
  confirmOkBtn: document.getElementById("confirmOkBtn"),
  confirmCancelBtn: document.getElementById("confirmCancelBtn"),
  confirmDontAgain: document.getElementById("confirmDontAgain"),
  confirmDontAgainLabel: document.getElementById("confirmDontAgainLabel"),
  bootstrapScrim: document.getElementById("bootstrapScrim"),
  bootstrapSpinner: document.getElementById("bootstrapSpinner"),
  bootstrapTitle: document.getElementById("bootstrapTitle"),
  bootstrapMessage: document.getElementById("bootstrapMessage"),
  bootstrapActionBtn: document.getElementById("bootstrapActionBtn"),
  bootstrapProviders: document.getElementById("bootstrapProviders"),
  bootstrapProviderList: document.getElementById("bootstrapProviderList"),
  bootstrapStackWrap: document.getElementById("bootstrapStackWrap"),
  bootstrapStackViz: document.getElementById("bootstrapStackViz"),
  bootstrapStackCanvas: document.getElementById("bootstrapStackCanvas"),
  bootstrapScanLabel: document.getElementById("bootstrapScanLabel"),
  bootstrapCancelBtn: document.getElementById("bootstrapCancelBtn"),
};

const STACK_VIZ = {
  scanId: null,
  spines: [],
  stackCount: 4,
  spineScale: 1,
  favoredStack: -1,
  maxStackHeightPx: 120,
  baseSpineHeightPx: 5,
  baseSpineWidthPx: 26,
};

const STACK_COLUMN_GAP_PX = 8;
const STACK_SHELF_HEIGHT_PX = 12;
const STACK_EMPTY_COLUMN_WIDTH_PX = 24;
const STACK_CANVAS_HEIGHT_PX = STACK_VIZ.maxStackHeightPx + STACK_SHELF_HEIGHT_PX;

const TITLE_EXTRACTION_STEPS = [
  {
    id: "edition",
    label: "Edition",
    tip: "Strip unabridged/abridged and bracketed edition tags, e.g. “(Unabridged)” or “[Audiobook]”.",
    example: "Dune (Unabridged) → Dune",
  },
  {
    id: "part_prefix",
    label: "Part markers",
    tip: "Remove leading track/part prefixes and trailing “Part 01” / “Pt 2” tails.",
    example: "Dark Age - Part 01 → Dark Age",
  },
  {
    id: "format_noise",
    label: "Format noise",
    tip: "Drop bitrate, codec, and bare-year release noise from the title string.",
    example: "Project Hail Mary 128k M4B → Project Hail Mary",
  },
  {
    id: "leading_index",
    label: "Leading index",
    tip: "Remove conservative leading indices such as “01 - ” or “1. ”.",
    example: "01 - Red Rising → Red Rising",
  },
  {
    id: "index_trailing",
    label: "Trailing index",
    tip: "Remove zero-padded trailing disc/track numbers like “Title 01”. More aggressive — off by default.",
    example: "The Heroes 01 → The Heroes",
  },
  {
    id: "colon_split",
    label: "Colon split",
    tip: "Keep the main title before a colon subtitle, e.g. “Athens: The Rivalry” → “Athens”.",
    example: "Athens: The Rivalry → Athens",
  },
  {
    id: "series_name",
    label: "Series name",
    tip: "Strip embedded series folder/tag names when they are not the book title.",
    example: "Mistborn The Final Empire → The Final Empire",
  },
  {
    id: "author",
    label: "Strip author",
    tip: "Remove known author prefix/suffix from the title when artist/album tags identify the author.",
    example: "Andy Weir - Artemis → Artemis",
  },
  {
    id: "junk_tail",
    label: "Junk tail",
    tip: "Remove junk subtitle tails like “ - A Novel” or “ - Unabridged”.",
    example: "Neuromancer - A Novel → Neuromancer",
  },
  {
    id: "multipart",
    label: "Multipart",
    tip: "Remove multi-file markers such as “(2 of 5)”.",
    example: "The Hobbit (2 of 5) → The Hobbit",
  },
  {
    id: "series_markers",
    label: "Series markers",
    tip: "Strip inline series markers like “Book 3”, “Vol. 2”, or “#1”.",
    example: "Morning Star Book 3 → Morning Star",
  },
  {
    id: "trim_edges",
    label: "Trim edges",
    tip: "Strip dangling spaces and separator punctuation left at the start or end after other cleanup.",
    example: "— Dark Age ~ → Dark Age",
  },
];

const TITLE_EXTRACTION_MODE_TIPS = {
  conservative: "Album tag first, then title tag, then filename, then folder.",
  balanced: "Finds the best shared title across tags and paths. Good default.",
  advanced: "Like Balanced, with optional extra cleanup you control.",
};

const ADVANCED_DEFAULT_PRE = [
  "edition",
  "part_prefix",
  "format_noise",
  "leading_index",
  "colon_split",
  "series_name",
];
const ADVANCED_DEFAULT_POST = ["colon_split", "trim_edges"];

let activeSettingsTab = "general";
let titleExtractionPreviewBookIds = [];
let titleExtractionPreviewTimer = null;

const scanProgressAnimator = {
  displayBooks: 0,
  displayMeta: 0,
  targetBooks: 0,
  targetMeta: 0,
  booksTotal: 0,
  metaTotal: 0,
  scanId: null,
  serverScan: null,
  dripTimer: null,
  finishTailTimer: null,
  finishing: false,

  getFinishScanAnimation() {
    try {
      const value = localStorage.getItem(FINISH_SCAN_ANIMATION_KEY);
      if (value === null) return true;
      return value !== "false";
    } catch (_err) {
      return true;
    }
  },

  setFinishScanAnimation(enabled) {
    try {
      localStorage.setItem(FINISH_SCAN_ANIMATION_KEY, enabled ? "true" : "false");
    } catch (_err) {
      /* ignore */
    }
  },

  clearDripTimer() {
    if (this.dripTimer) {
      clearTimeout(this.dripTimer);
      this.dripTimer = null;
    }
  },

  clearFinishTailTimer() {
    if (this.finishTailTimer) {
      clearTimeout(this.finishTailTimer);
      this.finishTailTimer = null;
    }
  },

  reset(scanId = null) {
    this.clearDripTimer();
    this.clearFinishTailTimer();
    this.displayBooks = 0;
    this.displayMeta = 0;
    this.targetBooks = 0;
    this.targetMeta = 0;
    this.booksTotal = 0;
    this.metaTotal = 0;
    this.scanId = scanId;
    this.serverScan = null;
    this.finishing = false;
  },

  booksBehind() {
    if (this.inDiscoveryPhase()) {
      return Math.max(0, this.targetBooks - this.displayBooks);
    }
    return 0;
  },

  metaBehind() {
    if (this.inDiscoveryPhase()) return 0;
    return Math.max(0, this.targetMeta - this.displayMeta);
  },

  inDiscoveryPhase() {
    const phase = this.serverScan?.scan_phase;
    if (phase === "metadata") return false;
    if (phase === "discovering" || phase === "indexing") return true;
    if (this.booksTotal > 0) {
      return this.displayBooks < this.booksTotal;
    }
    return true;
  },

  tickOnce() {
    if (this.booksBehind() > 0) {
      this.displayBooks += 1;
      return true;
    }
    if (this.metaBehind() > 0) {
      this.displayMeta += 1;
      return true;
    }
    return false;
  },

  getDisplay() {
    return {
      displayBooks: this.displayBooks,
      displayMeta: this.displayMeta,
      booksTotal: this.booksTotal,
      metaTotal: this.metaTotal,
      inDiscovery: this.inDiscoveryPhase(),
    };
  },

  render() {
    if (!this.serverScan || (!bootstrapScanActive && !this.finishing)) return;
    syncBootstrapScanUi(this.serverScan, this.getDisplay());
  },

  scheduleDripCycle() {
    this.clearDripTimer();
    const behind = this.booksBehind() || this.metaBehind();
    if (behind <= 0) return;

    const tickMs = Math.max(SCAN_DRIP_MIN_TICK_MS, Math.floor(SCAN_POLL_MS / behind));
    let remaining = behind;

    const step = () => {
      if (remaining <= 0) return;
      if (this.tickOnce()) {
        remaining -= 1;
        this.render();
      }
      if (remaining > 0 && (this.booksBehind() > 0 || this.metaBehind() > 0)) {
        this.dripTimer = setTimeout(step, tickMs);
      }
    };

    this.dripTimer = setTimeout(step, tickMs);
  },

  onPoll(scan) {
    this.serverScan = scan;
    if (scan?.id && this.scanId !== scan.id) {
      this.reset(scan.id);
    }

    const booksDiscovered = scan.books_discovered ?? scan.books_found ?? 0;
    const booksTotal = scan.books_total ?? scan.total_books ?? 0;
    const booksComplete = scan.books_complete ?? scan.metadata_done ?? 0;
    const metaTotal = scan.metadata_total ?? booksTotal;

    if (booksTotal > 0) {
      this.booksTotal = Math.max(this.booksTotal, booksTotal);
      this.metaTotal = Math.max(this.metaTotal, metaTotal || booksTotal);
      this.targetBooks = Math.max(this.targetBooks, booksTotal);
    } else {
      this.targetBooks = Math.max(this.targetBooks, booksDiscovered);
    }
    this.targetMeta = Math.max(this.targetMeta, booksComplete);

    this.scheduleDripCycle();
    this.render();
  },

  waitForFinishTail() {
    this.clearFinishTailTimer();
    return new Promise((resolve) => {
      this.finishTailTimer = setTimeout(() => {
        this.finishTailTimer = null;
        resolve();
      }, SCAN_POLL_MS);
    });
  },

  async handleScanComplete(scan, onDone) {
    this.onPoll(scan);
    const shouldAnimate =
      scan.status === "completed" && this.getFinishScanAnimation();
    if (!shouldAnimate) {
      this.reset();
      await onDone();
      return;
    }

    this.finishing = true;
    this.scheduleDripCycle();
    this.render();
    await this.waitForFinishTail();
    this.reset();
    await onDone();
  },
};

let cachedProviders = [];
let cancelInFlight = false;
let cancelPending = false;

function scanIsCancelling(scan) {
  return cancelPending || (scan?.message || "").includes("Cancelling");
}

function scanIsIndexing(scan) {
  return scan?.scan_phase === "indexing" || (scan?.message || "").includes("Indexing");
}

function scanInDiscoveryPhase(scan, displayBooks, booksTotal) {
  const phase = scan?.scan_phase;
  if (phase === "metadata") return false;
  if (phase === "discovering" || phase === "indexing") return true;
  if (booksTotal > 0) {
    const discovered = scan?.books_discovered ?? scan?.books_found ?? 0;
    return discovered < booksTotal;
  }
  return true;
}

let confirmResolver = null;
let confirmPreferenceKey = null;

function hashSeed(input) {
  let h = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function seededUnit(seed) {
  const x = Math.sin(seed) * 10000;
  return x - Math.floor(x);
}

function resetStackViz(scanId) {
  STACK_VIZ.scanId = scanId;
  STACK_VIZ.spines = [];
  STACK_VIZ.stackCount = 4;
  STACK_VIZ.spineScale = 1;
  STACK_VIZ.favoredStack = -1;
  const canvas = els.bootstrapStackCanvas;
  if (canvas) {
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
  if (scanId === null) {
    scanProgressAnimator.reset();
  }
}

function stackHeightPx(stackIndex) {
  return STACK_VIZ.spines
    .filter((s) => s.stackIndex === stackIndex)
    .reduce((sum, s) => sum + STACK_VIZ.baseSpineHeightPx * s.heightFactor * STACK_VIZ.spineScale, 0);
}

function tallestStackHeightPx() {
  let max = 0;
  for (let i = 0; i < STACK_VIZ.stackCount; i += 1) {
    max = Math.max(max, stackHeightPx(i));
  }
  return max;
}

function pickWeightedStackIndex() {
  const weights = [];
  let total = 0;
  for (let i = 0; i < STACK_VIZ.stackCount; i += 1) {
    const w = i === STACK_VIZ.favoredStack ? 3 : 1;
    weights.push(w);
    total += w;
  }
  let roll = seededUnit(hashSeed(`${STACK_VIZ.scanId}:pick:${STACK_VIZ.spines.length}`)) * total;
  for (let i = 0; i < weights.length; i += 1) {
    roll -= weights[i];
    if (roll <= 0) return i;
  }
  return STACK_VIZ.stackCount - 1;
}

function maybeRescaleStacks() {
  const limit = STACK_VIZ.maxStackHeightPx;
  if (tallestStackHeightPx() < limit) return;
  STACK_VIZ.spineScale *= 0.8;
  STACK_VIZ.stackCount += 1;
  STACK_VIZ.favoredStack = STACK_VIZ.stackCount - 1;
}

function createSpine(bookIndex) {
  const seed = hashSeed(`${STACK_VIZ.scanId}:${bookIndex}`);
  const stackIndex = pickWeightedStackIndex();
  STACK_VIZ.spines.push({
    stackIndex,
    hue: Math.floor(seededUnit(seed) * 360),
    widthFactor: 0.82 + seededUnit(seed + 1) * 0.36,
    heightFactor: 0.75 + seededUnit(seed + 3) * 0.55,
    xOffset: Math.round((seededUnit(seed + 2) - 0.5) * 5),
    metaFilled: false,
  });
  maybeRescaleStacks();
}

function rebuildStackViz(scanId, booksFound, metadataDone) {
  if (STACK_VIZ.scanId !== scanId) {
    resetStackViz(scanId);
  }
  while (STACK_VIZ.spines.length < booksFound) {
    createSpine(STACK_VIZ.spines.length);
  }
  for (let i = 0; i < STACK_VIZ.spines.length; i += 1) {
    STACK_VIZ.spines[i].metaFilled = i < metadataDone;
  }
  renderStackVizCanvas();
}

function spineLayerHeightPx(spine) {
  return Math.max(3, STACK_VIZ.baseSpineHeightPx * spine.heightFactor * STACK_VIZ.spineScale);
}

function spineLayerWidthPx(spine) {
  return Math.max(12, STACK_VIZ.baseSpineWidthPx * spine.widthFactor * STACK_VIZ.spineScale);
}

function ghostSpineHeightPx() {
  return STACK_VIZ.baseSpineHeightPx * STACK_VIZ.spineScale;
}

function ghostSpineWidthPx() {
  return Math.max(12, STACK_VIZ.baseSpineWidthPx * STACK_VIZ.spineScale);
}

function drawGhostSpine(ctx, x, y, w, h) {
  ctx.strokeStyle = "rgba(139, 146, 160, 0.35)";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(x + 0.75, y + 0.75, Math.max(1, w - 1.5), Math.max(1, h - 1.5));
}

function drawSpine(ctx, x, y, w, h, spine) {
  const gradient = ctx.createLinearGradient(x, y, x, y + h);
  if (spine.metaFilled) {
    gradient.addColorStop(0, `hsl(${spine.hue}, 52%, 52%)`);
    gradient.addColorStop(1, `hsl(${spine.hue}, 58%, 38%)`);
  } else {
    gradient.addColorStop(0, "#8b92a0");
    gradient.addColorStop(1, "#5a6170");
  }
  ctx.fillStyle = gradient;
  ctx.fillRect(x, y, w, h);

  if (h >= 2) {
    ctx.strokeStyle = spine.metaFilled ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.1)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, y + 0.5);
    ctx.lineTo(x + w, y + 0.5);
    ctx.stroke();

    ctx.strokeStyle = spine.metaFilled ? "rgba(0,0,0,0.22)" : "rgba(0,0,0,0.2)";
    ctx.beginPath();
    ctx.moveTo(x, y + h - 0.5);
    ctx.lineTo(x + w, y + h - 0.5);
    ctx.stroke();
  }
}

function drawBookshelf(ctx, x, y, width, height) {
  const gradient = ctx.createLinearGradient(x, y, x, y + height);
  gradient.addColorStop(0, "#7a5230");
  gradient.addColorStop(1, "#3d2512");
  ctx.fillStyle = gradient;
  ctx.fillRect(x, y, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, y + 0.5);
  ctx.lineTo(x + width, y + 0.5);
  ctx.stroke();

  const frontEdge = Math.min(2, height);
  ctx.fillStyle = "#2a1808";
  ctx.fillRect(x, y + height - frontEdge, width, frontEdge);

  ctx.strokeStyle = "rgba(0,0,0,0.15)";
  ctx.lineWidth = 1;
  const grainOffsets = [0.25, 0.45, 0.62, 0.82];
  for (const fraction of grainOffsets) {
    const gy = y + height * fraction;
    if (gy >= y + height - frontEdge - 0.5) continue;
    ctx.beginPath();
    ctx.moveTo(x + 1, gy);
    ctx.lineTo(x + width - 1, gy);
    ctx.stroke();
  }
}

function layoutStackColumns() {
  const columns = [];
  for (let stackIndex = 0; stackIndex < STACK_VIZ.stackCount; stackIndex += 1) {
    const columnSpines = STACK_VIZ.spines.filter((s) => s.stackIndex === stackIndex);
    if (columnSpines.length === 0) {
      columns.push({
        width: STACK_EMPTY_COLUMN_WIDTH_PX,
        height: 0,
        minX: 0,
        spines: [],
      });
      continue;
    }
    let minX = 0;
    let maxX = 12;
    let height = 0;
    const spines = columnSpines.map((spine) => {
      const h = spineLayerHeightPx(spine);
      const w = spineLayerWidthPx(spine);
      minX = Math.min(minX, spine.xOffset);
      maxX = Math.max(maxX, spine.xOffset + w);
      height += h;
      return { spine, h, w, xOffset: spine.xOffset };
    });
    columns.push({
      width: Math.max(maxX - minX, STACK_EMPTY_COLUMN_WIDTH_PX),
      height,
      minX,
      spines,
    });
  }

  let totalWidth = 0;
  columns.forEach((col, index) => {
    totalWidth += col.width;
    if (index > 0) totalWidth += STACK_COLUMN_GAP_PX;
  });
  const tallest = columns.reduce((max, col) => Math.max(max, col.height), 0);
  return { columns, totalWidth, tallest };
}

function computeStackContentWidth(layout) {
  if (layout.totalWidth > 0) return layout.totalWidth;
  return (
    STACK_VIZ.stackCount * STACK_EMPTY_COLUMN_WIDTH_PX +
    Math.max(0, STACK_VIZ.stackCount - 1) * STACK_COLUMN_GAP_PX
  );
}

function computeStackFitScale(totalWidth) {
  if (!els.bootstrapStackViz || !totalWidth) return 1;
  const available = els.bootstrapStackViz.clientWidth - 8;
  if (totalWidth <= available) return 1;
  return Math.max(0.35, available / totalWidth);
}

function computeStackVerticalFitScale(contentHeight) {
  if (!contentHeight || contentHeight <= STACK_CANVAS_HEIGHT_PX) return 1;
  return STACK_CANVAS_HEIGHT_PX / contentHeight;
}

function setCanvasSize(canvas, displayWidth, displayHeight) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(displayWidth * dpr));
  canvas.height = Math.max(1, Math.round(displayHeight * dpr));
  canvas.style.width = `${displayWidth}px`;
  canvas.style.height = `${displayHeight}px`;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function renderStackVizCanvas() {
  const canvas = els.bootstrapStackCanvas;
  if (!canvas || !els.bootstrapStackViz) return;

  const layout = layoutStackColumns();
  const contentWidth = computeStackContentWidth(layout);
  const stackTallest = Math.max(layout.tallest, ghostSpineHeightPx());
  const contentHeight = stackTallest + STACK_SHELF_HEIGHT_PX;
  const displayWidth = Math.max(1, els.bootstrapStackViz.clientWidth);
  const displayHeight = STACK_CANVAS_HEIGHT_PX;
  const fitScale = Math.min(
    computeStackFitScale(contentWidth),
    computeStackVerticalFitScale(contentHeight),
  );
  const ctx = setCanvasSize(canvas, displayWidth, displayHeight);
  if (!ctx) return;

  ctx.clearRect(0, 0, displayWidth, displayHeight);
  if (contentWidth <= 0) return;

  // Anchor canvas bottom to shelf bottom; stacks sit on shelf top at y = stackTallest.
  ctx.save();
  ctx.translate(displayWidth / 2, displayHeight);
  ctx.scale(fitScale, fitScale);
  ctx.translate(-contentWidth / 2, -(stackTallest + STACK_SHELF_HEIGHT_PX));

  drawBookshelf(ctx, 0, stackTallest, contentWidth, STACK_SHELF_HEIGHT_PX);

  let columnX = 0;
  for (const col of layout.columns) {
    const spineCount = col.spines.length;
    if (spineCount === 0) {
      const gw = ghostSpineWidthPx();
      const gh = ghostSpineHeightPx();
      const drawX = columnX + (col.width - gw) / 2;
      const drawY = stackTallest - gh;
      drawGhostSpine(ctx, drawX, drawY, gw, gh);
    } else {
      let y = stackTallest;
      for (let i = 0; i < spineCount; i += 1) {
        const { spine, h, w, xOffset } = col.spines[i];
        const y1 = Math.round(y);
        y -= h;
        const y0 = Math.round(y);
        const drawH = y1 - y0;
        const drawX = columnX + xOffset - col.minX;
        drawSpine(ctx, drawX, y0, w, drawH, spine);
      }
    }

    columnX += col.width + STACK_COLUMN_GAP_PX;
  }
  ctx.restore();
}

function formatAnimatedScanLabel(display) {
  const { displayBooks, displayMeta, booksTotal, metaTotal, inDiscovery } = display;
  if (booksTotal > 0 && !inDiscovery && metaTotal > 0) {
    return `Metadata: ${displayMeta} / ${metaTotal}`;
  }
  if (booksTotal > 0 && !inDiscovery) {
    return `${booksTotal} books found`;
  }
  if (displayBooks === 0 && booksTotal === 0) {
    return "Discovering…";
  }
  return `Discovering… ${displayBooks} found`;
}

function bootstrapScrimPanel() {
  return els.bootstrapScrim?.querySelector(".bootstrap-scrim-panel");
}

function setBootstrapScanPanelMode(active) {
  bootstrapScrimPanel()?.classList.toggle("bootstrap-scrim-panel--scan", !!active);
}

function syncBootstrapScanUi(scan, display = null) {
  const scanBooksTotal = scan.books_total ?? scan.total_books ?? 0;
  const discovered = scan.books_discovered ?? scan.books_found ?? 0;
  const complete = scan.books_complete ?? scan.metadata_done ?? 0;
  const animated = display || {
    displayBooks: discovered,
    displayMeta: complete,
    booksTotal: scanBooksTotal,
    metaTotal: scan.metadata_total ?? scanBooksTotal,
    inDiscovery: scanInDiscoveryPhase(scan, discovered, scanBooksTotal),
  };
  const { displayBooks, displayMeta, booksTotal, inDiscovery } = animated;
  const metaTotal = animated.metaTotal || booksTotal;
  const isCancelling = scanIsCancelling(scan);
  const showStacks = scan.status === "running" || scanProgressAnimator.finishing;

  els.bootstrapProviders?.classList.add("hidden");
  els.bootstrapStackWrap?.classList.toggle("hidden", !showStacks);
  els.bootstrapCancelBtn?.classList.toggle("hidden", scan.status !== "running");
  if (els.bootstrapCancelBtn && scan.status === "running") {
    els.bootstrapCancelBtn.textContent = "Cancel scan";
    els.bootstrapCancelBtn.disabled = isCancelling || cancelInFlight;
  }
  els.bootstrapSpinner?.classList.add("hidden");

  if (showStacks) {
    const spineCount = inDiscovery ? displayBooks : booksTotal || displayBooks;
    const vizScanId = scan.id || STACK_VIZ.scanId || "pending";
    rebuildStackViz(vizScanId, spineCount, displayMeta);
  }
  if (els.bootstrapTitle) {
    els.bootstrapTitle.classList.toggle("hidden", showStacks);
  }
  if (els.bootstrapScanLabel) {
    els.bootstrapScanLabel.textContent = "";
    els.bootstrapScanLabel.classList.toggle("hidden", showStacks);
  }
  if (els.bootstrapMessage) {
    els.bootstrapMessage.textContent = "";
    els.bootstrapMessage.classList.toggle("hidden", true);
  }
}

function providerStatusClass(provider, testResult) {
  if (testResult) {
    if (testResult.status === "ok") return "ok";
    if (testResult.status === "error") return "error";
  }
  if (provider.requires_key && !provider.configured) return "missing-key";
  return "ready";
}

function renderProviderList(providers, testResults = null, { pending = false } = {}) {
  if (!els.bootstrapProviderList) return;
  const byId = new Map((testResults || []).map((r) => [r.id, r]));
  els.bootstrapProviderList.innerHTML = providers
    .map((p) => {
      const result = byId.get(p.id);
      const cls = providerStatusClass(p, result);
      let icon;
      if (pending && cls !== "missing-key") {
        icon = '<span class="provider-status pending" title="Checking…"></span>';
      } else if (cls === "missing-key") {
        icon = '<span class="provider-status missing-key" title="API key not configured">key</span>';
      } else {
        icon = `<span class="provider-status ${cls}" title="${escapeAttr(result?.message || p.label)}"></span>`;
      }
      return `<span class="provider-chip" role="listitem">${icon}<span>${escapeHtml(p.label)}</span></span>`;
    })
    .join("");
}

async function loadMetadataProviders() {
  const data = await api("/api/metadata/providers");
  cachedProviders = data.providers || [];
  renderProviderList(cachedProviders);
}

async function testMetadataProviders() {
  const data = await api("/api/metadata/providers/test", { method: "POST" });
  renderProviderList(cachedProviders, data.results || []);
}

async function loadAndTestMetadataProviders() {
  try {
    await loadMetadataProviders();
    renderProviderList(cachedProviders, null, { pending: true });
    await testMetadataProviders();
  } catch (_err) {
    if (els.bootstrapProviderList && cachedProviders.length) {
      renderProviderList(cachedProviders);
    }
  }
}

async function cancelActiveScan() {
  if (!currentScanId || cancelInFlight) return;
  const scanId = currentScanId;
  cancelInFlight = true;
  cancelPending = true;
  if (els.bootstrapCancelBtn) els.bootstrapCancelBtn.disabled = true;
  try {
    const result = await api(`/api/scan/${encodeURIComponent(scanId)}/cancel`, { method: "POST" });
    showToast("Cancelling scan…", false, true);
    const scan = await api(`/api/scan/${encodeURIComponent(scanId)}`);
    if (result.message && !scan.message?.includes("Cancelling")) {
      scan.message = result.message;
    }
    applyScanStatus(scan);
    if (bootstrapScanActive) {
      syncBootstrapScanUi(scan);
    }
    clearScanPollTimer();
    pollScan();
  } catch (err) {
    cancelPending = false;
    showToast(err.message || "Could not cancel scan", true);
  } finally {
    cancelInFlight = false;
    if (els.bootstrapCancelBtn && !cancelPending) {
      els.bootstrapCancelBtn.disabled = false;
    }
  }
}

async function cancelActiveAutoRun() {
  if (!currentAutoRunId || cancelInFlight) return;
  cancelInFlight = true;
  if (els.bootstrapCancelBtn) els.bootstrapCancelBtn.disabled = true;
  try {
    await api(`/api/auto/${encodeURIComponent(currentAutoRunId)}/cancel`, { method: "POST" });
    showToast("Auto-run cancelled", false, true);
  } catch (err) {
    showToast(err.message || "Could not cancel auto-run", true);
  } finally {
    cancelInFlight = false;
    if (els.bootstrapCancelBtn) els.bootstrapCancelBtn.disabled = false;
  }
}

function showBootstrapProvidersPanel() {
  els.bootstrapProviders?.classList.remove("hidden");
  els.bootstrapStackWrap?.classList.add("hidden");
  els.bootstrapCancelBtn?.classList.add("hidden");
  els.bootstrapSpinner?.classList.add("hidden");
  void loadAndTestMetadataProviders();
}

function showBootstrapPreScanModal({
  title = "Scan your library",
  message = "Check metadata providers, then start the scan.",
} = {}) {
  bootstrapScanActive = false;
  if (els.bootstrapTitle) els.bootstrapTitle.classList.remove("hidden");
  showBootstrapScrim({
    title,
    message,
    actionLabel: "Start Scan",
    onAction: () => beginScan(),
  });
  showBootstrapProvidersPanel();
}

function openScanModal() {
  if (currentScanId || currentAutoRunId) return;
  if (els.scanBtn?.disabled && !document.body.classList.contains("bootstrap-needs-scan")) return;
  showBootstrapPreScanModal();
}

const CONFIRM_SKIP_PREFIX = "stager.confirmSkip.";
const SECTION_COLLAPSE_PREFIX = "stager.sectionCollapsed.";

const ICON_REVERT = `<svg class="icon-action-svg" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z"/></svg>`;

const ICON_CHECK = `<svg class="icon-action-svg" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M6.2 11.2 3.4 8.4a.75.75 0 0 0-1.06 1.06l3.25 3.25a.75.75 0 0 0 1.08-.02l7.2-8.2a.75.75 0 1 0-1.13-.98L6.2 11.2z"/></svg>`;

function isConfirmSkipped(key) {
  if (!key) return false;
  try {
    return localStorage.getItem(CONFIRM_SKIP_PREFIX + key) === "1";
  } catch {
    return false;
  }
}

function setConfirmSkipped(key, skip) {
  if (!key) return;
  try {
    if (skip) localStorage.setItem(CONFIRM_SKIP_PREFIX + key, "1");
    else localStorage.removeItem(CONFIRM_SKIP_PREFIX + key);
  } catch {
    /* ignore quota / private mode */
  }
}

const blockableSections = [
  { content: () => els.awayContent, key: "away" },
  { content: () => els.conflictsContent, key: "conflicts" },
  { content: () => els.partialContent, key: "partial" },
  { content: () => els.stagingContent, key: "staging" },
];

function setSectionListView({ emptyEl, listEl, hasItems, message }) {
  if (message != null && emptyEl) emptyEl.textContent = message;
  emptyEl?.classList.toggle("hidden", hasItems);
  listEl?.classList.toggle("hidden", !hasItems);
}

function getActiveFilter() {
  return els.statusFilter?.value || "pending";
}

function stagingEmptyMessage() {
  const q = els.searchBox?.value.trim();
  if (q) return "No books match your search.";
  const status = getActiveFilter();
  if (status === "pending") return "All books staged.";
  if (status === "staged") return "No staged books.";
  if (status === "skipped") return "No skipped books.";
  return "No books match this filter.";
}

function isRowSelectable(book) {
  const filter = getActiveFilter();
  if (book.status !== filter) return false;
  if (filter === "pending" && (book.in_conflict || mergeBookIds.has(book.id))) return false;
  return true;
}

function syncRowCheckToSelection(checkbox) {
  const id = checkbox.dataset.id;
  const set = selectionByFilter[getActiveFilter()];
  if (checkbox.checked) set.add(id);
  else set.delete(id);
}

function restoreSectionShells() {
  if (els.awayContent) {
    els.awayContent.innerHTML = `
      <p class="section-empty-state" id="awayEmpty">Nothing happened while you were away.</p>
      <div id="awayListWrap" class="book-list-wrap book-list-wrap--away hidden">
        <div class="book-item book-item__head" aria-hidden="true">
          <div class="book-item__path">Source path</div>
          <div class="book-item__meta">Book</div>
          <div class="book-item__conf">Conf</div>
          <div class="book-item__staged">Staged at</div>
          <div class="book-item__when">When</div>
          <div class="book-item__actions col-actions-head">Actions</div>
        </div>
        <div id="awayList" class="book-list book-list--away" role="list"></div>
      </div>`;
    els.awayEmpty = document.getElementById("awayEmpty");
    els.awayListWrap = document.getElementById("awayListWrap");
    els.awayList = document.getElementById("awayList");
    els.awayList?.addEventListener("click", awayListClickHandler);
  }
  if (els.conflictsContent) {
    els.conflictsContent.innerHTML = `
      <p class="section-empty-state" id="conflictsEmpty">No conflicts.</p>
      <div id="conflictsListWrap" class="book-list-wrap book-list-wrap--conflicts hidden">
        <div class="book-item book-item__head" aria-hidden="true">
          <div class="book-item__meta">Book</div>
          <div class="book-item__sides">Sides</div>
          <div class="book-item__kind">Kind</div>
          <div class="book-item__status">Status</div>
          <div class="book-item__actions col-actions-head">Actions</div>
        </div>
        <div id="conflictsList" class="book-list book-list--conflicts" role="list"></div>
      </div>`;
    els.conflictsEmpty = document.getElementById("conflictsEmpty");
    els.conflictsListWrap = document.getElementById("conflictsListWrap");
    els.conflictsList = document.getElementById("conflictsList");
  }
  if (els.partialContent) {
    els.partialContent.innerHTML = `
      <p class="section-empty-state" id="partialEmpty">No partially staged books.</p>
      <div id="partialListWrap" class="book-list-wrap book-list-wrap--partial hidden">
        <div class="book-item book-item__head" aria-hidden="true">
          <div class="book-item__path">Source path</div>
          <div class="book-item__files">Files</div>
          <div class="book-item__linked">Linked</div>
          <div class="book-item__meta">Book</div>
          <div class="book-item__status">Status</div>
          <div class="book-item__actions col-actions-head">Actions</div>
        </div>
        <div id="partialList" class="book-list book-list--partial" role="list"></div>
      </div>`;
    els.partialEmpty = document.getElementById("partialEmpty");
    els.partialListWrap = document.getElementById("partialListWrap");
    els.partialList = document.getElementById("partialList");
    els.partialList?.addEventListener("click", partialListClickHandler);
  }
  if (els.stagingContent) {
    els.stagingContent.innerHTML = `
      <p class="section-empty-state" id="stagingEmpty">All books staged.</p>
      <div id="booksListWrap" class="book-list-wrap book-list-wrap--staging hidden">
        ${stagingListHeadHtml()}
        <div id="booksList" class="book-list book-list--staging" role="list"></div>
      </div>`;
    els.stagingEmpty = document.getElementById("stagingEmpty");
    els.booksListWrap = document.getElementById("booksListWrap");
    els.booksList = document.getElementById("booksList");
    wireStagingListControls();
    updateStagingSortIndicators();
  }
}

function wireStagingSortControls() {
  stagingSort = loadStagingSort();
  els.stagingSortSelect = document.getElementById("stagingSortSelect");
  els.stagingContent?.addEventListener("click", stagingSortClickHandler);
  els.stagingSortSelect?.addEventListener("change", stagingSortSelectChangeHandler);
  updateStagingSortIndicators();
}

function stagingListChangeHandler(ev) {
  if (!ev.target.matches(".row-check")) return;
  syncRowCheckToSelection(ev.target);
  updateStagingBulkBtn();
}

function wireStagingListControls() {
  els.selectAll = document.getElementById("selectAll");
  els.booksList = document.getElementById("booksList");
  els.booksList?.addEventListener("click", booksListClickHandler);
  els.selectAll?.addEventListener("change", selectAllChangeHandler);
  els.booksList?.addEventListener("change", stagingListChangeHandler);
}

async function awayListClickHandler(ev) {
  const btn = ev.target.closest("button[data-away-action]");
  if (!btn || btn.disabled) return;
  const bookId = btn.dataset.id;
  const actionId = btn.dataset.actionId;
  try {
    if (btn.dataset.awayAction === "detail" && bookId) {
      return showDetail(bookId, { triggerBtn: btn });
    }
    if (btn.dataset.awayAction === "dismiss" && actionId) {
      await api("/api/auto/review/dismiss", {
        method: "POST",
        body: JSON.stringify({ action_ids: [actionId] }),
      });
      await loadAwayReview();
      showToast("Marked okay", false, true);
      return;
    }
    if (btn.dataset.awayAction === "revert" && bookId) {
      const ok = await showConfirmDialog({
        title: "Revert auto-staged book?",
        message: "Library hardlinks will be removed and the book returns to pending.",
        confirmLabel: "Revert",
        cancelLabel: "Keep staged",
        dangerous: true,
        preferenceKey: "away-revert",
      });
      if (!ok) return;
      await withStagingScrim("Reverting auto-stage…", async () => {
        await api(`/api/books/${encodeURIComponent(bookId)}/revert`, { method: "POST" });
        await loadAwayReview();
        await loadBooks();
      });
      showToast("Book reverted to pending", false, true);
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

function booksListClickHandler(ev) {
  const btn = ev.target.closest("button[data-action]");
  if (btn) handleBookAction(btn);
}

function partialListClickHandler(ev) {
  const btn = ev.target.closest("button[data-action]");
  if (btn) handleBookAction(btn);
}

function getSelectableRowChecks() {
  return [...document.querySelectorAll("#booksList .row-check:not(:disabled)")];
}

function getCheckedRowChecks() {
  return [...document.querySelectorAll("#booksList .row-check:checked")];
}

function syncSelectAllState() {
  if (!els.selectAll) return;
  const selectable = getSelectableRowChecks();
  const checked = getCheckedRowChecks();
  if (!selectable.length) {
    els.selectAll.checked = false;
    els.selectAll.indeterminate = false;
    els.selectAll.disabled = true;
    return;
  }
  els.selectAll.disabled = false;
  els.selectAll.checked = checked.length === selectable.length;
  els.selectAll.indeterminate = checked.length > 0 && checked.length < selectable.length;
}

function selectAllChangeHandler() {
  const filter = getActiveFilter();
  const set = selectionByFilter[filter];
  const checked = els.selectAll.checked;
  getSelectableRowChecks().forEach((el) => {
    el.checked = checked;
    if (checked) set.add(el.dataset.id);
    else set.delete(el.dataset.id);
  });
  els.selectAll.indeterminate = false;
  updateStagingBulkBtn();
}

function closeConfirmDialog(result) {
  if (result && confirmPreferenceKey && els.confirmDontAgain?.checked) {
    setConfirmSkipped(confirmPreferenceKey, true);
  }
  if (els.confirmDontAgain) els.confirmDontAgain.checked = false;
  confirmPreferenceKey = null;
  if (confirmResolver) {
    const resolve = confirmResolver;
    confirmResolver = null;
    resolve(result);
  }
  els.confirmDialog?.close();
}

function showConfirmDialog({
  title = "Confirm",
  message = "",
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  dangerous = false,
  preferenceKey = null,
} = {}) {
  if (preferenceKey && isConfirmSkipped(preferenceKey)) {
    return Promise.resolve(true);
  }
  if (!els.confirmDialog) {
    return Promise.resolve(window.confirm(message || title));
  }
  return new Promise((resolve) => {
    confirmResolver = resolve;
    confirmPreferenceKey = preferenceKey;
    if (els.confirmTitle) els.confirmTitle.textContent = title;
    if (els.confirmMessage) els.confirmMessage.textContent = message;
    if (els.confirmOkBtn) {
      els.confirmOkBtn.textContent = confirmLabel;
      els.confirmOkBtn.classList.toggle("primary", !dangerous);
      els.confirmOkBtn.classList.toggle("danger", dangerous);
    }
    if (els.confirmCancelBtn) els.confirmCancelBtn.textContent = cancelLabel;
    els.confirmDontAgainLabel?.classList.toggle("hidden", !preferenceKey);
    if (els.confirmDontAgain) els.confirmDontAgain.checked = false;
    openDialog(els.confirmDialog, {
      focus: dangerous ? els.confirmCancelBtn : els.confirmOkBtn,
    });
  });
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    let message = text || res.statusText;
    let detail = null;
    try {
      const parsed = JSON.parse(text);
      detail = parsed.detail ?? null;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail?.message) {
        message = detail.message;
      }
    } catch {
      /* keep raw text */
    }
    const err = new Error(message);
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

function showToast(message, isError = false, isInfo = false) {
  const applyToastClasses = (el) => {
    el.textContent = message;
    el.classList.toggle("toast-error", isError);
    el.classList.toggle("toast-info", isInfo && !isError);
    el.classList.toggle("detail-toast-error", isError);
    el.classList.toggle("detail-toast-info", isInfo && !isError);
    el.classList.remove("hidden");
  };

  applyToastClasses(els.toast);
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => els.toast.classList.add("hidden"), 6000);

  const detailToast = document.getElementById("detailToast");
  if (detailToast && els.detailDialog?.open) {
    applyToastClasses(detailToast);
    clearTimeout(window.detailToastTimer);
    window.detailToastTimer = setTimeout(() => detailToast.classList.add("hidden"), 8000);
  } else if (detailToast) {
    detailToast.classList.add("hidden");
  }
}

let modalScrollLockDepth = 0;

function lockModalScroll() {
  modalScrollLockDepth += 1;
  if (modalScrollLockDepth === 1) {
    document.documentElement.classList.add("modal-open");
  }
}

function unlockModalScroll() {
  modalScrollLockDepth = Math.max(0, modalScrollLockDepth - 1);
  if (modalScrollLockDepth === 0) {
    document.documentElement.classList.remove("modal-open");
  }
}

function focusDialog(dialog, focus) {
  requestAnimationFrame(() => {
    let target = null;
    if (focus instanceof HTMLElement) {
      target = focus;
    } else if (typeof focus === "string") {
      target = dialog.querySelector(focus);
    } else {
      target = dialog.querySelector(
        "[autofocus], button:not(.dialog-close-btn), input:not([type='hidden']), select, textarea, [href], [tabindex]:not([tabindex='-1'])"
      );
    }
    (target || dialog).focus({ preventScroll: true });
  });
}

function openDialog(dialog, { focus } = {}) {
  if (!dialog) return;
  if (!dialog.open) {
    lockModalScroll();
    dialog.showModal();
  }
  focusDialog(dialog, focus);
}

function preventModalBackgroundScroll(event) {
  if (!document.documentElement.classList.contains("modal-open")) return;
  const openDialogs = [...document.querySelectorAll("dialog[open]")];
  if (!openDialogs.length) return;
  const topDialog = openDialogs[openDialogs.length - 1];
  if (topDialog.contains(event.target)) return;
  event.preventDefault();
}

function showStagingScrim(message = "Staging…") {
  stagingScrimDepth += 1;
  els.stagingScrimMessage.textContent = message;
  els.stagingScrim.classList.remove("hidden");
  els.stagingScrim.setAttribute("aria-hidden", "false");
  document.body.classList.add("staging-busy");
}

function hideStagingScrim() {
  stagingScrimDepth = Math.max(0, stagingScrimDepth - 1);
  if (stagingScrimDepth === 0) {
    els.stagingScrim.classList.add("hidden");
    els.stagingScrim.setAttribute("aria-hidden", "true");
    document.body.classList.remove("staging-busy");
  }
}

async function withStagingScrim(message, fn) {
  showStagingScrim(message);
  try {
    return await fn();
  } finally {
    hideStagingScrim();
  }
}

function btnSpinnerHtml() {
  return '<span class="btn-spinner" aria-hidden="true"></span>';
}

function setButtonBusy(btn, busy, { label } = {}) {
  if (!btn) return;
  if (busy) {
    if (!btn.dataset.busyOriginalLabel) {
      btn.dataset.busyOriginalLabel = btn.textContent.trim();
    }
    btn.disabled = true;
    btn.classList.add("btn-busy");
    btn.setAttribute("aria-busy", "true");
    const busyLabel = label || btn.dataset.busyOriginalLabel;
    btn.innerHTML = `${btnSpinnerHtml()} ${escapeHtml(busyLabel)}`;
  } else {
    btn.disabled = false;
    btn.classList.remove("btn-busy");
    btn.removeAttribute("aria-busy");
    const original = btn.dataset.busyOriginalLabel;
    if (original) {
      btn.textContent = original;
      delete btn.dataset.busyOriginalLabel;
    }
  }
}

async function withButtonBusy(btn, fn, { label } = {}) {
  if (!btn || btn.classList.contains("btn-busy")) return;
  setButtonBusy(btn, true, { label });
  try {
    return await fn();
  } finally {
    setButtonBusy(btn, false);
  }
}

function flashButtonSaved(btn, durationMs = 1500) {
  if (!btn) return;
  btn.classList.add("btn-saved");
  clearTimeout(btn.savedFlashTimer);
  btn.savedFlashTimer = setTimeout(() => btn.classList.remove("btn-saved"), durationMs);
}

const METADATA_EDIT_FIELDS = [
  {
    key: "author",
    label: "Author",
    inputId: "editAuthor",
    setKey: "chosen_author_set",
    suggestedKey: "suggested_author",
    effectiveKey: "effective_author",
    draftKey: "author",
  },
  {
    key: "title",
    label: "Title",
    inputId: "editTitle",
    setKey: "chosen_title_set",
    suggestedKey: "suggested_title",
    effectiveKey: "effective_title",
    draftKey: "title",
  },
  {
    key: "series",
    label: "Series",
    inputId: "editSeries",
    setKey: "chosen_series_set",
    suggestedKey: "suggested_series",
    effectiveKey: "effective_series",
    draftKey: "series",
  },
  {
    key: "series_index",
    label: "Series #",
    inputId: "editSeriesIndex",
    setKey: "chosen_series_index_set",
    suggestedKey: "suggested_series_index",
    effectiveKey: "effective_series_index",
    draftKey: "seriesIndex",
  },
];

function isMetadataFieldManual(book, field) {
  return Boolean(book?.[field.setKey]);
}

function manualMetadataFieldLabels(book) {
  if (!book) return [];
  return METADATA_EDIT_FIELDS.filter((field) => isMetadataFieldManual(book, field)).map(
    (field) => field.label
  );
}

function manualMetadataFieldCount(book) {
  if (!book) return 0;
  return METADATA_EDIT_FIELDS.filter((field) => isMetadataFieldManual(book, field)).length;
}

function metadataManualSuggestedCounts(book) {
  const manual = manualMetadataFieldCount(book);
  return { manual, suggested: METADATA_EDIT_FIELDS.length - manual };
}

function metadataFieldSuggestedHint(book, field) {
  const suggested = isMetadataFieldManual(book, field)
    ? (book?.[field.suggestedKey] ?? "").trim()
    : (book?.[field.effectiveKey] ?? "").trim();
  if (field.key === "series_index" && suggested) {
    return `#${suggested}`;
  }
  return suggested;
}

function renderMetadataModeBadge(book, field) {
  if (isMetadataFieldManual(book, field)) {
    return `<span class="metadata-mode-badge metadata-mode-badge--manual" title="Manual — re-lookup won't change this">Manual</span>`;
  }
  return `<span class="metadata-mode-badge metadata-mode-badge--suggested" title="Suggested — re-lookup may update this">Suggested</span>`;
}

function renderMetadataFieldHint(book, field) {
  const hint = metadataFieldSuggestedHint(book, field);
  if (hint) {
    return `<span class="metadata-field-hint">Suggested: ${escapeHtml(hint)}</span>`;
  }
  return `<span class="metadata-field-hint metadata-field-hint--empty">Suggested: —</span>`;
}

function renderMetadataStatusLine(book) {
  const { manual, suggested } = metadataManualSuggestedCounts(book);
  return `<span class="metadata-status-line">${manual} manual · ${suggested} suggested</span>`;
}

function renderMetadataRevertBtn(field) {
  return `<button type="button" class="metadata-revert-btn" data-revert-field="${escapeAttr(field.key)}" title="Revert to suggested" aria-label="Revert to suggested">↺</button>`;
}

function renderMetadataEditField(book, field) {
  const value = book?.[field.effectiveKey] ?? "";
  const manual = isMetadataFieldManual(book, field);
  const lviMatched = metadataFieldLviMatched(book?.lvi_form_match, field.key);
  return `
    <label class="metadata-field${lviMatched ? " metadata-field--lvi-match" : ""}" data-metadata-field="${escapeAttr(field.key)}">
      <span class="metadata-field-label">
        <span class="metadata-field-name">${escapeHtml(field.label)}</span>
        <span class="metadata-field-badges">
          ${renderMetadataModeBadge(book, field)}
          ${manual ? renderMetadataRevertBtn(field) : ""}
        </span>
      </span>
      <input id="${field.inputId}" class="${lviMatched ? "field-lvi-match" : ""}" value="${escapeAttr(value)}" />
      ${renderMetadataFieldHint(book, field)}
    </label>`;
}

function renderMetadataEditForm(book) {
  return `
    <div class="meta-block edit-metadata-form">
      <div class="metadata-form-header">
        <h3>Edit metadata</h3>
        ${renderMetadataStatusLine(book)}
      </div>
      ${METADATA_EDIT_FIELDS.map((field) => renderMetadataEditField(book, field)).join("")}
      <div class="target-preview-block">
        <span class="target-preview-label">Library path</span>
        <span id="detailTargetPreview" class="target-preview-value">${escapeHtml(book.target_key_preview || "—")}</span>
      </div>
      <div class="edit-metadata-actions">
        <button type="button" id="saveEdit">Save</button>
        <button type="button" id="revertAllMetadata" class="metadata-revert-all-btn">↺ All</button>
      </div>
    </div>`;
}

function applyDetailMetadataChrome(book) {
  if (!book) return;
  METADATA_EDIT_FIELDS.forEach((field) => {
    const label = document.querySelector(`[data-metadata-field="${field.key}"]`);
    const input = document.getElementById(field.inputId);
    if (!label || !input) return;
    const badges = label.querySelector(".metadata-field-badges");
    if (badges) {
      const manual = isMetadataFieldManual(book, field);
      badges.innerHTML = `${renderMetadataModeBadge(book, field)}${manual ? renderMetadataRevertBtn(field) : ""}`;
    }
    const hint = label.querySelector(".metadata-field-hint");
    if (hint) {
      hint.outerHTML = renderMetadataFieldHint(book, field);
    }
  });
  const statusLine = document.querySelector(".metadata-status-line");
  if (statusLine) {
    statusLine.outerHTML = renderMetadataStatusLine(book);
  }
  applyDetailLviChrome(book?.lvi_form_match);
}

async function revertMetadataFields(bookId, { fields = [], revertAll = false } = {}) {
  const body = revertAll ? { revert_all: true } : { revert_fields: fields };
  const updated = await api(`/api/books/${encodeURIComponent(bookId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  if (selectedBookId === bookId) {
    updateDetailModal(updated);
  }
  void loadBooks();
  return updated;
}

function markDetailFieldsSaved(saved) {
  const fields = ["editAuthor", "editTitle", "editSeries", "editSeriesIndex"];
  fields.forEach((id) => {
    const input = document.getElementById(id);
    if (!input) return;
    input.classList.toggle("field-saved", saved);
  });
}

function getDetailMetadataInputs() {
  return {
    author: document.getElementById("editAuthor")?.value ?? "",
    title: document.getElementById("editTitle")?.value ?? "",
    series: document.getElementById("editSeries")?.value ?? "",
    seriesIndex: document.getElementById("editSeriesIndex")?.value ?? "",
  };
}

let targetPreviewTimer = null;

async function refreshDetailTargetPreview(bookId) {
  const inputs = getDetailMetadataInputs();
  try {
    const preview = await api(`/api/books/${encodeURIComponent(bookId)}/target-key-preview`, {
      method: "POST",
      body: JSON.stringify({
        chosen_author: inputs.author,
        chosen_title: inputs.title,
        chosen_series: inputs.series,
        chosen_series_index: inputs.seriesIndex,
      }),
    });
    const pathEl = document.getElementById("detailTargetPreview");
    if (pathEl) pathEl.textContent = preview.target_key_preview || "—";
    if (preview.lvi_form_match) applyDetailLviChrome(preview.lvi_form_match);
  } catch {
    /* ignore preview errors while typing */
  }
}

function scheduleDetailTargetPreview(bookId) {
  clearTimeout(targetPreviewTimer);
  targetPreviewTimer = setTimeout(() => refreshDetailTargetPreview(bookId), 300);
}

function wireDetailMetadataPreview(bookId) {
  ["editAuthor", "editTitle", "editSeries", "editSeriesIndex"].forEach((id) => {
    const input = document.getElementById(id);
    if (!input || input.dataset.previewWired === "1") return;
    input.dataset.previewWired = "1";
    input.addEventListener("input", () => scheduleDetailTargetPreview(bookId));
  });
}

function wireDetailMetadataRevert(bookId) {
  const form = document.querySelector(".edit-metadata-form");
  if (!form || form.dataset.revertWired === "1") return;
  form.dataset.revertWired = "1";

  form.addEventListener("click", async (ev) => {
    const revertAllBtn = ev.target.closest("#revertAllMetadata");
    if (revertAllBtn) {
      if (revertAllBtn.disabled || revertAllBtn.classList.contains("btn-busy")) return;
      try {
        await withButtonBusy(revertAllBtn, async () => {
          await revertMetadataFields(bookId, { revertAll: true });
          showToast("Reverted to suggested", false, true);
        }, { label: "Reverting…" });
      } catch (err) {
        showToast(err.message, true);
      }
      return;
    }

    const revertBtn = ev.target.closest(".metadata-revert-btn");
    if (!revertBtn) return;
    if (revertBtn.disabled || revertBtn.classList.contains("btn-busy")) return;
    const fieldKey = revertBtn.dataset.revertField;
    try {
      await withButtonBusy(revertBtn, async () => {
        await revertMetadataFields(bookId, { fields: [fieldKey] });
        showToast("Reverted to suggested", false, true);
      });
    } catch (err) {
      showToast(err.message, true);
    }
  });
}

function updateDetailModal(book) {
  const authorInput = document.getElementById("editAuthor");
  const titleInput = document.getElementById("editTitle");
  const seriesInput = document.getElementById("editSeries");
  const seriesIndexInput = document.getElementById("editSeriesIndex");
  if (authorInput) authorInput.value = book.effective_author ?? "";
  if (titleInput) titleInput.value = book.effective_title ?? "";
  if (seriesInput) seriesInput.value = book.effective_series ?? "";
  if (seriesIndexInput) seriesIndexInput.value = book.effective_series_index ?? "";
  markDetailFieldsSaved(false);
  applyDetailMetadataChrome(book);

  const pathEl = document.getElementById("detailTargetPreview");
  if (pathEl) pathEl.textContent = book.target_key_preview || "—";

  let warnBlock = document.getElementById("detailConflictWarn");
  if (book.in_conflict) {
    if (!warnBlock) {
      warnBlock = document.createElement("div");
      warnBlock.id = "detailConflictWarn";
      warnBlock.className = "meta-block warn-block";
      warnBlock.innerHTML =
        "<h3>Conflict</h3><div>Resolve in the Conflicts section before approving.</div>";
      els.detailContent.appendChild(warnBlock);
    }
  } else if (warnBlock) {
    warnBlock.remove();
  }
}

function optimisticSkipRow(btn, skipping) {
  const row = btn.closest(".book-item[data-book-id]");
  if (!row) return null;
  const pill = row.querySelector(".status-pill");
  const actionBtns = row.querySelectorAll("button[data-action]");
  if (skipping) {
    row.dataset.prevStatus = pill?.textContent || "pending";
    if (pill) pill.textContent = "skipped";
    row.classList.add("book-item--skipped");
    actionBtns.forEach((b) => {
      b.disabled = true;
    });
  } else {
    const prev = row.dataset.prevStatus || "pending";
    if (pill) pill.textContent = prev;
    row.classList.remove("book-item--skipped");
    delete row.dataset.prevStatus;
    const pending = prev === "pending";
    actionBtns.forEach((b) => {
      if (b.dataset.action === "detail") {
        b.disabled = false;
      } else if (b.dataset.action === "approve") {
        b.disabled = !pending;
      } else if (b.dataset.action === "skip") {
        b.disabled = !pending;
      }
    });
  }
  return row;
}

function setScanButtonRunning(running) {
  if (!els.scanBtn) return;
  els.scanBtn.disabled = running;
  els.scanBtn.textContent = running ? "Scanning…" : "Start Scan";
  els.scanBtn.setAttribute("aria-busy", running ? "true" : "false");
}

function updateStagingBulkBtn() {
  if (!els.stagingBulkBtn) return;
  const filter = getActiveFilter();
  const config = STAGING_BULK_CONFIG[filter] || STAGING_BULK_CONFIG.pending;
  const count = selectionByFilter[filter]?.size ?? 0;
  const label = count === 0 ? config.label : `${config.label} (${count})`;
  const disabled = count === 0;
  els.stagingBulkBtn.disabled = disabled;
  els.stagingBulkBtn.textContent = label;
  els.stagingBulkBtn.title = count === 0 ? config.emptyTitle : "";
  if (els.mobileBulkBtn) {
    els.mobileBulkBtn.disabled = disabled;
    els.mobileBulkBtn.textContent = label;
    els.mobileBulkBtn.title = count === 0 ? config.emptyTitle : "";
  }
  if (els.mobileBulkCount) {
    els.mobileBulkCount.textContent = count === 0 ? "" : `${count} selected`;
  }
  if (els.mobileBulkBar) {
    els.mobileBulkBar.classList.toggle("hidden", count === 0);
  }
  syncSelectAllState();
}

function lerpScoreRgb(a, b, t) {
  return {
    r: Math.round(a.r + (b.r - a.r) * t),
    g: Math.round(a.g + (b.g - a.g) * t),
    b: Math.round(a.b + (b.b - a.b) * t),
  };
}

function scoreToRgb(value) {
  const minGate = Math.max(0.01, Math.min(1, autoMinConfidence));
  const v = Math.max(0, Math.min(1, Number(value) || 0));
  const knots = [
    { t: 0, rgb: SCORE_RGB_RED },
    { t: 0.5, rgb: SCORE_RGB_YELLOW },
    { t: minGate, rgb: SCORE_RGB_GREEN },
    { t: 1, rgb: SCORE_RGB_GREEN_BRIGHT },
  ].sort((a, b) => a.t - b.t);

  const stops = [];
  for (const knot of knots) {
    if (stops.length && stops[stops.length - 1].t === knot.t) {
      stops[stops.length - 1] = knot;
    } else {
      stops.push(knot);
    }
  }

  if (v <= stops[0].t) return stops[0].rgb;
  for (let i = 0; i < stops.length - 1; i++) {
    const left = stops[i];
    const right = stops[i + 1];
    if (v <= right.t) {
      const span = right.t - left.t;
      const t = span > 0 ? (v - left.t) / span : 0;
      return lerpScoreRgb(left.rgb, right.rgb, t);
    }
  }
  return stops[stops.length - 1].rgb;
}

function scorePillStyle(value) {
  const { r, g, b } = scoreToRgb(value);
  return `background:rgba(${r},${g},${b},0.18);border:1px solid rgba(${r},${g},${b},0.45);color:var(--text);`;
}

function isMetadataOverridden(book) {
  if (!book) return false;
  if (book.any_chosen_set) return true;
  return Boolean(
    book.chosen_author_set ||
      book.chosen_title_set ||
      book.chosen_series_set ||
      book.chosen_series_index_set
  );
}

function renderScorePill(value, { title = "Confidence" } = {}) {
  const v = Number(value);
  if (!Number.isFinite(v)) return "—";
  return `<span class="score-pill" title="${escapeAttr(title)}" style="${scorePillStyle(v)}">${v.toFixed(2)}</span>`;
}

function metadataFieldLviMatched(formMatch, fieldKey) {
  if (!formMatch) return false;
  if (fieldKey === "author") return Boolean(formMatch.author_matched);
  if (fieldKey === "series") return Boolean(formMatch.series_matched);
  return false;
}

function parseTargetKeyDisplay(targetKey) {
  const parts = String(targetKey || "").split("/").filter(Boolean);
  if (parts.length >= 3) {
    return {
      author: parts[0],
      series: parts[1],
      title: parts.slice(2).join("/"),
      seriesIndex: "",
    };
  }
  if (parts.length === 2) {
    return { author: parts[0], title: parts[1], series: "", seriesIndex: "" };
  }
  if (parts.length === 1) {
    return { author: parts[0], title: "—", series: "", seriesIndex: "" };
  }
  return { author: "—", title: "—", series: "", seriesIndex: "" };
}

function renderBookMetaFromTargetKey(targetKey) {
  const meta = parseTargetKeyDisplay(targetKey);
  return renderBookMeta({ ...meta, targetKey });
}

function renderEffectiveBookMeta(source) {
  const title = source.effective_title || source.flatten_name || source.title || "";
  return renderBookMeta({
    author: source.effective_author || source.author || "",
    title,
    series: source.effective_series || "",
    seriesIndex: source.effective_series_index || "",
    formMatch: source.lvi_form_match,
    targetKey: source.target_key_preview || source.target_key || "",
    titleAttr: title,
  });
}

function renderBookMeta({
  author = "",
  title = "",
  series = "",
  seriesIndex = "",
  formMatch,
  lviAuthorMatched,
  lviSeriesMatched,
  targetKey,
  titleAttr,
} = {}) {
  const authorMatched = lviAuthorMatched ?? Boolean(formMatch?.author_matched);
  const seriesMatched = lviSeriesMatched ?? Boolean(formMatch?.series_matched);
  const authorCls = authorMatched ? "book-meta__author lvi-match-text" : "book-meta__author";
  const authorLine = `<div class="${authorCls}">${escapeHtml(author || "—")}</div>`;
  const titleLine = `<div class="book-meta__title"${titleAttr ? ` title="${escapeAttr(titleAttr)}"` : ""}>${escapeHtml(title || "—")}</div>`;

  let seriesLine = "";
  const seriesStr = String(series || "").trim();
  const indexStr = String(seriesIndex || "").trim();
  if (seriesStr || indexStr) {
    const seriesCls = seriesMatched ? "book-meta__series lvi-match-text" : "book-meta__series";
    let seriesContent = "";
    if (seriesStr) seriesContent += escapeHtml(seriesStr);
    if (indexStr) {
      if (seriesContent) seriesContent += " ";
      seriesContent += `<span class="book-meta__index">#${escapeHtml(indexStr)}</span>`;
    }
    seriesLine = `<div class="${seriesCls}">${seriesContent}</div>`;
  }

  const pathKey = String(targetKey || "").trim();
  const pathTooltip = pathKey ? ` title="${escapeAttr(pathKey)}"` : "";
  return `<div class="book-meta"${pathTooltip}>${authorLine}${titleLine}${seriesLine}</div>`;
}

function applyDetailLviChrome(formMatch) {
  METADATA_EDIT_FIELDS.forEach((field) => {
    const label = document.querySelector(`[data-metadata-field="${field.key}"]`);
    const input = document.getElementById(field.inputId);
    if (!label || !input) return;
    const matched = metadataFieldLviMatched(formMatch, field.key);
    label.classList.toggle("metadata-field--lvi-match", matched);
    input.classList.toggle("field-lvi-match", matched);
  });
}

function renderCandidateScores(c) {
  const cluster = Number(c.cluster_confidence);
  const centrality = Number(c.medoid_score);
  const seriesMembership = Number(c.series_membership);
  const hasSeriesPill = Number.isFinite(seriesMembership) && seriesMembership > 0;
  const seriesPill = hasSeriesPill
    ? renderScorePill(seriesMembership, { title: "Series match" })
    : "";
  const hasScores =
    Number.isFinite(cluster) &&
    Number.isFinite(centrality) &&
    (cluster > 0 || centrality > 0 || c.in_winning_cluster);
  if (!hasScores) {
    if (!seriesPill) return renderScorePill(c.confidence, { title: "Confidence" });
    return `<span class="candidate-scores">${renderScorePill(c.confidence, { title: "Confidence" })}${seriesPill}</span>`;
  }
  return `<span class="candidate-scores">
    ${renderScorePill(cluster, { title: "Confidence" })}
    ${renderScorePill(centrality, { title: "Centrality" })}
    ${seriesPill}
  </span>`;
}

function renderBookConfidence(book) {
  if (isMetadataOverridden(book)) {
    const labels = manualMetadataFieldLabels(book);
    const title = labels.length
      ? `Manual: ${labels.join(", ")}`
      : "Metadata set manually";
    return `<span class="score-pill score-pill-manual" title="${escapeAttr(title)}" style="${scorePillStyle(1)}">Manual</span>`;
  }
  const conf = book.staging_confidence ?? book.confidence;
  return renderScorePill(conf);
}

function loadStagingSort() {
  try {
    const raw = localStorage.getItem(STAGING_SORT_KEY);
    if (!raw) return { key: "source_path", dir: "asc" };
    const parsed = JSON.parse(raw);
    if (!STAGING_SORT_KEYS.has(parsed.key)) return { key: "source_path", dir: "asc" };
    return { key: parsed.key, dir: parsed.dir === "desc" ? "desc" : "asc" };
  } catch {
    return { key: "source_path", dir: "asc" };
  }
}

function saveStagingSort() {
  localStorage.setItem(STAGING_SORT_KEY, JSON.stringify(stagingSort));
}

function bookDisplayAuthor(book) {
  return (book.effective_author || book.chosen_author || book.suggested_author || "").trim().toLowerCase();
}

function bookDisplayTitle(book) {
  return (
    book.effective_title || book.chosen_title || book.suggested_title || book.flatten_name || ""
  )
    .trim()
    .toLowerCase();
}

function bookSortConfidence(book) {
  if (isMetadataOverridden(book)) return 1.0;
  return Number(book.staging_confidence ?? book.confidence) || 0;
}

function compareStagingBooks(a, b) {
  const dir = stagingSort.dir === "desc" ? -1 : 1;
  let cmp = 0;
  switch (stagingSort.key) {
    case "source_path":
      cmp = (a.source_path || "").localeCompare(b.source_path || "", undefined, { sensitivity: "base" });
      break;
    case "metadata": {
      const authorCmp = bookDisplayAuthor(a).localeCompare(bookDisplayAuthor(b));
      cmp = authorCmp !== 0 ? authorCmp : bookDisplayTitle(a).localeCompare(bookDisplayTitle(b));
      break;
    }
    case "confidence":
      cmp = bookSortConfidence(a) - bookSortConfidence(b);
      break;
    default:
      cmp = 0;
  }
  if (cmp !== 0) return cmp * dir;
  return (a.source_path || "").localeCompare(b.source_path || "", undefined, { sensitivity: "base" });
}

function sortStagingBooks(staging) {
  return [...staging].sort(compareStagingBooks);
}

function stagingSortSelectValue() {
  return `${stagingSort.key}:${stagingSort.dir}`;
}

function parseStagingSortSelectValue(value) {
  const [key, dir] = (value || "").split(":");
  if (!STAGING_SORT_KEYS.has(key)) return null;
  return { key, dir: dir === "desc" ? "desc" : "asc" };
}

function setStagingSort(key, dir) {
  stagingSort = { key, dir: dir === "desc" ? "desc" : "asc" };
  saveStagingSort();
  if (cachedBooksPayload) renderBooksPayload(cachedBooksPayload);
  else updateStagingSortIndicators();
}

function stagingSortClickHandler(ev) {
  const btn = ev.target.closest(".book-item__sort-btn");
  if (!btn) return;
  const col = btn.closest("[data-sort]");
  if (!col || !col.closest(".book-item__head")) return;
  const key = col.dataset.sort;
  if (!STAGING_SORT_KEYS.has(key)) return;
  ev.preventDefault();
  if (stagingSort.key === key) {
    setStagingSort(key, stagingSort.dir === "asc" ? "desc" : "asc");
  } else {
    setStagingSort(key, "asc");
  }
}

function stagingSortSelectChangeHandler() {
  const parsed = parseStagingSortSelectValue(els.stagingSortSelect?.value);
  if (!parsed) return;
  if (parsed.key === stagingSort.key && parsed.dir === stagingSort.dir) return;
  stagingSort = parsed;
  saveStagingSort();
  if (cachedBooksPayload) renderBooksPayload(cachedBooksPayload);
  else updateStagingSortIndicators();
}

function updateStagingSortIndicators() {
  document.querySelectorAll(".book-item__head [data-sort]").forEach((col) => {
    const key = col.dataset.sort;
    if (key === stagingSort.key) {
      col.setAttribute("aria-sort", stagingSort.dir === "asc" ? "ascending" : "descending");
    } else {
      col.setAttribute("aria-sort", "none");
    }
  });
  if (els.stagingSortSelect) {
    els.stagingSortSelect.value = stagingSortSelectValue();
  }
}

function stagingListHeadHtml() {
  return `
        <div class="book-item book-item__head" role="row">
          <div class="book-item__check" role="columnheader"><input type="checkbox" id="selectAll" aria-label="Select all" /></div>
          <div class="book-item__path book-item__sort" role="columnheader" data-sort="source_path">
            <button type="button" class="book-item__sort-btn">Source path</button>
          </div>
          <div class="book-item__files" role="columnheader">Files</div>
          <div class="book-item__meta book-item__sort" role="columnheader" data-sort="metadata">
            <button type="button" class="book-item__sort-btn">Book</button>
          </div>
          <div class="book-item__conf book-item__sort" role="columnheader" data-sort="confidence">
            <button type="button" class="book-item__sort-btn">Conf</button>
          </div>
          <div class="book-item__status" role="columnheader">Status</div>
          <div class="book-item__actions col-actions-head" role="columnheader">Actions</div>
        </div>`;
}

const CONFLICT_KIND_LABELS = {
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

function renderConflictKindTag(kind) {
  const info = CONFLICT_KIND_LABELS[kind];
  if (!info) return "";
  return `<span class="conflict-kind-pill conflict-kind-${escapeAttr(kind)}" title="${escapeAttr(info.title)}">${escapeHtml(info.label)}</span>`;
}

function formatBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`;
  if (v < 1024 * 1024 * 1024) return `${(v / (1024 * 1024)).toFixed(1)} MB`;
  return `${(v / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.round(Number(totalSeconds) || 0));
  if (!s) return "0m";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return sec > 0 ? `${m}m ${sec}s` : `${m}m`;
  return `${sec}s`;
}

function renderDurationLoadButton() {
  return `<button type="button" class="duration-load-btn" title="Load duration">${DURATION_PLACEHOLDER}</button>`;
}

const ICON_COPY = `<svg class="tag-copy-svg" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M4 1.5h7A1.5 1.5 0 0 1 12.5 3v7H11.5V3H4V1.5zm-1.5 2H10A1.5 1.5 0 0 1 11.5 5v7.5A1.5 1.5 0 0 1 10 14H2.5A1.5 1.5 0 0 1 1 12.5V5A1.5 1.5 0 0 1 2.5 3.5zm0 1v8H10V4.5H2.5z"/></svg>`;

const PRIMARY_TAG_FIELDS = ["title", "album", "artist"];
const ADDITIONAL_TAG_FIELDS = ["albumartist", "narrator", "asin", "contentgroup", "grouping"];

function fileExtension(name) {
  const n = String(name || "");
  const dot = n.lastIndexOf(".");
  if (dot < 0) return "";
  return n.slice(dot + 1).toLowerCase();
}

function summarizeFiles(files) {
  const list = files || [];
  const formats = [...new Set(list.map((f) => fileExtension(f.name)).filter(Boolean))].sort();
  const totalSizeBytes = list.reduce((sum, f) => sum + (Number(f.size_bytes) || 0), 0);
  return {
    fileCount: list.length,
    totalSizeBytes,
    formats,
  };
}

function renderTagCopyButton(value) {
  if (!value) return '<span class="tag-copy-spacer" aria-hidden="true"></span>';
  return `<button type="button" class="tag-copy-btn" data-copy-value="${escapeAttr(value)}" title="Copy" aria-label="Copy">${ICON_COPY}</button>`;
}

function renderTagFieldRow(label, value) {
  const display = value ? escapeHtml(value) : "—";
  return `
    <div class="tag-field-row">
      <span class="tag-field-label">${escapeHtml(label)}</span>
      <span class="tag-field-value">${display}</span>
      ${renderTagCopyButton(value || "")}
    </div>`;
}

function renderOverviewStats({ files, bookId } = {}) {
  const { totalSizeBytes, formats } = summarizeFiles(files);
  const formatsStr = formats.length ? formats.join(", ") : "—";
  const durationId = bookId ? ' id="detailDuration"' : "";
  const durationData = bookId
    ? ` data-side-type="seed" data-book-id="${escapeAttr(bookId)}"`
    : "";
  return `
    <div class="meta-block detail-overview-block">
      <dl class="detail-overview-stats">
        <div class="detail-overview-stat">
          <dt>Duration</dt>
          <dd class="side-duration"${durationId}${durationData}>${renderDurationLoadButton()}</dd>
        </div>
        <div class="detail-overview-stat">
          <dt>Size</dt>
          <dd>${formatBytes(totalSizeBytes)}</dd>
        </div>
        <div class="detail-overview-stat">
          <dt>Formats</dt>
          <dd>${escapeHtml(formatsStr)}</dd>
        </div>
      </dl>
    </div>`;
}

function renderFileList(files) {
  const list = files || [];
  const { fileCount, totalSizeBytes } = summarizeFiles(list);
  const rows = list
    .map((f) => {
      const ext = fileExtension(f.name) || "?";
      return `
      <div class="file-list-row" title="${escapeAttr(f.source || f.name)}">
        <span class="format-badge">${escapeHtml(ext)}</span>
        <span class="file-list-name">${escapeHtml(f.name)}</span>
        <span class="file-list-size">${formatBytes(f.size_bytes)}</span>
      </div>`;
    })
    .join("");
  return `
    <details class="meta-collapse file-list-collapse">
      <summary>File(s) (${fileCount})</summary>
      <div class="file-list-rows">${rows || '<div class="file-list-empty">No files</div>'}</div>
      <div class="file-list-total">Total: ${formatBytes(totalSizeBytes)}</div>
    </details>`;
}

function renderStagingFileStatusLabel(status) {
  const labels = {
    linked: "Linked",
    unlinked: "Not linked",
    source_missing: "Source missing",
  };
  return labels[status] || status;
}

function renderStagingFileList(staging) {
  const files = staging?.files || [];
  const rows = files
    .map((f) => {
      const ext = fileExtension(f.name) || "?";
      const libHint = f.library_paths?.length
        ? ` title="${escapeAttr(f.library_paths.join(", "))}"`
        : "";
      return `
      <div class="file-list-row file-list-row-staging"${libHint}>
        <span class="format-badge">${escapeHtml(ext)}</span>
        <span class="file-list-name">${escapeHtml(f.name)}</span>
        <span class="file-status-pill file-status-${escapeAttr(f.status)}">${escapeHtml(renderStagingFileStatusLabel(f.status))}</span>
        <span class="file-list-size">${formatBytes(f.size_bytes)}</span>
      </div>`;
    })
    .join("");
  return `
    <details class="meta-collapse file-list-collapse" open>
      <summary>Source files (${files.length})</summary>
      <div class="file-list-rows">${rows || '<div class="file-list-empty">No files</div>'}</div>
    </details>`;
}

function renderExtraLibraryFiles(extras) {
  if (!extras?.length) return "";
  const rows = extras
    .map(
      (f) => `
      <div class="file-list-row file-list-row-extra" title="${escapeAttr(f.relative_path)}">
        <span class="format-badge">${escapeHtml(fileExtension(f.name) || "?")}</span>
        <span class="file-list-name">${escapeHtml(f.name)}</span>
        <span class="file-status-pill file-status-extra">Extra</span>
        <span class="file-list-size">${formatBytes(f.size_bytes)}</span>
      </div>`
    )
    .join("");
  return `
    <div class="meta-block extra-files-block">
      <h3>Extra library files</h3>
      <p class="staging-note">Audio in the library folder that does not match this book's source files.</p>
      <div class="file-list-rows">${rows}</div>
    </div>`;
}

function formatLinkError(message) {
  const text = String(message || "");
  if (/cross-device link|errno 18|exdev/i.test(text)) {
    return "Hardlink failed — Books and Audiobooks must share one Docker mount (DATA_ROOT bind).";
  }
  return text;
}

function libraryNamesFromBook(book) {
  const dir = book.staging?.target_dir || book.staged_path || "";
  if (!dir.includes("/")) return null;
  const idx = dir.indexOf("/");
  return { author: dir.slice(0, idx), title: dir.slice(idx + 1) };
}

function isPartialFullyLinked(book) {
  const s = book.staging;
  if (!s) return false;
  return s.linked_count === s.total && s.unlinked_count === 0 && s.total > 0;
}

function renderPartialMeta(book) {
  const lib = libraryNamesFromBook(book);
  const metaAuthor = book.chosen_author || book.suggested_author || "";
  const metaTitle = book.chosen_title || book.suggested_title || book.flatten_name;
  const series = book.effective_series || "";
  const seriesIndex = book.effective_series_index || "";
  const formMatch = book.lvi_form_match;
  const targetKey = book.target_key_preview || book.staged_path || "";
  const metaOpts = { series, seriesIndex, formMatch, targetKey };
  if (lib && (lib.author !== metaAuthor || lib.title !== metaTitle)) {
    return `
      ${renderBookMeta({ author: lib.author, title: lib.title, ...metaOpts })}
      <div class="library-meta-note" title="ID3 / lookup metadata">${escapeHtml(metaAuthor)} — ${escapeHtml(metaTitle)}</div>`;
  }
  return renderBookMeta({ author: metaAuthor, title: metaTitle, titleAttr: metaTitle, ...metaOpts });
}

function renderPartialStagingBlock(book, bookId) {
  if (book.status !== "partial_staged" || !book.staging) return "";
  const s = book.staging;
  const fullyLinked = isPartialFullyLinked(book);
  const summaryParts = [`${s.linked_count} linked`];
  if (s.unlinked_count) summaryParts.push(`${s.unlinked_count} not linked`);
  if (s.source_missing_count) summaryParts.push(`${s.source_missing_count} source missing`);
  const extraCount = (s.extra_library_files || []).length;
  if (extraCount) {
    summaryParts.push(`${extraCount} extra library file${extraCount === 1 ? "" : "s"}`);
  }
  const canLink = s.unlinked_count > 0;
  const canComplete = fullyLinked;
  const canRemoveExtras = extraCount > 0;
  const errorBlock = book.error && !fullyLinked
    ? `<p class="staging-error warn-block">${escapeHtml(formatLinkError(book.error))}</p>`
    : "";
  const linkLabel = canComplete ? "Complete staging" : "Link missing files";
  const linkEnabled = canLink || canComplete;
  return `
    <div class="meta-block staging-status-block">
      <h3>Staging status</h3>
      <p class="staging-summary">${escapeHtml(summaryParts.join(", "))}</p>
      ${errorBlock}
      ${s.target_dir ? `<div class="path-value">Library folder: ${escapeHtml(s.target_dir)}</div>` : ""}
      ${renderStagingFileList(s)}
      ${renderExtraLibraryFiles(s.extra_library_files)}
      <div class="detail-staging-actions">
        <button type="button" class="primary" data-staging-action="complete-partial" data-book-id="${escapeAttr(bookId)}" ${linkEnabled ? "" : "disabled"}>${linkLabel}</button>
        <button type="button" class="danger" data-staging-action="remove-extras" data-book-id="${escapeAttr(bookId)}" ${canRemoveExtras ? "" : "disabled"}>Remove extras</button>
        <button type="button" data-staging-action="unstage" data-book-id="${escapeAttr(bookId)}">Unstage</button>
      </div>
    </div>`;
}

function formatPartialLinked(book) {
  const s = book.staging;
  if (!s) return "—";
  return `${s.linked_count} / ${s.total}`;
}

function renderPartialActions(book) {
  const unlinked = book.staging?.unlinked_count ?? 0;
  const canComplete = isPartialFullyLinked(book) && book.status === "partial_staged";
  const enabled = unlinked > 0 || canComplete;
  const label = canComplete && !unlinked ? "Complete" : "Link missing";
  return `
    <div class="actions-inner">
      <button data-action="detail" data-id="${book.id}">Detail</button>
      <button data-action="complete-partial" data-id="${book.id}" ${enabled ? "" : "disabled"}>${label}</button>
      <button data-action="unstage" data-id="${book.id}">Unstage</button>
    </div>`;
}

function renderTagsPanel(tags) {
  tags = tags || {};
  const primary = PRIMARY_TAG_FIELDS.map((key) => renderTagFieldRow(key, tags[key])).join("");

  const additionalRows = [];
  for (const key of ADDITIONAL_TAG_FIELDS) {
    const val = tags[key];
    if (val) additionalRows.push(renderTagFieldRow(key, val));
  }
  const shownKeys = new Set([...PRIMARY_TAG_FIELDS, ...ADDITIONAL_TAG_FIELDS]);
  const raw = tags.raw && typeof tags.raw === "object" ? tags.raw : {};
  for (const [key, val] of Object.entries(raw)) {
    if (shownKeys.has(key) || val == null || val === "") continue;
    const strVal = typeof val === "string" ? val : JSON.stringify(val);
    additionalRows.push(renderTagFieldRow(key, strVal));
  }

  const additionalBlock = additionalRows.length
    ? `<details class="meta-collapse tags-additional-collapse">
        <summary>Additional</summary>
        <div class="tags-additional">${additionalRows.join("")}</div>
      </details>`
    : "";

  return `
    <details class="meta-collapse tags-panel-collapse">
      <summary>ID3 Tags</summary>
      <div class="tags-panel-body">
        <div class="tags-primary">${primary}</div>
        ${additionalBlock}
      </div>
    </details>`;
}

let copyButtonsAttached = false;

function attachCopyButtons() {
  if (copyButtonsAttached) return;
  copyButtonsAttached = true;
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".tag-copy-btn");
    if (!btn) return;
    const value = btn.dataset.copyValue;
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      showToast("Copied", false);
    } catch {
      showToast("Could not copy", true);
    }
  });
}

function setDurationCellLoading(cell, loading) {
  if (!cell) return;
  if (loading) {
    cell.dataset.loading = "true";
    cell.innerHTML = durationSkeletonHtml;
    return;
  }
  delete cell.dataset.loading;
  cell.innerHTML = renderDurationLoadButton();
}

async function loadSideDuration(cell) {
  if (!cell || cell.dataset.loading === "true" || cell.dataset.loaded === "true") return;

  const sideType = cell.dataset.sideType;
  const bookId = cell.dataset.bookId;
  const targetKey = currentResolveKey || currentConflictKey;

  setDurationCellLoading(cell, true);
  try {
    let total = 0;
    if (sideType === "seed") {
      if (!bookId) {
        throw new Error("Missing book id for this side.");
      }
      const data = await api(`/api/books/${encodeURIComponent(bookId)}/duration`);
      total = data.total_duration_seconds;
    } else if (sideType === "library") {
      if (!targetKey) {
        throw new Error("Conflict target not available.");
      }
      const data = await api(`/api/conflicts/${encodeConflictTargetKey(targetKey)}/duration`);
      const lib = (data.sides || []).find((s) => String(s.side_id) === "library");
      total = lib?.total_duration_seconds ?? 0;
    }
    cell.textContent = formatDuration(total);
    cell.dataset.loaded = "true";
  } catch (err) {
    setDurationCellLoading(cell, false);
    showToast(err.message, true);
  } finally {
    delete cell.dataset.loading;
  }
}

async function loadBookDuration(bookId, cell) {
  const target = cell || document.getElementById("detailDuration");
  if (!bookId || !target || target.dataset.loading === "true" || target.dataset.loaded === "true") return;

  setDurationCellLoading(target, true);
  try {
    const data = await api(`/api/books/${encodeURIComponent(bookId)}/duration`);
    target.textContent = formatDuration(data.total_duration_seconds);
    target.dataset.loaded = "true";
  } catch (err) {
    setDurationCellLoading(target, false);
    showToast(err.message, true);
  } finally {
    delete target.dataset.loading;
  }
}

function renderStats(stats) {
  if (!stats) {
    els.stats.innerHTML = "";
    return;
  }
  els.stats.innerHTML = Object.entries(stats)
    .map(([k, v]) => `<span class="stat-chip">${escapeHtml(k)}: ${escapeHtml(String(v))}</span>`)
    .join("");
}

function setSectionCount({ countEl, sectionEl, count }) {
  const n = Math.max(0, Number(count) || 0);
  if (countEl) {
    countEl.textContent = n > 0 ? String(n) : "";
    countEl.dataset.count = String(n);
  }
  sectionEl?.classList.toggle("section-empty", n === 0);
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(text) {
  return String(text).replaceAll('"', "&quot;");
}

function sanitizeFolderName(name, maxLen = 120) {
  let cleaned = String(name).replace(/[<>:"/\\|?*]/g, "_").replace(/^[\s.]+|[\s.]+$/g, "");
  if (!cleaned) cleaned = "untitled";
  return cleaned.slice(0, maxLen);
}

function formatTitleFolder(title, seriesIndex) {
  const base = sanitizeFolderName(title || "Untitled");
  const idx = String(seriesIndex || "").trim();
  return idx ? `${idx} - ${base}` : base;
}

function computeTargetKey(author, title, series = "", seriesIndex = "") {
  const authorDir = sanitizeFolderName(author || "Unknown Author");
  if (!String(series || "").trim()) {
    return `${authorDir}/${sanitizeFolderName(title || "Untitled")}`;
  }
  const seriesDir = sanitizeFolderName(series);
  return `${authorDir}/${seriesDir}/${formatTitleFolder(title, seriesIndex)}`;
}

function tagsSummaryFromTags(tags) {
  return {
    author: tags?.artist || tags?.albumartist || "",
    title: tags?.title || tags?.album || "",
    narrator: tags?.narrator || "",
    asin: tags?.asin || "",
  };
}

function closeConflictModal() {
  closeResolvePanel();
}

function resetConflictSession() {
  currentConflictKey = null;
  conflictQueue = [];
  conflictSessionBookIds = new Set();
}

function seedBookIdsOf(group) {
  return (group?.sides || [])
    .filter((side) => side.type === "seed" && side.book_id)
    .map((side) => side.book_id);
}

function addGroupToSession(group) {
  if (!group) return;
  for (const id of seedBookIdsOf(group)) {
    conflictSessionBookIds.add(id);
  }
  if (group.target_key && !conflictQueue.includes(group.target_key)) {
    conflictQueue.push(group.target_key);
  }
}

function initConflictSession(group) {
  resetConflictSession();
  currentConflictKey = group?.target_key || null;
  currentResolveKey = currentConflictKey;
  addGroupToSession(group);
}

// Append any live group that now contains a book this session has touched,
// so conflicts spawned by renames/saves get pulled into the queue.
function addLiveGroupsToSession() {
  for (const group of lastConflicts) {
    if (!group?.target_key || conflictQueue.includes(group.target_key)) continue;
    const sides = group.sides || [];
    if (sides.some((side) => side.book_id && conflictSessionBookIds.has(side.book_id))) {
      addGroupToSession(group);
    }
  }
}

// Queue keys that still map to a live conflict group (>=2 sides), in queue order.
function liveConflictGroups() {
  return conflictQueue
    .map((key) => lastConflicts.find((g) => g.target_key === key))
    .filter((g) => g && (g.sides || []).length >= 2);
}

function getSelectedWinnerSideId() {
  return els.conflictDialogContent.querySelector('input[type="radio"]:checked')?.value || "";
}

function getWinnerCardInputs(winnerSideId) {
  if (!winnerSideId || winnerSideId === "library") return null;
  const card = els.conflictDialogContent.querySelector(
    `.conflict-side-card input[type="radio"][value="${CSS.escape(winnerSideId)}"]`
  )?.closest(".conflict-side-card");
  if (!card) return null;
  const author = card.querySelector(`.conflict-author[data-book-id="${winnerSideId}"]`)?.value ?? "";
  const title = card.querySelector(`.conflict-title[data-book-id="${winnerSideId}"]`)?.value ?? "";
  const series = card.querySelector(`.conflict-series[data-book-id="${winnerSideId}"]`)?.value ?? "";
  const seriesIndex = card.querySelector(`.conflict-series-index[data-book-id="${winnerSideId}"]`)?.value ?? "";
  return { author, title, series, seriesIndex };
}

function updateConflictApproveFooter() {
  const winner = getSelectedWinnerSideId();
  if (winner === "library") {
    els.conflictApproveBtn.textContent = "Keep library";
    els.conflictApprovePreview.classList.add("hidden");
    els.conflictApprovePreview.textContent = "";
    return;
  }
  if (!winner) {
    els.conflictApproveBtn.textContent = "Select";
    els.conflictApprovePreview.classList.add("hidden");
    els.conflictApprovePreview.textContent = "";
    return;
  }
  els.conflictApproveBtn.textContent = "Stage winner";
  const inputs = getWinnerCardInputs(winner);
  if (!inputs) {
    els.conflictApprovePreview.classList.add("hidden");
    els.conflictApprovePreview.textContent = "";
    return;
  }
  const targetKey = computeTargetKey(inputs.author, inputs.title, inputs.series, inputs.seriesIndex);
  els.conflictApprovePreview.classList.remove("hidden");
  els.conflictApprovePreview.textContent = `Stage to: ${targetKey}`;
}

function collectConflictSeedEdits() {
  const edits = new Map();
  els.conflictDialogContent.querySelectorAll(".conflict-author").forEach((input) => {
    const bookId = input.dataset.bookId;
    if (!bookId) return;
    const titleInput = els.conflictDialogContent.querySelector(
      `.conflict-title[data-book-id="${CSS.escape(bookId)}"]`
    );
    const seriesInput = els.conflictDialogContent.querySelector(
      `.conflict-series[data-book-id="${CSS.escape(bookId)}"]`
    );
    const seriesIndexInput = els.conflictDialogContent.querySelector(
      `.conflict-series-index[data-book-id="${CSS.escape(bookId)}"]`
    );
    edits.set(bookId, {
      author: input.value,
      title: titleInput?.value ?? "",
      series: seriesInput?.value ?? "",
      seriesIndex: seriesIndexInput?.value ?? "",
    });
  });
  return edits;
}

function renderSummaryCard(side) {
  const tags = side.tags_summary || side.tags || {};
  const label = side.type === "library"
    ? "Library"
    : escapeHtml(side.source_path || side.book_id || "Seed");
  const metaAuthor =
    side.effective_author || tags.author || tags.artist || "";
  const metaTitle = side.effective_title || tags.title || tags.album || "";
  const metaBlock =
    metaAuthor || metaTitle || side.effective_series || side.effective_series_index
      ? `<div class="summary-card-meta">${renderBookMeta({
          author: metaAuthor,
          title: metaTitle,
          series: side.effective_series || "",
          seriesIndex: side.effective_series_index || "",
        })}</div>`
      : "";
  return `
    <div class="summary-card">
      ${metaBlock}
      <div class="summary-card-title">${label}</div>
      <dl class="summary-dl">
        <dt>Files</dt><dd>${side.file_count ?? "—"}</dd>
        <dt>Total size</dt><dd>${formatBytes(side.total_size_bytes)}</dd>
        <dt>Duration</dt><dd class="side-duration" data-side-id="${escapeAttr(side.side_id || "")}" data-side-type="${escapeAttr(side.type || "")}" data-book-id="${escapeAttr(side.book_id || "")}">${renderDurationLoadButton()}</dd>
        <dt>Full path</dt><dd class="path-value">${escapeHtml(side.full_path || "—")}</dd>
        <dt>Format</dt><dd>${escapeHtml(side.dominant_format || "—")}</dd>
        <dt>Confidence</dt><dd>${side.confidence != null ? renderScorePill(side.confidence) : "—"}</dd>
        <dt>Author</dt><dd>${escapeHtml(tags.author || tags.artist || "—")}</dd>
        <dt>Title</dt><dd>${escapeHtml(tags.title || tags.album || "—")}</dd>
        <dt>Narrator</dt><dd>${escapeHtml(tags.narrator || "—")}</dd>
        <dt>ASIN</dt><dd>${escapeHtml(tags.asin || "—")}</dd>
      </dl>
    </div>
  `;
}

function renderBookActions(book, { allowApprove = true } = {}) {
  const filter = getActiveFilter();
  if (filter === "staged") {
    return `
    <div class="actions-inner">
      <button data-action="detail" data-id="${book.id}">Detail</button>
      <button data-action="unstage" data-id="${book.id}">Unstage</button>
    </div>`;
  }
  if (filter === "skipped") {
    return `
    <div class="actions-inner">
      <button data-action="detail" data-id="${book.id}">Detail</button>
      <button data-action="unskip" data-id="${book.id}">Unskip</button>
    </div>`;
  }
  const pending = book.status === "pending";
  return `
    <div class="actions-inner">
      <button data-action="detail" data-id="${book.id}">Detail</button>
      <button data-action="approve" data-id="${book.id}" ${pending && allowApprove ? "" : "disabled"}>Approve</button>
      <button data-action="skip" data-id="${book.id}" ${pending ? "" : "disabled"}>Skip</button>
    </div>
  `;
}

function renderBookItem(book, { showCheckbox = true, allowApprove = true } = {}) {
  const filter = getActiveFilter();
  const selectable = isRowSelectable(book);
  const checked = selectionByFilter[filter]?.has(book.id);
  const skippedClass = book.status === "skipped" ? " book-item--skipped" : "";
  const checkCell = showCheckbox
    ? `<div class="book-item__check"><input type="checkbox" class="row-check" data-id="${book.id}" ${selectable ? "" : "disabled"} ${checked ? "checked" : ""} aria-label="Select book" /></div>`
    : "";
  return `
    <article class="book-item${skippedClass}" role="listitem" data-book-id="${book.id}">
      ${checkCell}
      <div class="book-item__path path" data-label="Source path">${escapeHtml(book.source_path)}</div>
      <div class="book-item__files" data-label="Files">${book.file_count}</div>
      <div class="book-item__meta" data-label="Book">
        ${renderEffectiveBookMeta(book)}
      </div>
      <div class="book-item__conf" data-label="Conf">${renderBookConfidence(book)}</div>
      <div class="book-item__status" data-label="Status"><span class="status-pill">${book.status}</span></div>
      <div class="book-item__actions">${renderBookActions(book, { allowApprove })}</div>
    </article>
  `;
}

function renderPartialItem(book) {
  return `
    <article class="book-item" role="listitem" data-book-id="${book.id}">
      <div class="book-item__path path" data-label="Source path">${escapeHtml(book.source_path)}</div>
      <div class="book-item__files" data-label="Files">${book.file_count}</div>
      <div class="book-item__linked col-linked-cell" data-label="Linked">${escapeHtml(formatPartialLinked(book))}</div>
      <div class="book-item__meta" data-label="Book">
        ${renderPartialMeta(book)}
      </div>
      <div class="book-item__status" data-label="Status"><span class="status-pill">${book.status}</span></div>
      <div class="book-item__actions">${renderPartialActions(book)}</div>
    </article>
  `;
}

function buildUnifiedGroups(conflicts, merges) {
  const map = new Map();
  for (const conflict of conflicts || []) {
    map.set(conflict.target_key, { target_key: conflict.target_key, conflict, merge: null });
  }
  for (const merge of merges || []) {
    const existing = map.get(merge.target_key);
    if (existing) {
      existing.merge = merge;
    } else {
      map.set(merge.target_key, { target_key: merge.target_key, conflict: null, merge });
    }
  }
  return [...map.values()].sort((a, b) => a.target_key.localeCompare(b.target_key));
}

function getUnifiedGroup(targetKey) {
  return buildUnifiedGroups(lastConflicts, lastMerges).find((g) => g.target_key === targetKey) || null;
}

function unifiedTargetMetadata(group) {
  return parseTargetKeyDisplay(group.target_key || "");
}

function unifiedSidesCount(group) {
  if (group.conflict) return (group.conflict.sides || []).length;
  return (group.merge?.members || []).length;
}

function unifiedKindLabel(group) {
  if (group.conflict?.conflict_kind) {
    return renderConflictKindTag(group.conflict.conflict_kind);
  }
  return '<span class="conflict-kind-pill conflict-kind-pending" title="Split audiobook parts at the same target">Merge</span>';
}

function mergeEligibleCount(group) {
  if (group.merge) return (group.merge.members || []).length;
  return (group.conflict?.merge_eligible_seed_ids || []).length;
}

function canResolveSelect(group) {
  return Boolean(group.conflict && (group.conflict.sides || []).length >= 2);
}

function canResolveMerge(group) {
  return mergeEligibleCount(group) >= 2;
}

function defaultResolveMode(group) {
  if (canResolveSelect(group)) return "select";
  if (canResolveMerge(group)) return "merge";
  return "merge";
}

function mergeDraftStorageKey(targetKey) {
  return `${MERGE_DRAFT_PREFIX}${targetKey}`;
}

function getMergeDraft(targetKey) {
  try {
    const raw = sessionStorage.getItem(mergeDraftStorageKey(targetKey));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(String) : null;
  } catch (_err) {
    return null;
  }
}

function persistMergeDraft(targetKey, memberIds) {
  try {
    if (!memberIds?.length) {
      sessionStorage.removeItem(mergeDraftStorageKey(targetKey));
      return;
    }
    sessionStorage.setItem(mergeDraftStorageKey(targetKey), JSON.stringify(memberIds));
  } catch (_err) {
    /* ignore quota / private mode */
  }
}

function mergeStagedNamesStorageKey(targetKey) {
  return `${MERGE_STAGED_NAMES_PREFIX}${targetKey}`;
}

function getMergeStagedNamesOverrides(targetKey) {
  if (!targetKey) return {};
  try {
    const raw = sessionStorage.getItem(mergeStagedNamesStorageKey(targetKey));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).map(([source, name]) => [String(source), String(name)])
    );
  } catch (_err) {
    return {};
  }
}

function persistMergeStagedNamesOverrides(targetKey, overrides) {
  if (!targetKey) return;
  try {
    const key = mergeStagedNamesStorageKey(targetKey);
    if (!overrides || !Object.keys(overrides).length) {
      sessionStorage.removeItem(key);
      return;
    }
    sessionStorage.setItem(key, JSON.stringify(overrides));
  } catch (_err) {
    /* ignore quota / private mode */
  }
}

function clearMergeSessionData(targetKey) {
  persistMergeDraft(targetKey, null);
  persistMergeStagedNamesOverrides(targetKey, null);
  setMergeSortMode(targetKey, null);
}

function mergeSortModeStorageKey(targetKey) {
  return `${MERGE_SORT_MODE_PREFIX}${targetKey}`;
}

function getMergeSortMode(targetKey) {
  if (!targetKey) return null;
  try {
    const raw = sessionStorage.getItem(mergeSortModeStorageKey(targetKey));
    if (raw === "pending") return "pending";
    if (raw === "basename") return "basename";
    return null;
  } catch (_err) {
    return null;
  }
}

function setMergeSortMode(targetKey, mode) {
  if (!targetKey) return;
  try {
    const key = mergeSortModeStorageKey(targetKey);
    if (!mode) {
      sessionStorage.removeItem(key);
      return;
    }
    sessionStorage.setItem(key, mode);
  } catch (_err) {
    /* ignore quota / private mode */
  }
}

function hasMergeStagedNameOverrides(targetKey = currentResolveKey) {
  return Object.keys(getMergeStagedNamesOverrides(targetKey)).length > 0;
}

let localeFileCollator = null;

function localeFileCollatorFn() {
  if (!localeFileCollator) {
    localeFileCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  }
  return localeFileCollator;
}

function compareStagedRows(a, b, mode) {
  const collator = localeFileCollatorFn();
  const fieldA = mode === "pending" ? a.staged_name || "" : a.basename || "";
  const fieldB = mode === "pending" ? b.staged_name || "" : b.basename || "";
  const cmp = collator.compare(fieldA, fieldB);
  if (cmp !== 0) return cmp;
  return String(a.source || "").localeCompare(String(b.source || ""));
}

function formatNumberedStagedName(index, total, basename) {
  const padWidth = Math.max(2, String(total).length);
  const num = String(index).padStart(padWidth, "0");
  const name = String(basename || "");
  const dot = name.lastIndexOf(".");
  if (dot < 0) return num;
  return num + name.slice(dot);
}

function buildNumberOverrides(rowsInDisplayOrder) {
  const total = rowsInDisplayOrder.length;
  const overrides = {};
  rowsInDisplayOrder.forEach((row, index) => {
    if (!row.source) return;
    overrides[row.source] = formatNumberedStagedName(index + 1, total, row.basename);
  });
  return overrides;
}

function buildPrefixOverrides(rows, membersByBookId) {
  const overrides = {};
  for (const row of rows) {
    if (!row.source) continue;
    const member = membersByBookId.get(row.book_id);
    const label = member ? mergePartLabel(member) : row.part_label || "";
    overrides[row.source] = label ? `${label}_${row.basename}` : row.basename;
  }
  return overrides;
}

function sortStagedFilesInCache(mode) {
  if (!mergePreviewCache?.staged_files?.length) return;
  const rows = readStagedNameRowsFromDom();
  const order = [...rows]
    .sort((a, b) => compareStagedRows(a, b, mode))
    .map((row) => row.source);
  const bySource = new Map(mergePreviewCache.staged_files.map((entry) => [entry.source, entry]));
  mergePreviewCache.staged_files = order.map((source) => bySource.get(source)).filter(Boolean);
}

function ensureDefaultMergeSort(targetKey) {
  if (!mergePreviewCache?.staged_files?.length) return;
  const mode = getMergeSortMode(targetKey) || "basename";
  setMergeSortMode(targetKey, mode);
  sortStagedFilesInCache(mode);
}

function mergeSortModeLabel(mode) {
  return mode === "pending" ? "pending" : "basename";
}

function renderMergeNamingToolbar(sortMode) {
  const mode = mergeSortModeLabel(sortMode);
  const sortLabel = mode === "pending" ? "Sort: pending" : "Sort: basename";
  return `
    <div class="merge-naming-actions">
      <button type="button" class="merge-name-action" data-action="number" title="Assign 01, 02, 03… in current list order">Number files</button>
      <button type="button" class="merge-name-action" data-action="prefix">Prefix folders</button>
      <button type="button" class="merge-name-action merge-name-action--sort" data-action="sort" data-sort-mode="${escapeAttr(mode)}">${escapeHtml(sortLabel)}</button>
      <button type="button" class="merge-name-action" data-action="reset">Reset names</button>
      <span class="merge-naming-hint">Number uses current list order (${escapeHtml(sortLabel)})</span>
    </div>`;
}

function mergePartLabel(member) {
  if (member?.flatten_name) return member.flatten_name;
  const path = member?.source_path || "";
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] || member?.book_id || "";
}

function effectiveStagedName(entry, overrides) {
  const override = overrides?.[entry.source];
  if (override != null && String(override).trim()) return String(override).trim();
  return entry.staged_name || entry.basename || "";
}

function collectStagedNameRows(preview, targetKey = currentResolveKey) {
  const overrides = getMergeStagedNamesOverrides(targetKey);
  return (preview?.staged_files || []).map((entry) => ({
    ...entry,
    staged_name: effectiveStagedName(entry, overrides),
  }));
}

function findDuplicateStagedNames(rows) {
  const seen = new Map();
  const duplicates = new Set();
  for (const row of rows) {
    const name = (row.staged_name || "").trim();
    if (!name) continue;
    if (seen.has(name)) {
      duplicates.add(name);
      duplicates.add(seen.get(name));
    } else {
      seen.set(name, name);
    }
  }
  return duplicates;
}

function hasInvalidStagedNames(rows) {
  if (!rows.length) return false;
  if (rows.some((row) => !(row.staged_name || "").trim())) return true;
  return findDuplicateStagedNames(rows).size > 0;
}

function syncStagedNamesOverridesFromInputs() {
  if (!currentResolveKey) return {};
  const overrides = { ...getMergeStagedNamesOverrides(currentResolveKey) };
  const inputs = els.conflictDialogContent?.querySelectorAll(".staged-file-input") || [];
  for (const input of inputs) {
    const source = input.dataset.source;
    if (!source) continue;
    const value = input.value.trim();
    if (value) overrides[source] = value;
    else delete overrides[source];
  }
  persistMergeStagedNamesOverrides(currentResolveKey, overrides);
  return overrides;
}

function getStagedNamesPayload() {
  const overrides = syncStagedNamesOverridesFromInputs();
  return Object.fromEntries(
    Object.entries(overrides).filter(([, name]) => String(name).trim())
  );
}

function getResolveStatus(group) {
  if (group.conflict?.winner_side_id) {
    const winner = group.conflict.winner_side_id;
    if (winner === "library") return "Keep library";
    const side = (group.conflict.sides || []).find((s) => s.side_id === winner);
    return side?.source_path || side?.book_id || winner;
  }
  const draft = getMergeDraft(group.target_key);
  if (draft && draft.length >= 2) {
    return `${draft.length} parts selected`;
  }
  return "—";
}

function renderUnifiedConflictRow(group) {
  const sidesLabel = group.conflict
    ? `${unifiedSidesCount(group)} sides`
    : `${unifiedSidesCount(group)} parts`;
  return `
    <article class="book-item" role="listitem" data-target-key="${escapeAttr(group.target_key)}">
      <div class="book-item__meta" data-label="Book">
        ${renderBookMetaFromTargetKey(group.target_key)}
      </div>
      <div class="book-item__sides" data-label="Sides">${escapeHtml(sidesLabel)}</div>
      <div class="book-item__kind" data-label="Kind">${unifiedKindLabel(group)}</div>
      <div class="book-item__status" data-label="Status">${escapeHtml(getResolveStatus(group))}</div>
      <div class="book-item__actions">
        <div class="actions-inner">
          <button type="button" class="conflict-resolve-btn" data-target-key="${escapeAttr(group.target_key)}">Resolve</button>
        </div>
      </div>
    </article>
  `;
}

function storeConflictsAndMerges(conflicts, merges) {
  lastConflicts = Array.isArray(conflicts) ? conflicts : [];
  lastMerges = Array.isArray(merges) ? merges : [];
  mergeBookIds = new Set();
  for (const group of lastMerges) {
    for (const id of group.member_book_ids || []) {
      mergeBookIds.add(id);
    }
  }
}

function updateConflictsSection() {
  if (sectionsBlocked) return;
  const groups = buildUnifiedGroups(lastConflicts, lastMerges);
  setSectionCount({
    countEl: els.conflictsCount,
    sectionEl: els.conflictsSection,
    count: groups.length,
  });
}

function renderUnifiedConflicts() {
  if (sectionsBlocked) return;
  const groups = buildUnifiedGroups(lastConflicts, lastMerges);
  updateConflictsSection();
  if (!els.conflictsList) {
    console.error("conflictsList element missing from page");
    return;
  }
  if (!groups.length) {
    els.conflictsList.innerHTML = "";
    setSectionListView({
      emptyEl: els.conflictsEmpty,
      listEl: els.conflictsListWrap,
      hasItems: false,
      message: "No conflicts.",
    });
    return;
  }
  try {
    setSectionListView({
      emptyEl: els.conflictsEmpty,
      listEl: els.conflictsListWrap,
      hasItems: true,
    });
    els.conflictsList.innerHTML = groups.map((group) => renderUnifiedConflictRow(group)).join("");
  } catch (err) {
    console.error("renderUnifiedConflicts failed", err);
    els.conflictsList.innerHTML = `<p class="empty-section conflict-error">Failed to render conflicts: ${escapeHtml(err.message)}</p>`;
  }
}

function getMergeEndpoints(group) {
  const key = encodeMergeTargetKey(group.target_key);
  if (group.merge) {
    return {
      preview: `/api/merges/${key}/preview`,
      approve: `/api/merges/${key}`,
    };
  }
  const conflictKey = encodeConflictTargetKey(group.target_key);
  return {
    preview: `/api/conflicts/${conflictKey}/merge/preview`,
    approve: `/api/conflicts/${conflictKey}/merge`,
  };
}

function getMergeMembers(group) {
  if (group.merge) return group.merge.members || [];
  const eligible = new Set(group.conflict?.merge_eligible_seed_ids || []);
  return (group.conflict?.sides || [])
    .filter((side) => side.type === "seed" && eligible.has(side.book_id))
    .map((side) => ({
      ...side,
      chosen_author: side.chosen_author,
      chosen_title: side.chosen_title,
      suggested_author: side.suggested_author,
      suggested_title: side.suggested_title,
    }));
}

function getDefaultPrimaryBookId(group, selectedIds) {
  const members = getMergeMembers(group).filter((member) => selectedIds.includes(member.book_id));
  if (!members.length) return "";
  const best = [...members].sort(
    (a, b) => (Number(b.confidence) || 0) - (Number(a.confidence) || 0)
  )[0];
  return best?.book_id || members[0]?.book_id || "";
}

function renderCandidateBookMeta(c) {
  return renderBookMeta({
    author: c.author,
    title: c.title,
    series: c.series || "",
    seriesIndex: c.series_index || "",
    lviAuthorMatched: c.lvi_author_matched,
    lviSeriesMatched: c.lvi_series_matched,
  });
}

function renderCandidateRow(c, { bookId, isSuggestedPick = false, applyClass = "", applyAttrs = "" } = {}) {
  const suggestedTag = isSuggestedPick
    ? `<span class="candidate-suggested-tag">Suggested</span>`
    : "";
  return `
      <div class="candidate">
        <div class="candidate-info">
          ${renderCandidateBookMeta(c)}
          <div class="candidate-meta">${suggestedTag}${suggestedTag ? " · " : ""}${escapeHtml(c.source || "")} ${renderCandidateScores(c)}</div>
        </div>
        <button type="button" class="${applyClass}" ${applyAttrs}>Apply</button>
      </div>`;
}

function renderDetailCandidates(book) {
  const candidates = book.candidates || [];
  if (!candidates.length) return "";
  return candidates
    .map((c, index) =>
      renderCandidateRow(c, {
        isSuggestedPick: index === 0,
        applyAttrs: `data-apply-author="${escapeAttr(c.author)}" data-apply-title="${escapeAttr(c.title)}" data-apply-series="${escapeAttr(c.series || "")}" data-apply-series-index="${escapeAttr(c.series_index || "")}"`,
      })
    )
    .join("");
}

function renderConflictCandidates(bookId, candidates) {
  if (!candidates?.length) {
    return "<div>No candidates</div>";
  }
  return candidates
    .map((c, index) =>
      renderCandidateRow(c, {
        isSuggestedPick: index === 0,
        applyClass: "conflict-candidate-apply",
        applyAttrs: `data-book-id="${escapeHtml(bookId)}" data-author="${escapeAttr(c.author)}" data-title="${escapeAttr(c.title)}" data-series="${escapeAttr(c.series || "")}" data-series-index="${escapeAttr(c.series_index || "")}"`,
      })
    )
    .join("");
}

function encodeConflictTargetKey(targetKey) {
  return String(targetKey)
    .split("/")
    .map(encodeURIComponent)
    .join("/");
}

function encodeMergeTargetKey(targetKey) {
  return encodeConflictTargetKey(targetKey);
}

function renderMergeSideCard(member, checkedIds) {
  const label = escapeHtml(member.source_path || member.book_id || "Seed");
  const files = member.files || [];
  const checked = !checkedIds || checkedIds.includes(member.book_id);
  return `
    <div class="conflict-side-card" data-book-id="${escapeAttr(member.book_id)}">
      <div class="conflict-side-card-header">
        <label class="merge-include-pick">
          <input type="checkbox" name="merge-include" value="${escapeAttr(member.book_id)}" ${checked ? "checked" : ""} />
          <span class="conflict-side-card-label">${label}</span>
        </label>
        <button type="button" class="merge-prefix-btn" data-book-id="${escapeAttr(member.book_id)}" title="Prefix all files with folder name">Prefix folder</button>
      </div>
      <div class="conflict-side-card-body">
        ${renderSummaryCard(member)}
        ${renderFileList(files)}
        ${renderTagsPanel(member.tags || {})}
      </div>
    </div>
  `;
}

function renderStagedFilesPreview(stagedFiles, filenameConflicts, duplicateStagedNames) {
  const conflictNames = new Set((filenameConflicts || []).map((item) => item.basename));
  const dupNames = duplicateStagedNames || new Set();
  const rows = (stagedFiles || [])
    .map((entry) => {
      const collision = conflictNames.has(entry.basename) || dupNames.has((entry.staged_name || "").trim());
      return `
        <div class="staged-file-row${collision ? " staged-file-row--collision" : ""}" data-source="${escapeAttr(entry.source)}">
          <span class="staged-file-source" title="${escapeAttr(entry.source || entry.basename)}">${escapeHtml(entry.basename || entry.source || "—")}</span>
          <span class="staged-file-arrow" aria-hidden="true">→</span>
          <input type="text" class="staged-file-input" data-source="${escapeAttr(entry.source)}" value="${escapeAttr(entry.staged_name || "")}" spellcheck="false" aria-label="Library filename for ${escapeAttr(entry.basename || entry.source)}" />
        </div>`;
    })
    .join("");
  return rows
    ? `<div class="staged-files-list">${rows}</div>`
    : '<p class="merge-duration-total">No staged filenames to preview.</p>';
}

function renderMergePreviewAccordion({ open = false, badge = "", summaryRight = "", body = "" } = {}) {
  const meta = summaryRight
    ? `<span class="merge-preview-accordion__meta">${summaryRight}</span>`
    : "";
  return `
    <details class="merge-preview-accordion"${open ? " open" : ""}>
      <summary class="merge-preview-accordion__header">
        <span class="merge-preview-accordion__header-left">
          <span class="merge-preview-accordion__chevron" aria-hidden="true"></span>
          <span class="merge-preview-accordion__title">Combined preview</span>
          ${badge}
        </span>
        ${meta}
      </summary>
      <div class="merge-preview-accordion__body">
        ${body}
      </div>
    </details>`;
}

function renderMergePreviewBlock(preview) {
  if (!preview) {
    return renderMergePreviewAccordion({
      summaryRight: "Loading…",
      body: '<p class="merge-duration-total">Loading preview…</p>',
    });
  }
  const filenameConflicts = preview.filename_conflicts || [];
  const hasFilenameConflicts = filenameConflicts.length > 0;
  const stagedRows = collectStagedNameRows(preview);
  const duplicateStagedNames = findDuplicateStagedNames(stagedRows);
  const hasStagedNameIssues =
    duplicateStagedNames.size > 0 || stagedRows.some((row) => !(row.staged_name || "").trim());
  const hasOverrides = Object.keys(getMergeStagedNamesOverrides(currentResolveKey)).length > 0;
  const badge = hasFilenameConflicts
    ? `<span class="filename-conflict-warn" title="Duplicate basenames — edit library filenames below">△ ${filenameConflicts.length} filename conflict${filenameConflicts.length === 1 ? "" : "s"}</span>`
    : "";
  const fileCount = stagedRows.length;
  const summaryRight = `${fileCount} file${fileCount === 1 ? "" : "s"} · ${escapeHtml(formatDuration(preview.total_duration_seconds))}`;
  const dupWarn = preview.duplicate_duration_warning
    ? `<p class="merge-duplicate-warn warn-block">Duplicate durations detected (${(preview.duplicate_durations_seconds || [])
        .map((s) => formatDuration(s))
        .join(", ")}). Some files may be duplicated across parts.</p>`
    : "";
  const nameWarn = hasStagedNameIssues
    ? `<p class="merge-duplicate-warn warn-block merge-staged-name-warn">Duplicate or empty library filenames — fix before approving.</p>`
    : `<p class="merge-duplicate-warn warn-block merge-staged-name-warn hidden">Duplicate or empty library filenames — fix before approving.</p>`;
  const sortMode = getMergeSortMode(currentResolveKey) || "basename";
  const namingToolbar = fileCount > 0 ? renderMergeNamingToolbar(sortMode) : "";
  return renderMergePreviewAccordion({
    open: hasFilenameConflicts || hasStagedNameIssues || hasOverrides,
    badge,
    summaryRight,
    body: `${dupWarn}${nameWarn}${namingToolbar}${renderStagedFilesPreview(stagedRows, filenameConflicts, duplicateStagedNames)}`,
  });
}

function getSelectedMergeMemberIds() {
  if (!els.conflictDialogContent) return [];
  return [...els.conflictDialogContent.querySelectorAll('input[name="merge-include"]:checked')].map(
    (el) => el.value
  );
}

function updateMergeApproveButtonState() {
  const count = getSelectedMergeMemberIds().length;
  const invalidNames =
    count >= 2 && mergePreviewCache ? hasInvalidStagedNames(readStagedNameRowsFromDom()) : false;
  if (els.mergeApproveBtn) {
    els.mergeApproveBtn.disabled = count < 2 || invalidNames;
    if (count < 2) {
      els.mergeApproveBtn.title = "Select at least two parts to merge";
    } else if (invalidNames) {
      els.mergeApproveBtn.title = "Fix duplicate or empty library filenames";
    } else {
      els.mergeApproveBtn.title = "";
    }
  }
}

function readStagedNameRowsFromDom() {
  const rows = collectStagedNameRows(mergePreviewCache);
  const inputs = els.conflictDialogContent?.querySelectorAll(".staged-file-input") || [];
  for (const input of inputs) {
    const source = input.dataset.source;
    if (!source) continue;
    const row = rows.find((entry) => entry.source === source);
    if (row) row.staged_name = input.value.trim();
  }
  return rows;
}

function updateMergePreviewValidation() {
  const rows = readStagedNameRowsFromDom();
  const duplicateStagedNames = findDuplicateStagedNames(rows);
  els.conflictDialogContent?.querySelectorAll(".staged-file-row").forEach((rowEl) => {
    const source = rowEl.dataset.source;
    const row = rows.find((entry) => entry.source === source);
    const invalid =
      !row ||
      !(row.staged_name || "").trim() ||
      duplicateStagedNames.has((row.staged_name || "").trim());
    rowEl.classList.toggle("staged-file-row--collision", invalid);
  });
  const warnEl = els.conflictDialogContent?.querySelector(".merge-staged-name-warn");
  const hasIssues = hasInvalidStagedNames(rows);
  if (warnEl) warnEl.classList.toggle("hidden", !hasIssues);
  updateMergeApproveButtonState();
}

function rerenderMergePreviewBlock() {
  const block = document.getElementById("mergePreviewBlock");
  if (block && mergePreviewCache) {
    block.innerHTML = renderMergePreviewBlock(mergePreviewCache);
    wireMergePreviewInputs();
    wireMergeNamingActions();
    updateMergePreviewValidation();
  }
}

function applyNumberAllFiles() {
  if (!currentResolveKey || !mergePreviewCache) return;
  syncStagedNamesOverridesFromInputs();
  const rows = readStagedNameRowsFromDom();
  persistMergeStagedNamesOverrides(currentResolveKey, buildNumberOverrides(rows));
  rerenderMergePreviewBlock();
}

function applyPrefixFoldersAll() {
  if (!currentResolveKey || !mergePreviewCache) return;
  const uniGroup = getUnifiedGroup(currentResolveKey);
  if (!uniGroup) return;
  const membersByBookId = new Map(getMergeMembers(uniGroup).map((member) => [member.book_id, member]));
  const rows = readStagedNameRowsFromDom();
  persistMergeStagedNamesOverrides(currentResolveKey, buildPrefixOverrides(rows, membersByBookId));
  rerenderMergePreviewBlock();
}

function toggleSortStagedFilesDisplay() {
  if (!currentResolveKey || !mergePreviewCache) return;
  syncStagedNamesOverridesFromInputs();
  const current = getMergeSortMode(currentResolveKey) || "basename";
  const next = current === "basename" ? "pending" : "basename";
  setMergeSortMode(currentResolveKey, next);
  sortStagedFilesInCache(next);
  rerenderMergePreviewBlock();
}

function resetStagedNames() {
  if (!currentResolveKey || !mergePreviewCache) return;
  const overrides = {};
  for (const entry of mergePreviewCache.staged_files || []) {
    if (entry.source && entry.basename) overrides[entry.source] = entry.basename;
  }
  persistMergeStagedNamesOverrides(currentResolveKey, overrides);
  setMergeSortMode(currentResolveKey, "basename");
  sortStagedFilesInCache("basename");
  rerenderMergePreviewBlock();
}

function wireMergeNamingActions() {
  els.conflictDialogContent?.querySelectorAll(".merge-name-action").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      if (action === "number") applyNumberAllFiles();
      else if (action === "prefix") applyPrefixFoldersAll();
      else if (action === "sort") toggleSortStagedFilesDisplay();
      else if (action === "reset") resetStagedNames();
    });
  });
}

function applyPrefixFolderForBook(bookId) {
  if (!currentResolveKey || !mergePreviewCache) return;
  const uniGroup = getUnifiedGroup(currentResolveKey);
  if (!uniGroup) return;
  const member = getMergeMembers(uniGroup).find((m) => m.book_id === bookId);
  if (!member) return;
  const label = mergePartLabel(member);
  const overrides = { ...getMergeStagedNamesOverrides(currentResolveKey) };
  for (const entry of mergePreviewCache.staged_files || []) {
    if (entry.book_id === bookId) {
      overrides[entry.source] = `${label}_${entry.basename}`;
    }
  }
  persistMergeStagedNamesOverrides(currentResolveKey, overrides);
  rerenderMergePreviewBlock();
}

function wireMergePreviewInputs() {
  els.conflictDialogContent?.querySelectorAll(".staged-file-input").forEach((input) => {
    input.addEventListener("input", () => {
      syncStagedNamesOverridesFromInputs();
      updateMergePreviewValidation();
    });
  });
}

function getMergeMetadataInputs() {
  const author = els.conflictDialogContent?.querySelector("#mergeAuthor")?.value ?? "";
  const title = els.conflictDialogContent?.querySelector("#mergeTitle")?.value ?? "";
  const series = els.conflictDialogContent?.querySelector("#mergeSeries")?.value ?? "";
  const seriesIndex = els.conflictDialogContent?.querySelector("#mergeSeriesIndex")?.value ?? "";
  return { author, title, series, seriesIndex };
}

function syncMergeMetadataFromPrimary() {
  const uniGroup = getUnifiedGroup(currentResolveKey);
  if (!uniGroup) return;
  const selectedIds = getSelectedMergeMemberIds();
  const primaryId = getDefaultPrimaryBookId(uniGroup, selectedIds);
  if (!primaryId) return;
  const member = getMergeMembers(uniGroup).find((m) => m.book_id === primaryId);
  if (!member) return;
  const authorInput = els.conflictDialogContent?.querySelector("#mergeAuthor");
  const titleInput = els.conflictDialogContent?.querySelector("#mergeTitle");
  const seriesInput = els.conflictDialogContent?.querySelector("#mergeSeries");
  const seriesIndexInput = els.conflictDialogContent?.querySelector("#mergeSeriesIndex");
  if (authorInput) {
    authorInput.value = member.effective_author ?? "";
  }
  if (titleInput) {
    titleInput.value = member.effective_title ?? "";
  }
  if (seriesInput) {
    seriesInput.value = member.effective_series ?? "";
  }
  if (seriesIndexInput) {
    seriesIndexInput.value = member.effective_series_index ?? "";
  }
  updateMergeApproveFooter();
}

function updateMergeApproveFooter() {
  const previewEl = els.mergeApprovePreview;
  if (!previewEl) return;
  const selectedCount = getSelectedMergeMemberIds().length;
  const { author, title, series, seriesIndex } = getMergeMetadataInputs();
  const targetKey = computeTargetKey(author, title, series, seriesIndex);
  previewEl.classList.remove("hidden");
  previewEl.textContent =
    selectedCount < 2
      ? "Select at least two parts to merge"
      : `Merge ${selectedCount} parts & stage to: ${targetKey}`;
  updateMergeApproveButtonState();
}

async function fetchMergeGroup(targetKey) {
  try {
    return await api(`/api/merges/${encodeMergeTargetKey(targetKey)}`);
  } catch (err) {
    if (err.status === 404) return null;
    return lastMerges.find((g) => g.target_key === targetKey) || null;
  }
}

async function loadMergePreview(targetKey, memberBookIds, endpoints) {
  const body =
    memberBookIds && memberBookIds.length
      ? { member_book_ids: memberBookIds }
      : undefined;
  const paths = endpoints || getMergeEndpoints(getUnifiedGroup(targetKey) || { target_key: targetKey });
  return api(paths.preview, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}

async function refreshMergePreview() {
  if (!currentResolveKey || currentResolveMode !== "merge") return;
  const uniGroup = getUnifiedGroup(currentResolveKey);
  if (!uniGroup) return;
  const memberBookIds = getSelectedMergeMemberIds();
  const block = document.getElementById("mergePreviewBlock");
  persistMergeDraft(currentResolveKey, memberBookIds);
  if (memberBookIds.length < 2) {
    mergePreviewCache = null;
    if (block) {
      block.innerHTML = renderMergePreviewAccordion({
        body: '<p class="merge-duration-total">Select at least two parts to preview the combined merge.</p>',
      });
    }
    updateMergeApproveButtonState();
    updateMergeApproveFooter();
    return;
  }
  if (block) {
    block.innerHTML = renderMergePreviewBlock(null);
  }
  try {
    const endpoints = getMergeEndpoints(uniGroup);
    mergePreviewCache = await loadMergePreview(currentResolveKey, memberBookIds, endpoints);
    ensureDefaultMergeSort(currentResolveKey);
    if (block && currentResolveKey) {
      block.innerHTML = renderMergePreviewBlock(mergePreviewCache);
      wireMergePreviewInputs();
      wireMergeNamingActions();
    }
  } catch (err) {
    if (block) {
      block.innerHTML = renderMergePreviewAccordion({
        open: true,
        summaryRight: "Error",
        body: `<p class="conflict-error">${escapeHtml(err.message)}</p>`,
      });
    }
  }
  updateMergeApproveButtonState();
  updateMergeApproveFooter();
  updateMergePreviewValidation();
}

function restoreMergeMemberSelection(memberIds) {
  const selected = new Set(memberIds || []);
  els.conflictDialogContent?.querySelectorAll('input[name="merge-include"]').forEach((input) => {
    input.checked = selected.has(input.value);
  });
}

async function handleMergeIncludeChange() {
  const targetKey = currentResolveKey;
  const previousIds = mergeSelectionSnapshot ?? getSelectedMergeMemberIds();
  mergeSelectionSnapshot = null;

  if (hasMergeStagedNameOverrides(targetKey)) {
    const ok = await showConfirmDialog({
      title: "Change merge selection?",
      message:
        "Changing which parts are included will reset library filenames to original basenames and re-sort the list (Sort: basename).",
      confirmLabel: "Change selection",
      cancelLabel: "Cancel",
      preferenceKey: "merge-selection-change",
    });
    if (!ok) {
      restoreMergeMemberSelection(previousIds);
      return;
    }
    persistMergeStagedNamesOverrides(targetKey, null);
  }

  setMergeSortMode(targetKey, "basename");
  syncMergeMetadataFromPrimary();
  await refreshMergePreview();
  renderUnifiedConflicts();
}

function wireMergePanelInteractions() {
  els.conflictDialogContent?.querySelectorAll('input[name="merge-include"]').forEach((input) => {
    input.addEventListener("pointerdown", () => {
      mergeSelectionSnapshot = getSelectedMergeMemberIds();
    });
    input.addEventListener("change", () => {
      void handleMergeIncludeChange();
    });
  });
  els.conflictDialogContent?.querySelectorAll(".merge-prefix-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyPrefixFolderForBook(btn.dataset.bookId);
    });
  });
  els.conflictDialogContent?.querySelector("#mergeAuthor")?.addEventListener("input", updateMergeApproveFooter);
  els.conflictDialogContent?.querySelector("#mergeTitle")?.addEventListener("input", updateMergeApproveFooter);
  els.conflictDialogContent?.querySelector("#mergeSeries")?.addEventListener("input", updateMergeApproveFooter);
  els.conflictDialogContent?.querySelector("#mergeSeriesIndex")?.addEventListener("input", updateMergeApproveFooter);
  wireMergePreviewInputs();
}

function renderResolveTabstrip(uniGroup) {
  const showSelect = canResolveSelect(uniGroup);
  const showMerge = canResolveMerge(uniGroup);
  if (!showSelect || !showMerge) return "";
  const selectActive = currentResolveMode === "select";
  return `
    <div class="resolve-tabstrip" role="tablist" aria-label="Resolve mode">
      <button type="button" class="resolve-tab resolve-tab--primary${selectActive ? " is-active" : ""}" role="tab" data-resolve-mode="select" aria-selected="${selectActive ? "true" : "false"}" tabindex="${selectActive ? "0" : "-1"}">Select</button>
      <button type="button" class="resolve-tab resolve-tab--secondary${selectActive ? "" : " is-active"}" role="tab" data-resolve-mode="merge" aria-selected="${selectActive ? "false" : "true"}" tabindex="${selectActive ? "-1" : "0"}">Merge</button>
    </div>`;
}

function renderResolveTabpanelHeader(uniGroup) {
  if (currentResolveMode === "merge") {
    const members = getMergeMembers(uniGroup);
    return `
      <div class="resolve-tabpanel-header">
        <div class="resolve-target">${renderBookMetaFromTargetKey(uniGroup.target_key)}</div>
        <div class="resolve-meta">${members.length} parts — select which to combine</div>
        <p class="conflict-swipe-hint">Swipe to compare parts →</p>
      </div>`;
  }
  const conflictGroup = uniGroup.conflict;
  const isRelated =
    conflictQueue.length > 1 && conflictGroup.target_key !== conflictQueue[0];
  const relatedBanner = isRelated
    ? `<div class="conflict-modal-warn conflict-related-banner">Related conflict — created by your edits.</div>`
    : "";
  return `
    <div class="resolve-tabpanel-header">
      <div class="resolve-target">${renderBookMetaFromTargetKey(conflictGroup.target_key)}</div>
      <div class="resolve-meta">${conflictGroup.sides.length} sides ${renderConflictKindTag(conflictGroup.conflict_kind)}</div>
      <p class="conflict-swipe-hint">Swipe to compare sides →</p>
      ${relatedBanner}
    </div>`;
}

function renderSelectResolveBody(conflictGroup) {
  const groupIndex = Math.max(
    0,
    lastConflicts.findIndex((g) => g.target_key === conflictGroup.target_key)
  );
  return `
    <div class="conflict-modal-scroll">
      ${conflictGroup.sides.map((side) => renderConflictSideCard(side, conflictGroup, groupIndex)).join("")}
    </div>
  `;
}

function renderMergeResolveBody(uniGroup, preview = mergePreviewCache) {
  const members = getMergeMembers(uniGroup);
  const draft = getMergeDraft(uniGroup.target_key);
  const checkedIds = draft && draft.length ? draft : members.map((m) => m.book_id);
  const primaryId = getDefaultPrimaryBookId(uniGroup, checkedIds);
  const primaryMember = members.find((m) => m.book_id === primaryId);
  const targetMeta = unifiedTargetMetadata(uniGroup);
  const mergeAuthor = primaryMember?.effective_author ?? targetMeta.author;
  const mergeTitle = primaryMember?.effective_title ?? targetMeta.title;
  const mergeSeries = primaryMember?.effective_series ?? targetMeta.series;
  const mergeSeriesIndex = primaryMember?.effective_series_index ?? "";
  return `
    <div class="conflict-modal-scroll">
      ${members.map((member) => renderMergeSideCard(member, checkedIds)).join("")}
    </div>
    <div class="meta-block edit-metadata-form">
      <h3>Merged metadata</h3>
      <label>Author <input id="mergeAuthor" value="${escapeAttr(mergeAuthor)}" /></label>
      <label>Title <input id="mergeTitle" value="${escapeAttr(mergeTitle)}" /></label>
      <label>Series <input id="mergeSeries" value="${escapeAttr(mergeSeries)}" /></label>
      <label>Series # <input id="mergeSeriesIndex" value="${escapeAttr(mergeSeriesIndex)}" /></label>
    </div>
    <div id="mergePreviewBlock">${renderMergePreviewBlock(preview)}</div>
  `;
}

function updateResolvePanelFooter() {
  const isSelect = currentResolveMode === "select";
  const isMerge = currentResolveMode === "merge";
  els.conflictSaveAllBtn?.classList.toggle("hidden", !isSelect);
  els.conflictApproveBtn?.classList.toggle("hidden", !isSelect);
  els.conflictNextBtn?.classList.toggle("hidden", !isSelect);
  els.mergeApproveBtn?.classList.toggle("hidden", !isMerge);
  if (isSelect) {
    els.mergeApprovePreview?.classList.add("hidden");
    els.mergeApprovePreview.textContent = "";
    updateConflictApproveFooter();
    updateConflictNextButton();
  } else {
    els.conflictApprovePreview?.classList.add("hidden");
    els.conflictApprovePreview.textContent = "";
    updateMergeApproveFooter();
  }
}

function canElementScrollVertically(el, deltaY) {
  if (!el) return false;
  const { overflowY } = getComputedStyle(el);
  if (overflowY !== "auto" && overflowY !== "scroll" && overflowY !== "overlay") return false;
  if (deltaY < 0) return el.scrollTop > 0;
  if (deltaY > 0) return el.scrollTop + el.clientHeight < el.scrollHeight - 1;
  return false;
}

function findNestedVerticalScroller(target, panelBody, deltaY) {
  let el = target;
  while (el && el !== panelBody) {
    if (canElementScrollVertically(el, deltaY)) return el;
    el = el.parentElement;
  }
  return null;
}

let resolvePanelWheelWired = false;

function wireResolvePanelWheelScroll() {
  if (resolvePanelWheelWired || !els.conflictDialogContent) return;
  resolvePanelWheelWired = true;
  els.conflictDialogContent.addEventListener(
    "wheel",
    (event) => {
      const panelBody = event.target.closest(".resolve-tabpanel-body--merge");
      if (!panelBody) return;
      const { deltaX, deltaY } = event;
      if (Math.abs(deltaX) > Math.abs(deltaY)) return;
      if (findNestedVerticalScroller(event.target, panelBody, deltaY)) return;
      panelBody.scrollTop += deltaY;
      event.preventDefault();
    },
    { passive: false }
  );
}

async function renderResolvePanelContent(uniGroup) {
  const tabstrip = renderResolveTabstrip(uniGroup);
  const hasTabstrip = Boolean(tabstrip);
  const body =
    currentResolveMode === "merge"
      ? renderMergeResolveBody(uniGroup)
      : renderSelectResolveBody(uniGroup.conflict);
  const panelClass = hasTabstrip
    ? "resolve-tabpanel resolve-tabpanel--tabbed"
    : "resolve-tabpanel resolve-tabpanel--solo";
  const bodyClass =
    currentResolveMode === "merge"
      ? "resolve-tabpanel-body resolve-tabpanel-body--merge"
      : "resolve-tabpanel-body resolve-tabpanel-body--select";
  els.conflictDialogTitle.textContent =
    currentResolveMode === "merge" ? "Merge audiobook parts" : "Resolve conflict";
  els.conflictDialogContent.innerHTML = `
    <div class="resolve-panel${hasTabstrip ? " resolve-panel--tabbed" : ""}">
      ${tabstrip}
      <div class="${panelClass}" role="tabpanel">
        ${renderResolveTabpanelHeader(uniGroup)}
        <div class="${bodyClass}">
          ${body}
        </div>
      </div>
    </div>`;
  if (currentResolveMode === "merge") {
    wireResolvePanelWheelScroll();
    wireMergePanelInteractions();
    syncMergeMetadataFromPrimary();
    updateMergeApproveFooter();
  } else {
    updateConflictApproveFooter();
    updateConflictNextButton();
  }
  updateResolvePanelFooter();
}

async function openResolvePanel(targetKey, { triggerBtn } = {}) {
  const open = async () => {
    try {
      let uniGroup = getUnifiedGroup(targetKey);
      if (!uniGroup) {
        const conflict = await fetchConflictGroup(targetKey);
        const merge = conflict ? null : await fetchMergeGroup(targetKey);
        if (conflict || merge) {
          storeConflictsAndMerges(
            conflict ? [...lastConflicts.filter((g) => g.target_key !== targetKey), conflict] : lastConflicts,
            merge ? [...lastMerges.filter((g) => g.target_key !== targetKey), merge] : lastMerges
          );
          uniGroup = getUnifiedGroup(targetKey);
        }
      }
      if (!uniGroup) {
        showToast("Conflict not found.", true);
        resetConflictSession();
        return;
      }
      currentResolveKey = targetKey;
      currentResolveMode = defaultResolveMode(uniGroup);
      if (!canResolveSelect(uniGroup) && currentResolveMode === "select") {
        currentResolveMode = "merge";
      }
      if (!canResolveMerge(uniGroup) && currentResolveMode === "merge") {
        currentResolveMode = "select";
      }
      if (currentResolveMode === "select" && uniGroup.conflict) {
        initConflictSession(uniGroup.conflict);
      } else {
        resetConflictSession();
        currentResolveKey = targetKey;
      }
      mergePreviewCache = null;
      await renderResolvePanelContent(uniGroup);
      openDialog(els.conflictDialog);
      if (currentResolveMode === "merge") {
        await refreshMergePreview();
      }
    } catch (err) {
      resetResolvePanel();
      showToast(err.message, true);
    }
  };
  if (triggerBtn) {
    return withButtonBusy(triggerBtn, open, { label: "Loading…" });
  }
  return open();
}

function resetResolvePanel() {
  if (currentResolveKey) clearMergeSessionData(currentResolveKey);
  currentResolveKey = null;
  currentResolveMode = "select";
  mergePreviewCache = null;
  resetConflictSession();
}

function closeResolvePanel() {
  els.conflictDialog.close();
  resetResolvePanel();
}

async function setResolveMode(mode) {
  const uniGroup = getUnifiedGroup(currentResolveKey);
  if (!uniGroup) return;
  if (mode === "select" && !canResolveSelect(uniGroup)) return;
  if (mode === "merge" && !canResolveMerge(uniGroup)) return;
  currentResolveMode = mode;
  if (mode === "select" && uniGroup.conflict) {
    initConflictSession(uniGroup.conflict);
  }
  mergePreviewCache = null;
  await renderResolvePanelContent(uniGroup);
  if (mode === "merge") {
    await refreshMergePreview();
  }
}

async function approveMerge(targetKey) {
  const uniGroup = getUnifiedGroup(targetKey);
  if (!uniGroup) {
    showToast("Merge group not found.", true);
    return false;
  }
  const memberBookIds = getSelectedMergeMemberIds();
  if (memberBookIds.length < 2) {
    showToast("Select at least two parts to merge.", true);
    return false;
  }
  const stagedRows = readStagedNameRowsFromDom();
  if (hasInvalidStagedNames(stagedRows)) {
    showToast("Fix duplicate or empty library filenames before merging.", true);
    return false;
  }
  const staged_names = getStagedNamesPayload();
  const { author, title, series, seriesIndex } = getMergeMetadataInputs();
  const endpoints = getMergeEndpoints(uniGroup);
  await withStagingScrim("Merging and staging…", async () => {
    await api(endpoints.approve, {
      method: "POST",
      body: JSON.stringify({
        member_book_ids: memberBookIds,
        chosen_author: author,
        chosen_title: title,
        chosen_series: series,
        chosen_series_index: seriesIndex,
        staged_names,
      }),
    });
    clearMergeSessionData(targetKey);
    await loadBooks();
  });
  closeResolvePanel();
  showToast("Merged and staged", false, true);
  return true;
}

function renderConflictSideCard(side, group, groupIndex) {
  const groupName = `conflict-winner-${groupIndex}`;
  const checked = side.side_id === group.winner_side_id ? "checked" : "";
  const label =
    side.type === "library"
      ? "Library"
      : escapeHtml(side.source_path || side.book_id || "Seed");

  let seedExtras = "";
  if (side.type === "seed") {
    const files = side.files || [];
    seedExtras = `
        ${renderFileList(files)}
        ${renderTagsPanel(side.tags || {})}
        <div class="meta-block edit-metadata-form">
          <h3>Edit metadata</h3>
          <label>Author <input class="conflict-author" data-book-id="${escapeHtml(side.book_id)}" value="${escapeAttr(side.effective_author ?? "")}" /></label>
          <label>Title <input class="conflict-title" data-book-id="${escapeHtml(side.book_id)}" value="${escapeAttr(side.effective_title ?? "")}" /></label>
          <label>Series <input class="conflict-series" data-book-id="${escapeHtml(side.book_id)}" value="${escapeAttr(side.effective_series ?? "")}" /></label>
          <label>Series # <input class="conflict-series-index" data-book-id="${escapeHtml(side.book_id)}" value="${escapeAttr(side.effective_series_index ?? "")}" /></label>
          <div class="edit-metadata-actions">
            <button type="button" class="conflict-save" data-book-id="${escapeHtml(side.book_id)}">Save</button>
          </div>
        </div>
        <div class="meta-block"><h3>Candidates</h3>${renderConflictCandidates(side.book_id, side.candidates)}</div>
        <div class="meta-block">
          <button type="button" class="conflict-skip-btn" data-book-id="${escapeHtml(side.book_id)}">Skip this book</button>
        </div>`;
  }

  return `
    <div class="conflict-side-card">
      <div class="conflict-side-card-header">
        <label class="winner-pick">
          <input type="radio" name="${groupName}" value="${escapeAttr(side.side_id)}" ${checked} />
          <span class="conflict-side-card-label">${label}</span>
        </label>
      </div>
      <div class="conflict-side-card-body">
        ${renderSummaryCard(side)}
        ${seedExtras}
      </div>
    </div>
  `;
}

async function fetchConflictGroup(targetKey) {
  try {
    return await api(`/api/conflicts/${encodeConflictTargetKey(targetKey)}`);
  } catch (err) {
    // Group dissolved (404) after renames — do not fall back to stale lastConflicts.
    if (err.status === 404) return null;
    return lastConflicts.find((g) => g.target_key === targetKey) || null;
  }
}

async function reconcileConflictSession() {
  if (!currentConflictKey || currentResolveMode !== "select") return;

  addLiveGroupsToSession();
  const live = liveConflictGroups();

  let group = live.find((g) => g.target_key === currentConflictKey);
  if (!group && live.length) {
    group = live[0];
    currentConflictKey = group.target_key;
  }

  if (!group) {
    closeResolvePanel();
    return;
  }
  currentResolveKey = currentConflictKey;
  const uniGroup = getUnifiedGroup(currentConflictKey);
  if (!uniGroup) {
    closeResolvePanel();
    return;
  }
  await renderResolvePanelContent(uniGroup);
}

function updateConflictNextButton() {
  const btn = els.conflictNextBtn;
  if (!btn) return;
  if (currentResolveMode !== "select") {
    btn.classList.add("hidden");
    btn.disabled = true;
    return;
  }
  const live = liveConflictGroups();
  if (live.length > 1) {
    btn.classList.remove("hidden");
    btn.disabled = false;
  } else {
    btn.classList.add("hidden");
    btn.disabled = true;
  }
}

async function advanceToNextConflict() {
  const live = liveConflictGroups();
  if (live.length < 2) return;
  const idx = live.findIndex((g) => g.target_key === currentConflictKey);
  const next = live[(idx + 1) % live.length];
  currentConflictKey = next.target_key;
  currentResolveKey = next.target_key;
  const uniGroup = getUnifiedGroup(next.target_key);
  if (uniGroup) await renderResolvePanelContent(uniGroup);
}

async function approveConflict(targetKey, winnerSideId, { chosenAuthor, chosenTitle, chosenSeries, chosenSeriesIndex } = {}) {
  if (!winnerSideId) {
    showToast("Select a winner side first.", true);
    return false;
  }
  let group = lastConflicts.find((g) => g.target_key === targetKey);
  if (!group) {
    group = await fetchConflictGroup(targetKey);
  }

  const winnerIsSeed = winnerSideId !== "library";

  if (!group?.sides?.length) {
    if (!winnerIsSeed) {
      showToast("Conflict not found.", true);
      return false;
    }
    await withStagingScrim("Staging winner…", async () => {
      if (chosenAuthor != null || chosenTitle != null || chosenSeries != null || chosenSeriesIndex != null) {
        await api(`/api/books/${encodeURIComponent(winnerSideId)}`, {
          method: "PATCH",
          body: JSON.stringify({
            chosen_author: chosenAuthor ?? "",
            chosen_title: chosenTitle ?? "",
            chosen_series: chosenSeries ?? "",
            chosen_series_index: chosenSeriesIndex ?? "",
          }),
        });
      }
      await api(`/api/books/${encodeURIComponent(winnerSideId)}/approve`, { method: "POST" });
      await loadBooks();
    });
    return true;
  }

  const hasLibrary = group.has_library_side;
  if (hasLibrary && winnerIsSeed) {
    const ok = await showConfirmDialog({
      title: `Approve seed for “${targetKey}”?`,
      message:
        "Existing library files at this path will be removed and replaced by the seed.",
      confirmLabel: "Replace",
      cancelLabel: "Cancel",
      preferenceKey: "conflict-approve-library",
    });
    if (!ok) return false;
  }
  const body = { winner_side: winnerSideId };
  if (winnerIsSeed) {
    body.chosen_author = chosenAuthor ?? "";
    body.chosen_title = chosenTitle ?? "";
    body.chosen_series = chosenSeries ?? "";
    body.chosen_series_index = chosenSeriesIndex ?? "";
  }
  await withStagingScrim("Staging winner…", async () => {
    await api(`/api/conflicts/${encodeConflictTargetKey(targetKey)}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    await loadBooks();
  });
  return true;
}

async function saveAllConflictEdits() {
  const edits = collectConflictSeedEdits();
  if (!edits.size || !(currentResolveKey || currentConflictKey)) return;

  const result = await api(
    `/api/conflicts/${encodeConflictTargetKey(currentResolveKey || currentConflictKey)}/save-edits`,
    {
      method: "POST",
      body: JSON.stringify({
        edits: [...edits.entries()].map(([bookId, { author, title, series, seriesIndex }]) => ({
          book_id: bookId,
          chosen_author: author,
          chosen_title: title,
          chosen_series: series,
          chosen_series_index: seriesIndex,
        })),
      }),
    }
  );

  const errors = result?.errors || [];
  const saved = result?.saved ?? 0;
  if (errors.length) {
    const detail = errors[0]?.error ? `: ${errors[0].error}` : "";
    showToast(`${errors.length} error(s) saving edits${detail}`, true);
  } else if (saved) {
    showToast(`Saved ${saved} edit${saved === 1 ? "" : "s"}`, false, true);
    flashButtonSaved(els.conflictSaveAllBtn);
  }

  await loadBooks();
  await reconcileConflictSession();
}

function renderBooksPayload(data) {
  if (!data) return;
  renderStats(data.stats);
  storeConflictsAndMerges(data.conflicts, data.merges);
  renderUnifiedConflicts();
  const stagingRaw = data.staging ?? (data.items || []).filter((b) => !b.in_conflict);
  const staging = stagingRaw.filter((b) => !mergeBookIds.has(b.id));
  const partial = data.partial ?? [];
  renderBooks(staging, partial);
  updateStagingBulkBtn();
}

function pruneSelectionForVisible(staging) {
  const filter = getActiveFilter();
  const visible = new Set(staging.map((b) => b.id));
  for (const id of selectionByFilter[filter]) {
    if (!visible.has(id)) selectionByFilter[filter].delete(id);
  }
}

function renderBooks(staging, partial) {
  if (sectionsBlocked) return;
  pruneSelectionForVisible(staging);
  setSectionCount({
    countEl: els.stagingCount,
    sectionEl: els.stagingSection,
    count: staging.length,
  });
  setSectionCount({
    countEl: els.partialCount,
    sectionEl: els.partialSection,
    count: partial.length,
  });
  setSectionListView({
    emptyEl: els.stagingEmpty,
    listEl: els.booksListWrap,
    hasItems: staging.length > 0,
    message: stagingEmptyMessage(),
  });
  setSectionListView({
    emptyEl: els.partialEmpty,
    listEl: els.partialListWrap,
    hasItems: partial.length > 0,
    message: "No partially staged books.",
  });
  const sortedStaging = sortStagingBooks(staging);
  if (els.booksList) {
    els.booksList.innerHTML = sortedStaging.length
      ? sortedStaging.map((b) => renderBookItem(b)).join("")
      : "";
  }
  updateStagingSortIndicators();
  if (els.partialList) {
    els.partialList.innerHTML = partial.length
      ? partial.map(renderPartialItem).join("")
      : "";
  }
}

function formatWhen(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function renderAwayItem(action) {
  return `
    <article class="book-item" role="listitem" data-action-id="${escapeAttr(action.id)}" data-book-id="${escapeAttr(action.book_id)}">
      <div class="book-item__path path" data-label="Source path">${escapeHtml(action.source_path || "—")}</div>
      <div class="book-item__meta" data-label="Book">
        ${renderEffectiveBookMeta(action)}
      </div>
      <div class="book-item__conf" data-label="Conf">${renderScorePill(action.confidence)}</div>
      <div class="book-item__staged path" data-label="Staged at">${escapeHtml(action.staged_path || "—")}</div>
      <div class="book-item__when" data-label="When">${escapeHtml(formatWhen(action.created_at))}</div>
      <div class="book-item__actions">
        <div class="actions-inner icon-actions">
          <button data-away-action="detail" data-id="${escapeAttr(action.book_id)}">Detail</button>
          <button type="button" class="icon-action icon-action-revert" data-away-action="revert" data-id="${escapeAttr(action.book_id)}" data-action-id="${escapeAttr(action.id)}" title="Revert" aria-label="Revert auto-stage">${ICON_REVERT}</button>
          <button type="button" class="icon-action icon-action-okay" data-away-action="dismiss" data-action-id="${escapeAttr(action.id)}" title="Okay" aria-label="Okay">${ICON_CHECK}</button>
        </div>
      </div>
    </article>
  `;
}

function renderAwaySection(items) {
  if (sectionsBlocked) return;
  const list = Array.isArray(items) ? items : [];
  setSectionCount({
    countEl: els.awayCount,
    sectionEl: els.awaySection,
    count: list.length,
  });
  if (!list.length) {
    els.dismissAllAwayBtn?.classList.add("hidden");
    setSectionListView({
      emptyEl: els.awayEmpty,
      listEl: els.awayListWrap,
      hasItems: false,
      message: "Nothing happened while you were away.",
    });
    if (els.awayList) els.awayList.innerHTML = "";
    return;
  }
  els.dismissAllAwayBtn?.classList.remove("hidden");
  setSectionListView({
    emptyEl: els.awayEmpty,
    listEl: els.awayListWrap,
    hasItems: true,
  });
  if (els.awayList) {
    els.awayList.innerHTML = list.map(renderAwayItem).join("");
  }
}

async function loadAwayReview() {
  try {
    const data = await api("/api/auto/review");
    renderAwaySection(data.items || []);
  } catch (err) {
    showToast(err.message, true);
  }
}

const SECTION_BLOCKED_DEFAULTS = {
  loading: "Loading…",
  auto: "Auto-scan and stage in progress — please wait",
  scan: "Scan in progress…",
};

function setSectionsBlocked(blocked, _message, { kind = "auto" } = {}) {
  if (blocked) {
    sectionsBlocked = true;
    sectionsBlockedKind = kind;
    els.scanBtn.disabled = true;
    return;
  }
  sectionsBlocked = false;
  sectionsBlockedKind = null;
  if (!currentScanId) {
    els.scanBtn.disabled = false;
  }
}

function applyAutoStatus(run) {
  if (!run || run.status !== "running") return;
  const msg = run.message || SECTION_BLOCKED_DEFAULTS.auto;
  setSectionsBlocked(true, msg, { kind: "auto" });
  els.bootstrapCancelBtn?.classList.remove("hidden");
  if (els.bootstrapCancelBtn) els.bootstrapCancelBtn.textContent = "Cancel auto-run";
  if (run.phase !== "scanning") {
    els.bootstrapScrim?.classList.remove("hidden");
    setBootstrapScrimOpen(true);
    if (els.bootstrapTitle) {
      els.bootstrapTitle.textContent = "Auto-scan and stage";
      els.bootstrapTitle.classList.remove("hidden");
    }
    els.bootstrapProviders?.classList.add("hidden");
    els.bootstrapStackWrap?.classList.add("hidden");
    els.bootstrapActionBtn?.classList.add("hidden");
    setBootstrapScrimMessage(msg);
  }
}

function clearAutoPollTimer() {
  if (autoPollTimer) {
    clearTimeout(autoPollTimer);
    autoPollTimer = null;
  }
}

function clearScanPollTimer() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function showBootstrapScanProgress(scan, { title = "Scan in progress" } = {}) {
  bootstrapScanActive = true;
  setBootstrapScanPanelMode(true);
  if (els.bootstrapTitle) {
    els.bootstrapTitle.textContent = title;
    els.bootstrapTitle.classList.add("hidden");
  }
  if (els.bootstrapMessage) els.bootstrapMessage.classList.add("hidden");
  els.bootstrapScrim?.classList.remove("hidden");
  setBootstrapScrimOpen(true);
  els.bootstrapActionBtn?.classList.add("hidden");
  bootstrapActionHandler = null;
  scanProgressAnimator.onPoll(
    scan || {
      status: "running",
      books_discovered: 0,
      books_found: 0,
      books_total: 0,
      books_complete: 0,
      metadata_done: 0,
      scan_phase: "discovering",
    },
  );
}

function attachToAutoRun(runId) {
  clearAutoPollTimer();
  currentAutoRunId = runId;
  currentScanId = null;
  bootstrapScanActive = true;
  clearScanPollTimer();
  setScanButtonRunning(false);
  applyAutoStatus({ status: "running", phase: "starting", message: "Auto-run starting..." });
  pollAutoRun();
}

async function pollAutoRun() {
  if (currentScanId) return;
  if (!currentAutoRunId && !sectionsBlocked) return;
  const prevRunId = currentAutoRunId;
  try {
    const run = await api("/api/auto/running");
    if (run.status === "running") {
      currentAutoRunId = run.id;
      applyAutoStatus(run);
      if (run.phase === "scanning" && run.scan_id) {
        try {
          const scan = await api(`/api/scan/${encodeURIComponent(run.scan_id)}`);
          if (scan.status === "running") {
            showBootstrapScanProgress(scan, { title: "Auto-scan in progress" });
            els.bootstrapCancelBtn?.classList.remove("hidden");
            if (els.bootstrapCancelBtn) els.bootstrapCancelBtn.textContent = "Cancel auto-run";
          } else if (scan.status === "completed" && bootstrapScanActive) {
            await scanProgressAnimator.handleScanComplete(scan, async () => {
              bootstrapScanActive = false;
            });
          }
        } catch (_err) {
          /* scan poll optional during auto */
        }
      } else {
        els.bootstrapStackWrap?.classList.add("hidden");
      }
      await loadBooks();
      autoPollTimer = setTimeout(pollAutoRun, SCAN_POLL_MS);
      return;
    }
    currentAutoRunId = null;
    bootstrapScanActive = false;
    resetStackViz(null);
    let finishedMsg = "Auto-scan and stage finished";
    if (prevRunId) {
      try {
        const settings = await api("/api/auto/settings");
        const last = settings.last_run;
        if (last?.id === prevRunId && last.status === "cancelled") {
          finishedMsg = "Auto-run cancelled";
        }
      } catch (_err) {
        /* ignore */
      }
    }
    if (els.bootstrapScrim && !els.bootstrapScrim.classList.contains("hidden")) {
      await completeBootstrapHome();
    } else {
      setSectionsBlocked(false);
      restoreSectionShells();
      await loadBooks();
      await loadAwayReview();
      await refreshAutoSettingsSummary();
    }
    showToast(finishedMsg, false, finishedMsg.includes("cancelled"));
  } catch (err) {
    currentAutoRunId = null;
    if (!currentScanId) {
      bootstrapScanActive = false;
      setSectionsBlocked(false);
      hideBootstrapScrim();
      if (!(await returnToPreScanIfNeeded())) {
        restoreSectionShells();
        await finishBootstrapIdle();
      }
    }
    void loadBooks();
    void loadAwayReview();
    showToast(err.message, true);
  }
}

async function resumeRunningAuto() {
  try {
    const run = await api("/api/auto/running");
    if (run.status === "running" && run.id) {
      attachToAutoRun(run.id);
      applyAutoStatus(run);
      return true;
    }
  } catch (err) {
    showToast(err.message, true);
  }
  return false;
}

function setSettingsTab(tabId) {
  const tabs = ["general", "metadata"];
  activeSettingsTab = tabs.includes(tabId) ? tabId : "general";
  const isMetadata = activeSettingsTab === "metadata";
  els.settingsDialog?.classList.toggle("settings-dialog--wide", isMetadata);
  els.settingsDialog?.querySelectorAll(".resolve-tab[data-settings-tab]").forEach((btn) => {
    const active = btn.dataset.settingsTab === activeSettingsTab;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
    btn.tabIndex = active ? 0 : -1;
  });
  els.settingsDialog?.querySelectorAll(".settings-tabpanel").forEach((panel) => {
    const show = panel.dataset.settingsTab === activeSettingsTab;
    panel.classList.toggle("hidden", !show);
    panel.classList.toggle("is-active", show);
  });
  if (isMetadata && getTitleExtractionMode() === "advanced" && !titleExtractionPreviewBookIds.length) {
    void refreshTitleExtractionPreview({ resample: true });
  }
}

function getTitleExtractionMode() {
  const checked = document.querySelector('input[name="titleExtractionMode"]:checked');
  return checked?.value || "balanced";
}

function applyTitleExtractionModeTooltips() {
  document.querySelectorAll('input[name="titleExtractionMode"]').forEach((input) => {
    const tip = TITLE_EXTRACTION_MODE_TIPS[input.value];
    const label = input.closest("label");
    if (label && tip) label.title = tip;
  });
}

function setTitleExtractionMode(mode) {
  const input = document.querySelector(`input[name="titleExtractionMode"][value="${mode}"]`);
  if (input) input.checked = true;
  onTitleExtractionModeChange();
}

function buildTitleCleanupStepsTable(preSteps, postSteps) {
  const tbody = els.titleCleanupStepsBody;
  if (!tbody) return;
  const pre = new Set(preSteps || []);
  const post = new Set(postSteps || []);
  tbody.replaceChildren();
  for (const step of TITLE_EXTRACTION_STEPS) {
    const tr = document.createElement("tr");

    const actionTd = document.createElement("td");
    actionTd.className = "title-cleanup-action-col";
    actionTd.scope = "row";
    const labelEl = document.createElement("span");
    labelEl.className = "title-cleanup-step-label";
    labelEl.textContent = step.label;
    actionTd.appendChild(labelEl);
    if (step.example) {
      const exampleEl = document.createElement("span");
      exampleEl.className = "title-cleanup-step-example";
      exampleEl.textContent = step.example;
      actionTd.appendChild(exampleEl);
    }
    if (step.tip) {
      actionTd.title = step.example ? `${step.tip}\nExample: ${step.example}` : step.tip;
    }

    const preTd = document.createElement("td");
    preTd.className = "title-cleanup-phase-col";
    const preInput = document.createElement("input");
    preInput.type = "checkbox";
    preInput.value = step.id;
    preInput.dataset.phase = "pre";
    preInput.checked = pre.has(step.id);
    preInput.title = step.tip
      ? `Pre: ${step.tip}`
      : "Apply before fuzzy matching on each candidate";
    preInput.setAttribute("aria-label", `${step.label} pre-cleanup`);
    preInput.addEventListener("change", scheduleTitleExtractionPreview);
    preTd.appendChild(preInput);

    const postTd = document.createElement("td");
    postTd.className = "title-cleanup-phase-col";
    const postInput = document.createElement("input");
    postInput.type = "checkbox";
    postInput.value = step.id;
    postInput.dataset.phase = "post";
    postInput.checked = post.has(step.id);
    postInput.title = step.tip
      ? `Post: ${step.tip}`
      : "Apply after fuzzy matching on the consensus title";
    postInput.setAttribute("aria-label", `${step.label} post-cleanup`);
    postInput.addEventListener("change", scheduleTitleExtractionPreview);
    postTd.appendChild(postInput);

    tr.append(actionTd, preTd, postTd);
    tbody.appendChild(tr);
  }
}

function readTitleCleanupSteps(phase) {
  const selector = `#titleCleanupStepsBody input[data-phase="${phase}"]:checked`;
  return [...document.querySelectorAll(selector)].map((el) => el.value);
}

function advancedStepsForForm(preSteps, postSteps) {
  const pre = preSteps || [];
  const post = postSteps || [];
  if (!pre.length && !post.length) {
    return { pre: ADVANCED_DEFAULT_PRE, post: ADVANCED_DEFAULT_POST };
  }
  return { pre, post };
}

function onTitleExtractionModeChange() {
  const mode = getTitleExtractionMode();
  const advanced = mode === "advanced";
  els.titleExtractionAdvancedPanel?.classList.toggle("hidden", !advanced);
  if (advanced) {
    const pre = readTitleCleanupSteps("pre");
    const post = readTitleCleanupSteps("post");
    if (!pre.length && !post.length) {
      buildTitleCleanupStepsTable(ADVANCED_DEFAULT_PRE, ADVANCED_DEFAULT_POST);
    }
    void refreshTitleExtractionPreview({ resample: !titleExtractionPreviewBookIds.length });
  }
}

function scheduleTitleExtractionPreview() {
  if (getTitleExtractionMode() !== "advanced") return;
  if (!titleExtractionPreviewBookIds.length) return;
  if (titleExtractionPreviewTimer) clearTimeout(titleExtractionPreviewTimer);
  titleExtractionPreviewTimer = setTimeout(() => {
    titleExtractionPreviewTimer = null;
    void refreshTitleExtractionPreview();
  }, 300);
}

function renderTitleExtractionPreview(samples) {
  const tbody = els.titleExtractionPreviewBody;
  const empty = els.titleExtractionPreviewEmpty;
  const table = els.titleExtractionPreviewTable;
  if (!tbody) return;
  tbody.replaceChildren();
  const rows = samples || [];
  if (empty) empty.classList.toggle("hidden", rows.length > 0);
  if (table) table.classList.toggle("hidden", rows.length === 0);
  for (const row of rows) {
    const tr = document.createElement("tr");
    if (row.changed) tr.classList.add("changed");
    const labelTd = document.createElement("td");
    labelTd.textContent = row.label || row.book_id || "—";
    labelTd.title = row.book_id || "";
    const beforeTd = document.createElement("td");
    beforeTd.textContent = row.current_title || "—";
    const afterTd = document.createElement("td");
    afterTd.textContent = row.extracted_title || "—";
    if (row.source_used) afterTd.title = `Source: ${row.source_used}`;
    tr.append(labelTd, beforeTd, afterTd);
    tbody.appendChild(tr);
  }
}

async function refreshTitleExtractionPreview({ resample = false } = {}) {
  if (getTitleExtractionMode() !== "advanced") return;
  try {
    const payload = {
      mode: "advanced",
      pre_steps: readTitleCleanupSteps("pre"),
      post_steps: readTitleCleanupSteps("post"),
      limit: 10,
    };
    if (!resample && titleExtractionPreviewBookIds.length) {
      payload.book_ids = titleExtractionPreviewBookIds;
    }
    const data = await api("/api/settings/title-extraction/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    titleExtractionPreviewBookIds = (data.samples || []).map((row) => row.book_id).filter(Boolean);
    renderTitleExtractionPreview(data.samples || []);
  } catch (err) {
    showToast(err.message || "Preview failed", true);
  }
}

async function refreshAutoSettingsSummary() {
  const data = await api("/api/auto/settings");
  populateSettingsForm(data.settings);
  applyTitleExtractionModeTooltips();
  renderSettingsLastRun(data.last_run);
}

function populateSettingsForm(settings) {
  if (settings) {
    if (els.settingsEnabled) els.settingsEnabled.checked = !!settings.enabled;
    if (els.settingsScanManualHints) {
      els.settingsScanManualHints.checked = !!settings.scan_manual_hints;
    }
    if (els.settingsLviSearch) els.settingsLviSearch.checked = settings.lvi_search !== false;
    if (els.settingsLviBoost) els.settingsLviBoost.checked = settings.lvi_boost !== false;
    if (els.settingsInterval) els.settingsInterval.value = settings.interval_hours ?? 2;
    if (els.settingsConfidence) els.settingsConfidence.value = settings.min_confidence ?? 0.9;
    if (els.settingsLockTimeout) els.settingsLockTimeout.value = settings.lock_timeout_minutes ?? 15;
    autoMinConfidence = Number(settings.min_confidence ?? 0.9);
    const mode = settings.title_extraction_mode || "balanced";
    const { pre, post } = mode === "advanced"
      ? advancedStepsForForm(settings.title_cleanup_pre, settings.title_cleanup_post)
      : { pre: settings.title_cleanup_pre || [], post: settings.title_cleanup_post || [] };
    buildTitleCleanupStepsTable(pre, post);
    setTitleExtractionMode(mode);
  }
  if (els.settingsFinishScanAnimation) {
    els.settingsFinishScanAnimation.checked = scanProgressAnimator.getFinishScanAnimation();
  }
}

function renderSettingsLastRun(lastRun) {
  if (!els.settingsLastRun) return;
  if (!lastRun) {
    els.settingsLastRun.textContent = "Last run: —";
    return;
  }
  const parts = [`Last run: ${formatWhen(lastRun.finished_at || lastRun.started_at)}`];
  if (lastRun.status) parts.push(lastRun.status);
  if (lastRun.books_staged != null) parts.push(`${lastRun.books_staged} staged`);
  if (lastRun.books_failed) parts.push(`${lastRun.books_failed} failed`);
  if (lastRun.message) parts.push(lastRun.message);
  els.settingsLastRun.textContent = parts.join(" · ");
}

async function openSettingsDialog() {
  if (!els.settingsDialog) {
    showToast("Settings dialog is missing from the page", true);
    return;
  }
  try {
    openDialog(els.settingsDialog);
    setSettingsTab("general");
  } catch (err) {
    showToast(err.message || "Could not open settings", true);
    return;
  }
  if (els.settingsRunNowBtn) els.settingsRunNowBtn.disabled = sectionsBlocked;
  try {
    await refreshAutoSettingsSummary();
  } catch (err) {
    showToast(err.message || "Could not load settings", true);
  }
}

async function saveSettings() {
  const mode = getTitleExtractionMode();
  const body = {
    enabled: !!els.settingsEnabled?.checked,
    scan_manual_hints: !!els.settingsScanManualHints?.checked,
    lvi_search: !!els.settingsLviSearch?.checked,
    lvi_boost: !!els.settingsLviBoost?.checked,
    interval_hours: Number(els.settingsInterval?.value || 2),
    min_confidence: Number(els.settingsConfidence?.value || 0.9),
    lock_timeout_minutes: Number(els.settingsLockTimeout?.value || 15),
    title_extraction_mode: mode,
  };
  if (mode === "advanced") {
    body.title_cleanup_pre = readTitleCleanupSteps("pre");
    body.title_cleanup_post = readTitleCleanupSteps("post");
  }
  scanProgressAnimator.setFinishScanAnimation(!!els.settingsFinishScanAnimation?.checked);
  await api("/api/auto/settings", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  showToast("Settings saved", false, true);
  await refreshAutoSettingsSummary();
  if (cachedBooksPayload) renderBooksPayload(cachedBooksPayload);
  if (mode === "advanced" && titleExtractionPreviewBookIds.length) {
    void refreshTitleExtractionPreview();
  }
}

async function runAutoNow() {
  if (sectionsBlocked) {
    showToast("Auto-run already in progress", false, true);
    return;
  }
  const result = await api("/api/auto/run", { method: "POST" });
  if (result.run_id) {
    attachToAutoRun(result.run_id);
  }
}

async function clearMetadataCache() {
  const ok = await showConfirmDialog({
    title: "Clear metadata cache?",
    message: "Pending books will re-lookup metadata on the next scan.",
    confirmLabel: "Clear cache",
    cancelLabel: "Cancel",
    dangerous: true,
    preferenceKey: "clear-metadata-cache",
  });
  if (!ok) return;
  await api("/api/auto/cache/clear", { method: "POST" });
  showToast("Metadata cache cleared", false, true);
}

async function loadBooks() {
  const status = getActiveFilter();
  const q = els.searchBox.value.trim();
  const params = new URLSearchParams({ partitioned: "true", status });
  if (q) params.set("q", q);

  try {
    const data = await api(`/api/books?${params.toString()}`);
    cachedBooksPayload = data;
    renderBooksPayload(data);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function saveBookMetadata(
  bookId,
  author,
  title,
  {
    series,
    seriesIndex,
    keepModalOpen = false,
    refreshDetail = false,
    optimisticPreview = false,
    saveBtn = null,
  } = {}
) {
  if (refreshDetail && optimisticPreview) {
    markDetailFieldsSaved(true);
  }

  const body = {
    chosen_author: author,
    chosen_title: title,
    chosen_series: series ?? "",
    chosen_series_index: seriesIndex ?? "",
  };

  try {
    const updated = await api(`/api/books/${encodeURIComponent(bookId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });

    if (keepModalOpen && (currentResolveKey || currentConflictKey)) {
      await loadBooks();
      await reconcileConflictSession();
      if (saveBtn) flashButtonSaved(saveBtn);
      return updated;
    }

    if (refreshDetail && selectedBookId === bookId) {
      updateDetailModal(updated);
      if (updated.in_conflict) {
        showToast(
          "Saved, but this target conflicts with another book — see Conflicts section.",
          false,
          true
        );
      }
      flashButtonSaved(saveBtn || document.getElementById("saveEdit"));
      void loadBooks();
      return updated;
    }

    await loadBooks();
    return updated;
  } catch (err) {
    if (refreshDetail && optimisticPreview) {
      markDetailFieldsSaved(false);
    }
    throw err;
  }
}

function formatScanLabel(scan) {
  const parts = [];
  if (scan.id) parts.push(`Scan ${scan.id}`);
  if (scan.message) parts.push(scan.message);
  else if (scan.status) parts.push(scan.status);
  if (scan.status === "running" && scan.total_books > 0) {
    const complete = scan.books_complete ?? scan.metadata_done ?? 0;
    parts.push(`${complete}/${scan.total_books} books`);
  }
  return parts.join(" · ");
}

function applyScanStatus(scan) {
  if (scan.status === "running") {
    const label = scanIsCancelling(scan)
      ? scan.message || "Cancelling…"
      : "Scan in progress…";
    setSectionsBlocked(true, label, { kind: "scan" });
  }
}

function attachToScan(scanId) {
  clearScanPollTimer();
  clearAutoPollTimer();
  currentAutoRunId = null;
  currentScanId = scanId;
  cancelPending = false;
  scanProgressAnimator.reset(scanId);
  resetStackViz(scanId);
  setScanButtonRunning(true);
  setSectionsBlocked(true, "Scan in progress…", { kind: "scan" });
  pollScan();
}

async function pollScan() {
  if (!currentScanId) return;
  try {
    const scan = await api(`/api/scan/${currentScanId}`);
    applyScanStatus(scan);
    if (bootstrapScanActive && scan.status === "running") {
      showBootstrapScanProgress(scan);
    }
    await loadBooks();
    if (scan.status === "running") {
      pollTimer = setTimeout(pollScan, SCAN_POLL_MS);
    } else {
      cancelPending = false;
      setScanButtonRunning(false);
      const endedId = currentScanId;
      currentScanId = null;
      if (scan.status === "cancelled") {
        showToast("Scan cancelled", false, true);
      }
      if (bootstrapScanActive) {
        if (scan.status === "cancelled" || scan.status === "failed") {
          scanProgressAnimator.reset();
          bootstrapScanActive = false;
          hideBootstrapScrim();
          setSectionsBlocked(false);
          if (await returnToPreScanIfNeeded()) {
            await loadBooks();
          } else {
            restoreSectionShells();
            await loadBooks();
            await finishBootstrapIdle();
          }
        } else {
          await scanProgressAnimator.handleScanComplete(scan, async () => {
            bootstrapScanActive = false;
            await completeBootstrapHome();
          });
        }
      } else if (els.bootstrapScrim && !els.bootstrapScrim.classList.contains("hidden")) {
        await completeBootstrapHome();
      } else {
        setSectionsBlocked(false);
        restoreSectionShells();
        await loadBooks();
      }
      if (endedId) resetStackViz(null);
    }
  } catch (err) {
    if (currentScanId) {
      pollTimer = setTimeout(pollScan, 3000);
      return;
    }
    setScanButtonRunning(false);
    bootstrapScanActive = false;
    scanProgressAnimator.reset();
    setSectionsBlocked(false);
    hideBootstrapScrim();
    if (!(await returnToPreScanIfNeeded())) {
      restoreSectionShells();
      await finishBootstrapIdle();
    }
    void loadBooks();
    showToast(err.message, true);
  }
}

async function resumeRunningScan() {
  try {
    if (await resumeRunningAuto()) return;
    const scan = await api("/api/scan/running");
    if (scan.status === "running" && scan.id) {
      bootstrapScanActive = true;
      showBootstrapScanProgress(scan);
      attachToScan(scan.id);
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

async function beginScan() {
  setScanButtonRunning(true);
  showBootstrapScanProgress({
    status: "running",
    books_discovered: 0,
    books_found: 0,
    books_total: 0,
    books_complete: 0,
    metadata_done: 0,
    scan_phase: "discovering",
  });
  try {
    const { scan_id } = await api("/api/scan", { method: "POST" });
    attachToScan(scan_id);
  } catch (err) {
    if (err.status === 409 && err.detail?.kind === "auto_run") {
      setScanButtonRunning(false);
      if (err.detail?.auto_run_id) {
        attachToAutoRun(err.detail.auto_run_id);
      } else {
        void resumeRunningAuto();
      }
      showToast("Auto-scan and stage in progress — please wait", false, true);
      return;
    }
    if (err.status === 409 && err.detail?.scan_id) {
      attachToScan(err.detail.scan_id);
      showToast("Resuming scan already in progress", false, true);
      return;
    }
    setScanButtonRunning(false);
    showBootstrapPreScanModal({ message: err.message || "Could not start scan. Try again." });
    showToast(err.message, true);
  }
}

async function startScan() {
  openScanModal();
}

async function showDetail(bookId, { triggerBtn } = {}) {
  const open = async () => {
    selectedBookId = bookId;
    const book = await api(`/api/books/${encodeURIComponent(bookId)}`);
    renderDetailContent(bookId, book);
    openDialog(els.detailDialog);
  };
  if (triggerBtn) {
    return withButtonBusy(triggerBtn, open, { label: "Loading…" });
  }
  return open();
}

function renderDetailContent(bookId, book) {
  const candidates = renderDetailCandidates(book);

  els.detailContent.innerHTML = `
    <div class="meta-block path-block">
      <h3>Path</h3>
      <div class="path-value">${escapeHtml(book.source_path)}</div>
      <h3 class="path-subheading">Full path</h3>
      <div class="path-value">${escapeHtml(book.full_path || "—")}</div>
    </div>
    ${renderOverviewStats({ files: book.files, bookId })}
    ${renderMetadataEditForm(book)}
    ${renderPartialStagingBlock(book, bookId)}
    ${book.status === "partial_staged" && book.staging ? "" : renderFileList(book.files)}
    ${renderTagsPanel(book.tags)}
    <div class="meta-block"><h3>Candidates</h3>${candidates || "<div>No candidates</div>"}</div>
    ${book.staged_path && book.status !== "partial_staged" ? `<div class="meta-block"><h3>Staged at</h3><div class="path-value">${escapeHtml(book.staged_path)}</div></div>` : ""}
    ${book.in_conflict ? `<div id="detailConflictWarn" class="meta-block warn-block"><h3>Conflict</h3><div>Resolve in the Conflicts section before approving.</div></div>` : ""}
    ${mergeBookIds.has(book.id) ? `<div id="detailMergeWarn" class="meta-block warn-block"><h3>Merge</h3><div>Combine in the Merge tab before approving.</div></div>` : ""}
  `;

  document.getElementById("saveEdit").onclick = async (ev) => {
    const saveBtn = ev.currentTarget;
    const inputs = getDetailMetadataInputs();
    try {
      await withButtonBusy(saveBtn, async () => {
        await saveBookMetadata(
          bookId,
          inputs.author,
          inputs.title,
          {
            series: inputs.series,
            seriesIndex: inputs.seriesIndex,
            refreshDetail: true,
            optimisticPreview: true,
            saveBtn,
          }
        );
      }, { label: "Saving…" });
    } catch (err) {
      showToast(err.message, true);
    }
  };

  wireDetailMetadataPreview(bookId);
  wireDetailMetadataRevert(bookId);

  els.detailContent.querySelectorAll("[data-apply-author]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await withButtonBusy(btn, async () => {
          document.getElementById("editAuthor").value = btn.dataset.applyAuthor;
          document.getElementById("editTitle").value = btn.dataset.applyTitle;
          document.getElementById("editSeries").value = btn.dataset.applySeries || "";
          document.getElementById("editSeriesIndex").value = btn.dataset.applySeriesIndex || "";
          await saveBookMetadata(
            bookId,
            btn.dataset.applyAuthor,
            btn.dataset.applyTitle,
            {
              series: btn.dataset.applySeries || "",
              seriesIndex: btn.dataset.applySeriesIndex || "",
              refreshDetail: true,
              optimisticPreview: true,
              saveBtn: document.getElementById("saveEdit"),
            }
          );
        }, { label: "Applying…" });
      } catch (err) {
        showToast(err.message, true);
      }
    };
  });

  attachCopyButtons();

  document.getElementById("detailDuration")?.querySelector(".duration-load-btn")?.addEventListener("click", () => {
    loadBookDuration(bookId, document.getElementById("detailDuration"));
  });

  attachDetailStagingActions(bookId);
}

async function runCompletePartial(bookId, { triggerBtn, refreshDetail = false } = {}) {
  const refreshAfter = async () => {
    if (refreshDetail && selectedBookId === bookId) {
      const book = await api(`/api/books/${encodeURIComponent(bookId)}`);
      renderDetailContent(bookId, book);
    }
    await loadBooks();
  };
  const run = async () => {
    try {
      const result = await api(`/api/books/${encodeURIComponent(bookId)}/complete-partial`, { method: "POST" });
      if (result?.status === "staged") {
        showToast("Book fully staged", false, true);
      } else if (result?.status === "partial_staged" && result?.staging) {
        const { linked_count: linked, total } = result.staging;
        showToast(`Linked files; ${linked} / ${total} in library`, false, true);
      } else {
        showToast("Missing files linked", false, true);
      }
    } catch (err) {
      const detail = formatLinkError(err.message);
      showToast(`Could not link missing files. ${detail}`, true);
    } finally {
      await refreshAfter();
    }
  };
  if (triggerBtn) {
    return withButtonBusy(triggerBtn, run, { label: "Linking…" });
  }
  return withStagingScrim("Linking missing files…", run);
}

async function runRemoveExtras(bookId, extraCount, { triggerBtn, refreshDetail = false } = {}) {
  const ok = await showConfirmDialog({
    title: "Remove extra library files?",
    message: `${extraCount} audio file${extraCount === 1 ? "" : "s"} in the library folder will be deleted. Source files are not affected.`,
    confirmLabel: "Remove extras",
    cancelLabel: "Cancel",
    dangerous: true,
    preferenceKey: "partial-remove-extras",
  });
  if (!ok) return;
  const run = async () => {
    await api(`/api/books/${encodeURIComponent(bookId)}/remove-extras`, { method: "POST" });
    if (refreshDetail && selectedBookId === bookId) {
      const book = await api(`/api/books/${encodeURIComponent(bookId)}`);
      renderDetailContent(bookId, book);
    }
    await loadBooks();
    showToast("Extra library files removed", false, true);
  };
  if (triggerBtn) {
    return withButtonBusy(triggerBtn, run, { label: "Removing…" });
  }
  return withStagingScrim("Removing extra files…", run);
}

function attachDetailStagingActions(bookId) {
  els.detailContent.querySelectorAll("[data-staging-action]").forEach((btn) => {
    btn.onclick = async () => {
      if (btn.disabled || btn.classList.contains("btn-busy")) return;
      try {
        const action = btn.dataset.stagingAction;
        if (action === "complete-partial") {
          await runCompletePartial(bookId, { triggerBtn: btn, refreshDetail: true });
        } else if (action === "remove-extras") {
          const book = await api(`/api/books/${encodeURIComponent(bookId)}`);
          const extraCount = book.staging?.extra_library_files?.length || 0;
          if (!extraCount) return;
          await runRemoveExtras(bookId, extraCount, { triggerBtn: btn, refreshDetail: true });
        } else if (action === "unstage") {
          const confirmed = await showConfirmDialog({
            title: "Unstage book?",
            message: "Linked library hardlinks will be removed and the book returns to pending.",
            confirmLabel: "Unstage",
            cancelLabel: "Cancel",
            dangerous: true,
            preferenceKey: "staging-unstage",
          });
          if (!confirmed) return;
          await withButtonBusy(btn, async () => {
            await withStagingScrim("Unstaging book…", async () => {
              await api(`/api/books/${encodeURIComponent(bookId)}/revert`, { method: "POST" });
              await loadBooks();
            });
            els.detailDialog.close();
            showToast("Book unstaged", false, true);
          }, { label: "Unstaging…" });
        }
      } catch (err) {
        if (btn.dataset.stagingAction !== "complete-partial") {
          showToast(err.message, true);
        }
      }
    };
  });
}

async function handleBookAction(btn) {
  if (btn.disabled || btn.classList.contains("btn-busy")) return;
  const id = btn.dataset.id;
  try {
    if (btn.dataset.action === "detail") {
      return showDetail(id, { triggerBtn: btn });
    }
    if (btn.dataset.action === "approve") {
      await withStagingScrim("Staging book…", async () => {
        await api(`/api/books/${encodeURIComponent(id)}/approve`, { method: "POST" });
        await loadBooks();
      });
    }
    if (btn.dataset.action === "complete-partial") {
      await runCompletePartial(id, {
        triggerBtn: btn,
        refreshDetail: selectedBookId === id && els.detailDialog.open,
      });
    }
    if (btn.dataset.action === "skip") {
      if (btn.classList.contains("btn-busy")) return;
      setButtonBusy(btn, true, { label: "Skipping…" });
      optimisticSkipRow(btn, true);
      try {
        await api(`/api/books/${encodeURIComponent(id)}/skip`, { method: "POST" });
        void loadBooks();
      } catch (err) {
        optimisticSkipRow(btn, false);
        setButtonBusy(btn, false);
        showToast(err.message, true);
      }
    }
    if (btn.dataset.action === "unskip") {
      setButtonBusy(btn, true, { label: "Unskipping…" });
      try {
        await api(`/api/books/${encodeURIComponent(id)}/unskip`, { method: "POST" });
        selectionByFilter.skipped.delete(id);
        void loadBooks();
      } catch (err) {
        setButtonBusy(btn, false);
        showToast(err.message, true);
      }
    }
    if (btn.dataset.action === "unstage") {
      const ok = await showConfirmDialog({
        title: "Unstage book?",
        message: "Library hardlinks will be removed and the book returns to pending.",
        confirmLabel: "Unstage",
        cancelLabel: "Cancel",
        dangerous: true,
        preferenceKey: "staging-unstage",
      });
      if (!ok) return;
      await withStagingScrim("Unstaging book…", async () => {
        await api(`/api/books/${encodeURIComponent(id)}/revert`, { method: "POST" });
        selectionByFilter.staged.delete(id);
        await loadBooks();
      });
      showToast("Book unstaged", false, true);
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

async function runStagingBulkAction() {
  const filter = getActiveFilter();
  const config = STAGING_BULK_CONFIG[filter] || STAGING_BULK_CONFIG.pending;
  const ids = [...selectionByFilter[filter]];
  if (!ids.length) {
    showToast(config.emptyTitle, false, true);
    return;
  }
  if (els.stagingBulkBtn?.disabled || els.stagingBulkBtn?.classList.contains("btn-busy")) return;
  if (els.mobileBulkBtn?.classList.contains("btn-busy")) return;

  if (config.confirm) {
    const ok = await showConfirmDialog({
      title: `Unstage ${ids.length} book${ids.length === 1 ? "" : "s"}?`,
      message: "Library hardlinks will be removed and selected books return to pending.",
      confirmLabel: "Unstage",
      cancelLabel: "Cancel",
      dangerous: true,
      preferenceKey: "staging-unstage-bulk",
    });
    if (!ok) return;
  }

  const execute = async () => {
    if (filter === "pending") {
      const result = await api("/api/books/bulk-approve", {
        method: "POST",
        body: JSON.stringify({ book_ids: ids }),
      });
      if (result.errors?.length) {
        showToast(`${result.errors.length} error(s) during bulk approve`, true);
      }
    } else if (filter === "skipped") {
      const result = await api("/api/books/bulk-unskip", {
        method: "POST",
        body: JSON.stringify({ book_ids: ids }),
      });
      if (result.errors?.length) {
        showToast(`${result.errors.length} error(s) during bulk unskip`, true);
      }
    } else if (filter === "staged") {
      const result = await api("/api/books/bulk-revert", {
        method: "POST",
        body: JSON.stringify({ book_ids: ids }),
      });
      if (result.errors?.length) {
        showToast(`${result.errors.length} error(s) during bulk unstage`, true);
      }
    }
    ids.forEach((bookId) => selectionByFilter[filter].delete(bookId));
    await loadBooks();
  };

  if (config.scrim) {
    await withStagingScrim(config.scrim, execute);
  } else {
    await execute();
  }
}

els.scanBtn.addEventListener("click", startScan);

els.settingsBtn?.addEventListener("click", () => {
  void openSettingsDialog().catch((err) => {
    showToast(err.message || "Could not open settings", true);
  });
});

els.settingsSaveBtn?.addEventListener("click", async () => {
  try {
    await withButtonBusy(els.settingsSaveBtn, saveSettings, { label: "Saving…" });
  } catch (err) {
    showToast(err.message, true);
  }
});

els.settingsRunNowBtn?.addEventListener("click", async () => {
  try {
    await withButtonBusy(els.settingsRunNowBtn, async () => {
      await runAutoNow();
      els.settingsDialog?.close();
    }, { label: "Starting…" });
  } catch (err) {
    if (err.status === 409 && err.detail?.kind === "auto_run") {
      if (err.detail?.auto_run_id) attachToAutoRun(err.detail.auto_run_id);
      else void resumeRunningAuto();
      els.settingsDialog?.close();
      showToast("Auto-run already in progress", false, true);
      return;
    }
    showToast(err.message, true);
  }
});

els.settingsClearCacheBtn?.addEventListener("click", async () => {
  try {
    await withButtonBusy(els.settingsClearCacheBtn, clearMetadataCache, { label: "Clearing…" });
  } catch (err) {
    showToast(err.message, true);
  }
});

document.querySelectorAll('input[name="titleExtractionMode"]').forEach((input) => {
  input.addEventListener("change", onTitleExtractionModeChange);
});

document.querySelectorAll("#settingsDialog .resolve-tab[data-settings-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    setSettingsTab(btn.dataset.settingsTab || "general");
  });
});

els.titleExtractionPreviewBtn?.addEventListener("click", () => {
  void refreshTitleExtractionPreview({ resample: true });
});

els.dismissAllAwayBtn?.addEventListener("click", async () => {
  try {
    await api("/api/auto/review/dismiss", {
      method: "POST",
      body: JSON.stringify({ dismiss_all: true }),
    });
    await loadAwayReview();
    showToast("Marked all okay", false, true);
  } catch (err) {
    showToast(err.message, true);
  }
});

els.awayList?.addEventListener("click", awayListClickHandler);
els.statusFilter.addEventListener("change", () => {
  updateStagingBulkBtn();
  void loadBooks();
});
els.searchBox.addEventListener("input", () => {
  clearTimeout(window.searchDebounce);
  window.searchDebounce = setTimeout(loadBooks, 250);
});

els.partialList?.addEventListener("click", partialListClickHandler);

els.stagingBulkBtn?.addEventListener("click", () => {
  runStagingBulkAction().catch((err) => showToast(err.message, true));
});

els.mobileBulkBtn?.addEventListener("click", () => {
  runStagingBulkAction().catch((err) => showToast(err.message, true));
});

wireStagingSortControls();
wireStagingListControls();

els.detailLookup.addEventListener("click", async () => {
  if (!selectedBookId) return;
  if (els.detailLookup.disabled || els.detailLookup.classList.contains("btn-busy")) return;
  const draftInputs = getDetailMetadataInputs();
  const manualBefore = {};
  METADATA_EDIT_FIELDS.forEach((field) => {
    manualBefore[field.key] = Boolean(
      document.querySelector(
        `[data-metadata-field="${field.key}"] .metadata-mode-badge--manual`
      )
    );
  });
  try {
    await withButtonBusy(els.detailLookup, async () => {
      await api(`/api/books/${encodeURIComponent(selectedBookId)}/lookup`, {
        method: "POST",
        body: JSON.stringify({
          author: draftInputs.author.trim(),
          title: draftInputs.title.trim(),
        }),
      });
      const book = await api(`/api/books/${encodeURIComponent(selectedBookId)}`);
      renderDetailContent(selectedBookId, book);
      METADATA_EDIT_FIELDS.forEach((field) => {
        const input = document.getElementById(field.inputId);
        if (!input) return;
        if (manualBefore[field.key]) {
          input.value = book[field.effectiveKey] ?? "";
        } else {
          input.value = draftInputs[field.draftKey] ?? "";
        }
      });
      applyDetailMetadataChrome(book);
      void loadBooks();
    }, { label: "Looking up…" });
  } catch (err) {
    showToast(err.message, true);
  }
});

async function conflictsContentClickHandler(ev) {
  const resolveBtn = ev.target.closest(".conflict-resolve-btn");
  if (resolveBtn) {
    openResolvePanel(resolveBtn.dataset.targetKey, { triggerBtn: resolveBtn });
  }
}

els.conflictsContent?.addEventListener("click", conflictsContentClickHandler);

els.conflictDialogContent.addEventListener("click", async (ev) => {
  const modeTab = ev.target.closest(".resolve-tab");
  if (modeTab?.dataset.resolveMode) {
    await setResolveMode(modeTab.dataset.resolveMode);
    return;
  }

  const durationBtn = ev.target.closest(".duration-load-btn");
  if (durationBtn) {
    const cell = durationBtn.closest(".side-duration");
    if (cell) loadSideDuration(cell);
    return;
  }

  const saveBtn = ev.target.closest(".conflict-save");
  if (saveBtn) {
    if (saveBtn.disabled || saveBtn.classList.contains("btn-busy")) return;
    const bookId = saveBtn.dataset.bookId;
    const card = saveBtn.closest(".conflict-side-card");
    const author = card.querySelector(`.conflict-author[data-book-id="${bookId}"]`)?.value;
    const title = card.querySelector(`.conflict-title[data-book-id="${bookId}"]`)?.value;
    const series = card.querySelector(`.conflict-series[data-book-id="${bookId}"]`)?.value;
    const seriesIndex = card.querySelector(`.conflict-series-index[data-book-id="${bookId}"]`)?.value;
    try {
      await withButtonBusy(saveBtn, async () => {
        await saveBookMetadata(bookId, author, title, {
          series,
          seriesIndex,
          keepModalOpen: true,
          saveBtn,
        });
      }, { label: "Saving…" });
    } catch (err) {
      showToast(err.message, true);
    }
    return;
  }

  const applyBtn = ev.target.closest(".conflict-candidate-apply");
  if (applyBtn) {
    if (applyBtn.disabled || applyBtn.classList.contains("btn-busy")) return;
    const bookId = applyBtn.dataset.bookId;
    const card = applyBtn.closest(".conflict-side-card");
    const authorInput = card?.querySelector(`.conflict-author[data-book-id="${bookId}"]`);
    const titleInput = card?.querySelector(`.conflict-title[data-book-id="${bookId}"]`);
    const seriesInput = card?.querySelector(`.conflict-series[data-book-id="${bookId}"]`);
    const seriesIndexInput = card?.querySelector(`.conflict-series-index[data-book-id="${bookId}"]`);
    if (authorInput) authorInput.value = applyBtn.dataset.author;
    if (titleInput) titleInput.value = applyBtn.dataset.title;
    if (seriesInput) seriesInput.value = applyBtn.dataset.series || "";
    if (seriesIndexInput) seriesIndexInput.value = applyBtn.dataset.seriesIndex || "";
    try {
      await withButtonBusy(applyBtn, async () => {
        await saveBookMetadata(bookId, applyBtn.dataset.author, applyBtn.dataset.title, {
          series: applyBtn.dataset.series || "",
          seriesIndex: applyBtn.dataset.seriesIndex || "",
          keepModalOpen: true,
          saveBtn: applyBtn,
        });
      }, { label: "Applying…" });
    } catch (err) {
      showToast(err.message, true);
    }
    return;
  }

  const skipBtn = ev.target.closest(".conflict-skip-btn");
  if (skipBtn) {
    if (skipBtn.disabled || skipBtn.classList.contains("btn-busy")) return;
    const bookId = skipBtn.dataset.bookId;
    try {
      await withButtonBusy(skipBtn, async () => {
        await api(`/api/books/${encodeURIComponent(bookId)}/skip`, { method: "POST" });
        await loadBooks();
        await reconcileConflictSession();
      }, { label: "Skipping…" });
    } catch (err) {
      showToast(err.message, true);
      await reconcileConflictSession();
    }
  }
});

els.conflictDialogContent.addEventListener("change", (ev) => {
  if (
    ev.target.matches('input[type="radio"]') ||
    ev.target.matches(".conflict-author") ||
    ev.target.matches(".conflict-title") ||
    ev.target.matches(".conflict-series") ||
    ev.target.matches(".conflict-series-index")
  ) {
    updateConflictApproveFooter();
  }
});

els.conflictSaveAllBtn?.addEventListener("click", async () => {
  if (els.conflictSaveAllBtn.disabled || els.conflictSaveAllBtn.classList.contains("btn-busy")) return;
  try {
    await withButtonBusy(els.conflictSaveAllBtn, async () => {
      await saveAllConflictEdits();
    }, { label: "Saving…" });
  } catch (err) {
    showToast(err.message, true);
  }
});

els.conflictApproveBtn.addEventListener("click", async () => {
  const targetKey = currentResolveKey || currentConflictKey;
  if (!targetKey) return;
  if (els.conflictApproveBtn.disabled || els.conflictApproveBtn.classList.contains("btn-busy")) return;
  const winner = getSelectedWinnerSideId();
  if (!winner) {
    showToast("Select a winner side first.", true);
    return;
  }
  const inputs = winner !== "library" ? getWinnerCardInputs(winner) : null;
  try {
    const ok = await approveConflict(targetKey, winner, {
      chosenAuthor: inputs?.author,
      chosenTitle: inputs?.title,
      chosenSeries: inputs?.series,
      chosenSeriesIndex: inputs?.seriesIndex,
    });
    if (ok) {
      await reconcileConflictSession();
    }
  } catch (err) {
    showToast(err.message, true);
  }
});

els.conflictNextBtn?.addEventListener("click", () => {
  advanceToNextConflict();
});

els.mergeApproveBtn?.addEventListener("click", async () => {
  if (!currentResolveKey) return;
  if (els.mergeApproveBtn.disabled || els.mergeApproveBtn.classList.contains("btn-busy")) return;
  try {
    await withButtonBusy(els.mergeApproveBtn, async () => {
      await approveMerge(currentResolveKey);
    }, { label: "Merging…" });
  } catch (err) {
    showToast(err.message, true);
  }
});

els.conflictDialog?.addEventListener("close", () => {
  resetResolvePanel();
});

function wireDialogCloseButtons() {
  document.querySelectorAll("dialog form[method='dialog']").forEach((form) => {
    form.querySelectorAll("button[type='submit']").forEach((btn) => {
      btn.type = "button";
      btn.classList.add("dialog-close-btn");
      btn.addEventListener("click", () => form.closest("dialog")?.close());
    });
  });
}

function installModalBehavior() {
  for (const dialog of [
    els.detailDialog,
    els.settingsDialog,
    els.confirmDialog,
    els.conflictDialog,
  ]) {
    if (!dialog) continue;
    dialog.setAttribute("tabindex", "-1");
    dialog.addEventListener("close", () => unlockModalScroll());
  }
  document.addEventListener("wheel", preventModalBackgroundScroll, { passive: false });
  document.addEventListener("touchmove", preventModalBackgroundScroll, { passive: false });
}

function setSectionCollapsed(section, collapsed, { persist = true } = {}) {
  if (!section) return;
  section.classList.toggle("section-collapsed", collapsed);
  const toggle = section.querySelector(".section-header-toggle");
  if (toggle) toggle.setAttribute("aria-expanded", String(!collapsed));
  if (!persist || !section.id) return;
  try {
    if (collapsed) localStorage.setItem(SECTION_COLLAPSE_PREFIX + section.id, "1");
    else localStorage.removeItem(SECTION_COLLAPSE_PREFIX + section.id);
  } catch {
    /* ignore quota / private mode */
  }
}

function installSectionCollapse() {
  for (const section of document.querySelectorAll(".page-section")) {
    const toggle = section.querySelector(".section-header-toggle");
    const body = section.querySelector(".section-body");
    if (!toggle || !body) continue;
    toggle.setAttribute("aria-controls", body.id);

    let collapsed = false;
    try {
      collapsed = localStorage.getItem(SECTION_COLLAPSE_PREFIX + section.id) === "1";
    } catch {
      collapsed = false;
    }
    setSectionCollapsed(section, collapsed, { persist: false });

    toggle.addEventListener("click", () => {
      setSectionCollapsed(section, !section.classList.contains("section-collapsed"));
    });
  }
}

els.detailDialog.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (e.target.id !== "editAuthor" && e.target.id !== "editTitle") return;
  e.preventDefault();
  const saveBtn = document.getElementById("saveEdit");
  if (saveBtn && !saveBtn.disabled && !saveBtn.classList.contains("btn-busy")) {
    saveBtn.click();
  }
});

els.conflictDialogContent.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (!e.target.matches(".conflict-author, .conflict-title")) return;
  e.preventDefault();
  const bookId = e.target.dataset.bookId;
  if (!bookId) return;
  const saveBtn = els.conflictDialogContent.querySelector(
    `.conflict-save[data-book-id="${CSS.escape(bookId)}"]`
  );
  if (saveBtn && !saveBtn.disabled && !saveBtn.classList.contains("btn-busy")) {
    saveBtn.click();
  }
});

wireDialogCloseButtons();
installModalBehavior();
installSectionCollapse();

els.confirmOkBtn?.addEventListener("click", () => closeConfirmDialog(true));
els.confirmCancelBtn?.addEventListener("click", () => closeConfirmDialog(false));
els.confirmDialog?.addEventListener("cancel", (ev) => {
  ev.preventDefault();
  closeConfirmDialog(false);
});
els.confirmDialog?.addEventListener("close", () => {
  if (confirmResolver) closeConfirmDialog(false);
});

els.conflictDialog.addEventListener("close", () => {
  resetConflictSession();
});

function setNeedsScanClass(needsScan) {
  document.body.classList.toggle("bootstrap-needs-scan", Boolean(needsScan));
}

function setBootstrapScrimOpen(open) {
  document.body.classList.toggle("bootstrap-scrim-open", Boolean(open));
}

async function returnToPreScanIfNeeded() {
  try {
    const status = await api("/api/session/status");
    setNeedsScanClass(status.needs_scan);
    if (!status.needs_scan) return false;
    setSectionsBlocked(true, null, { kind: "loading" });
    const title =
      status.state === "stale_scan"
        ? "Your scan is out of date"
        : "Scan your library to get started";
    showBootstrapPreScanModal({
      title,
      message: "Check metadata providers, then start the scan.",
    });
    return true;
  } catch (err) {
    showToast(err.message, true);
    return false;
  }
}

function hideBootstrapScrim() {
  bootstrapScanActive = false;
  scanProgressAnimator.reset();
  setBootstrapScanPanelMode(false);
  els.bootstrapScrim?.classList.add("hidden");
  setBootstrapScrimOpen(false);
  els.bootstrapSpinner?.classList.add("hidden");
  els.bootstrapProviders?.classList.add("hidden");
  els.bootstrapStackWrap?.classList.add("hidden");
  els.bootstrapCancelBtn?.classList.add("hidden");
  els.bootstrapActionBtn?.classList.add("hidden");
  if (els.bootstrapTitle) els.bootstrapTitle.classList.remove("hidden");
  bootstrapActionHandler = null;
}

function showBootstrapScrim({
  title,
  message,
  showSpinner = false,
  actionLabel = "",
  onAction = null,
} = {}) {
  els.bootstrapScrim?.classList.remove("hidden");
  setBootstrapScrimOpen(true);
  setBootstrapScanPanelMode(false);
  els.bootstrapStackWrap?.classList.add("hidden");
  els.bootstrapProviders?.classList.add("hidden");
  els.bootstrapCancelBtn?.classList.add("hidden");
  if (els.bootstrapTitle) {
    els.bootstrapTitle.textContent = title || "";
    els.bootstrapTitle.classList.toggle("hidden", !title);
  }
  if (els.bootstrapMessage) {
    const msg = message || "";
    els.bootstrapMessage.textContent = msg;
    els.bootstrapMessage.classList.toggle("hidden", !msg);
  }
  els.bootstrapSpinner?.classList.toggle("hidden", !showSpinner);
  if (actionLabel && els.bootstrapActionBtn) {
    els.bootstrapActionBtn.textContent = actionLabel;
    els.bootstrapActionBtn.classList.remove("hidden");
    bootstrapActionHandler = onAction;
  } else {
    els.bootstrapActionBtn?.classList.add("hidden");
    bootstrapActionHandler = null;
  }
}

function setBootstrapScrimMessage(message, { showSpinner = true } = {}) {
  if (!els.bootstrapScrim || els.bootstrapScrim.classList.contains("hidden")) return;
  if (els.bootstrapMessage) {
    const msg = message || "Please wait…";
    els.bootstrapMessage.textContent = msg;
    els.bootstrapMessage.classList.toggle("hidden", !msg);
  }
  els.bootstrapSpinner?.classList.toggle("hidden", !showSpinner);
}

async function completeBootstrapHome() {
  showBootstrapScrim({
    title: "Preparing staging area…",
    message: "Loading books and conflicts.",
    showSpinner: true,
  });
  try {
    await Promise.all([
      loadBooks(),
      loadAwayReview(),
      refreshAutoSettingsSummary().catch(() => {}),
    ]);
  } catch (err) {
    showToast(err.message || "Failed to load staging data", true);
  } finally {
    hideBootstrapScrim();
    await finishBootstrapIdle();
  }
}

async function finishBootstrapIdle() {
  if (currentScanId || currentAutoRunId || bootstrapScanActive) return;
  if (document.body.classList.contains("bootstrap-needs-scan")) return;
  restoreSectionShells();
  sectionsBlocked = false;
  sectionsBlockedKind = null;
  els.scanBtn.disabled = false;
  renderBooksPayload(cachedBooksPayload);
  setNeedsScanClass(false);
}

async function handleBootstrapStatus(status) {
  setNeedsScanClass(status.needs_scan);

  if (status.state === "auto_running" && status.auto_run?.id) {
    bootstrapScanActive = true;
    showBootstrapScrim({
      title: "Scan in progress",
      message: status.auto_run.message || "Please wait…",
      showSpinner: true,
    });
    attachToAutoRun(status.auto_run.id);
    return;
  }

  if (status.state === "scan_running" && status.scan?.id) {
    showBootstrapScanProgress(status.scan);
    attachToScan(status.scan.id);
    return;
  }

  if (status.state === "no_scan" || status.state === "stale_scan") {
    setSectionsBlocked(true, null, { kind: "loading" });
    showBootstrapPreScanModal({
      title:
        status.state === "stale_scan"
          ? "Your scan is out of date"
          : "Scan your library to get started",
      message: "Check metadata providers, then start the scan.",
    });
    return;
  }

  await completeBootstrapHome();
}

function reloadAfterAway() {
  location.reload();
}

async function bootstrapApp() {
  setSectionsBlocked(true, "Loading…", { kind: "loading" });
  showBootstrapScrim({
    title: "Loading…",
    showSpinner: true,
  });
  try {
    const status = await api("/api/session/status");
    await handleBootstrapStatus(status);
  } catch (err) {
    showToast(err.message, true);
    hideBootstrapScrim();
    if (!(await returnToPreScanIfNeeded())) {
      await finishBootstrapIdle();
    }
  }
}

els.bootstrapActionBtn?.addEventListener("click", () => {
  if (typeof bootstrapActionHandler === "function") {
    bootstrapActionHandler();
  }
});

els.bootstrapCancelBtn?.addEventListener("click", () => {
  if (currentScanId) {
    void cancelActiveScan();
    return;
  }
  if (currentAutoRunId) {
    void cancelActiveAutoRun();
  }
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    awayHiddenAt = Date.now();
    return;
  }
  if (
    awayHiddenAt &&
    Date.now() - awayHiddenAt >= AWAY_TIMEOUT_MS &&
    !currentScanId &&
    !currentAutoRunId
  ) {
    showBootstrapScrim({
      title: "You've been away for a while",
      message: "Reload to refresh books and conflicts.",
      actionLabel: "Reload",
      onAction: reloadAfterAway,
    });
  }
  awayHiddenAt = null;
});

window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  void bootstrapApp();
});

attachCopyButtons();
applyTitleExtractionModeTooltips();
void bootstrapApp();
