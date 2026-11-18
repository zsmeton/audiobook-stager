<script setup>
import { computed, onUnmounted, reactive, ref, watch } from "vue";

import { api } from "./api.js";
import { completePartialLabel, partialFullyLinked, partialSummary } from "./groups.js";
import { METADATA_FIELDS, PREVIEW_DEBOUNCE_MS, formatDuration } from "./staging.js";

const props = defineProps({
  book: { type: Object, required: true },
});

const emit = defineEmits(["close", "saved", "unstage", "complete-partial", "remove-extras", "toast"]);

const draft = reactive({
  author: "",
  title: "",
  series: "",
  seriesIndex: "",
});
const preview = ref("");
const previewNote = ref("");
const lviMatch = ref(null);
const saving = ref(false);
const lookingUp = ref(false);
const durationText = ref("");
const durationState = ref("idle");

let previewTimer = null;

const extraCount = computed(() => ((props.book.staging && props.book.staging.extra_library_files) || []).length);
const canLinkPartial = computed(() => {
  const staging = props.book.staging;
  if (!staging || props.book.status !== "partial_staged") return false;
  return staging.unlinked_count > 0 || partialFullyLinked(props.book);
});

const inputIds = {
  author: "editAuthor",
  title: "editTitle",
  series: "editSeries",
  series_index: "editSeriesIndex",
};

function fillDraft(book) {
  draft.author = book.effective_author || "";
  draft.title = book.effective_title || "";
  draft.series = book.effective_series || "";
  draft.seriesIndex = book.effective_series_index || "";
  preview.value = book.target_key_preview || "—";
  previewNote.value = "";
  lviMatch.value = book.lvi_form_match || null;
  durationText.value = "";
  durationState.value = "idle";
}

watch(() => props.book, (book) => fillDraft(book), { immediate: true });

onUnmounted(() => {
  if (previewTimer) clearTimeout(previewTimer);
});

function fieldManual(field) {
  return Boolean(props.book[field.set]);
}

function fieldLvi(field) {
  const match = lviMatch.value;
  if (!match) return false;
  if (field.key === "author") return Boolean(match.author_matched);
  if (field.key === "series") return Boolean(match.series_matched);
  return false;
}

function suggestedHint(field) {
  const value = String(props.book[field.suggested] || "").trim();
  if (!value) return "—";
  return field.key === "series_index" ? `#${value}` : value;
}

function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    void refreshPreview();
  }, PREVIEW_DEBOUNCE_MS);
}

async function refreshPreview() {
  const bookId = props.book.id;
  try {
    const result = await api(`/api/books/${encodeURIComponent(bookId)}/target-key-preview`, {
      method: "POST",
      body: JSON.stringify({
        chosen_author: draft.author,
        chosen_title: draft.title,
        chosen_series: draft.series,
        chosen_series_index: draft.seriesIndex,
      }),
    });
    if (props.book.id !== bookId) return;
    preview.value = result.target_key_preview || "—";
    const match = result.lvi_form_match;
    if (result.lvi_form_match) lviMatch.value = result.lvi_form_match;
    if (match && (match.author_matched || match.series_matched)) {
      const bits = [];
      if (match.author_matched) bits.push("author");
      if (match.series_matched) bits.push("series");
      previewNote.value = `Library vocabulary matches ${bits.join(" and ")}.`;
    } else {
      previewNote.value = "";
    }
  } catch {
    /* preview while typing is best-effort */
  }
}

async function save(body, toast) {
  saving.value = true;
  try {
    const updated = await api(`/api/books/${encodeURIComponent(props.book.id)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    emit("saved", updated);
    if (updated.in_conflict) emit("toast", "Saved, but this target conflicts with another book — see Conflicts section.");
    else if (toast) emit("toast", toast);
  } catch (err) {
    emit("toast", err.message || "Could not save metadata");
  } finally {
    saving.value = false;
  }
}

function saveDraft() {
  return save({
    chosen_author: draft.author,
    chosen_title: draft.title,
    chosen_series: draft.series,
    chosen_series_index: draft.seriesIndex,
  });
}

function revertField(key) {
  return save({ revert_fields: [key] }, "Reverted to suggested");
}

function revertAll() {
  return save({ revert_all: true }, "Reverted to suggested");
}

async function applyCandidate(candidate) {
  draft.author = candidate.author || "";
  draft.title = candidate.title || "";
  draft.series = candidate.series || "";
  draft.seriesIndex = candidate.series_index || "";
  await saveDraft();
}

async function lookup() {
  if (lookingUp.value) return;
  lookingUp.value = true;
  try {
    const updated = await api(`/api/books/${encodeURIComponent(props.book.id)}/lookup`, {
      method: "POST",
      body: JSON.stringify({
        author: draft.author.trim(),
        title: draft.title.trim(),
      }),
    });
    emit("saved", updated);
    emit("toast", "Lookup finished");
  } catch (err) {
    emit("toast", err.message || "Lookup failed");
  } finally {
    lookingUp.value = false;
  }
}

async function loadDuration() {
  if (durationState.value === "loading" || durationState.value === "done") return;
  durationState.value = "loading";
  try {
    const data = await api(`/api/books/${encodeURIComponent(props.book.id)}/duration`);
    durationText.value = formatDuration(data && data.total_duration_seconds);
    durationState.value = "done";
  } catch (err) {
    durationState.value = "idle";
    emit("toast", err.message || "Could not load duration");
  }
}

function candidateLine(candidate) {
  if (!candidate || typeof candidate !== "object") return String(candidate || "");
  const series = candidate.series ? ` · ${candidate.series}` : "";
  const index = candidate.series_index ? ` #${candidate.series_index}` : "";
  const provider = candidate.provider || candidate.source || "";
  const who = provider ? ` (${provider})` : "";
  return `${candidate.author || "—"} — ${candidate.title || "—"}${series}${index}${who}`;
}
</script>

<template>
  <div id="detailContent" class="detail-content">
    <div class="detail-block">
      <h3>Path</h3>
      <p class="detail-path">{{ book.source_path }}</p>
      <h3>Full path</h3>
      <p class="detail-path">{{ book.full_path || "—" }}</p>
    </div>

    <div class="detail-block">
      <h3>Overview</h3>
      <p>
        {{ (book.files || []).length }} files
        · duration
        <span id="detailDuration">
          <button v-if="durationState !== 'done'" type="button" class="duration-load-btn" :disabled="durationState === 'loading'" @click="loadDuration">
            {{ durationState === "loading" ? "Loading…" : "Load duration" }}
          </button>
          <span v-else>{{ durationText }}</span>
        </span>
      </p>
      <ul v-if="book.files && book.files.length" class="detail-files">
        <li v-for="(file, index) in book.files" :key="`${file.name}-${index}`">
          {{ file.name }}
          <span v-if="file.size_bytes != null"> · {{ file.size_bytes }} B</span>
        </li>
      </ul>
    </div>

    <form class="detail-block" @submit.prevent="saveDraft">
      <div class="detail-form-head">
        <h3>Edit metadata</h3>
        <button id="revertAllMetadata" type="button" :disabled="saving" @click="revertAll">Revert all</button>
      </div>
      <label
        v-for="field in METADATA_FIELDS"
        :key="field.key"
        class="detail-field metadata-field"
        :class="{ 'metadata-field--lvi-match': fieldLvi(field) }"
        :data-metadata-field="field.key"
      >
        <span class="detail-field-label">
          {{ field.label }}
          <span class="meta-badge">{{ fieldManual(field) ? "Manual" : "Suggested" }}</span>
          <button
            v-if="fieldManual(field)"
            type="button"
            class="metadata-revert-btn"
            :data-revert-field="field.key"
            :disabled="saving"
            @click.stop="revertField(field.key)"
          >
            Revert
          </button>
        </span>
        <input
          :id="inputIds[field.key]"
          v-model="draft[field.draft]"
          type="text"
          :class="{ 'field-lvi-match': fieldLvi(field) }"
          @input="schedulePreview"
        />
        <span class="detail-hint">Suggested: {{ suggestedHint(field) }}</span>
      </label>
      <p class="detail-preview">
        Library path
        <span id="detailTargetPreview">{{ preview }}</span>
      </p>
      <p v-if="previewNote" class="detail-hint">{{ previewNote }}</p>
      <button id="saveEdit" type="submit" class="primary" :disabled="saving">{{ saving ? "Saving…" : "Save" }}</button>
    </form>

    <div v-if="book.status === 'partial_staged' && book.staging" class="detail-block staging-status-block">
      <h3>Staging status</h3>
      <p class="staging-summary">{{ partialSummary(book) }}</p>
      <p v-if="book.error && !partialFullyLinked(book)" class="staging-error">{{ book.error }}</p>
      <p v-if="book.staging.target_dir" class="detail-path">Library folder: {{ book.staging.target_dir }}</p>
      <ul v-if="book.staging.files && book.staging.files.length" class="detail-files">
        <li v-for="file in book.staging.files" :key="file.source || file.name">
          {{ file.name || file.source }} — {{ file.status }}
        </li>
      </ul>
      <ul v-if="book.staging.extra_library_files && book.staging.extra_library_files.length" class="detail-files">
        <li v-for="extra in book.staging.extra_library_files" :key="extra.relative_path || extra.name">
          Extra: {{ extra.name }}
        </li>
      </ul>
      <div class="dialog-actions detail-staging-actions">
        <button
          type="button"
          class="primary"
          data-staging-action="complete-partial"
          :disabled="saving || !canLinkPartial"
          @click="emit('complete-partial')"
        >
          {{ completePartialLabel(book, { detail: true }) }}
        </button>
        <button
          type="button"
          class="danger"
          data-staging-action="remove-extras"
          :disabled="saving || !extraCount"
          @click="emit('remove-extras')"
        >
          Remove extras
        </button>
      </div>
    </div>

    <div v-if="book.staged_path" class="detail-block">
      <h3>Staged at</h3>
      <p class="detail-path">{{ book.staged_path }}</p>
    </div>

    <div v-if="book.in_conflict" class="detail-block detail-warn">
      <h3>Conflict</h3>
      <p>Resolve in the Conflicts section before approving.</p>
    </div>

    <div class="detail-block">
      <h3>Candidates</h3>
      <p v-if="!(book.candidates && book.candidates.length)">No candidates</p>
      <ul v-else class="detail-candidates">
        <li v-for="(candidate, index) in book.candidates" :key="index">
          <span>{{ candidateLine(candidate) }}</span>
          <button
            v-if="candidate && typeof candidate === 'object'"
            type="button"
            :disabled="saving"
            @click="applyCandidate(candidate)"
          >
            Apply
          </button>
        </li>
      </ul>
    </div>

    <div class="dialog-actions">
      <button
        v-if="book.status === 'staged' || book.status === 'partial_staged'"
        type="button"
        data-staging-action="unstage"
        @click="emit('unstage')"
      >
        Unstage
      </button>
      <button id="detailLookup" type="button" :disabled="lookingUp" @click="lookup">
        {{ lookingUp ? "Looking up…" : "Re-lookup" }}
      </button>
      <button type="button" @click="emit('close')">Close</button>
    </div>
  </div>
</template>
