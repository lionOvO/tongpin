<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { Upload, Plus, ArrowUpRight, FileText, Trash2, LoaderCircle, Download, Inbox, Search, LayoutGrid, List, ZoomIn, Sparkles, ShieldCheck, X } from '@lucide/vue'
import { notifyError, state, candidate, job, api, action, refresh, download } from '../store'
import { origin } from '../presentation'
import type { RecordData, Resume } from '../types'
import Context from '../components/Context.vue'
import Empty from '../components/Empty.vue'
import Notice from '../components/Notice.vue'
import ApplicantResumes from '../components/ApplicantResumes.vue'
import ReportGenerator from '../components/ReportGenerator.vue'
import ResumePaper from '../components/ResumePaper.vue'
import ResumePdf from '../components/ResumePdf.vue'
import { sortedResumes, resumeDate, type ResumeSort } from '../resume-display'
import '../resume-library.css'
const applicantImport = ref(false)
function imported(resume: Resume) {
  state.resumes = [resume, ...state.resumes.filter(r => r.id !== resume.id)]
  state.resumeId = resume.id
  if (!state.jobId && resume.application_job_id) state.jobId = resume.application_job_id
}
async function downloadResume(resume: Resume, textOnly = false) {
  const original = textOnly ? undefined : resume.original_file
  const filename = original?.name || resume.display_name.replace(/[\\/:*?"<>|\r\n]/g, '_') + '.txt'
  await action(() => download('/resumes/' + resume.id + (original ? '/original' : '/download'), filename))
}
const hasPdf = (resume: Resume) => resume.original_file?.media_type === 'application/pdf'
const importing = ref(false); const importTab = ref('file'); const files = ref<File[]>([]); const name = ref(''); const text = ref(''); const dataOrigin = ref('real')
const query = ref(''); const selected = ref<string[]>([]); const batches = ref<RecordData[]>([]); const failures = ref<RecordData[]>([]); const expanded = ref('')
const sort = ref<ResumeSort>('newest')
function savedLayout(): 'grid' | 'list' {
  try { return typeof localStorage !== 'undefined' && localStorage.getItem('tongpin:resume-layout') === 'list' ? 'list' : 'grid' } catch { return 'grid' }
}
const layout = ref(savedLayout())
watch(layout, value => { try { if (typeof localStorage !== 'undefined') localStorage.setItem('tongpin:resume-layout', value) } catch { /* View preference is optional. */ } })
type PreviewTab = 'original' | 'paper' | 'source' | 'evidence'
const previewTab = ref<PreviewTab>('paper')
const preview = computed(() => jobResumes.value.find(r => r.id === expanded.value))
function openPreview(resume: Resume, tab?: PreviewTab) { expanded.value = resume.id; previewTab.value = tab || (hasPdf(resume) ? 'original' : 'paper') }
function reimportOriginal() { expanded.value = ''; importTab.value = 'file'; importing.value = true }
const deleteTarget = ref<Resume | null>(null); const deleteError = ref(''); const deleting = ref(false)
const jobResumes = computed(() => state.resumes.filter(r => candidate.value || !r.source_application_id || !state.jobId || r.application_job_id === state.jobId))
const rows = computed(() => sortedResumes(jobResumes.value, query.value, sort.value))
const batch = (id: string) => batches.value.find(b => b.resume_id === id)
const batchLabel = (b?: RecordData) => !b ? '未整理初筛' : b.hard_gate_result === '规则未通过' ? '规则待复核' : b.hard_gate_result === '信息待补充' ? '信息待补充' : b.tier === '高匹配' ? '描述较相符' : '有待了解'
let sequence = 0
async function load() { batches.value = []; const id = state.jobId; const ticket = ++sequence; if (!id || candidate.value) return; try { const b = await api<RecordData[]>('/batches?job_id=' + id); if (ticket === sequence) batches.value = b } catch (e) { if (ticket === sequence) notifyError(e) } }
watch(() => state.jobId, () => { selected.value = []; load() }); onMounted(load)
let sharedTimer: ReturnType<typeof setInterval> | undefined
let sharedAlive = true
async function refreshShared() {
  if (candidate.value || state.busy || importing.value || applicantImport.value || document.visibilityState !== 'visible' || !state.resumes.some(r => r.source_application_id)) return
  const epoch = state.epoch
  try {
    const fresh = await api<Resume[]>('/resumes')
    if (!sharedAlive || epoch !== state.epoch) return
    state.resumes = fresh
    selected.value = selected.value.filter(id => fresh.some(r => r.id === id))
    if (!fresh.some(r => r.id === expanded.value)) expanded.value = ''
    if (!fresh.some(r => r.id === state.resumeId)) state.resumeId = fresh[0]?.id || ''
    await load()
  } catch (e) { if (sharedAlive && epoch === state.epoch) notifyError(e) }
}
onMounted(() => { if (!candidate.value) { sharedTimer = setInterval(refreshShared, 15000); document.addEventListener('visibilitychange', refreshShared) } })
onUnmounted(() => { sharedAlive = false; clearInterval(sharedTimer); if (sharedTimer) document.removeEventListener('visibilitychange', refreshShared) })
async function importResume() { await action(async () => { failures.value = []; if (importTab.value === 'file') { const form = new FormData(); files.value.forEach(f => form.append('files', f)); form.append('data_origin', dataOrigin.value); const result = await api('/resumes/batch', 'POST', form); failures.value = result.errors; state.success = `已导入 ${result.resumes.length} 份简历。`; if (!result.errors.length) importing.value = false } else { await api('/resumes', 'POST', { name: name.value, text: text.value, data_origin: dataOrigin.value }); importing.value = false; name.value = ''; text.value = ''; state.success = '文字简历已保存。' } await refresh() }) }
async function screen() { await action(async () => { await api('/batches/run', 'POST', { job_id: state.jobId }); await load() }, '初筛已整理。规则仅标记供复核，不删除简历。') }
function selectFiles(e: Event) { files.value = Array.from((e.target as HTMLInputElement).files || []) }
function requestDelete(resume: Resume) {
  if (state.busy) return
  deleteTarget.value = resume; deleteError.value = ''
}
async function deleteResume() {
  if (!deleteTarget.value || state.busy || state.switching) return
  const id = deleteTarget.value.id
  const epoch = state.epoch
  await action(async () => {
    deleting.value = true; deleteError.value = ''
    try {
      await api('/resumes/' + id, 'DELETE')
      state.resumes = state.resumes.filter(r => r.id !== id)
      if (state.resumeId === id) state.resumeId = state.resumes[0]?.id || ''
      selected.value = selected.value.filter(value => value !== id)
      batches.value = batches.value.filter(b => b.resume_id !== id)
      if (expanded.value === id) expanded.value = ''
      deleteTarget.value = null
      state.success = '简历已从材料列表删除，已有对话、报告和投递记录保留。'
    } catch (error) {
      if (epoch === state.epoch) deleteError.value = error instanceof Error ? error.message : '删除失败，请重试。'
      throw error
    } finally { deleting.value = false }
  })
}
</script>
<template>
  <div class="page-heading heading-action resume-library-heading"><div><p class="eyebrow">{{ candidate ? '求职空间 / 简历库' : '招聘工作台 / 第二步' }}</p><h1>{{ candidate ? '我的简历' : '简历与初筛' }}</h1><p>{{ candidate ? '把经历放在眼前，随时继续完善。' : '阅读候选人的具体经历，保留每一份了解的机会。' }}</p></div><div class="resume-heading-actions"><button v-if="!candidate" class="primary" @click="applicantImport = true"><Inbox :size="18" />导入投递者简历</button><button :class="candidate ? 'primary' : 'secondary'" @click="importing = true"><Upload :size="18" />{{ candidate ? '导入简历' : '本地导入' }}</button></div></div>
  <p v-if="!candidate" class="notice">可从已授权投递一键导入简历，也可上传自有材料。投递进展在 <RouterLink to="/applications" class="text-link">应聘与邀请 →</RouterLink> 中查看。</p>
  <Context v-if="!candidate"><button class="secondary" :disabled="state.busy || !job || job.status !== '已确认' || !jobResumes.length" @click="screen">整理本岗位初筛</button></Context>
  <p v-if="!candidate && job?.status !== '已确认'" class="notice">请先在岗位详情确认画像，再开始初筛或分析。</p>
  <div v-if="failures.length" class="feedback error"><div v-for="(f,i) in failures" :key="i">{{ f.filename || f.name }}：{{ f.message }}</div></div>
  <Empty v-if="!jobResumes.length" title="从第一份简历开始" :text="candidate ? '上传 PDF、DOC、DOCX、TXT、JSON，或粘贴简历文字。导入后即可预览和继续完善。扫描 PDF 请先转换为可提取的文本。' : '从当前岗位的已授权投递中导入，或上传自有简历。'"><button v-if="!candidate" class="primary" @click="applicantImport = true"><Inbox :size="16" />从投递中导入</button><button :class="candidate ? 'primary' : 'secondary'" @click="importing = true"><Plus :size="16" />{{ candidate ? '导入第一份简历' : '本地导入简历' }}</button></Empty>
  <section v-else class="resume-library" aria-labelledby="resume-library-title">
    <div class="resume-library-toolbar">
      <div class="resume-library-total"><h2 id="resume-library-title">{{ candidate ? '全部简历' : '已导入的简历' }}<span>{{ jobResumes.length }}</span></h2><p><ShieldCheck :size="14" />{{ candidate ? '仅你可见，投递时由你授权共享' : '仅显示当前身份可用的材料' }}</p></div>
      <div class="resume-library-controls"><label class="resume-search"><span class="sr-only">搜索简历</span><Search :size="17" /><input type="search" v-model="query" placeholder="搜索简历名称"></label><label class="resume-sort"><span class="sr-only">简历排序</span><select v-model="sort" aria-label="简历排序"><option value="newest">最近导入</option><option value="oldest">最早导入</option><option value="name">按名称排序</option></select></label><div class="resume-layout-switch" role="group" aria-label="简历展示方式"><button :aria-pressed="layout === 'grid'" aria-label="卡片视图" title="卡片视图" @click="layout = 'grid'"><LayoutGrid :size="18" /></button><button :aria-pressed="layout === 'list'" aria-label="列表视图" title="列表视图" @click="layout = 'list'"><List :size="19" /></button></div></div>
    </div>
    <p v-if="!candidate" class="resume-selection-hint">勾选需要深入分析的简历，每批最多 50 份。初筛仅提供参考，所有简历均可查看。</p>
    <Notice v-if="!candidate && batches.length" />
    <div :class="['resume-collection', 'resume-collection-' + layout]">
      <article v-for="r in rows" :key="r.id" :class="['resume-item', 'resume-library-card', { 'is-selected': selected.includes(r.id) }]">
        <div v-if="!candidate" class="resume-card-select resume-row"><label class="check"><input type="checkbox" v-model="selected" :value="r.id" :disabled="state.busy || (!selected.includes(r.id) && selected.length >= 50)" :aria-label="'选择 ' + r.display_name"><span>用于分析</span></label><span :class="['pill', { teal: batch(r.id)?.tier === '高匹配' }]">{{ batchLabel(batch(r.id)) }}</span></div>
        <div class="resume-cover"><div class="resume-cover-paper" aria-hidden="true"><ResumePdf v-if="hasPdf(r)" :resume-id="r.id" :name="r.display_name" compact /><ResumePaper v-else :name="r.display_name" :text="r.text" compact /></div><button class="resume-cover-open" :aria-label="'预览简历：' + r.display_name" @click="openPreview(r)"><span><ZoomIn :size="15" />放大预览</span></button></div>
        <div class="resume-card-information"><div class="resume-card-title"><FileText :size="17" /><h3><button :title="r.display_name" @click="openPreview(r)">{{ r.display_name }}</button></h3></div><p class="resume-card-date">{{ resumeDate(r.created_at) }}<span>{{ r.text.length }} 字</span></p><p v-if="hasPdf(r)" class="resume-card-format">PDF 原版 · 保留上传时排版</p><p class="resume-card-origin">{{ r.source_application_id ? '主动投递 · ' + r.application_job_title : origin(r.data_origin) }}</p><p v-if="r.supplement_notice" class="resume-card-supplement">含本人补充 · 未外部核验</p></div>
        <div class="resume-card-actions"><RouterLink v-if="candidate" :to="{ path: '/ai-workspace', query: { resume: r.id } }" class="resume-ai-action"><Sparkles :size="15" />与 AI 完善<ArrowUpRight :size="14" /></RouterLink><button class="resume-evidence-action" @click="openPreview(r, candidate ? 'source' : 'evidence')">查看依据<ArrowUpRight :size="14" /></button><div class="resume-card-file-actions"><button class="resume-download-link" :disabled="state.busy" :aria-label="'下载简历：' + r.display_name" @click="downloadResume(r)"><Download :size="14" /><span>下载</span></button><button class="resume-delete-link" :disabled="state.busy" :aria-label="'删除简历：' + r.display_name" @click="requestDelete(r)"><Trash2 :size="14" /><span>删除</span></button></div></div>
      </article>
    </div>
    <div v-if="!rows.length" class="resume-search-empty"><Search :size="27" /><h3>没有找到对应的简历</h3><p>试试其他名称，或清空搜索查看全部。</p><button class="secondary" @click="query = ''">清空搜索</button></div>
    <Notice v-if="!candidate && batches.length" footer />
    <ReportGenerator v-if="!candidate" :job-id="state.jobId" :selected="selected" :disabled="job?.status !== '已确认'" @clear="selected = []" />
  </section>
  <div v-if="preview" class="modal-backdrop resume-reader-backdrop" @click.self="expanded = ''"><section v-dialog class="modal resume-reader" role="dialog" aria-modal="true" aria-labelledby="resume-reader-title">
    <header class="resume-reader-heading"><div><p>简历材料</p><h2 id="resume-reader-title">{{ preview.display_name }}</h2></div><button class="icon-button" aria-label="关闭简历预览" @click="expanded = ''"><X :size="21" /></button></header>
    <div class="resume-reader-toolbar"><div class="resume-reader-tabs" role="group" aria-label="简历阅读方式"><button v-if="hasPdf(preview)" :aria-pressed="previewTab === 'original'" @click="previewTab = 'original'">原 PDF</button><button :aria-pressed="previewTab === 'paper'" @click="previewTab = 'paper'">文本排版</button><button :aria-pressed="previewTab === 'source'" @click="previewTab = 'source'">分析文本</button><button v-if="!candidate" :aria-pressed="previewTab === 'evidence'" @click="previewTab = 'evidence'">初筛依据</button></div><button class="secondary" :disabled="state.busy" @click="downloadResume(preview, previewTab === 'source')"><Download :size="15" />{{ preview.original_file && previewTab !== 'source' ? '下载原文件' : '下载文本' }}</button></div>
    <div class="resume-reader-scroll" tabindex="0" aria-label="简历阅读内容"><div v-if="preview.original_file && !hasPdf(preview) && previewTab === 'paper'" class="resume-original-notice"><p>当前为提取文字的阅读视图。点击“下载原文件”可查看 Word 原版排版。</p></div><div v-if="!preview.original_file && previewTab === 'paper'" class="resume-original-notice"><div><strong>当前仅保存了分析文本</strong><p>这份材料未保留原文件，无法还原原来的字体、颜色与布局。重新上传 PDF 后，即可查看和下载原版。</p></div><button class="secondary" @click="reimportOriginal"><Upload :size="15" />重新上传 PDF</button></div><div v-if="previewTab === 'original' && hasPdf(preview)" class="resume-reader-canvas"><ResumePdf :key="preview.id" :resume-id="preview.id" :name="preview.display_name" /></div><div v-else-if="previewTab === 'paper'" class="resume-reader-canvas"><ResumePaper :name="preview.display_name" :text="preview.text" /></div><div v-else-if="previewTab === 'source'" class="resume-reader-source"><h3>用于分析的简历文本</h3><p class="resume-source-note">文字从文件中提取，并隔离联系方式等敏感信息；PDF 中的换行可能保留在此处。</p><p class="source-text">{{ preview.text }}</p></div><div v-else class="resume-reader-evidence"><template v-if="batch(preview.id)"><article v-for="(s,i) in [...batch(preview.id)!.hits, ...batch(preview.id)!.misses]" :key="i"><h3>{{ s.skill }}</h3><p>{{ s.reason }}</p><blockquote v-for="(q,n) in s.evidence" :key="n"><small>简历原文</small>{{ q }}</blockquote></article><p v-if="batch(preview.id)!.hard_gate_rule_ids.length" class="muted">规则编号：{{ batch(preview.id)!.hard_gate_rule_ids.join('、') }}；仅供人工复核。</p></template><p v-else class="notice">这份简历尚未整理初筛，可先阅读完整材料，再选择是否分析。</p></div></div>
    <footer class="resume-reader-footer"><p>{{ previewTab === 'original' ? '按上传的 PDF 原样展示，分析文本单独保存。' : '此视图按提取的文本排版，供阅读与分析使用。' }}<span v-if="preview.supplement_notice">含本人补充（未外部核验）。</span></p><RouterLink v-if="candidate" :to="{ path: '/ai-workspace', query: { resume: preview.id } }" class="primary"><Sparkles :size="16" />与 AI 完善<ArrowUpRight :size="15" /></RouterLink></footer>
  </section></div>
  <ApplicantResumes v-if="applicantImport && !candidate" :job-id="state.jobId" :job-title="job?.title" @close="applicantImport = false" @imported="imported" />
  <div v-if="importing" class="modal-backdrop" @click.self="!state.busy && (importing = false)"><section v-dialog class="modal" role="dialog" aria-modal="true" aria-labelledby="import-title"><div class="detail-heading"><h2 id="import-title">导入简历材料</h2><button class="icon-button" @click="importing = false" :disabled="state.busy" aria-label="关闭导入简历">×</button></div><div class="resume-import-method-row"><div class="resume-import-method" role="group" aria-label="简历导入方式"><button type="button" :aria-pressed="importTab === 'file'" :disabled="state.busy" @click="importTab = 'file'">上传文件</button><button type="button" :aria-pressed="importTab === 'text'" :disabled="state.busy" @click="importTab = 'text'">粘贴文字</button></div></div><form @submit.prevent="importResume"><div v-if="importTab === 'file'" class="upload-zone"><Upload :size="33" /><strong>选择要导入的简历</strong><p>PDF、DOC、DOCX、TXT、JSON · 单份不超过 10 MB</p><p class="resume-upload-note">PDF 保留原版排版；Word 保留原文件供下载，提取文字用于预览与 AI 分析。</p><input type="file" multiple accept=".pdf,.doc,.docx,.txt,.json" @change="selectFiles" required aria-label="选择简历文件"><small v-if="files.length">已选择 {{ files.length }} 个文件</small></div><template v-else><label>展示名称<input v-model="name" required maxlength="40" placeholder="演示请使用虚构姓名"></label><label>简历原文<textarea v-model="text" required minlength="20" maxlength="50000" rows="10" placeholder="粘贴教育、技能、项目与实习的具体描述。" /></label></template><label>数据来源<select v-model="dataOrigin"><option value="real">本人 / 自有简历</option><option value="synthetic">合成 / 演示数据</option></select></label><div class="form-footer"><span>示例与用户导入数据分别标记。</span><button class="primary" :disabled="state.busy">{{ importTab === 'file' ? '导入所选文件' : '保存文字简历' }}</button></div></form></section></div>
  <div v-if="deleteTarget" class="modal-backdrop" @click.self="!state.busy && (deleteTarget = null)">
    <section v-dialog class="modal resume-delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-resume-title" aria-describedby="delete-resume-description">
      <div class="detail-heading"><h2 id="delete-resume-title">删除这份简历？</h2><button class="icon-button" aria-label="关闭删除简历" :disabled="state.busy" @click="deleteTarget = null">×</button></div>
      <div class="resume-delete-body">
        <p class="resume-delete-name"><FileText :size="20" />{{ deleteTarget.display_name }}</p>
        <p id="delete-resume-description">删除后，这份简历不再出现在材料列表中，也不能用于新的投递和分析。需要再次使用时，可重新导入。</p>
        <p class="resume-delete-history">已有 AI 对话、分析报告和已授权的投递快照保留。如需停止向企业共享，请在“我的投递”中撤回授权。</p>
        <p v-if="deleteError" class="feedback error" role="alert">{{ deleteError }}</p>
        <div class="resume-delete-actions"><button class="secondary" :disabled="state.busy" @click="deleteTarget = null">取消</button><button class="danger" :disabled="state.busy" @click="deleteResume"><LoaderCircle v-if="deleting" class="spin" :size="16" /><Trash2 v-else :size="16" />{{ deleting ? '正在删除…' : '确认删除' }}</button></div>
      </div>
    </section>
  </div>
</template>

<style scoped>

.resume-import-method-row{padding:22px 26px 0}
.resume-import-method{display:inline-grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;padding:4px;border:1px solid var(--border-soft);border-radius:10px;background:var(--surface-soft);max-width:100%}
.resume-import-method>button{display:flex;align-items:center;justify-content:center;min-width:0;min-height:38px;padding:8px 18px;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--text-muted);font-size:12px;line-height:1.6;font-weight:500;box-shadow:none;transform:none}
.resume-import-method>button:hover:not(:disabled){background:var(--surface-paper);color:var(--brand-ink)}
.resume-import-method>button[aria-pressed=true]:not(:disabled){background:var(--brand);border-color:var(--brand);color:var(--brand-on);font-weight:600;box-shadow:0 1px 3px var(--button-shadow)}
.resume-import-method>button:focus-visible{outline:2px solid var(--brand-focus);outline-offset:2px}
@media(max-width:600px){.resume-import-method-row{padding:20px 20px 0}.resume-import-method{display:grid;width:100%}}

.resume-heading-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.resume-download-link{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.resume-delete-link { color: #aa3846; white-space: nowrap; }
.resume-delete-link:hover { color: #832431; }
.resume-delete-modal { width: min(560px, 100%); }
.resume-delete-body { padding: 24px 26px 26px; display: grid; gap: 18px; font-size: 14px; line-height: 1.8; }
.resume-delete-name { display: flex; align-items: flex-start; gap: 10px; font-weight: 600; overflow-wrap: anywhere; }
.resume-delete-name svg { flex-shrink: 0; margin-top: 3px; color:var(--brand-ink); }
.resume-delete-history { color: var(--muted); padding-top: 16px; border-top: 1px solid var(--line); font-size: 13px; }
.resume-delete-actions { display: flex; justify-content: flex-end; gap: 12px; padding-top: 6px; }
.resume-delete-body .feedback { margin: 0; }
</style>
