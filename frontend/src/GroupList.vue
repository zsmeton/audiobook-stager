<script setup>
import { inject } from "vue";

import { kindInfo, resolveStatus, sidesLabel, targetSeriesLine } from "./groups.js";

const resolve = inject("resolveState");

function author(group) {
  const parts = String(group.target_key || "").split("/");
  return parts[0] || "—";
}

function title(group) {
  const parts = String(group.target_key || "").split("/").filter(Boolean);
  if (parts.length >= 3) return parts.slice(2).join("/");
  return parts[1] || "—";
}
</script>

<template>
  <div id="conflictsContent" class="section-list" :data-total="resolve.total" :data-offset="resolve.offset">
    <p v-if="!resolve.total" id="conflictsEmpty" class="section-empty-state">No conflicts.</p>
    <div v-else id="conflictsListWrap" class="section-list-wrap">
      <div class="group-head" aria-hidden="true">
        <span>Book</span>
        <span>Sides</span>
        <span>Kind</span>
        <span>Status</span>
        <span>Actions</span>
      </div>
      <div
        id="conflictsList"
        class="section-rows"
        role="list"
        :data-rendered="resolve.pageGroups.length"
        :data-total="resolve.total"
      >
        <article
          v-for="group in resolve.pageGroups"
          :key="group.target_key"
          class="group-row"
          role="listitem"
          :data-target-key="group.target_key"
        >
          <div class="group-book">
            <strong>{{ author(group) }}</strong>
            <span>{{ title(group) }}</span>
            <span v-if="targetSeriesLine(group.target_key)" class="meta-badge">{{ targetSeriesLine(group.target_key) }}</span>
          </div>
          <div>{{ sidesLabel(group) }}</div>
          <div>
            <span class="status-pill" :title="kindInfo(group).title">{{ kindInfo(group).label }}</span>
          </div>
          <div class="group-status">{{ resolveStatus(group) }}</div>
          <div class="staging-actions">
            <button
              type="button"
              class="conflict-resolve-btn"
              :data-target-key="group.target_key"
              :disabled="resolve.busy"
              @click="resolve.openGroup(group.target_key)"
            >
              Resolve
            </button>
          </div>
        </article>
      </div>
      <div class="staging-pager">
        <button id="conflictsPrev" type="button" :disabled="!resolve.canPrev" @click="resolve.prevPage">Previous</button>
        <p class="staging-page-status">Groups {{ resolve.pageFrom }}–{{ resolve.pageTo }} of {{ resolve.total }}</p>
        <button id="conflictsNext" type="button" :disabled="!resolve.canNext" @click="resolve.nextPage">Next</button>
      </div>
    </div>
  </div>
</template>
