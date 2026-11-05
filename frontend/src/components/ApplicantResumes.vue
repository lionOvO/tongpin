<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { Download, FileText, LoaderCircle, Check, ArrowDownToLine, X } from '@lucide/vue'
import { api, download, state } from '../store'
import type { Resume } from '../types'
import type { ApplicationDetail, ApplicationSummary } from '../hiring'
import { applicationLabels } from '../hiring'

const props = defineProps<{ jobId: string; jobTitle?: string }>()
const emit = defineEmits<{ close: []; imported: [resume: Resume] }>()
type Applicant = ApplicationSummary & { imported_resume_id: string | null }
const rows = ref<Applicant[]>([]); const total = ref(0); const offset = ref(0); const query = ref('')
const loading = ref(false); const pending = ref(''); const error = ref(''); const success = ref('')
const preview = ref<ApplicationDetail | null>(null)
let alive = true; let sequence = 0; let debounce: ReturnType<typeof setTimeout> | undefined
let refreshTimer: ReturnType<typeof setInterval> | undefined
async function load(quiet = false) {
  const ticket = ++sequence
  if (!quiet) { loading.value = true; error.value = ''; preview.value = null }
  try {
    const params = new URLSearchParams({ offset: String(offset.value), limit: '20', q: query.value })
    if (props.jobId) params.set('job_id', props.jobId)
    const page = await api<{ items: Applicant[]; total: number }>('/resumes/applicants?' + params)
    if (!alive || ticket !== sequence) return
    rows.value = page.items; total.value = page.total
    if (preview.value && !rows.value.some(row => row.id === preview.value?.id)) preview.value = null
  } catch (e) { if (alive && ticket === sequence) { rows.value = []; preview.value = null; error.value = e instanceof Error ? e.message : '无法读取投递简历，请重试。' } }
  finally { if (alive && ticket === sequence) loading.value = false }
}
async function operate(row: Applicant, operation: 'import' | 'preview' | 'download') {
  if (pending.value || loading.value || state.switching) return
  const epoch = state.epoch; pending.value = row.id; error.value = ''; success.value = ''
  try {
    if (operation === 'download') await download('/applications/' + row.id + '/resume-download', row.resume_name.replace(/[\\/:*?"<>|\r\n]/g, '_') + '.txt')
    else if (operation === 'preview') {
      const detail = await api<ApplicationDetail>('/applications/' + row.id)
      if (!alive || epoch !== state.epoch) return
      if (!detail.resume_shared || !detail.resume_snapshot) { await load(); error.value = '这份简历已停止授权，请选择其他投递。'; return }
      preview.value = detail
    } else {
      const result = await api<{ resume: Resume; already_imported: boolean }>('/applications/' + row.id + '/resume-import', 'POST', { expected_version: row.version })
      if (!alive || epoch !== state.epoch) return
      row.imported_resume_id = result.resume.id
      emit('imported', result.resume)
      success.value = result.already_imported ? '这份投递简历已导入，可在材料列表中使用。' : '已导入，可在材料列表中查看和分析。'
    }
  } catch (e) {
    if (alive && epoch === state.epoch) {
      // Re-read consent and deduplication state before allowing another attempt.
      await load()
      if (alive) error.value = e instanceof Error ? e.message : '操作未完成，请重试。'
    }
  } finally { if (alive) pending.value = '' }
}
function page(step: number) { if (pending.value || loading.value) return; offset.value += step * 20; void load() }
watch(query, () => { clearTimeout(debounce); debounce = setTimeout(() => { offset.value = 0; void load() }, 300) })
watch(() => props.jobId, () => { offset.value = 0; void load() })
function refreshConsent() { if (document.visibilityState === 'visible' && !pending.value && !loading.value) void load(true) }
onMounted(() => { void load(); refreshTimer = setInterval(refreshConsent, 15000); document.addEventListener('visibilitychange', refreshConsent) })
onUnmounted(() => { alive = false; sequence++; clearTimeout(debounce); clearInterval(refreshTimer); document.removeEventListener('visibilitychange', refreshConsent) })
</script>

<template>
  <div class="modal-backdrop" @click.self="!pending && emit('close')">
    <section v-dialog class="modal applicant-modal" role="dialog" aria-modal="true" aria-labelledby="applicant-import-title">
      <header class="detail-heading"><div><p class="eyebrow">来自求职者的主动投递</p><h2 id="applicant-import-title">导入投递者简历</h2></div><button class="icon-button" :disabled="!!pending" aria-label="关闭投递简历窗口" @click="emit('close')"><X :size="20" /></button></header>
      <div class="applicant-body">
        <p class="applicant-scope">{{ jobTitle ? '当前岗位：' + jobTitle : '全部岗位的已授权投递' }}<span>仅使用投递时的版本，求职者后续修改不会自动替换。下载为 TXT 文本。</span></p>
        <div class="applicant-toolbar"><label><span class="sr-only">搜索投递者或岗位</span><input v-model="query" type="search" maxlength="100" placeholder="搜索投递者或岗位" :disabled="!!pending"></label><span class="muted">{{ total }} 份已授权投递</span></div>
        <p v-if="error" class="feedback error" role="alert">{{ error }}</p><p v-if="success" class="feedback success" role="status">{{ success }}</p>
        <p v-if="loading" class="applicant-empty" role="status"><LoaderCircle class="spin" :size="18" />正在读取投递简历…</p>
        <div v-else-if="!rows.length" class="applicant-empty"><FileText :size="28" /><strong>{{ query ? '没有找到对应的投递' : '当前暂无已授权的投递简历' }}</strong><p>求职者向岗位投递并授权后，会显示在这里。</p><button class="text-link" @click="load()">刷新列表</button></div>
        <article v-for="row in loading ? [] : rows" :key="row.id" class="applicant-row">
          <span class="applicant-icon"><FileText :size="22" /></span><div class="applicant-info"><h3>{{ row.candidate_name }}</h3><p>{{ row.job_title }} · {{ applicationLabels[row.status] }}</p><small>{{ new Date(row.created_at).toLocaleString('zh-CN') }}</small></div>
          <div class="applicant-actions"><button class="text-link" :disabled="!!pending" @click="operate(row, 'preview')">查看简历</button><button class="text-link" :disabled="!!pending" @click="operate(row, 'download')"><Download :size="15" />下载</button><button :class="row.imported_resume_id ? 'secondary' : 'primary'" :disabled="!!pending || !!row.imported_resume_id" @click="operate(row, 'import')"><LoaderCircle v-if="pending === row.id" class="spin" :size="15" /><Check v-else-if="row.imported_resume_id" :size="15" /><ArrowDownToLine v-else :size="15" />{{ row.imported_resume_id ? '已导入' : '一键导入' }}</button></div>
        </article>
        <section v-if="preview?.resume_snapshot" class="applicant-preview"><div class="row-between"><h3>{{ preview.resume_snapshot.name }} · 投递版本</h3><button class="text-link" @click="preview = null">收起预览</button></div><p class="source-text">{{ preview.resume_snapshot.text }}</p></section>
        <div v-if="total > 20" class="applicant-pages"><button class="secondary" :disabled="offset === 0 || !!pending || loading" @click="page(-1)">上一页</button><span>{{ offset + 1 }}–{{ Math.min(offset + 20, total) }} / {{ total }}</span><button class="secondary" :disabled="offset + 20 >= total || !!pending || loading" @click="page(1)">下一页</button></div>
        <p class="applicant-footer">导入后仅用于原投递岗位；授权撤回或结束后，站内材料及关联分析将停止向企业展示。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.applicant-modal{width:min(940px,100%)}.applicant-modal .detail-heading{align-items:center}.applicant-modal .eyebrow{margin:0 0 8px}.applicant-body{padding:24px 28px;display:grid;gap:18px}.applicant-scope{font-size:14px;font-weight:600;line-height:1.7}.applicant-scope span{display:block;font-weight:400;color:var(--muted);font-size:12px;margin-top:6px}.applicant-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px}.applicant-toolbar label{margin:0;max-width:360px;flex:1}.applicant-toolbar>.muted{font-size:12px}.applicant-row{display:flex;align-items:center;gap:14px;border:1px solid var(--line);border-left:3px solid var(--primary);border-radius:10px;padding:18px;background:#fff}.applicant-icon{display:grid;place-items:center;width:42px;height:46px;flex-shrink:0;color:var(--brand-ink);background:var(--brand-soft);border-radius:9px}.applicant-info{flex:1;min-width:0}.applicant-info h3{font-size:15px;overflow-wrap:anywhere}.applicant-info p{font-size:12px;color:var(--muted);margin:7px 0;line-height:1.6}.applicant-info small{font-size:11px;color:var(--muted)}.applicant-actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.applicant-actions button{font-size:12px;white-space:nowrap}.applicant-actions .text-link{display:flex;align-items:center;gap:5px}.applicant-actions .primary,.applicant-actions .secondary{min-height:36px;padding:8px 12px}.applicant-empty{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:14px;min-height:170px;text-align:center;color:var(--muted);font-size:13px}.applicant-preview{border:1px solid var(--line);border-radius:10px;padding:20px;background:var(--brand-faint)}.applicant-preview h3{font-size:14px}.applicant-preview .source-text{max-height:340px;overflow:auto;margin-top:16px;font-size:13px}.applicant-footer{border-top:1px solid var(--line);padding-top:16px;font-size:12px;color:var(--muted);line-height:1.8}.applicant-pages{display:flex;align-items:center;justify-content:flex-end;gap:12px;font-size:12px}.applicant-body>.feedback{margin:0}@media(max-width:700px){.applicant-body{padding:18px}.applicant-row{flex-wrap:wrap}.applicant-actions{width:100%;justify-content:flex-end}.applicant-toolbar{flex-wrap:wrap}.applicant-toolbar label{max-width:none;flex-basis:100%}}
</style>
