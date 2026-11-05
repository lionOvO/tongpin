<script setup lang="ts">
import { createRequestId } from '../request-id'
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Sparkles, Plus, ArrowUp, FileText, BriefcaseBusiness, PanelLeftClose, PanelRightClose, MessageSquare, Check, LoaderCircle, Trash2, ArrowUpRight, X, ChevronDown, ScanText, Maximize2, Minimize2, History, Info, Search } from '@lucide/vue'
import { state, api, streamApi, notifyError, refresh, ApiError } from '../store'
import { findingLabel, sourceLabel, currentDraft, noteSaved } from '../ai-workspace'
import type { Workspace, WorkspaceSummary, Message, ModelCatalog } from '../ai-workspace'
import InfoHint from '../components/InfoHint.vue'
import ResumeDraftEdit from '../components/ResumeDraftEdit.vue'
import WorkspaceJobResults from '../components/WorkspaceJobResults.vue'
const route = useRoute(); const router = useRouter()
const sessions = ref<WorkspaceSummary[]>([]); const workspace = ref<Workspace | null>(null)
const historyOpen = ref(false); const historySearch = ref('')
const filteredHistory = computed(() => sessions.value.filter(s => `${s.title} ${s.preview || ''}`.toLocaleLowerCase().includes(historySearch.value.trim().toLocaleLowerCase())))
const hasPendingMaterials = computed(() => !!workspace.value?.pending_materials)
const displayResume = computed(() => workspace.value?.pending_materials?.resume || workspace.value?.resume)
const displayJob = computed(() => workspace.value?.pending_materials ? workspace.value.pending_materials.job : workspace.value?.job)
const applicationJob = computed(() => !hasPendingMaterials.value && !workspace.value?.job?.personal_reference ? state.jobs.find(j => j.id === workspace.value?.job?.id && j.accepts_applications) : undefined)
const turnLocked = computed(() => locked.value || hasPendingMaterials.value)
async function showHistory() { historySearch.value = ''; historyOpen.value = true; try { await list() } catch (e) { if (alive) notifyError(e) } }
const catalog = ref<ModelCatalog | null>(null); const modelId = ref('')
watch(() => workspace.value?.model_id, id => { if (id) modelId.value = id })
const selectedModel = computed(() => workspace.value?.selected_model || catalog.value?.models.find(m => m.id === modelId.value))
const pending = ref(false); const loading = ref(false); const status = ref(''); const input = ref(''); const chatLog = ref<HTMLElement | null>(null)
const useMaterialAgent = ref(true)
const supportsMaterialAgent = computed(() => ['deepseek', 'deepseek-pro'].includes(modelId.value))
const cancelling = ref(false)
const liveReply = ref(''); const submittedText = ref('')
const jobComparisonActive = computed(() => ['queued', 'running'].includes(workspace.value?.job_assistance?.comparison?.status || ''))
const previewText = computed(() => liveReply.value || (workspace.value?.processing ? workspace.value.agent_run?.preview || '' : ''))
let progressTimer: ReturnType<typeof setInterval> | undefined
let readingProgress = false
async function readProgress() {
  const row = workspace.value
  if (!row || readingProgress || !((pending.value && useMaterialAgent.value && supportsMaterialAgent.value) || row.processing || jobComparisonActive.value)) return
  readingProgress = true
  try {
    const fresh = await api<Workspace>(`/ai/workspaces/${row.id}`)
    if (!alive || workspace.value?.id !== row.id || fresh.version < workspace.value.version) return
    const finished = !!workspace.value.processing && !fresh.processing
    workspace.value = fresh
    if (!fresh.processing) liveReply.value = ''
    if (finished && fresh.agent_run?.status === 'completed') {
      resultUpdated.value = true
      if (fresh.drafts.some(d => d.status === 'pending')) resultTab.value = 'draft'
      await scrollChat()
    }
  } catch { /* The active POST reports failures; polling never replays it. */ }
  finally { readingProgress = false }
}
async function cancelMaterialAgent() {
  const row = workspace.value; const run = row?.agent_run
  if (!row || !run || cancelling.value || run.status !== 'running') return
  cancelling.value = true
  try {
    const fresh = await api<Workspace>(`/ai/workspaces/${row.id}/cancel`, 'POST', { run_id: run.id })
    if (alive && workspace.value?.id === row.id) { workspace.value = fresh; liveReply.value = ''; status.value = '已停止，正在结束本次请求…' }
  } catch (e) { if (alive) notifyError(e) }
  finally { cancelling.value = false }
}
const tab = ref<'chat' | 'materials' | 'results'>('chat'); const resultTab = ref<'analysis' | 'draft'>('analysis')
const layoutPreferenceKey = `tongpin:ai-layout:${state.user?.id || 'local'}`
function savedLayout(): 'conversation' | 'workbench' {
  try { return localStorage.getItem(layoutPreferenceKey) === 'workbench' ? 'workbench' : 'conversation' } catch { return 'conversation' }
}
const layoutMode = ref(savedLayout())
const leftOpen = ref(layoutMode.value === 'workbench'); const rightOpen = ref(layoutMode.value === 'workbench'); const creating = ref(false)
const resultReading = ref(false); const resultUpdated = ref(false)
const composerInput = ref<HTMLTextAreaElement | null>(null)
const compactQuery = window.matchMedia('(max-width:1250px)')
const compactView = ref(compactQuery.matches)
const materialsVisible = computed(() => compactView.value ? tab.value === 'materials' : leftOpen.value)
const resultsVisible = computed(() => compactView.value ? tab.value === 'results' : rightOpen.value)
let previousPanels = { left: false, right: false, reading: false }
function applyLayout() {
  state.aiFocus = false
  tab.value = 'chat'; resultReading.value = false
  leftOpen.value = rightOpen.value = layoutMode.value === 'workbench'
  try { localStorage.setItem(layoutPreferenceKey, layoutMode.value) } catch { /* Layout remains usable without browser storage. */ }
  void resizeComposer()
}
function changeCompactView(event: MediaQueryListEvent) { compactView.value = event.matches; tab.value = 'chat'; resultReading.value = false }
function togglePanel(panel: 'materials' | 'results') {
  if (panel === 'results') resultUpdated.value = false
  resultReading.value = false
  if (compactView.value) { tab.value = tab.value === panel ? 'chat' : panel; return }
  if (panel === 'materials') { leftOpen.value = !leftOpen.value; rightOpen.value = false }
  else { rightOpen.value = !rightOpen.value; leftOpen.value = false }
}
function showConversation() { tab.value = 'chat'; leftOpen.value = rightOpen.value = layoutMode.value === 'workbench' && !state.aiFocus; resultReading.value = false }
function focusConversation() {
  if (!state.aiFocus) { previousPanels = { left: leftOpen.value, right: rightOpen.value, reading: resultReading.value }; state.aiFocus = true; showConversation() }
  else { state.aiFocus = false; leftOpen.value = previousPanels.left; rightOpen.value = previousPanels.right; resultReading.value = previousPanels.reading }
}
async function resizeComposer() {
  await nextTick()
  const el = composerInput.value
  if (!alive || !el) return
  el.style.height = 'auto'
  const mobile = window.matchMedia('(max-width:760px)').matches
  const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 24
  // Empty placeholder measurement can be inflated during a layout switch.
  // Keep an empty composer compact; long input scrolls within the height cap.
  const contentHeight = el.value ? el.scrollHeight : lineHeight * (mobile ? 2 : 1)
  const heightLimit = Math.max(56, Math.min(mobile ? 96 : 144, window.innerHeight * .2))
  el.style.height = Math.min(heightLimit, Math.max(28, contentHeight)) + 'px'
}
watch(input, resizeComposer)
watch(() => workspace.value?.id, resizeComposer)
watch([leftOpen, rightOpen, tab, () => state.aiFocus], resizeComposer)
const resumeId = ref(''); const jobId = ref(''); const pastedJD = ref(''); const pastedTitle = ref(''); const addition = ref(''); const confirmation = ref<'note' | 'draft' | 'delete' | null>(null); const noteMessage = ref<Message | null>(null)
const materialEditor = ref<{ kind: 'resume' | 'job'; title: string; text: string; originalTitle: string; originalText: string; sessionId: string; version: number; requestId: string } | null>(null)
const materialError = ref('')
const materialChanged = computed(() => !!materialEditor.value && (materialEditor.value.title.trim() !== materialEditor.value.originalTitle || materialEditor.value.text.trim() !== materialEditor.value.originalText.trim()))
function editMaterial(kind: 'resume' | 'job') {
  const current = workspace.value
  if (!current || locked.value || kind === 'job' && !current.job) return
  const materials = current.pending_materials || current
  const title = kind === 'resume' ? materials.resume.name : materials.job!.title
  const text = kind === 'resume' ? materials.resume.text : materials.job!.text
  materialError.value = ''
  materialEditor.value = { kind, title, text, originalTitle: title, originalText: text, sessionId: current.id, version: current.version, requestId: createRequestId() }
}
async function saveMaterial() {
  const editor = materialEditor.value
  if (!editor || locked.value || !materialChanged.value) return
  pending.value = true; state.error = ''; materialError.value = ''
  try {
    await api<Workspace>(`/ai/workspaces/${editor.sessionId}/materials/edit`, 'POST', { kind: editor.kind, title: editor.title, text: editor.text, expected_version: editor.version, request_id: editor.requestId })
    if (!alive) return
    workspace.value = await api<Workspace>(`/ai/workspaces/${editor.sessionId}`)
    if (!alive) return
    materialEditor.value = null; resultReading.value = false; tab.value = 'chat'
    state.success = '修改已保存。请选择开启新对话，或在当前对话中更新资料分析。'
    await Promise.all([list(), refresh()])
    await scrollChat()
  } catch (e) { if (alive) { notifyError(e); materialError.value = state.error } }
  finally { if (alive) pending.value = false }
}
async function resolveMaterials(choice: 'new' | 'update') {
  const row = workspace.value; const staged = row?.pending_materials
  if (!row || !staged || locked.value || choice === 'update' && !ready.value) return
  pending.value = true; status.value = '正在更新资料…'; state.error = ''
  let updated = false
  try {
    const result = await api<Workspace>(`/ai/workspaces/${row.id}/materials/resolve`, 'POST', { choice, pending_session_id: staged.session_id, expected_version: row.version })
    if (!alive || workspace.value?.id !== row.id) return
    workspace.value = result; resultTab.value = 'analysis'; resultUpdated.value = false; tab.value = 'chat'
    if (choice === 'new') {
      input.value = ''; await router.replace({ path: '/ai-workspace', query: { task: result.id } })
      state.success = '已用修改后的资料开启新对话，旧对话可在对话历史中查看。'
    } else { updated = true; state.success = '资料已更新，正在重新分析全部当前资料。' }
    await list(); await scrollChat()
  } catch (e) {
    if (alive) {
      notifyError(e)
      try { const fresh = await api<Workspace>(`/ai/workspaces/${row.id}`); if (alive && workspace.value?.id === row.id) workspace.value = fresh } catch { /* Retain the notice for retry. */ }
    }
  } finally { if (alive) { pending.value = false; status.value = '' } }
  if (updated && alive) await send('analyze')
}
let alive = true; let sequence = 0
const draft = computed(() => currentDraft(workspace.value?.drafts || []))
const draftEdits = ref<Record<number, string>>({})
const selectedEdits = ref<boolean[]>([])
watch(() => [workspace.value?.id, draft.value?.id], () => {
  draftEdits.value = Object.fromEntries((draft.value?.rewrites || []).map((r, i) => [i, r.after]))
  selectedEdits.value = (draft.value?.rewrites || []).map(() => true)
})
const selectedEditCount = computed(() => selectedEdits.value.filter(Boolean).length)
const ready = computed(() => !!selectedModel.value?.available)
const locked = computed(() => pending.value || loading.value || workspace.value?.processing)
const questions = computed(() => [...(workspace.value?.messages || [])].reverse().find(m => m.role === 'assistant' && (m.material_epoch || 0) === (workspace.value?.material_epoch || 0))?.questions || [])
const draftSource = (id: string) => sourceLabel(workspace.value?.sources || [], id)
const isSupplement = (id: string) => workspace.value?.sources.find(s => s.id === id)?.kind === 'supplement'
async function scrollChat() { await nextTick(); if (alive && chatLog.value) chatLog.value.scrollTop = chatLog.value.scrollHeight }
async function list() { const rows = await api<WorkspaceSummary[]>('/ai/workspaces'); if (alive) sessions.value = rows }
async function loadModels() { const result = await api<ModelCatalog>('/ai/models'); if (alive) { catalog.value = result; if (!modelId.value) modelId.value = result.default_model_id } }
async function changeModel() {
  const row = workspace.value
  if (!row || locked.value || row.model_id === modelId.value) return
  const previous = row.model_id; pending.value = true; status.value = '正在切换模型…'; state.error = ''
  try {
    const result = await api<Workspace>(`/ai/workspaces/${row.id}/model`, 'POST', { model_id: modelId.value, expected_version: row.version })
    if (!alive || workspace.value?.id !== row.id) return
    workspace.value = result
  } catch (e) {
    if (alive) { modelId.value = previous; notifyError(e) }
  } finally { if (alive) { pending.value = false; status.value = '' } }
}
async function open(id: string) {
  if (pending.value) return
  const ticket = ++sequence; loading.value = true
  try {
    const row = await api<Workspace>('/ai/workspaces/' + encodeURIComponent(id))
    if (!alive || ticket !== sequence) return
    workspace.value = row; input.value = ''; confirmation.value = null; historyOpen.value = false; tab.value = 'chat'; resultReading.value = false
    resultTab.value = draft.value?.status === 'pending' ? 'draft' : 'analysis'
    await router.replace({ path: '/ai-workspace', query: { task: id } })
  } catch (e) { if (alive && ticket === sequence) notifyError(e) }
  finally { if (alive && ticket === sequence) { loading.value = false; await scrollChat() } }
}
function newTask() {
  resumeId.value = workspace.value?.resume_id || state.resumeId || state.resumes[0]?.id || ''
  jobId.value = workspace.value?.job_id || ''; pastedJD.value = ''; pastedTitle.value = ''; creating.value = true
}
async function create() {
  pending.value = true
  try {
    const row = await api<Workspace>('/ai/workspaces', 'POST', { resume_id: resumeId.value, model_id: modelId.value || undefined, job_id: jobId.value === '__paste__' ? null : jobId.value || null, ...(jobId.value === '__paste__' ? { jd: pastedJD.value, title: pastedTitle.value } : {}) })
    if (!alive) return
    workspace.value = row; creating.value = false; await refresh(); input.value = ''; resultTab.value = 'analysis'; tab.value = 'chat'
    await list(); await router.replace({ path: '/ai-workspace', query: { task: row.id } })
  } catch (e) { if (alive) notifyError(e) } finally { if (alive) pending.value = false }
}
async function send(action: 'chat' | 'analyze' | 'draft') {
  const row = workspace.value
  if (!row || turnLocked.value || !ready.value || (action === 'chat' && !input.value.trim())) return
  const text = input.value; pending.value = true; liveReply.value = ''; submittedText.value = action === 'chat' ? text : ''; state.error = ''; status.value = action === 'draft' ? '正在整理修改草稿…' : action === 'analyze' ? '正在理解材料并核对引用…' : '正在结合当前材料思考…'
  void scrollChat()
  try {
    const useAgent = useMaterialAgent.value && supportsMaterialAgent.value
    const payload = { action, message: action === 'chat' ? text : '', expected_version: row.version, agent: useAgent }
    const result = useAgent ? await streamApi<Workspace>(`/ai/workspaces/${row.id}/turns/stream`, payload, (event, value) => {
      if (!alive || workspace.value?.id !== row.id) return
      if (event === 'preview') liveReply.value = String(value)
      if (event === 'reset') liveReply.value = ''
      if (event === 'progress') status.value = (value as { label: string }).label
      // Follow new output only if the reader is already close to the bottom.
      const el = chatLog.value
      if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 120) void scrollChat()
    }) : await api<Workspace>(`/ai/workspaces/${row.id}/turns`, 'POST', payload, 150000)
    if (!alive || workspace.value?.id !== row.id) return
    workspace.value = result; if (action === 'chat') input.value = ''; tab.value = 'chat'
    if (action === 'draft' || result.drafts.some(d => d.status === 'pending' && !row.drafts.some(old => old.id === d.id))) { resultTab.value = 'draft'; resultUpdated.value = true }
    else if (action === 'analyze' && result.analysis) { resultTab.value = 'analysis'; resultUpdated.value = true }
    await list(); await scrollChat()
  } catch (e) {
    if (alive) {
      if (e instanceof ApiError && e.code === 'AI_CANCELLED') { await readProgress(); return }
      notifyError(e)
      await readProgress()
      if (e instanceof ApiError && e.code === 'AI_JOB_UNAVAILABLE') { workspace.value = null; await list(); return }
      // On timeout/conflict, read the server's task rather than replaying a write.
      if (e instanceof ApiError && ['AI_VERSION_CONFLICT', 'AI_BUSY', ''].includes(e.code)) {
        try { const fresh = await api<Workspace>(`/ai/workspaces/${row.id}`); if (alive && workspace.value?.id === row.id) workspace.value = fresh } catch { /* Keep original input available for retry. */ }
      }
    }
  } finally { if (alive) { pending.value = false; status.value = ''; liveReply.value = ''; submittedText.value = '' } }
}
async function optimizeJob(id: string) {
  const row = workspace.value
  if (!row || turnLocked.value) return
  pending.value = true
  try {
    const next = await api<Workspace>('/ai/workspaces', 'POST', { resume_id: row.resume_id, job_id: id, model_id: modelId.value })
    if (!alive) return
    workspace.value = next; input.value = ''; resultTab.value = 'draft'; tab.value = 'chat'
    await router.replace({ path: '/ai-workspace', query: { task: next.id } }); await list()
  } catch (e) { notifyError(e); return }
  finally { if (alive) pending.value = false }
  await send('draft')
}
async function discussJobs() { input.value = '请读取这次岗位契合度分析结果，说明现有证据下的差异，不要求我补充缺失信息。'; await send('chat') }
async function exploreJobs() { input.value = '请根据我的简历查询相关岗位，选择最多六个岗位发起契合度分析。'; await send('chat') }
function showDraft() { resultTab.value = 'draft'; resultUpdated.value = false; resultReading.value = false; if (compactView.value) tab.value = 'results'; else { rightOpen.value = true; leftOpen.value = false } }
function prepareNote(message?: Message) { noteMessage.value = message || null; addition.value = message?.text || ''; confirmation.value = 'note' }
async function confirmNote() {
  const row = workspace.value; if (!row || !addition.value.trim()) return
  pending.value = true
  try {
    const path = noteMessage.value ? 'notes' : 'additions'
    const payload = noteMessage.value ? { message_id: noteMessage.value.id, expected_version: row.version } : { text: addition.value, expected_version: row.version }
    const result = await api<Workspace>(`/ai/workspaces/${row.id}/${path}`, 'POST', payload)
    if (!alive) return
    workspace.value = result; confirmation.value = null; resultTab.value = 'analysis'; state.success = '已保存为本人补充。点击“更新分析”重新核对材料。'; await scrollChat()
  } catch (e) { if (alive) notifyError(e) } finally { if (alive) pending.value = false }
}
async function confirmDraft() {
  const row = workspace.value; if (!row || !draft.value) return
  pending.value = true
  try {
    const indices = selectedEdits.value.flatMap((selected, index) => selected ? [index] : [])
    if (!indices.length) return
    const edits = draft.value.rewrites.flatMap((r, index) => selectedEdits.value[index] && draftEdits.value[index] !== undefined && draftEdits.value[index] !== r.after ? [{ index, after: draftEdits.value[index] }] : [])
    const result = await api<{ session: Workspace; resume: { id: string } }>(`/ai/workspaces/${row.id}/drafts/confirm`, 'POST', { draft_id: draft.value.id, expected_version: row.version, edits, indices, continue_in_workspace: true })
    if (!alive) return
    workspace.value = result.session; confirmation.value = null; await refresh(); state.resumeId = result.resume.id
    state.success = '已采纳所选修改并切换到优化版，原始简历保留。'
  } catch (e) { if (alive) notifyError(e) } finally { if (alive) pending.value = false }
}
async function continueDraft() { if (!draft.value?.saved_resume_id) return; resumeId.value = draft.value.saved_resume_id; jobId.value = workspace.value?.job_id || ''; await create() }
async function remove() {
  if (!workspace.value) return
  pending.value = true
  try { await api(`/ai/workspaces/${workspace.value.id}`, 'DELETE'); if (!alive) return; workspace.value = null; confirmation.value = null; await list(); await router.replace('/ai-workspace'); state.success = '任务已删除，简历和已保存的优化版本仍保留。' }
  catch (e) { if (alive) notifyError(e) } finally { if (alive) pending.value = false }
}
function keyboard(e: KeyboardEvent) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); void send('chat') } }
onMounted(async () => {
  progressTimer = setInterval(() => { void readProgress() }, 1200)
  compactQuery.addEventListener('change', changeCompactView)
  window.addEventListener('resize', resizeComposer)
  loading.value = true
  try { await Promise.all([list(),loadModels()]); const id = typeof route.query.task === 'string' ? route.query.task : route.query.resume || route.query.job ? undefined : sessions.value[0]?.id; if (id) await open(id); else { resumeId.value = typeof route.query.resume === 'string' && state.resumes.some(r => r.id === route.query.resume) ? route.query.resume : state.resumeId; jobId.value = typeof route.query.job === 'string' && state.jobs.some(j => j.id === route.query.job) ? route.query.job : ''; } }
  catch (e) { if (alive) notifyError(e) } finally { if (alive) loading.value = false }
})
onUnmounted(() => { alive = false; sequence++; clearInterval(progressTimer); state.aiFocus = false; compactQuery.removeEventListener('change', changeCompactView); window.removeEventListener('resize', resizeComposer) })
</script>

<template>
  <section class="ai-workspace">
    <header class="ai-heading ai-toolbar"><h1>{{ workspace ? 'AI 协作' : '把经历说清楚' }}</h1>
      <div class="ai-model-bar"><label class="sr-only" for="ai-model">AI 模型</label><select id="ai-model" v-model="modelId" :disabled="locked || !catalog" :title="selectedModel?.model" @change="changeModel"><option v-if="workspace && catalog && !catalog.models.some(m => m.id === modelId)" :value="modelId" disabled>{{ workspace.selected_model.label }}（已移除）</option><option v-for="model in catalog?.models || []" :key="model.id" :value="model.id" :disabled="!model.available">{{ model.label }}{{ model.available ? '' : '（未启用）' }}</option></select></div>
      <div class="ai-layout-choice"><label class="sr-only" for="ai-layout-mode">布局模式</label><select id="ai-layout-mode" v-model="layoutMode" @change="applyLayout" :title="compactView && layoutMode === 'workbench' ? '宽屏时材料、对话与结果并排；当前窗口使用分区查看' : '选择喜欢的布局，自动记住你的选择'"><option value="conversation">对话模式</option><option value="workbench">工作台模式</option></select></div>
      <nav v-if="layoutMode === 'conversation' || compactView || state.aiFocus" class="ai-panel-nav" aria-label="工作区视图"><button :aria-pressed="compactView ? tab === 'chat' : !leftOpen && !rightOpen" @click="showConversation"><MessageSquare :size="15" />对话</button><button :aria-pressed="materialsVisible" aria-controls="ai-workspace-materials" @click="togglePanel('materials')"><FileText :size="15" />材料与任务</button><button :aria-pressed="resultsVisible" aria-controls="ai-workspace-results" @click="togglePanel('results')"><ScanText :size="15" />结果与草稿<span v-if="resultUpdated || draft?.status === 'pending'" class="status-dot" /></button></nav>
      <span v-else class="ai-workbench-caption">材料 · 对话 · 结果</span>
      <div class="ai-heading-actions"><button class="secondary ai-history-toggle" :disabled="pending" aria-label="对话历史" @click="showHistory"><History :size="15" /><span>对话历史</span></button><button class="secondary ai-focus-toggle" :aria-pressed="state.aiFocus" @click="focusConversation"><component :is="state.aiFocus ? Minimize2 : Maximize2" :size="15" />{{ state.aiFocus ? '退出专注' : '专注对话' }}</button><button class="secondary" :disabled="locked" @click="newTask"><Plus :size="15" />新建任务</button></div>
    </header>
    <div v-if="historyOpen" class="modal-backdrop" @click.self="historyOpen = false">
      <section v-dialog class="modal ai-history-modal" role="dialog" aria-modal="true" aria-labelledby="ai-history-title">
        <header class="detail-heading"><h2 id="ai-history-title">对话历史</h2><button class="icon-button" aria-label="关闭对话历史" @click="historyOpen = false"><X :size="19" /></button></header>
        <p class="muted">仅显示你的对话，点击可查看完整记录并继续聊天。</p>
        <label class="ai-history-search"><span class="sr-only">搜索对话历史</span><Search :size="17" /><input v-model="historySearch" type="search" placeholder="搜索简历、岗位或最近话题" /></label>
        <div class="ai-history-list" tabindex="0" role="region" aria-label="历史对话列表">
          <p v-if="!filteredHistory.length" class="ai-small-note">{{ historySearch ? '没有找到匹配的对话。' : '还没有对话，从一份简历开始。' }}</p>
          <button v-for="s in filteredHistory" :key="s.id" :class="['ai-history-entry', { active: workspace?.id === s.id }]" :disabled="locked" @click="open(s.id)"><MessageSquare :size="18" /><span><strong>{{ s.title }}</strong><small>{{ s.preview }}</small><em>{{ new Date(s.updated_at || s.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }} · {{ s.message_count || 0 }} 条消息{{ workspace?.id === s.id ? ' · 当前对话' : '' }}</em></span><ArrowUpRight :size="15" /></button>
        </div>
      </section>
    </div>
    <div v-if="materialEditor" class="modal-backdrop" @click.self="!pending && (materialEditor = null)">
      <section v-dialog class="modal ai-material-modal" role="dialog" aria-modal="true" aria-labelledby="material-edit-title">
        <header class="detail-heading"><h2 id="material-edit-title">{{ materialEditor.kind === 'resume' ? '修改简历' : '修改目标岗位' }}</h2><button class="icon-button" :disabled="pending" aria-label="关闭材料修改" @click="materialEditor = null"><X :size="19" /></button></header>
        <form @submit.prevent="saveMaterial">
          <p class="muted">修改会影响此前的对话与分析，建议重新分析全部资料。保存后会留在当前对话，由你选择开启新对话或更新资料分析。原始材料保留。</p>
          <p v-if="materialError" class="feedback error" role="alert">{{ materialError }}</p>
          <label>{{ materialEditor.kind === 'resume' ? '简历名称' : '岗位名称' }}<input v-model="materialEditor.title" required :minlength="materialEditor.kind === 'resume' ? 1 : 2" :maxlength="materialEditor.kind === 'resume' ? 40 : 100" :disabled="pending" /></label>
          <label>{{ materialEditor.kind === 'resume' ? '简历内容' : '岗位描述' }}<textarea v-model="materialEditor.text" required minlength="20" :maxlength="materialEditor.kind === 'resume' ? 50000 : 30000" rows="12" :disabled="pending" /></label>
          <div class="form-footer"><button type="button" class="secondary" :disabled="pending" @click="materialEditor = null">取消</button><button class="primary" :disabled="pending || !materialChanged">{{ pending ? '正在保存…' : '保存修改' }}</button></div>
        </form>
      </section>
    </div>
    <div v-if="!ready && catalog" class="ai-availability" role="status"><Sparkles :size="17" /><p>{{ selectedModel?.unavailable_reason || '当前模型不可用，请选择已配置的模型。' }}可以先选择材料、保存经历补充。</p></div>
    <div :class="['ai-layout', { 'ai-left-closed': !leftOpen, 'ai-right-closed': !rightOpen, 'ai-results-reading': resultReading, 'ai-workbench': layoutMode === 'workbench' && !state.aiFocus }]">
      <aside id="ai-workspace-materials" :class="['ai-materials', { 'ai-mobile-visible': tab === 'materials' }]">
        <div class="ai-panel-heading"><h2>材料与任务</h2><button v-if="layoutMode === 'conversation' || state.aiFocus" class="icon-button ai-desktop-toggle" aria-label="收起材料面板" @click="leftOpen = false"><PanelLeftClose :size="17" /></button></div>
        <div class="ai-material-scroll" tabindex="0" role="region" aria-label="当前材料与历史任务">
          <template v-if="workspace"><p class="ai-section-caption">当前任务的材料<span v-if="hasPendingMaterials"> · 已修改，待更新分析</span></p><div class="ai-material-card"><FileText :size="18" /><div><strong>{{ displayResume?.name }}</strong><small>{{ hasPendingMaterials ? '修改后资料 · 待更新' : workspace.resume.revision_kind === 'user_edited_material' ? '手动修改版' : workspace.resume.revision ? '已保存的优化版' : '简历原文' }} · {{ displayResume?.text.length }} 字</small><div class="ai-material-edit-row"><InfoHint label="修改简历提示" text="修改会影响对话分析，建议重新分析全部资料。" /><button class="ai-material-edit" :disabled="locked" aria-label="修改简历材料" @click="editMaterial('resume')">修改</button></div></div></div><div v-if="displayJob" class="ai-material-card"><BriefcaseBusiness :size="18" /><div><strong>{{ displayJob?.title }}</strong><small>{{ hasPendingMaterials ? '修改后个人参照 · 待更新' : workspace.job?.personal_reference ? '个人参照 · 未发布' : '目标岗位' }}</small><div class="ai-material-edit-row"><InfoHint label="修改岗位提示" text="修改会影响对话分析，建议重新分析全部资料。" /><button class="ai-material-edit" :disabled="locked" aria-label="修改岗位材料" @click="editMaterial('job')">修改</button></div></div></div><p v-else class="ai-small-note">当前检查简历表达。新建任务可选择岗位，一起对照。</p><RouterLink v-if="applicationJob && workspace" :to="{ path: '/jobs', query: { job: applicationJob.id, resume: workspace.resume.id } }" class="text-link ai-apply-link">查看岗位并投递 <ArrowUpRight :size="14" /></RouterLink><details class="ai-source-preview"><summary>查看简历原文 <ChevronDown :size="14" /></summary><p>{{ displayResume?.text }}</p></details><details v-if="displayJob" class="ai-source-preview"><summary>查看岗位原文 <ChevronDown :size="14" /></summary><p>{{ displayJob?.text }}</p></details><p v-if="workspace.truncated" class="ai-small-note">材料较长，本轮仅分析部分段落。请拆分简历或岗位后继续，不能据此判断全文。</p>
          <div class="ai-note-heading"><p class="ai-section-caption">本人补充 <span>{{ workspace.notes.length }}</span></p><button class="text-link" :disabled="turnLocked" @click="prepareNote()"><Plus :size="14" />补充</button></div><p v-if="!workspace.notes.length" class="ai-small-note">把具体职责、过程和产出补充进来，帮助 AI 理解。补充内容单独保存。</p><article v-for="note in workspace.notes" :key="note.id" class="ai-self-note"><small>本人补充 · 未外部核验</small><p>{{ note.text }}</p></article></template>
          <template v-else><p class="ai-small-note">选定材料后，分析、对话和草稿会保存在同一个任务中。</p><RouterLink to="/resumes" class="text-link"><FileText :size="15" />我的简历</RouterLink></template>
          <div class="ai-history-heading"><button class="text-link" @click="showHistory"><History :size="14" />对话历史</button><span>{{ sessions.length }}</span></div><p v-if="!sessions.length" class="ai-small-note">还没有任务，从一份简历开始。</p><button v-for="s in sessions" :key="s.id" :class="['ai-history-item', { active: workspace?.id === s.id }]" :disabled="pending" @click="open(s.id)"><MessageSquare :size="15" /><span>{{ s.title }}<small>{{ new Date(s.updated_at || s.created_at).toLocaleDateString('zh-CN') }} · {{ s.message_count || 0 }} 条消息</small></span></button>
        </div>
        <div class="ai-material-footer"><RouterLink to="/resumes" class="text-link">导入 / 管理简历<ArrowUpRight :size="14" /></RouterLink></div>
      </aside>
      <section :class="['ai-chat', { 'ai-mobile-visible': tab === 'chat' }]" aria-label="材料协作对话">
        <header class="ai-chat-heading"><div><h2 :title="workspace ? workspace.resume.name + (workspace.job ? ' · ' + workspace.job.title : '') : ''">{{ workspace ? workspace.resume.name + (workspace.job ? ' · ' + workspace.job.title : '') : '从你的真实经历开始' }}</h2><p v-if="ready" class="ai-model-notice">仅你可见 · 分析使用当前材料和已确认补充，发送至 {{ selectedModel?.provider || '当前模型服务' }}{{ selectedModel?.external ? '，经中转服务处理' : '' }}。</p></div><button v-if="workspace?.messages.length" class="ai-latest-button" @click="scrollChat">回到最新</button><button v-if="workspace" class="icon-button ai-delete" :disabled="locked" aria-label="删除当前任务" @click="confirmation = 'delete'"><Trash2 :size="16" /></button></header>
        <div v-if="loading" class="ai-chat-empty" role="status"><LoaderCircle class="spin" :size="24" /><p>正在读取任务…</p></div>
        <div v-else-if="!workspace" class="ai-chat-empty ai-start-screen" tabindex="0" role="region" aria-label="选择协作材料"><span class="ai-start-mark"><Sparkles :size="27" /></span><h2>先理解，再完善。</h2><p>检查简历、对照岗位，或聊聊你想突出的经历。<br>所有修改都先形成草稿，由你决定是否保存。</p><form v-if="state.resumes.length" class="ai-start-form" @submit.prevent="create"><div class="ai-start-fields"><label>选择简历<select v-model="resumeId" required><option v-for="r in state.resumes" :key="r.id" :value="r.id">{{ r.display_name }}</option></select></label><label><span>目标岗位 <small>可选</small></span><select v-model="jobId"><option value="">先检查简历</option><option value="__paste__">粘贴目标岗位描述</option><option v-for="j in state.jobs" :key="j.id" :value="j.id">{{ j.title }}</option></select></label></div><template v-if="jobId === '__paste__'"><label>岗位名称<input v-model="pastedTitle" required minlength="2" maxlength="100" placeholder="例如：Python 后端开发"></label><label>岗位描述<textarea v-model="pastedJD" required minlength="20" maxlength="30000" rows="4" placeholder="粘贴职责和要求，仅作为你个人的投递参照。" /></label></template><button class="primary" :disabled="pending || !resumeId"><Plus :size="16" />创建协作任务</button></form><RouterLink v-else to="/resumes" class="button primary"><Plus :size="17" />先导入一份简历</RouterLink></div>
        <template v-else><div v-if="workspace.pending_materials" class="ai-material-change" role="status"><div><Info :size="17" /><strong>资料已修改，当前对话仍保留修改前的分析</strong></div><p>修改会影响此前的结论，建议重新分析全部资料。你希望如何继续？</p><div class="ai-material-change-actions"><button class="secondary" :disabled="locked" @click="resolveMaterials('new')">在新对话中聊天<ArrowUpRight :size="14" /></button><button class="primary" :disabled="locked || !ready" @click="resolveMaterials('update')">更新资料分析<Sparkles :size="14" /></button></div><small v-if="!ready">更新分析需要先选择可用模型；也可以先开启新对话。</small></div><div ref="chatLog" class="ai-chat-log" tabindex="0" role="log" aria-label="协作对话记录" aria-live="polite" aria-relevant="additions"><p v-if="workspace.material_epoch" class="ai-material-boundary">资料已更新。标记为“修改前资料”的旧消息仅用于回看，后续分析使用更新后的资料。</p><p v-if="workspace.last_error && !pending" class="ai-small-note" role="status">上次处理未完成：{{ workspace.last_error }}</p><div v-if="!workspace.messages.length" class="ai-conversation-start"><span class="ai-assistant-mark"><Sparkles :size="17" /></span><h3>材料已经准备好。</h3><p>可以先检查简历，也可以直接说说你想解决的问题。<br>比如：“我想投后端开发，帮我讲清楚这个项目里我做了什么。”</p><div class="ai-starters"><button :disabled="turnLocked || !ready" @click="send('analyze')">{{ workspace.job ? '对照这个岗位' : '检查我的简历' }}<ArrowUpRight :size="15" /></button><button :disabled="turnLocked" @click="prepareNote()">补充一段经历<Plus :size="15" /></button></div></div>
          <article v-for="m in workspace.messages" :key="m.id" :class="['ai-message', m.role]"><div class="ai-message-label"><span v-if="m.role === 'assistant'" class="ai-assistant-mark"><Sparkles :size="14" /></span><strong>{{ m.role === 'assistant' ? '同频助手' : '你' }}</strong><small v-if="m.role === 'assistant' && m.model">{{ m.model }}</small><span v-if="(m.material_epoch || 0) < (workspace.material_epoch || 0)" class="ai-old-material-label">修改前资料</span><small>{{ new Date(m.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</small></div><p>{{ m.text }}</p><button v-if="m.role === 'user' && m.action === 'chat'" class="ai-save-note" :disabled="turnLocked || noteSaved(workspace, m.id)" @click="prepareNote(m)"><Check v-if="noteSaved(workspace, m.id)" :size="13" />{{ noteSaved(workspace, m.id) ? '已作为本人补充保存' : '作为经历补充保存' }}</button></article>
          <article v-if="workspace.processing && (submittedText || workspace.agent_run?.request_text)" class="ai-message user ai-pending-user"><div class="ai-message-label"><strong>你</strong><small>本次任务</small></div><p>{{ submittedText || workspace.agent_run?.request_text }}</p></article>
          <article v-if="previewText" class="ai-message assistant ai-stream-message" aria-label="正在生成的回答"><div class="ai-message-label"><span class="ai-assistant-mark"><Sparkles :size="14" /></span><strong>同频助手</strong><small>生成中 · 等待校验</small></div><p>{{ previewText }}<span class="ai-stream-caret" aria-hidden="true" /></p></article>
          <WorkspaceJobResults v-if="workspace.job_assistance" :assistance="workspace.job_assistance" :locked="!!turnLocked" @optimize="optimizeJob" @discuss="discussJobs" />
          <div v-if="draft?.status === 'pending' && !workspace.processing" class="ai-draft-ready"><FileText :size="18" /><div><strong>修改建议已准备</strong><p>{{ draft.rewrites.length }} 段文字有优化建议，确认采纳前简历保持原样。</p></div><button class="secondary" type="button" @click="showDraft">查看修改前后<ArrowUpRight :size="14" /></button></div>
          <details v-if="questions.length" class="ai-question-list"><summary>继续讨论 · {{ questions.length }} 个建议问题</summary><div class="ai-question-chips" aria-label="可讨论的问题"><button v-for="q in questions" :key="q" :disabled="locked" @click="input = q">{{ q }}</button><small>可补充，也可以跳过。</small></div></details>
          <section v-if="workspace.agent_run" class="ai-agent-progress" aria-label="材料助手执行进度">
            <div><strong><Sparkles :size="14" />材料助手</strong><span role="status">{{ workspace.agent_run.label }}</span><button v-if="workspace.processing && workspace.agent_run.status === 'running'" type="button" :disabled="cancelling" @click="cancelMaterialAgent">{{ cancelling ? '正在停止…' : '停止' }}</button></div>
            <details v-if="workspace.agent_run.steps.length"><summary>查看执行步骤 · {{ workspace.agent_run.steps.filter(s => s.status === 'completed').length }} 项完成</summary><ol><li v-for="(step, i) in workspace.agent_run.steps" :key="i"><Check v-if="step.status === 'completed'" :size="13" /><LoaderCircle v-else-if="workspace.processing" :size="13" class="spin" /><span v-else>·</span>{{ step.label }}</li></ol></details>
            <small v-if="workspace.agent_run.status === 'failed' || workspace.agent_run.status === 'interrupted'">可以重新发送问题重试，已有材料与结果保留。</small>
          </section>
          <div v-if="pending" class="ai-thinking" role="status"><LoaderCircle :size="17" class="spin" /><p>{{ workspace.agent_run?.status === 'running' ? workspace.agent_run.label : status || '正在保存…' }}</p></div><p v-else-if="workspace.processing" class="ai-small-note">正在读取服务器进度，完成后会自动显示结果。</p>
        </div><div class="ai-chat-bottom"><form class="ai-composer" @submit.prevent="send('chat')"><label class="sr-only" for="ai-message">告诉 AI 想解决的问题</label><textarea id="ai-message" ref="composerInput" v-model="input" rows="1" maxlength="4000" :disabled="turnLocked" :placeholder="hasPendingMaterials ? '请先选择如何使用修改后的资料…' : compactView ? '说说你想解决的问题，或想突出的经历…' : '说说你想投的方向，或补充具体负责的任务、过程和产出…'" @keydown="keyboard" /><div class="ai-composer-footer"><small>对话不会自动写入简历 · Ctrl / ⌘ + Enter 发送</small><button class="ai-send" :disabled="turnLocked || !ready || !input.trim()" aria-label="发送消息"><ArrowUp :size="19" /></button></div></form><div class="ai-task-actions"><label class="ai-agent-choice" :title="supportsMaterialAgent ? '读取材料、查询岗位、发起契合度分析并优化简历，采纳修改前需确认' : '材料助手支持 DeepSeek 官方模型'"><input v-model="useMaterialAgent" type="checkbox" :disabled="turnLocked || !supportsMaterialAgent" />材料助手<small v-if="!supportsMaterialAgent">需 DeepSeek</small></label><button :disabled="turnLocked || !ready" @click="send('analyze')"><Sparkles :size="14" />{{ workspace.notes.length || workspace.analysis ? '更新分析' : '分析材料' }}</button><button :disabled="turnLocked || !ready" @click="send('draft')"><FileText :size="14" />生成优化草稿</button><button v-if="supportsMaterialAgent && useMaterialAgent" :disabled="turnLocked || !ready" @click="exploreJobs"><Search :size="14" />找岗位并对照</button></div></div></template>
      </section>
      <aside id="ai-workspace-results" :class="['ai-results', { 'ai-mobile-visible': tab === 'results' }]">
        <div class="ai-panel-heading"><h2>一起核对结果</h2><div class="ai-result-controls"><button class="ai-reading-toggle ai-desktop-toggle" @click="resultReading = !resultReading"><component :is="resultReading ? Minimize2 : Maximize2" :size="14" />{{ resultReading ? '恢复并排' : '展开阅读' }}</button><button v-if="layoutMode === 'conversation' || state.aiFocus || resultReading" class="icon-button ai-desktop-toggle" aria-label="收起结果面板" @click="showConversation"><PanelRightClose :size="17" /></button></div></div><div class="ai-result-tabs"><button :class="{ active: resultTab === 'analysis' }" @click="resultTab = 'analysis'">分析与依据</button><button :class="{ active: resultTab === 'draft' }" @click="resultTab = 'draft'">修改草稿<span v-if="draft?.status === 'pending'" class="status-dot" /></button></div>
        <div class="ai-result-scroll" tabindex="0" role="region" aria-label="分析结果与修改草稿"><p v-if="hasPendingMaterials" class="ai-material-boundary">以下分析与草稿仍基于修改前的资料，请在对话区选择更新资料分析。</p><template v-if="resultTab === 'analysis'"><template v-if="workspace?.analysis"><p v-if="workspace.analysis.model" class="ai-result-model">生成模型：{{ workspace.analysis.model_label || workspace.analysis.model }} · {{ workspace.analysis.model }}</p><p class="ai-small-note">{{ workspace.job ? '围绕所选岗位逐项理解材料。' : '围绕简历表达和信息完整性。' }}描述不足不代表能力不足。</p><p v-if="workspace.analysis.partial" class="ai-small-note">本次仅覆盖材料的部分段落。</p><article v-for="(finding, i) in workspace.analysis.findings" :key="i" class="ai-finding"><div><h3>{{ finding.topic }}</h3><span :class="['ai-evidence-status', finding.status]">{{ findingLabel(finding.status) }}</span></div><p>{{ finding.observation }}</p><blockquote v-for="(c, index) in finding.citations" :key="index"><small>{{ sourceLabel(workspace.analysis.sources, c.source_id) }}</small>{{ c.quote }}</blockquote><div class="ai-next-step"><small>下一步</small><p>{{ finding.advice }}</p></div></article></template><div v-else class="ai-result-empty"><ScanText :size="29" /><h3>结论旁边，就是依据。</h3><p>分析后，这里会列出材料已有支持的内容、尚需了解的部分和可以采取的下一步。</p><p v-if="workspace?.notes.length">你已补充材料，点击“更新分析”生成新的结果。</p><button v-if="workspace" class="secondary" :disabled="turnLocked || !ready" @click="send('analyze')">{{ workspace.notes.length ? '更新分析' : '分析材料' }}</button></div></template>
        <template v-else><template v-if="draft"><p v-if="draft.model" class="ai-result-model">草稿模型：{{ draft.model_label || draft.model }} · {{ draft.model }}</p><p class="ai-small-note">核对高亮的文字变化，勾选想采纳的段落，也可以手动调整。确认后更新当前使用版本，原件保留。</p><article v-for="(edit, i) in draft.rewrites" :key="i" class="ai-draft-edit"><small>{{ draftSource(edit.source_id) }}</small><h3>表达建议</h3><ResumeDraftEdit :before="edit.before" :model-value="draftEdits[i] ?? edit.after" :selected="!!selectedEdits[i]" :index="i" :pending="draft.status === 'pending'" :disabled="!!locked" :supplement="!!isSupplement(edit.source_id)" @update:model-value="draftEdits[i] = $event" @update:selected="selectedEdits[i] = $event" /><p class="ai-edit-reason">{{ edit.reason }}</p><details v-if="edit.citations?.length" class="ai-draft-basis"><summary>核对修改依据</summary><blockquote v-for="(c, n) in edit.citations" :key="n"><small>{{ draftSource(c.source_id) }}</small><p>{{ c.quote }}</p></blockquote></details></article><p v-if="draft.status === 'saved'" class="ai-saved-label"><Check :size="16" />优化版已保存，原件保留</p><button v-if="draft.status === 'pending'" class="primary full" :disabled="turnLocked || !selectedEditCount" @click="confirmation = 'draft'">确认并保存为新版本 · {{ selectedEditCount }} 段</button><button v-if="draft.status === 'saved'" class="secondary full" :disabled="turnLocked" @click="continueDraft">以新版本继续<ArrowUpRight :size="15" /></button></template><div v-else class="ai-result-empty"><FileText :size="29" /><h3>每个修改，都由你决定。</h3><p>优化草稿会保留前后对照。AI 可以帮你改善表达，真实的职责与产出需要你确认。</p><button v-if="workspace" class="secondary" :disabled="turnLocked || !ready" @click="send('draft')">生成优化草稿</button></div></template></div>
        <p class="ai-results-footer">材料用于当前任务。建议供参考，不作录用决定。</p>
      </aside>
    </div>
    <div v-if="creating || confirmation" class="modal-backdrop" @click.self="!pending && (creating = false, confirmation = null)"><section v-dialog class="modal ai-modal" role="dialog" aria-modal="true" aria-labelledby="ai-dialog-title"><header class="detail-heading"><h2 id="ai-dialog-title">{{ creating ? '新建协作任务' : confirmation === 'note' ? '确认经历补充' : confirmation === 'draft' ? '保存优化版简历' : '删除这个任务？' }}</h2><button class="icon-button" :disabled="pending" aria-label="关闭确认窗口" @click="creating = false; confirmation = null"><X :size="19" /></button></header><form v-if="creating" @submit.prevent="create"><label>选择简历<select v-model="resumeId" required><option value="" disabled>请先选择简历</option><option v-for="r in state.resumes" :key="r.id" :value="r.id">{{ r.display_name }}</option></select></label><label>目标岗位（可选）<select v-model="jobId"><option value="">先检查简历</option><option value="__paste__">粘贴目标岗位描述</option><option v-for="j in state.jobs" :key="j.id" :value="j.id">{{ j.title }}</option></select></label><template v-if="jobId === '__paste__'"><label>岗位名称<input v-model="pastedTitle" required minlength="2" maxlength="100" placeholder="例如：Python 后端开发"></label><label>岗位描述<textarea v-model="pastedJD" required minlength="20" maxlength="30000" rows="5" placeholder="粘贴职责和要求，仅作为你个人的投递参照。" /></label></template><p class="muted">每个任务使用一组固定材料，便于回看分析与修改过程。</p><RouterLink v-if="!state.resumes.length" to="/resumes" class="text-link">先去导入简历 →</RouterLink><div class="form-footer"><button class="primary" :disabled="pending || !resumeId">创建任务</button></div></form><form v-else-if="confirmation === 'note'" @submit.prevent="confirmNote"><p class="muted">仅保存你本人提供的经历，作为“本人补充”单独使用。请检查内容确实是事实描述，不包含密码、联系方式或指令。</p><label>补充内容<textarea v-model="addition" :readonly="!!noteMessage" required maxlength="4000" rows="7" /></label><p class="muted">保存后需重新分析。原始简历不会改变。</p><div class="form-footer"><button class="primary" :disabled="pending || !addition.trim()">确认保存补充</button></div></form><div v-else-if="confirmation === 'draft'"><p class="muted">将采纳所选的 {{ selectedEditCount }} 段修改，并切换到这份优化版继续协作。未勾选的段落保持原样；原始简历保留，不影响已经投递的材料。</p><div class="form-footer"><button class="secondary" :disabled="pending" @click="confirmation = null">返回核对</button><button class="primary" :disabled="pending || !selectedEditCount" @click="confirmDraft">确认采纳并使用优化版</button></div></div><div v-else><p class="muted">本任务的对话、补充和分析将删除。原简历和已保存的优化版不会删除。</p><div class="form-footer"><button class="danger" :disabled="pending" @click="remove">删除任务</button></div></div></section></div>
  </section>
</template>

<style scoped>
.ai-apply-link{display:flex;align-items:center;gap:6px;font-size:12px;margin:10px 0 18px}
</style>
