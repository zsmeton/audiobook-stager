<script setup>
import { confidenceLabel, isRowSelectable, seriesLine } from "./staging.js";

const props = defineProps({
  rows: { type: Array, required: true },
  status: { type: String, required: true },
  query: { type: String, required: true },
  requestText: { type: String, required: true },
  loading: { type: Boolean, required: true },
  loaded: { type: Boolean, required: true },
  errorText: { type: String, required: true },
  offset: { type: Number, required: true },
  pageSize: { type: Number, required: true },
  sort: { type: Object, required: true },
  selectedIds: { type: Array, required: true },
  bulkLabel: { type: String, required: true },
  emptyMessage: { type: String, required: true },
  sectionsBlocked: { type: Boolean, required: true },
  busy: { type: Boolean, required: true },
  canPrev: { type: Boolean, required: true },
  canNext: { type: Boolean, required: true },
  allPageSelected: { type: Boolean, required: true },
  mergeIds: { type: Object, required: true },
  scanning: { type: Boolean, required: true },
});

defineEmits([
  "set-status",
  "search",
  "toggle-sort",
  "set-sort",
  "toggle-row",
  "toggle-page",
  "row-action",
  "bulk",
  "next",
  "prev",
]);

function selectable(book) {
  return isRowSelectable(book, props.status, props.mergeIds);
}

function actionsFor() {
  if (props.status === "staged") return [["detail", "Detail"], ["unstage", "Unstage"]];
  if (props.status === "skipped") return [["detail", "Detail"], ["unskip", "Unskip"]];
  return [["detail", "Detail"], ["approve", "Approve"], ["skip", "Skip"]];
}

function actionDisabled(action, book) {
  if (props.sectionsBlocked || props.busy) return true;
  if (action === "approve" || action === "skip") return book.status !== "pending";
  if (action === "unskip") return book.status !== "skipped";
  if (action === "unstage") return book.status !== "staged" && book.status !== "partial_staged";
  return false;
}

function sortMark(key) {
  if (props.sort.key !== key) return "";
  return props.sort.dir === "asc" ? "↑" : "↓";
}

function sortAria(key) {
  if (props.sort.key !== key) return "none";
  return props.sort.dir === "asc" ? "ascending" : "descending";
}
</script>

<template>
  <div
    id="stagingContent"
    class="staging-content"
    :data-request="requestText"
    :data-limit="pageSize"
    :data-offset="offset"
    :data-status="status"
  >
    <div class="staging-toolbar">
      <label>
        Filter
        <select id="statusFilter" :value="status" :disabled="sectionsBlocked" @change="$emit('set-status', $event.target.value)">
          <option value="pending">Pending</option>
          <option value="staged">Staged</option>
          <option value="skipped">Skipped</option>
        </select>
      </label>
      <label class="staging-search">
        Search
        <input
          id="searchBox"
          type="search"
          :value="query"
          placeholder="title, author, series, path..."
          :disabled="sectionsBlocked"
          @input="$emit('search', $event.target.value)"
        />
      </label>
      <label class="staging-sort-mobile">
        Sort
        <select
          id="stagingSortSelect"
          :value="`${sort.key}:${sort.dir}`"
          :disabled="sectionsBlocked"
          @change="$emit('set-sort', $event.target.value)"
        >
          <option value="source_path:asc">Path (A→Z)</option>
          <option value="source_path:desc">Path (Z→A)</option>
          <option value="metadata:asc">Book (A→Z)</option>
          <option value="metadata:desc">Book (Z→A)</option>
          <option value="confidence:asc">Confidence (low→high)</option>
          <option value="confidence:desc">Confidence (high→low)</option>
        </select>
      </label>
      <button id="stagingBulkBtn" type="button" :disabled="sectionsBlocked || busy || !selectedIds.length" @click="$emit('bulk')">
        {{ bulkLabel }}
      </button>
    </div>

    <p id="stagingRequest" class="staging-request">
      This page does not list every book.
      {{ loaded ? "Last request" : "Next request" }}: {{ requestText }}
    </p>
    <p id="stagingPageStatus" class="staging-page-status">
      Showing {{ rows.length }} on this page
      <span v-if="loaded && rows.length === 0"> · no books in this page</span>
      <span v-if="loading"> · loading</span>
    </p>
    <p v-if="errorText" class="staging-error">{{ errorText }}</p>
    <p v-if="!loaded && scanning" class="section-empty-state">Scan in progress…</p>
    <p v-else-if="!loaded" class="section-empty-state">Waiting for the staging page.</p>
    <p v-else-if="rows.length === 0" id="stagingEmpty" class="section-empty-state">{{ emptyMessage }}</p>

    <div id="booksListWrap" class="book-list-wrap" :class="{ hidden: rows.length === 0 }">
      <div class="staging-head" role="row">
        <div>
          <input
            id="selectAll"
            type="checkbox"
            aria-label="Select all on this page"
            :checked="allPageSelected"
            :disabled="sectionsBlocked || !rows.some(selectable)"
            @change="$emit('toggle-page', $event.target.checked)"
          />
        </div>
        <div :aria-sort="sortAria('source_path')">
          <button type="button" class="sort-btn" data-sort="source_path" @click="$emit('toggle-sort', 'source_path')">Source path {{ sortMark("source_path") }}</button>
        </div>
        <div>Files</div>
        <div :aria-sort="sortAria('metadata')">
          <button type="button" class="sort-btn" data-sort="metadata" @click="$emit('toggle-sort', 'metadata')">Book {{ sortMark("metadata") }}</button>
        </div>
        <div :aria-sort="sortAria('confidence')">
          <button type="button" class="sort-btn" data-sort="confidence" @click="$emit('toggle-sort', 'confidence')">Conf {{ sortMark("confidence") }}</button>
        </div>
        <div>Status</div>
        <div>Actions</div>
      </div>
      <div id="booksList" class="book-list" role="list">
        <article
          v-for="book in rows"
          :key="book.id"
          class="staging-row"
          :class="{ 'is-skipped': book.status === 'skipped' }"
          role="listitem"
          :data-book-id="book.id"
        >
          <div>
            <input
              type="checkbox"
              class="row-check"
              :data-id="book.id"
              aria-label="Select book"
              :checked="selectedIds.includes(book.id)"
              :disabled="sectionsBlocked || !selectable(book)"
              @change="$emit('toggle-row', book.id, $event.target.checked)"
            />
          </div>
          <div class="staging-path">{{ book.source_path }}</div>
          <div>{{ book.file_count }}</div>
          <div class="staging-meta">
            <div>{{ book.effective_author || "—" }}</div>
            <div>{{ book.effective_title || book.flatten_name || "—" }}</div>
            <div v-if="seriesLine(book)" class="staging-series">{{ seriesLine(book) }}</div>
          </div>
          <div>{{ confidenceLabel(book) }}</div>
          <div><span class="status-pill">{{ book.status }}</span></div>
          <div class="staging-actions">
            <button
              v-for="[action, label] in actionsFor()"
              :key="action"
              type="button"
              :data-action="action"
              :data-id="book.id"
              :disabled="actionDisabled(action, book)"
              @click="$emit('row-action', action, book)"
            >
              {{ label }}
            </button>
          </div>
        </article>
      </div>
    </div>

    <div class="staging-pager">
      <button id="stagingPrev" type="button" :disabled="!canPrev" @click="$emit('prev')">Previous page</button>
      <button id="stagingNext" type="button" :disabled="!canNext" @click="$emit('next')">Next page</button>
    </div>
  </div>

  <div id="mobileBulkBar" class="mobile-bulk-bar" :class="{ hidden: !selectedIds.length }">
    <span id="mobileBulkCount">{{ selectedIds.length }} selected</span>
    <button id="mobileBulkBtn" type="button" class="primary" :disabled="sectionsBlocked || busy" @click="$emit('bulk')">
      {{ bulkLabel }}
    </button>
  </div>
</template>
