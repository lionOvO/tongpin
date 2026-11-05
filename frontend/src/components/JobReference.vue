<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { FileText, RefreshCw } from '@lucide/vue'
import { api, ApiError, state, confirmedJobs } from '../store'
import type { RecordData } from '../types'
import JobRequirements from './JobRequirements.vue'
import Empty from './Empty.vue'

const job = computed(() => confirmedJobs.value.find(j => j.id === state.jobId))
const statistics = ref<RecordData[]>([]), levelNames = ref<Record<string, string>>()
const status = ref<'loading' | 'ready' | 'empty' | 'error'>('empty')
const unavailable = ref(false)
const relevantStatistics = computed(() => statistics.value.filter(b => job.value?.profile.requirements.some(r => r.skill.trim().toLowerCase() === String(b.skill).trim().toLowerCase())))
let alive = true, sequence = 0
async function loadStatistics() {
  const ticket = ++sequence, epoch = state.epoch, id = job.value?.id
  statistics.value = []; unavailable.value = false
  if (!id) { status.value = 'empty'; return }
  status.value = 'loading'
  try {
    const rows = await api<RecordData[]>('/fit/benchmark?job_id=' + encodeURIComponent(id), 'GET', undefined, 15000)
    if (!alive || ticket !== sequence || epoch !== state.epoch) return
    statistics.value = rows; status.value = rows.length ? 'ready' : 'empty'
  } catch (e) {
    if (!alive || ticket !== sequence || epoch !== state.epoch) return
    if (e instanceof ApiError && e.code === 'INSUFFICIENT_SAMPLES') status.value = 'empty'
    else { status.value = 'error'; unavailable.value = e instanceof ApiError && e.status === 404 }
  }
}
onMounted(async () => {
  const epoch = state.epoch
  try {
    const rubric = await api<RecordData>('/config/rubric', 'GET', undefined, 15000)
    if (alive && epoch === state.epoch) levelNames.value = rubric.skill_names
  } catch { /* The original requirements remain readable without a glossary. */ }
})
watch(() => [job.value?.id, job.value?.version, state.epoch], () => { void loadStatistics() }, { immediate: true })
onUnmounted(() => { alive = false; sequence++ })
</script>

<template>
  <section v-if="job && !unavailable" class="job-reference surface" aria-labelledby="job-reference-title">
    <header class="job-reference-heading">
      <div><p class="eyebrow">从岗位原文了解要求</p><h2 id="job-reference-title">岗位要求参照</h2><p>先看这个岗位需要什么，再结合自己的经历判断。</p></div>
      <label for="reference-target-job">参照岗位<select id="reference-target-job" v-model="state.jobId" :disabled="state.switching"><option v-for="j in confirmedJobs" :key="j.id" :value="j.id">{{ j.title }}{{ j.personal_reference ? ' · 个人参照' : '' }}</option></select></label>
    </header>
    <div class="job-reference-body">
      <div class="job-reference-identity"><div><span>{{ job.personal_reference ? '个人参照 · 仅自己可见' : job.company_name || '招聘岗位' }}</span><h3>{{ job.title }}</h3></div><span class="job-reference-source"><FileText :size="14" />基于岗位原文</span></div>
      <JobRequirements :profile="job.profile" :level-names="levelNames" />
      <p class="job-reference-note">要求程度由岗位描述整理，以引用原文为准；这是岗位要求，不是对你的能力评分。</p>
      <details class="job-reference-original"><summary>查看完整岗位原文</summary><div>{{ job.source_jd || '暂未保存完整原文，可查看上方逐项引用。' }}</div></details>
      <section class="job-reference-statistics" aria-labelledby="reference-statistics-title">
        <header><div><h3 id="reference-statistics-title">同类岗位统计 <small>补充参考</small></h3><p>有足够的有效样本时，额外展示统计范围。</p></div><button v-if="status !== 'loading'" class="secondary small" type="button" @click="loadStatistics"><RefreshCw :size="14" />刷新统计</button></header>
        <p v-if="status === 'loading'" class="job-reference-status" role="status">正在查询可用统计，岗位要求可直接查看。</p>
        <div v-else-if="status === 'ready' && relevantStatistics.length" class="job-reference-ranges"><article v-for="b in relevantStatistics" :key="b.id"><h4>{{ b.skill }}</h4><p><strong>{{ b.lower_level }}–{{ b.upper_level }}</strong> 级要求范围</p><span>{{ b.sample_size }} 个不同岗位 · {{ b.source_type === 'B_synthetic' ? '合成样例统计，非真实招聘数据' : '岗位要求统计' }}</span></article><p class="job-reference-scope">统计来自同一招聘账号下、同方向、同数据来源的岗位，不代表整个行业或实际录用门槛。</p></div>
        <p v-else-if="status === 'error'" class="job-reference-status" role="status">统计暂时无法加载，可稍后刷新；不影响查看上方岗位要求。</p>
        <p v-else class="job-reference-status">暂未提供可用的同类岗位统计。可先按上方岗位原文了解要求，不影响契合度分析。</p>
      </section>
    </div>
  </section>
  <Empty v-else-if="unavailable" title="这个岗位暂时无法访问" text="岗位可能已撤下或权限发生变化，请重新选择可查看的岗位。" to="/jobs" label="查看岗位" />
  <Empty v-else title="先选择一个参照岗位" text="可以在岗位契合度中添加个人参照，也可以查看已发布的岗位。" to="/jobs" label="查看岗位" />
</template>

<style scoped>
.job-reference{overflow:hidden}.job-reference-heading{display:grid;grid-template-columns:1fr minmax(240px,38%);align-items:center;gap:26px;padding:26px 28px;background:var(--brand-faint);border-bottom:1px solid var(--brand-edge)}.job-reference-heading h2{font-size:23px;margin:5px 0 10px}.job-reference-heading p{margin:0;color:var(--text-muted);font-size:13px;line-height:1.8}.job-reference-heading label{display:grid;gap:9px;font-size:13px;font-weight:600;min-width:0}.job-reference-heading select{width:100%;background:white}.job-reference-body{padding:28px}.job-reference-identity{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:24px}.job-reference-identity h3{font-size:21px;line-height:1.6;margin:7px 0 0;overflow-wrap:anywhere}.job-reference-identity>div>span{font-size:12px;color:var(--text-muted)}.job-reference-source{display:inline-flex;align-items:center;gap:6px;flex-shrink:0;border:1px solid var(--brand-edge);border-radius:6px;padding:6px 9px;font-size:11px;color:var(--brand-ink);background:var(--brand-faint)}.job-reference-note{font-size:12px;line-height:1.8;color:var(--text-muted);margin:18px 0}.job-reference-original{border:1px solid var(--border-soft);border-radius:9px;overflow:hidden}.job-reference-original>summary{padding:14px 17px;font-size:13px;font-weight:600;color:var(--brand-ink);cursor:pointer}.job-reference-original>div{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.9;font-size:13px;padding:18px;border-top:1px solid var(--border-soft);max-height:360px;overflow:auto;background:var(--brand-faint)}.job-reference-statistics{margin-top:30px;padding-top:25px;border-top:1px solid var(--border-soft)}.job-reference-statistics>header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px}.job-reference-statistics h3{margin:0;font-size:17px}.job-reference-statistics h3 small{font-size:11px;font-weight:400;color:var(--text-muted);margin-left:8px}.job-reference-statistics header p{font-size:12px;color:var(--text-muted);margin:8px 0 0;line-height:1.8}.job-reference-statistics button{flex-shrink:0}.job-reference-status{font-size:13px;line-height:1.9;margin:0;padding:15px 17px;border:1px solid var(--border-soft);border-radius:8px;background:var(--brand-faint);color:var(--text-muted)}.job-reference-ranges{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.job-reference-ranges article{padding:18px;border:1px solid var(--brand-edge);border-radius:9px;background:var(--brand-faint);min-width:0}.job-reference-ranges h4{font-size:15px;overflow-wrap:anywhere;margin:0 0 10px}.job-reference-ranges article p{font-size:12px;color:var(--text-muted);margin:0 0 10px}.job-reference-ranges strong{font-size:24px;color:var(--brand-ink)}.job-reference-ranges article span{font-size:11px;line-height:1.8;color:var(--text-muted)}.job-reference-scope{grid-column:1/-1;font-size:12px;line-height:1.8;color:var(--text-muted);margin:0}
@media(max-width:800px){.job-reference-heading{grid-template-columns:1fr;padding:22px;gap:20px}.job-reference-body{padding:20px}.job-reference-identity{flex-wrap:wrap;gap:10px}.job-reference-ranges{grid-template-columns:1fr 1fr}.job-reference-statistics>header{align-items:flex-start;flex-wrap:wrap}}@media(max-width:520px){.job-reference-ranges{grid-template-columns:1fr}.job-reference-body{padding:20px 16px}.job-reference-heading{padding:22px 16px}}
</style>
