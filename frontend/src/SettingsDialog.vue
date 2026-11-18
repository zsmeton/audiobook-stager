<script setup>
import { inject } from "vue";

import { TITLE_MODE_TIPS, TITLE_STEPS } from "./titleExtraction.js";

const settings = inject("settingsState");
defineProps({
  blocked: { type: Boolean, required: true },
});
</script>

<template>
  <h2>Settings</h2>
  <div class="resolve-tabstrip" role="tablist" aria-label="Settings sections">
    <button
      type="button"
      class="resolve-tab"
      role="tab"
      data-settings-tab="general"
      :class="{ 'is-active': settings.tab === 'general' }"
      :aria-selected="settings.tab === 'general' ? 'true' : 'false'"
      @click="settings.setTab('general')"
    >
      General
    </button>
    <button
      type="button"
      class="resolve-tab"
      role="tab"
      data-settings-tab="metadata"
      :class="{ 'is-active': settings.tab === 'metadata' }"
      :aria-selected="settings.tab === 'metadata' ? 'true' : 'false'"
      @click="settings.setTab('metadata')"
    >
      Metadata
    </button>
  </div>

  <div v-show="settings.tab === 'general'" id="settingsTabGeneral" class="settings-tabpanel">
    <section class="settings-section">
      <h3>Auto-stage</h3>
      <label class="settings-row settings-row-check">
        <input id="settingsEnabled" v-model="settings.form.enabled" type="checkbox" />
        <span>Enable scheduled auto-scan and stage</span>
      </label>
      <label class="settings-row">
        Interval (hours)
        <input id="settingsInterval" v-model.number="settings.form.interval_hours" type="number" min="0.25" step="0.25" />
      </label>
      <label class="settings-row">
        Min confidence
        <input id="settingsConfidence" v-model.number="settings.form.min_confidence" type="number" min="0" max="1" step="0.01" />
      </label>
      <label class="settings-row">
        Activity lock timeout (minutes)
        <input id="settingsLockTimeout" v-model.number="settings.form.lock_timeout_minutes" type="number" min="1" step="1" />
      </label>
      <p class="settings-note">Scheduled runs are skipped while you are actively using the stager (lock renews on approve, skip, edit, scan, etc.).</p>
      <div id="settingsLastRun" class="settings-last-run">{{ settings.lastRunText }}</div>
      <div class="settings-actions">
        <button id="settingsRunNowBtn" type="button" :disabled="blocked || settings.busy" @click="settings.runNow">
          Run auto-scan+stage now
        </button>
      </div>
    </section>
    <section class="settings-section">
      <h3>Interface</h3>
      <label class="settings-row settings-row-check">
        <input id="settingsFinishScanAnimation" v-model="settings.form.finish_scan_animation" type="checkbox" />
        <span>Finish scan animation</span>
      </label>
      <p class="settings-note">When finish scan animation is on, the scan screen stays visible for one poll cycle after completion.</p>
    </section>
  </div>

  <div v-show="settings.tab === 'metadata'" id="settingsTabMetadata" class="settings-tabpanel">
    <section class="settings-section">
      <h3>Lookup</h3>
      <label class="settings-row settings-row-check">
        <input id="settingsScanManualHints" v-model="settings.form.scan_manual_hints" type="checkbox" />
        <span>Use manual author/title as lookup hints during scan</span>
      </label>
      <p class="settings-note">When enabled, books with manual author/title use those values for provider search on scan. When disabled, scan uses file tags and folder names only. Per-book Re-lookup always uses the detail fields.</p>
      <label class="settings-row settings-row-check">
        <input id="settingsLviSearch" v-model="settings.form.lvi_search" type="checkbox" />
        <span>Use library vocabulary for search</span>
      </label>
      <label class="settings-row settings-row-check">
        <input id="settingsLviBoost" v-model="settings.form.lvi_boost" type="checkbox" />
        <span>Use library vocabulary for candidate ranking</span>
      </label>
      <p class="settings-note">LVI uses staged library folder names. Gold text marks author or series that exactly match a staged path segment.</p>
      <div class="settings-actions">
        <button id="settingsClearCacheBtn" type="button" :disabled="settings.busy" @click="settings.clearCache">
          Clear metadata cache
        </button>
      </div>
    </section>
    <section class="settings-section">
      <h3>Title extraction</h3>
      <p class="settings-note">How the stager picks a search title from your files. Applies on scan or Re-lookup.</p>
      <fieldset class="title-extraction-modes">
        <label class="settings-row settings-row-check" :title="TITLE_MODE_TIPS.conservative">
          <input
            type="radio"
            name="titleExtractionMode"
            value="conservative"
            :checked="settings.form.title_extraction_mode === 'conservative'"
            @change="settings.setMode('conservative')"
          />
          <span><strong>Conservative</strong> — album, then title, then file, then folder</span>
        </label>
        <label class="settings-row settings-row-check" :title="TITLE_MODE_TIPS.balanced">
          <input
            type="radio"
            name="titleExtractionMode"
            value="balanced"
            :checked="settings.form.title_extraction_mode === 'balanced'"
            @change="settings.setMode('balanced')"
          />
          <span><strong>Balanced</strong> — smart match across tags and paths (default)</span>
        </label>
        <label class="settings-row settings-row-check" :title="TITLE_MODE_TIPS.advanced">
          <input
            type="radio"
            name="titleExtractionMode"
            value="advanced"
            :checked="settings.form.title_extraction_mode === 'advanced'"
            @change="settings.setMode('advanced')"
          />
          <span><strong>Advanced</strong> — pick your own cleanup steps</span>
        </label>
      </fieldset>
      <div v-show="settings.form.title_extraction_mode === 'advanced'" id="titleExtractionAdvancedPanel" class="title-extraction-advanced">
        <table id="titleCleanupStepsTable" class="title-cleanup-steps-table">
          <thead>
            <tr>
              <th scope="col">Action</th>
              <th scope="col">Pre</th>
              <th scope="col">Post</th>
            </tr>
          </thead>
          <tbody id="titleCleanupStepsBody">
            <tr v-for="step in TITLE_STEPS" :key="step.id">
              <td :title="step.tip">
                <div>{{ step.label }}</div>
                <div class="settings-note">{{ step.example }}</div>
              </td>
              <td>
                <input
                  v-model="settings.form.pre[step.id]"
                  type="checkbox"
                  :value="step.id"
                  data-phase="pre"
                  :aria-label="`${step.label} pre-cleanup`"
                  @change="settings.schedulePreview"
                />
              </td>
              <td>
                <input
                  v-model="settings.form.post[step.id]"
                  type="checkbox"
                  :value="step.id"
                  data-phase="post"
                  :aria-label="`${step.label} post-cleanup`"
                  @change="settings.schedulePreview"
                />
              </td>
            </tr>
          </tbody>
        </table>
        <div class="settings-actions">
          <button id="titleExtractionPreviewBtn" type="button" @click="settings.refreshPreview(true)">Refresh preview</button>
        </div>
        <table id="titleExtractionPreviewTable" class="title-cleanup-steps-table">
          <thead>
            <tr>
              <th>Book</th>
              <th>Before</th>
              <th>After</th>
            </tr>
          </thead>
          <tbody id="titleExtractionPreviewBody">
            <tr v-for="row in settings.previewRows" :key="row.book_id || row.label" :class="{ changed: row.changed }">
              <td :title="row.book_id || ''">{{ row.label || row.book_id || "—" }}</td>
              <td>{{ row.current_title || "—" }}</td>
              <td :title="row.source_used ? `Source: ${row.source_used}` : ''">{{ row.extracted_title || "—" }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="!settings.previewRows.length" id="titleExtractionPreviewEmpty" class="settings-note">No pending or staged books to preview.</p>
      </div>
    </section>
  </div>

  <div class="dialog-actions">
    <button id="settingsSaveBtn" type="button" class="primary" :disabled="settings.busy" @click="settings.save">Save settings</button>
    <button type="button" @click="settings.close">Close</button>
  </div>
</template>
