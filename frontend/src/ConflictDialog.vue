<script setup>
import { inject } from "vue";

import { formatBytes, kindInfo, parseTargetKeyDisplay, candidateLine, mergeMembers } from "./groups.js";

const resolve = inject("resolveState");

function labelFor(side) {
  if (side.type === "library") return "Library";
  return side.source_path || side.book_id || "Seed";
}

function metaAuthor(side) {
  return side.effective_author || side.tags_summary?.author || side.tags?.artist || side.tags?.author || "";
}

function metaTitle(side) {
  return side.effective_title || side.tags_summary?.title || side.tags?.title || side.tags?.album || "";
}

const target = () => (resolve.group ? parseTargetKeyDisplay(resolve.group.target_key) : null);
</script>

<template>
  <div v-if="resolve.group" id="conflictDialogContent" class="resolve-panel">
    <div v-if="resolve.showTabs" class="resolve-tabstrip" role="tablist" aria-label="Resolve mode">
      <button
        type="button"
        class="resolve-tab"
        role="tab"
        data-resolve-mode="select"
        :class="{ 'is-active': resolve.mode === 'select' }"
        :aria-selected="resolve.mode === 'select' ? 'true' : 'false'"
        @click="resolve.setMode('select')"
      >
        Select
      </button>
      <button
        type="button"
        class="resolve-tab"
        role="tab"
        data-resolve-mode="merge"
        :class="{ 'is-active': resolve.mode === 'merge' }"
        :aria-selected="resolve.mode === 'merge' ? 'true' : 'false'"
        @click="resolve.setMode('merge')"
      >
        Merge
      </button>
    </div>

    <section v-if="resolve.mode === 'select' && resolve.group.conflict" class="resolve-body" role="tabpanel">
      <header class="resolve-tabpanel-header">
        <p class="resolve-target">
          <strong>{{ target().author }}</strong>
          {{ target().title }}
          <span v-if="target().series" class="meta-badge">{{ target().series }}</span>
        </p>
        <p class="resolve-meta">
          {{ resolve.group.conflict.sides.length }} sides
          <span class="status-pill" :title="kindInfo(resolve.group).title">{{ kindInfo(resolve.group).label }}</span>
        </p>
      </header>
      <article v-for="side in resolve.group.conflict.sides" :key="side.side_id" class="conflict-side-card">
        <label class="winner-pick">
          <input v-model="resolve.winner" type="radio" name="conflict-winner" :value="side.side_id" />
          <span>{{ labelFor(side) }}</span>
        </label>
        <dl class="summary-dl">
          <dt>Author</dt>
          <dd>{{ metaAuthor(side) || "—" }}</dd>
          <dt>Title</dt>
          <dd>{{ metaTitle(side) || "—" }}</dd>
          <dt>Files</dt>
          <dd>{{ side.file_count ?? (side.files || []).length }}</dd>
          <dt>Size</dt>
          <dd>{{ formatBytes(side.total_size_bytes) }}</dd>
          <dt>Path</dt>
          <dd class="detail-path">{{ side.full_path || side.source_path || "—" }}</dd>
          <dt>Confidence</dt>
          <dd>{{ side.confidence != null ? Number(side.confidence).toFixed(2) : "—" }}</dd>
        </dl>
        <ul v-if="side.files && side.files.length" class="detail-files">
          <li v-for="file in side.files" :key="file.source || file.name">{{ file.name || file.source }}</li>
        </ul>
        <div v-if="side.type === 'seed' && resolve.drafts[side.book_id]" class="detail-block">
          <h3>Edit metadata</h3>
          <label class="detail-field">
            Author
            <input v-model="resolve.drafts[side.book_id].author" class="conflict-author" :data-book-id="side.book_id" type="text" />
          </label>
          <label class="detail-field">
            Title
            <input v-model="resolve.drafts[side.book_id].title" class="conflict-title" :data-book-id="side.book_id" type="text" />
          </label>
          <label class="detail-field">
            Series
            <input v-model="resolve.drafts[side.book_id].series" class="conflict-series" :data-book-id="side.book_id" type="text" />
          </label>
          <label class="detail-field">
            Series #
            <input
              v-model="resolve.drafts[side.book_id].seriesIndex"
              class="conflict-series-index"
              :data-book-id="side.book_id"
              type="text"
            />
          </label>
          <div class="dialog-actions">
            <button type="button" class="conflict-save" :data-book-id="side.book_id" :disabled="resolve.busy" @click="resolve.saveOne(side.book_id)">
              Save
            </button>
          </div>
          <h3>Candidates</h3>
          <p v-if="!(side.candidates && side.candidates.length)">No candidates</p>
          <ul v-else class="detail-candidates">
            <li v-for="(candidate, index) in side.candidates" :key="index">
              <span>{{ candidateLine(candidate) }}</span>
              <button
                v-if="candidate && typeof candidate === 'object'"
                type="button"
                class="conflict-candidate-apply"
                :disabled="resolve.busy"
                @click="resolve.applyCandidate(side.book_id, candidate)"
              >
                Apply
              </button>
            </li>
          </ul>
          <button type="button" class="conflict-skip-btn" :data-book-id="side.book_id" :disabled="resolve.busy" @click="resolve.skipSeed(side.book_id)">
            Skip this book
          </button>
        </div>
      </article>
    </section>

    <section v-else-if="resolve.mode === 'merge'" class="resolve-body" role="tabpanel">
      <header class="resolve-tabpanel-header">
        <p class="resolve-target">
          <strong>{{ target().author }}</strong>
          {{ target().title }}
        </p>
        <p class="resolve-meta">{{ mergeMembers(resolve.group).length }} parts — select which to combine</p>
      </header>
      <article v-for="member in mergeMembers(resolve.group)" :key="member.book_id" class="conflict-side-card">
        <label class="merge-include-pick">
          <input
            type="checkbox"
            name="merge-include"
            :value="member.book_id"
            :checked="Boolean(resolve.selected[member.book_id])"
            @change="resolve.toggleMember(member.book_id, $event.target.checked, $event)"
          />
          <span>{{ member.source_path || member.book_id }}</span>
        </label>
        <dl class="summary-dl">
          <dt>Author</dt>
          <dd>{{ metaAuthor(member) || "—" }}</dd>
          <dt>Title</dt>
          <dd>{{ metaTitle(member) || "—" }}</dd>
          <dt>Files</dt>
          <dd>{{ member.file_count ?? (member.files || []).length }}</dd>
          <dt>Path</dt>
          <dd class="detail-path">{{ member.full_path || member.source_path || "—" }}</dd>
        </dl>
        <ul v-if="member.files && member.files.length" class="detail-files">
          <li v-for="file in member.files" :key="file.source || file.name">{{ file.name || file.source }}</li>
        </ul>
      </article>
      <div class="detail-block">
        <h3>Merged metadata</h3>
        <label class="detail-field">
          Author
          <input id="mergeAuthor" v-model="resolve.mergeMeta.author" type="text" />
        </label>
        <label class="detail-field">
          Title
          <input id="mergeTitle" v-model="resolve.mergeMeta.title" type="text" />
        </label>
        <label class="detail-field">
          Series
          <input id="mergeSeries" v-model="resolve.mergeMeta.series" type="text" />
        </label>
        <label class="detail-field">
          Series #
          <input id="mergeSeriesIndex" v-model="resolve.mergeMeta.seriesIndex" type="text" />
        </label>
      </div>
      <details id="mergePreviewBlock" class="merge-preview" open>
        <summary>
          Combined preview
          <span v-if="resolve.preview">{{ resolve.stagedRows.length }} files · {{ resolve.previewDuration }}</span>
          <span v-else-if="resolve.previewLoading">Loading…</span>
        </summary>
        <p v-if="resolve.preview && resolve.preview.duplicate_duration_warning" class="detail-warn">
          Duplicate durations detected. Some files may be duplicated across parts.
        </p>
        <p v-if="resolve.preview && resolve.preview.filename_conflicts && resolve.preview.filename_conflicts.length" class="detail-warn">
          {{ resolve.preview.filename_conflicts.length }} filename
          {{ resolve.preview.filename_conflicts.length === 1 ? "conflict" : "conflicts" }} — edit library filenames below.
        </p>
        <p v-if="resolve.previewError" class="staging-error">{{ resolve.previewError }}</p>
        <p v-else-if="Object.keys(resolve.selected).length < 2" class="section-empty-state">Select at least two parts to preview.</p>
        <div v-for="row in resolve.stagedRows" :key="row.source" class="staged-file-row">
          <span class="detail-path">{{ row.basename }}</span>
          <input
            class="staged-file-input"
            type="text"
            spellcheck="false"
            :aria-label="`Library filename for ${row.basename}`"
            :value="row.staged_name"
            @input="resolve.onStagedName(row.source, $event.target.value)"
          />
        </div>
      </details>
    </section>
  </div>
</template>
