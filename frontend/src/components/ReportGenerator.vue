<script setup lang="ts">
import { createRequestId } from '../request-id'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { LoaderCircle, RefreshCw } from '@lucide/vue'
import { api, ApiError, state } from '../store'
import type { RecordData } from '../types'
const props = defineProps<{ jobId: string; selected: string[]; disabled: boolean }>()
const emit = defineEmits<{ clear: [] }>()
const tasks = ref<RecordData[]>([]); const submitting = ref(false); const error = ref(''); const readError = ref(''); const checking = ref(false)
const uncertain = ref<{ job: string; ids: string[]; key: string } | null>(null)
const active = computed(() => tasks.value.find(t => ['queued', 'running'].includes(t.status)))
const latest = computed(() => active.value || tasks.value[0])
const blocked = computed(() => props.disabled || state.busy || submitting.value || !!active.value)
let alive = true; let version = 0; let reading = false; let timer: ReturnType<typeof setInterval>
async function load() {
  if (!props.jobId || reading) return
  const job = props.jobId, epoch = state.epoch, ticket = version
  reading = true; checking.value = true
  try {
    const rows = await api<RecordData[]>('/assessment-tasks?job_id=' + encodeURIComponent(job), 'GET', undefined, 15000)
    if (!alive || epoch !== state.epoch || ticket !== version) return
    tasks.value = rows
    readError.value = ''
    if (uncertain.value && rows.some(t => t.request_id === uncertain.value!.key)) { uncertain.value = null; error.value = '' }
  } catch (e) {
    if (alive && epoch === state.epoch && ticket === version && !(e instanceof ApiError && e.code === 'STALE_CONTEXT'))
      readError.value = '暂时无法读取报告进度，后台任务不会因此取消。可稍后刷新进度。'
  } finally {
    reading = false
    if (alive && ticket === version) checking.value = false
    else if (alive) void load()
  }
}
async function generate() {
  if (blocked.value || !props.selected.length) return
  const job = props.jobId, epoch = state.epoch, ticket = version
  const ids = [...props.selected]
  const attempt = uncertain.value?.job === job && JSON.stringify(uncertain.value.ids) === JSON.stringify(ids)
    ? uncertain.value : { job, ids, key: createRequestId() }
  uncertain.value = attempt; submitting.value = true; error.value = ''
  try {
    const task = await api('/assessment-tasks', 'POST', { job_id: job, resume_ids: ids, request_id: attempt.key }, 15000)
    if (!alive || epoch !== state.epoch || ticket !== version) return
    tasks.value = [task, ...tasks.value.filter(t => t.id !== task.id)]; uncertain.value = null
  } catch (e) {
    if (!alive || epoch !== state.epoch || ticket !== version) return
    error.value = e instanceof Error ? e.message : '报告任务未能提交，请重试。'
    if (e instanceof ApiError && e.status > 0) uncertain.value = null
    await load()
  } finally { if (alive && ticket === version) submitting.value = false }
}
watch(() => props.jobId, () => { version++; tasks.value = []; error.value = ''; readError.value = ''; uncertain.value = null; submitting.value = false; checking.value = false; void load() })
function visible() { if (document.visibilityState === 'visible') void load() }
onMounted(() => { void load(); timer = setInterval(visible, 4000); document.addEventListener('visibilitychange', visible) })
onUnmounted(() => { alive = false; version++; clearInterval(timer); document.removeEventListener('visibilitychange', visible) })
</script>

<template>
  <div class="report-generation">
    <div v-if="error || readError" class="feedback error" role="alert">{{ error || readError }}<button class="text-link" :disabled="checking" @click="load">刷新进度</button></div>
    <div v-if="latest" class="report-task" :class="{ failed: ['failed', 'interrupted'].includes(latest.status) }" role="status" aria-live="polite">
      <div class="task-summary"><LoaderCircle v-if="active" class="spin" :size="18" /><strong>{{ active ? (latest.status === 'queued' ? '报告已排队' : '正在生成能力报告') : latest.message }}</strong><button class="text-link" :disabled="checking" @click="load"><RefreshCw :size="14" />刷新进度</button></div>
      <p>{{ latest.model?.label }} · 已处理 {{ latest.processed }} / {{ latest.resume_ids.length }} 份 · 已生成 {{ latest.report_ids.length }} 份</p>
      <p v-if="active" class="muted">任务在后台执行，可以离开此页；返回或刷新后会继续显示进度。完成后前往报告审阅。</p>
      <p v-for="(failure, i) in latest.errors" :key="i" class="task-error">{{ failure.name ? failure.name + '：' : '' }}{{ failure.message }}</p>
      <p v-if="!active && ['failed', 'partial', 'interrupted'].includes(latest.status)" class="muted">已有报告保留；可核对后勾选未完成的简历重新生成。</p>
    </div>
    <div class="selection-footer"><span>已选择 <strong>{{ selected.length }}</strong> 份</span><button class="secondary" @click="emit('clear')" :disabled="state.busy || submitting || !selected.length">取消选择</button><button class="primary" @click="generate" :disabled="blocked || !selected.length"><LoaderCircle v-if="submitting || active" class="spin" :size="16" />{{ submitting ? '正在提交…' : active ? '报告生成中…' : '生成能力报告' }}</button><RouterLink to="/reports" class="text-link">前往审阅 →</RouterLink></div>
  </div>
</template>

<style scoped>
.report-task{margin:20px 24px;padding:18px 20px;border:1px solid var(--line);border-radius:12px;background:var(--surface-soft,var(--brand-faint));font-size:14px;line-height:1.7}.task-summary{display:flex;align-items:center;gap:10px}.task-summary>.text-link{margin-left:auto;display:inline-flex;gap:5px;align-items:center}.report-task p{margin-top:6px}.task-error{color:#a52e40}.failed{border-color:#edccd1}.report-generation>.feedback{margin:16px 24px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
</style>
