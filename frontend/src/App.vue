<script setup>
import { computed, nextTick, provide, reactive, watch } from "vue";

import AwayList from "./AwayList.vue";
import BookDetail from "./BookDetail.vue";
import ConflictDialog from "./ConflictDialog.vue";
import GroupList from "./GroupList.vue";
import PartialList from "./PartialList.vue";
import SettingsDialog from "./SettingsDialog.vue";
import StagingList from "./StagingList.vue";
import { useAway } from "./awayState.js";
import { usePartial } from "./partialState.js";
import { useResolve } from "./resolveState.js";
import { readSectionCollapsed, writeSectionCollapsed } from "./sections.js";
import { useSettings } from "./settingsState.js";
import { useShell } from "./shellState.js";
import { useStaging } from "./stagingState.js";

const shell = useShell();
const staging = reactive(useStaging(shell));
const resolve = reactive(useResolve(shell, staging));
const partial = reactive(usePartial(shell, staging));
const away = reactive(useAway(shell, staging));
const settings = reactive(useSettings(shell, staging));
provide("resolveState", resolve);
provide("partialState", partial);
provide("settingsState", settings);

const collapsed = reactive({
  awaySection: readSectionCollapsed("awaySection"),
  conflictsSection: readSectionCollapsed("conflictsSection"),
  partialSection: readSectionCollapsed("partialSection"),
  stagingSection: readSectionCollapsed("stagingSection"),
});

function toggleSection(sectionId) {
  collapsed[sectionId] = !collapsed[sectionId];
  writeSectionCollapsed(sectionId, collapsed[sectionId]);
}

const {
  AWAY_TIMEOUT_MS,
  SCAN_POLL_MS,
  mode,
  sessionState,
  needsScan,
  scrimTitle,
  scrimMessage,
  showScrim,
  sectionsBlocked,
  scanButtonDisabled,
  showProviders,
  showCancel,
  showStartScan,
  showReload,
  providerChips,
  bookSummary,
  bookStatusText,
  bookRefreshCount,
  pollCount,
  lastPollGapMs,
  finishTail,
  scanProgressText,
  toast,
  cancelBusy,
  autoPollCount,
  lastAutoPollGapMs,
  openPreScan,
  beginScan,
  cancelActivity,
  reloadAfterAway,
  bootstrap,
  showToast,
} = shell;

watch(
  () => staging.confirmState,
  async (state) => {
    await nextTick();
    const dialog = document.getElementById("confirmDialog");
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (state && !dialog.open) dialog.showModal();
    if (!state && dialog.open) dialog.close();
  },
);

watch(
  () => staging.detailBook,
  async (book) => {
    await nextTick();
    const dialog = document.getElementById("detailDialog");
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (book && !dialog.open) dialog.showModal();
    if (!book && dialog.open) dialog.close();
  },
);

watch(
  () => settings.open,
  async (isOpen) => {
    await nextTick();
    const dialog = document.getElementById("settingsDialog");
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (isOpen && !dialog.open) dialog.showModal();
    if (!isOpen && dialog.open) dialog.close();
  },
);

watch(
  () => resolve.open,
  async (isOpen) => {
    await nextTick();
    const dialog = document.getElementById("conflictDialog");
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (isOpen && !dialog.open) dialog.showModal();
    if (!isOpen && dialog.open) dialog.close();
  },
);

const scanBlocking = computed(() =>
  mode.value === "scan" || mode.value === "finishing" || mode.value === "auto",
);

function sectionBody(idleText) {
  return scanBlocking.value ? "Scan in progress…" : idleText;
}

</script>

<template>
  <main
    id="appMain"
    class="app-main"
    :data-mode="mode"
    :data-session-state="sessionState"
    :data-needs-scan="needsScan ? 'true' : 'false'"
    :data-away-timeout-ms="AWAY_TIMEOUT_MS"
    :data-scan-poll-ms="SCAN_POLL_MS"
    :data-finish-tail="finishTail"
    :data-poll-count="pollCount"
    :data-poll-gap-ms="lastPollGapMs ?? ''"
    :data-book-refresh-count="bookRefreshCount"
    :data-auto-poll-count="autoPollCount"
    :data-auto-poll-gap-ms="lastAutoPollGapMs ?? ''"
    :data-away-count="away.items.length"
    :data-away-loaded="away.loaded ? 'true' : 'false'"
  >
    <header>
      <h1>Audiobook Stager</h1>
      <p class="subtitle">
        Scan seeds, verify metadata, hardlink to <code>Author/Series/Title/</code>. Flat <code>Author/Title/</code> when series is empty.
      </p>
      <p id="sessionState" class="session-line">Session: {{ sessionState || "…" }}</p>
    </header>

    <section class="toolbar">
      <button id="scanBtn" class="primary" type="button" :disabled="scanButtonDisabled" @click="openPreScan">
        {{ mode === "scan" || mode === "finishing" ? "Scanning…" : "Start Scan" }}
      </button>
      <button
        id="settingsBtn"
        class="toolbar-icon"
        type="button"
        title="Auto-stage settings"
        aria-label="Auto-stage settings"
        @click="settings.openDialog"
      >
        Settings
      </button>
    </section>

    <section id="stats" class="stats" role="status">
      <p id="bookStatusLine">{{ bookStatusText }}</p>
    </section>

    <div class="sections-stack" :class="{ 'is-blocked': sectionsBlocked }">
      <section id="awaySection" class="page-section" :class="{ 'section-collapsed': collapsed.awaySection }">
        <div class="section-header">
          <button
            type="button"
            class="section-header-toggle"
            :aria-expanded="collapsed.awaySection ? 'false' : 'true'"
            aria-controls="awayContent"
            @click="toggleSection('awaySection')"
          >
            <h2>
              While you were away
              <span id="awayCount" class="section-count" :data-count="away.items.length">{{ away.loaded ? away.items.length : "—" }}</span>
            </h2>
          </button>
          <button
            id="dismissAllAwayBtn"
            type="button"
            :class="{ hidden: !away.items.length }"
            :disabled="sectionsBlocked || away.busy"
            @click="away.dismissAll"
          >
            Okay all
          </button>
        </div>
        <div id="awayContent" class="section-body">
          <p class="section-note">Books auto-staged since your last visit. Mark okay or revert if something looks wrong.</p>
          <AwayList :items="away.items" :blocked="sectionsBlocked" :busy="away.busy" @action="away.act" />
        </div>
      </section>

      <section id="conflictsSection" class="page-section" :class="{ 'section-collapsed': collapsed.conflictsSection }">
        <div class="section-header">
          <button
            type="button"
            class="section-header-toggle"
            :aria-expanded="collapsed.conflictsSection ? 'false' : 'true'"
            aria-controls="conflictsContent"
            @click="toggleSection('conflictsSection')"
          >
            <h2>
              Conflicts
              <span class="section-count" title="Groups on this page">{{ bookSummary ? resolve.pageGroups.length : "—" }}</span>
            </h2>
          </button>
        </div>
        <div class="section-body">
          <p class="section-note">Resolve target collisions or combine split audiobook parts at the same library path.</p>
          <p v-if="scanBlocking || !bookSummary" class="section-empty-state">
            {{ sectionBody("Conflicts appear after a scan.") }}
          </p>
          <GroupList v-else />
        </div>
      </section>

      <section id="partialSection" class="page-section" :class="{ 'section-collapsed': collapsed.partialSection }">
        <div class="section-header">
          <button
            type="button"
            class="section-header-toggle"
            :aria-expanded="collapsed.partialSection ? 'false' : 'true'"
            aria-controls="partialContent"
            @click="toggleSection('partialSection')"
          >
            <h2>
              Partial staged
              <span class="section-count" title="Rows on this page">{{ bookSummary ? partial.rows.length : "—" }}</span>
            </h2>
          </button>
        </div>
        <div id="partialContent" class="section-body">
          <p class="section-note">Some files are already hardlinked. Link the rest, or remove extra library files.</p>
          <p v-if="scanBlocking || !bookSummary" class="section-empty-state">
            {{ sectionBody("Partial rows appear after a scan.") }}
          </p>
          <PartialList v-else />
        </div>
      </section>

      <section id="stagingSection" class="page-section" :class="{ 'section-collapsed': collapsed.stagingSection }">
        <div class="section-header">
          <button
            type="button"
            class="section-header-toggle"
            :aria-expanded="collapsed.stagingSection ? 'false' : 'true'"
            aria-controls="stagingContent"
            @click="toggleSection('stagingSection')"
          >
            <h2>
              Staging
              <span id="stagingCount" class="section-count" :data-count="staging.sortedRows.length" title="Rows on this page">{{ staging.sortedRows.length }}</span>
            </h2>
          </button>
        </div>
        <div class="section-body">
        <StagingList
          :rows="staging.sortedRows"
          :status="staging.status"
          :query="staging.query"
          :request-text="staging.requestText"
          :loading="staging.loading"
          :loaded="staging.loaded"
          :error-text="staging.errorText"
          :offset="staging.offset"
          :page-size="staging.PAGE_SIZE"
          :sort="staging.sort"
          :selected-ids="staging.selectedIds"
          :bulk-label="staging.bulkLabel"
          :empty-message="staging.emptyMessage"
          :sections-blocked="sectionsBlocked"
          :busy="staging.busy"
          :can-prev="staging.canPrev"
          :can-next="staging.canNext"
          :all-page-selected="staging.allPageSelected"
          :merge-ids="staging.mergeIds"
          :scanning="scanBlocking"
          @set-status="staging.setStatus"
          @search="staging.onSearch"
          @toggle-sort="staging.toggleSort"
          @set-sort="staging.setSortValue"
          @toggle-row="staging.toggleRow"
          @toggle-page="staging.togglePage"
          @row-action="staging.runRow"
          @bulk="staging.runBulk"
          @next="staging.nextPage"
          @prev="staging.prevPage"
        />
        </div>
      </section>
    </div>
  </main>

  <p id="toast" class="toast" :class="{ hidden: !toast }" role="status">{{ toast }}</p>

  <div id="bootstrapScrim" class="bootstrap-scrim" :class="{ hidden: !showScrim }" aria-live="polite">
    <div class="bootstrap-scrim-panel">
      <div
        id="bootstrapSpinner"
        class="bootstrap-scrim-spinner"
        :class="{ hidden: mode !== 'loading' && mode !== 'auto' }"
        aria-hidden="true"
      ></div>
      <h2 id="bootstrapTitle">{{ scrimTitle }}</h2>
      <p id="bootstrapMessage">{{ scrimMessage }}</p>

      <div id="bootstrapProviders" :class="{ hidden: !showProviders }">
        <h3>Metadata providers</h3>
        <div id="bootstrapProviderList" class="provider-list" role="list">
          <span v-for="chip in providerChips" :key="chip.id" class="provider-chip" role="listitem">
            <span class="provider-status" :class="chip.statusClass" :title="chip.title">{{ chip.mark }}</span>
            <span>{{ chip.label }}</span>
          </span>
        </div>
      </div>

      <div id="bootstrapStackWrap" :class="{ hidden: mode !== 'scan' && mode !== 'finishing' }">
        <p id="scanProgress">{{ scanProgressText }}</p>
        <p id="scanPollInterval">
          Polling every {{ SCAN_POLL_MS }} ms
          <span v-if="pollCount"> · polls {{ pollCount }}</span>
          <span v-if="lastPollGapMs != null"> · last gap {{ lastPollGapMs }} ms</span>
        </p>
        <p id="scanBookStatus">{{ bookStatusText }}</p>
      </div>

      <button
        id="bootstrapCancelBtn"
        type="button"
        class="bootstrap-cancel-btn"
        :class="{ hidden: !showCancel }"
        :disabled="cancelBusy"
        @click="cancelActivity"
      >
        {{ mode === "auto" ? "Cancel auto-run" : "Cancel scan" }}
      </button>
      <button
        id="bootstrapActionBtn"
        type="button"
        class="primary"
        :class="{ hidden: !showStartScan }"
        @click="beginScan"
      >
        Start Scan
      </button>
      <button
        id="bootstrapReloadBtn"
        type="button"
        class="primary"
        :class="{ hidden: !showReload }"
        @click="reloadAfterAway"
      >
        Reload
      </button>
      <button v-if="mode === 'error'" id="bootstrapRetryBtn" type="button" class="primary" @click="bootstrap">
        Retry
      </button>
    </div>
  </div>

  <div id="stagingScrim" class="staging-scrim" :class="{ hidden: !staging.scrimMessage }" :aria-hidden="staging.scrimMessage ? 'false' : 'true'">
    <p id="stagingScrimMessage">{{ staging.scrimMessage || "Staging…" }}</p>
  </div>

  <dialog id="detailDialog" @close="staging.closeDetail">
    <h2>Book detail</h2>
    <BookDetail
      v-if="staging.detailBook"
      :book="staging.detailBook"
      @close="staging.closeDetail"
      @saved="staging.onDetailSaved"
      @unstage="staging.unstageFromDetail"
      @complete-partial="partial.complete(staging.detailBook.id)"
      @remove-extras="partial.removeExtras(staging.detailBook)"
      @toast="showToast"
    />
  </dialog>

  <dialog id="settingsDialog" :class="{ 'settings-dialog--wide': settings.tab === 'metadata' }" @close="settings.onDialogClose">
    <SettingsDialog :blocked="sectionsBlocked" />
  </dialog>

  <dialog id="confirmDialog" @close="staging.onConfirmDialogClose">
    <h2 id="confirmTitle">{{ staging.confirmState ? staging.confirmState.title : "Confirm" }}</h2>
    <p id="confirmMessage">{{ staging.confirmState ? staging.confirmState.message : "" }}</p>
    <label v-if="staging.confirmState && staging.confirmState.preferenceKey" id="confirmDontAgainLabel" class="confirm-again">
      <input id="confirmDontAgain" v-model="staging.confirmState.dontAgain" type="checkbox" />
      Don’t show again
    </label>
    <div class="dialog-actions">
      <button id="confirmCancelBtn" type="button" @click="staging.settleConfirm(false)">
        {{ staging.confirmState ? staging.confirmState.cancelLabel : "Cancel" }}
      </button>
      <button
        id="confirmOkBtn"
        type="button"
        :class="staging.confirmState && staging.confirmState.dangerous ? 'danger' : 'primary'"
        @click="staging.settleConfirm(true)"
      >
        {{ staging.confirmState ? staging.confirmState.confirmLabel : "Confirm" }}
      </button>
    </div>
  </dialog>

  <dialog id="conflictDialog" @close="resolve.onDialogClose">
    <h2 id="conflictDialogTitle">{{ resolve.mode === "merge" ? "Merge audiobook parts" : "Resolve conflict" }}</h2>
    <ConflictDialog />
    <div class="dialog-actions conflict-dialog-actions">
      <button
        v-if="resolve.mode === 'select'"
        id="conflictSaveAllBtn"
        type="button"
        :disabled="resolve.busy"
        @click="resolve.saveAll"
      >
        Save all edits
      </button>
      <div class="conflict-dialog-actions-right">
        <button
          v-if="resolve.mode === 'select' && resolve.hasNext"
          id="conflictNextBtn"
          type="button"
          :disabled="resolve.busy"
          @click="resolve.advance"
        >
          Next conflict
        </button>
        <button
          v-if="resolve.mode === 'select'"
          id="conflictApproveBtn"
          type="button"
          class="primary"
          :disabled="resolve.busy"
          @click="resolve.approveSelect"
        >
          Select
        </button>
        <button
          v-if="resolve.mode === 'merge'"
          id="mergeApproveBtn"
          type="button"
          class="primary"
          :disabled="resolve.busy || !resolve.canMerge"
          :title="resolve.mergeBlockedReason"
          @click="resolve.approveMerge"
        >
          Merge &amp; stage
        </button>
        <button type="button" @click="resolve.close">Close</button>
      </div>
    </div>
  </dialog>
</template>
