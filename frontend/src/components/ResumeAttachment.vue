<script setup lang="ts">
import { FileText, ChevronDown } from '@lucide/vue'
defineProps<{ name: string; text: string; note?: string }>()
</script>
<template>
  <details class="resume-file-card">
    <summary><span class="resume-file-icon" aria-hidden="true"><FileText :size="24" :stroke-width="1.6" /><small>简历</small></span><span class="resume-file-info"><strong>{{ name }}</strong><small>{{ note || '授权简历 · 投递时保存的版本' }}</small></span><ChevronDown class="resume-file-chevron" :size="16" aria-hidden="true" /></summary>
    <div class="resume-file-content"><slot /><p class="source-text">{{ text }}</p></div>
  </details>
</template>
<style scoped>
.resume-file-card{border:1px solid var(--brand-edge);background:var(--surface-paper);border-radius:10px;overflow:hidden;padding:0;min-width:0}
.resume-file-card>summary{display:flex;align-items:center;gap:12px;list-style:none;padding:14px;margin:0;background:var(--surface-paper);cursor:pointer;color:var(--text-main);border:0;min-height:78px}
.resume-file-card>summary::-webkit-details-marker{display:none}.resume-file-card>summary:hover{background:var(--brand-faint)}
.resume-file-icon{display:flex;flex-direction:column;align-items:center;justify-content:center;flex:0 0 42px;height:52px;border:1px solid var(--brand-edge);border-radius:7px;color:var(--brand-ink);background:var(--brand-soft)}
.resume-file-icon small{font-size:9px;line-height:1.3;margin-top:2px}.resume-file-info{flex:1;min-width:0;display:flex;flex-direction:column;gap:5px}.resume-file-info strong{font-size:13px;line-height:1.6;overflow-wrap:anywhere}.resume-file-info small{font-size:10px;color:var(--text-muted);line-height:1.6}.resume-file-chevron{flex-shrink:0;transition:transform .18s}.resume-file-card[open] .resume-file-chevron{transform:rotate(180deg)}.resume-file-content{padding:14px;border-top:1px solid var(--border-soft)}.resume-file-content .source-text{margin:0;font-size:12px;line-height:1.8;max-height:440px;overflow:auto;overflow-wrap:anywhere}
@media(prefers-reduced-motion:reduce){.resume-file-chevron{transition:none}}
</style>
