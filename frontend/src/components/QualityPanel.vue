<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { api, notifyError } from '../store'
import type { RecordData } from '../types'
const props = defineProps<{jobId:string;staff?:boolean}>()
const summary = ref<RecordData | null>(null); const loading = ref(false)
let sequence = 0; let alive = true
async function load() {
  const ticket = ++sequence; summary.value = null
  if (!props.jobId) return
  loading.value = true
  try { const data = await api((props.staff ? '/admin/governance/quality' : '/quality/summary')+'?job_id='+encodeURIComponent(props.jobId)); if (alive && ticket === sequence) summary.value = data }
  catch(e) { if (alive && ticket === sequence) notifyError(e) }
  finally { if (alive && ticket === sequence) loading.value = false }
}
const percent = (value:number|null) => value === null ? '暂无数据' : (value*100).toFixed(1)+'%'
watch(() => [props.jobId,props.staff],load,{immediate:true}); onUnmounted(() => { alive = false; sequence++ })
</script>
<template>
  <section class="surface settings-section"><div class="section-heading"><h2>材料与审阅质量</h2><button type="button" class="secondary" :disabled="loading || !jobId" @click="load">刷新统计</button></div>
    <p v-if="!jobId" class="muted">选择一个企业岗位，查看该岗位的统计。</p><p v-else-if="loading" class="muted">正在加载统计…</p>
    <template v-else-if="summary"><p class="muted">{{ summary.scope }}</p><div class="audit-strip"><div><small>初筛材料</small><strong>{{ summary.batch_resumes }}</strong></div><div><small>最新有效报告</small><strong>{{ summary.reports_total }}</strong></div><div><small>证据不足率</small><strong>{{ percent(summary.insufficient_rate) }}</strong></div><div><small>人工修改报告比例</small><strong>{{ percent(summary.human_change_rate) }}</strong></div></div>
      <div class="table-wrap"><table><thead><tr><th>维度</th><th>相对岗位要求的关系分布</th><th>证据不足（含部分）</th></tr></thead><tbody><tr v-for="d in summary.dimensions" :key="d.name"><td>{{ d.name }}</td><td><span v-for="(count,label) in d.distribution" :key="label" class="pill">{{ label }}：{{ count }}</span></td><td>{{ d.insufficient_count }} / {{ d.count }}</td></tr></tbody></table></div>
      <details class="evidence-detail"><summary>每日生成与人工修订趋势</summary><div class="table-wrap"><table><thead><tr><th>日期（UTC）</th><th>生成报告</th><th>人工修改事件</th></tr></thead><tbody><tr v-for="day in summary.trend" :key="day.date"><td>{{ day.date }}</td><td>{{ day.generated }}</td><td>{{ day.changed }}</td></tr></tbody></table></div></details><p class="muted">{{ summary.note }}</p>
    </template>
  </section>
</template>
