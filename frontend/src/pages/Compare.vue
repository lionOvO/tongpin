<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { Download } from '@lucide/vue'
import { notifyError, state, candidate, api, action, download } from '../store'
import { relation, violations } from '../presentation'
import type { RecordData } from '../types'
import Notice from '../components/Notice.vue'
import Context from '../components/Context.vue'
import Empty from '../components/Empty.vue'
import JobFitComparison from '../components/JobFitComparison.vue'
import JobReference from '../components/JobReference.vue'
const rows = ref<RecordData[]>([]); const selected = ref<string[]>([]); const tab = ref('compare')
const cfg = computed(() => state.presentation!)
const safe = computed(() => rows.value.every(r => [r.display_name,r.job_title,...r.dimensions.flatMap((d: RecordData) => [d.name,...d.evidence])].every(t => !violations(t,cfg.value,true))))
const compared = computed(() => rows.value.filter(r => selected.value.includes(r.id)))
let sequence = 0
async function load() {
  const ticket = ++sequence
  rows.value = []; selected.value = []
  if (candidate.value || !state.jobId) return
  try {
    const result = await api<RecordData[]>('/candidates/ranking?job_id=' + encodeURIComponent(state.jobId))
    if (ticket === sequence) rows.value = result
  } catch (e) { if (ticket === sequence) notifyError(e) }
}
onMounted(load); watch(() => [state.jobId,state.resumeId,tab.value], load)
</script>
<template>
  <div class="page-heading"><p class="eyebrow">{{ candidate ? '求职空间 / 自选参照' : '招聘工作台 / 已确认报告' }}</p><h1>{{ candidate ? '岗位契合度' : '已确认报告比较' }}</h1><p>{{ candidate ? '从简历经历出发，了解哪些岗位更相符，以及为什么。' : '把证据放在一起，人工确认后的报告才会参与比较。' }}</p></div>
  <template v-if="candidate"><div class="compare-view-switch" role="group" aria-label="比较视图"><button type="button" :aria-pressed="tab === 'compare'" @click="tab = 'compare'">岗位契合度</button><button type="button" :aria-pressed="tab === 'benchmark'" @click="tab = 'benchmark'">岗位参考基准</button></div><JobFitComparison v-if="tab === 'compare'" /><JobReference v-else /><Notice footer />
  </template>
  <template v-else><Context><button class="secondary" :disabled="state.busy || !rows.length || !safe" @click="action(() => download('/candidates/export?job_id=' + state.jobId,'候选人对照.csv'))"><Download :size="16" />导出 CSV</button></Context><Notice /><Empty v-if="!rows.length" title="还没有已确认的报告" text="先完成能力报告审阅，再回到这里比较。" to="/reports" label="前往审阅" /><template v-else-if="safe"><section class="surface table-wrap"><table><thead><tr><th>对照</th><th>位次</th><th>展示名称</th><th v-for="d in rows[0].dimensions" :key="d.dimension_id">{{ d.name }}</th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td><input type="checkbox" v-model="selected" :value="r.id" :disabled="!selected.includes(r.id) && selected.length >= 4" :aria-label="'比较 ' + r.display_name"></td><td>{{ r.rank }}</td><td><strong>{{ r.display_name }}</strong></td><td v-for="d in rows[0].dimensions" :key="d.dimension_id">{{ relation(r.dimensions.find((x:RecordData) => x.dimension_id === d.dimension_id)?.tier || 'insufficient',cfg) }}</td></tr></tbody></table></section><p class="muted">只包含每份简历最新的已确认报告。结果相同则并列，不自动晋级或淘汰。勾选最多 4 位查看证据。</p><div class="evidence-comparison"><article v-for="r in compared" :key="r.id" class="surface context-card"><h3>{{ r.display_name }}</h3><section v-for="d in r.dimensions" :key="d.dimension_id"><h4>{{ d.name }}</h4><span class="pill">{{ relation(d.tier,cfg) }}</span><blockquote v-for="(q,i) in d.evidence.slice(0,1)" :key="i"><small>简历原文</small>{{ q }}</blockquote><p v-if="!d.evidence.length" class="muted">现有文本证据不足。</p></section></article></div></template><Empty v-else title="结果暂不可展示" text="内容未通过呈现检查，请刷新后重新查看。" /><Notice footer /></template>
</template>
<style scoped>
.compare-view-switch{display:inline-flex;align-items:center;gap:6px;max-width:100%;padding:5px;margin:0 0 24px;background:var(--surface-paper);border:1px solid var(--brand-edge);border-radius:12px;box-shadow:0 2px 6px var(--button-shadow)}
.compare-view-switch>button{display:flex;align-items:center;justify-content:center;min-height:40px;padding:9px 19px;border:1px solid transparent;border-radius:8px;background:transparent;color:var(--text-muted);font-size:13px;line-height:1.5;font-weight:500;box-shadow:none;transition:background .16s,color .16s,box-shadow .16s}
.compare-view-switch>button:hover{background:var(--brand-faint);color:var(--brand-ink)}
.compare-view-switch>button[aria-pressed=true]{background:var(--brand);color:var(--brand-on);border-color:var(--brand);font-weight:600;box-shadow:inset 0 1px 0 #ffffff40,0 2px 3px var(--button-shadow)}
.compare-view-switch>button:focus-visible{outline:2px solid var(--brand-focus);outline-offset:2px}
@media(max-width:520px){.compare-view-switch>button{padding:9px 16px}}
@media(prefers-reduced-motion:reduce){.compare-view-switch>button{transition:none}}
</style>
