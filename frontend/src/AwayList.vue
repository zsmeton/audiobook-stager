<script setup>
import { seriesLine } from "./staging.js";

defineProps({
  items: { type: Array, required: true },
  blocked: { type: Boolean, required: true },
  busy: { type: Boolean, required: true },
});

const emit = defineEmits(["action"]);

function formatWhen(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return date.toLocaleString();
}

function confidenceText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toFixed(2);
}

function bookLine(item) {
  const series = seriesLine(item);
  return [item.effective_author || "—", item.effective_title || "—", series].filter(Boolean).join(" · ");
}
</script>

<template>
  <p v-if="blocked" class="section-empty-state">Scan in progress…</p>
  <p v-else-if="!items.length" id="awayEmpty" class="section-empty-state">Nothing happened while you were away.</p>
  <div v-else id="awayListWrap" class="section-list-wrap">
    <div class="away-head" aria-hidden="true">
      <span>Source path</span>
      <span>Book</span>
      <span>Conf</span>
      <span>Staged at</span>
      <span>When</span>
      <span>Actions</span>
    </div>
    <div id="awayList" class="section-rows" role="list">
      <article
        v-for="item in items"
        :key="item.id"
        class="away-row"
        role="listitem"
        :data-action-id="item.id"
        :data-book-id="item.book_id"
      >
        <div class="staging-path">{{ item.source_path || "—" }}</div>
        <div>{{ bookLine(item) }}</div>
        <div>{{ confidenceText(item.confidence) }}</div>
        <div class="staging-path">{{ item.staged_path || "—" }}</div>
        <div>{{ formatWhen(item.created_at) }}</div>
        <div class="staging-actions">
          <button type="button" data-away-action="detail" :data-id="item.book_id" :disabled="busy || !item.book_id" @click="emit('action', 'detail', item)">
            Detail
          </button>
          <button type="button" data-away-action="revert" :data-id="item.book_id" :disabled="busy || !item.book_id" @click="emit('action', 'revert', item)">
            Revert
          </button>
          <button type="button" data-away-action="dismiss" :data-action-id="item.id" :disabled="busy" @click="emit('action', 'dismiss', item)">
            Okay
          </button>
        </div>
      </article>
    </div>
  </div>
</template>
