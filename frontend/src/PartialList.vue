<script setup>
import { inject } from "vue";

import { canRunCompletePartial, completePartialLabel, partialLinkedLabel, partialSummary } from "./groups.js";
import { seriesLine as bookSeries } from "./staging.js";

const partial = inject("partialState");

function titleOf(book) {
  return book.effective_title || book.chosen_title || book.suggested_title || book.flatten_name || "—";
}

function authorOf(book) {
  return book.effective_author || book.chosen_author || book.suggested_author || "—";
}
</script>

<template>
  <div id="partialContent" class="section-list" :data-total="partial.total" :data-offset="partial.offset">
    <p v-if="!partial.total" id="partialEmpty" class="section-empty-state">No partially staged books.</p>
    <div v-else id="partialListWrap" class="section-list-wrap">
      <div class="group-head partial-head" aria-hidden="true">
        <span>Source path</span>
        <span>Linked</span>
        <span>Book</span>
        <span>Actions</span>
      </div>
      <div id="partialList" class="section-rows" role="list" :data-rendered="partial.rows.length" :data-total="partial.total">
        <article v-for="book in partial.rows" :key="book.id" class="group-row partial-row" role="listitem" :data-book-id="book.id">
          <div class="detail-path">{{ book.source_path }}</div>
          <div>{{ partialLinkedLabel(book) }}</div>
          <div class="group-book">
            <strong>{{ authorOf(book) }}</strong>
            <span>{{ titleOf(book) }}</span>
            <span v-if="bookSeries(book)" class="meta-badge">{{ bookSeries(book) }}</span>
            <span class="section-note">{{ partialSummary(book) }}</span>
          </div>
          <div class="staging-actions">
            <button type="button" :disabled="Boolean(partial.busyId)" @click="partial.openDetail(book.id)">Detail</button>
            <button
              type="button"
              data-action="complete-partial"
              :data-id="book.id"
              :disabled="Boolean(partial.busyId) || !canRunCompletePartial(book)"
              @click="partial.complete(book.id)"
            >
              {{ completePartialLabel(book) }}
            </button>
            <button
              type="button"
              class="danger"
              data-action="remove-extras"
              :data-id="book.id"
              :disabled="Boolean(partial.busyId) || !((book.staging && book.staging.extra_library_files) || []).length"
              @click="partial.removeExtras(book)"
            >
              Remove extras
            </button>
          </div>
        </article>
      </div>
      <div class="staging-pager">
        <button id="partialPrev" type="button" :disabled="!partial.canPrev" @click="partial.prevPage">Previous</button>
        <p class="staging-page-status">Partial {{ partial.pageFrom }}–{{ partial.pageTo }} of {{ partial.total }}</p>
        <button id="partialNext" type="button" :disabled="!partial.canNext" @click="partial.nextPage">Next</button>
      </div>
    </div>
  </div>
</template>
