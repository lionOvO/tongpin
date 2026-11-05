<script setup lang="ts">
import { createRequestId } from '../request-id'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { ArrowUp, LoaderCircle, Sparkles, RefreshCw, SlidersHorizontal, X, History, Plus, Download, Trash2, Copy } from '@lucide/vue'
import { api, streamApi, ApiError } from '../store'
import type { ApplicationDetail } from '../hiring'
import { recruiterSourceLabel, recruiterExport, saveRecruiterText, type RecruiterAction, type RecruiterConversation, type RecruiterPlanQuestion } from '../recruiter-assistant'
const props = defineProps<{ application: ApplicationDetail; toolbarTarget?: HTMLElement | null }>()
const emit = defineEmits<{ busy: [value: boolean]; unavailable: []; history: [count: number]; change: [value: RecruiterConversation]; results: []; review: [] }>()
const conversation = ref<RecruiterConversation | null>(null)
const contextOpen = ref(false); const contextToggle = ref<HTMLButtonElement | null>(null)
const historyOpen = ref(false); const historySearch = ref(''); const confirmation = ref<'new'|'delete'|null>(null)
const input = ref(''); const context = ref(''); const loading = ref(true); const pending = ref(false); const error = ref(''); const success = ref('')
const copied = ref(''); const log = ref<HTMLElement | null>(null)
const useAgent = ref(true); const liveReply = ref(''); const submittedText = ref(''); const submittedRequest = ref(''); const runLabel = ref(''); const cancelling = ref(false)
const preview = computed(() => liveReply.value || (conversation.value?.processing ? conversation.value.agent_run?.preview || '' : ''))
const locked = computed(() => loading.value || pending.value || !!conversation.value?.processing)
const readOnly = computed(() => !!conversation.value?.archived)
const ready = computed(() => !!conversation.value?.model.available && !readOnly.value)
const contextDirty = computed(() => context.value !== (conversation.value?.business_context || ''))
const sessions = computed(() => (conversation.value?.sessions || []).filter(s => s.title.toLowerCase().includes(historySearch.value.trim().toLowerCase())))
let alive = true; let sequence = 0; let timer: ReturnType<typeof setInterval> | undefined
let submission: { fingerprint: string; request_id: string } | null = null
let mutation: { fingerprint: string; request_id: string } | null = null
function closeContext() { contextOpen.value = false; contextToggle.value?.focus?.() }
async function scroll() { await nextTick(); if (alive && log.value) log.value.scrollTop = log.value.scrollHeight }
function accept(current: RecruiterConversation, resetContext = false) {
  const dirty = contextDirty.value; const different = current.session_id !== conversation.value?.session_id
  conversation.value = current
  if (resetContext || different || !dirty) context.value = current.business_context
  emit('history', current.sessions.reduce((n, s) => n + s.message_count, 0)); emit('change', current)
}
function fail(e: unknown) {
  if (e instanceof ApiError && ['STALE_CONTEXT', 'AUTH_REQUIRED'].includes(e.code)) return
  error.value = e instanceof Error ? e.message : '招聘 AI 暂时无法连接，请稍后重试。'
  if (e instanceof ApiError && [401, 403, 404].includes(e.status) && e.code !== 'AI_SESSION_NOT_FOUND') { conversation.value = null; emit('unavailable') }
}
async function load(initial = false, sessionId?: string) {
  const ticket = ++sequence
  const id = sessionId ?? (conversation.value?.archived ? conversation.value.session_id : '')
  try {
    const current = await api<RecruiterConversation>(`/applications/${props.application.id}/recruiter-assistant${id ? '?session_id=' + encodeURIComponent(id) : ''}`, 'GET', undefined, 15000)
    if (!alive || ticket !== sequence) return
    const changed = current.version !== conversation.value?.version || current.session_id !== conversation.value?.session_id
    accept(current, initial)
    if (!current.processing) liveReply.value = ''
    if (initial && current.processing && current.agent_run?.request_text && !input.value) input.value = current.agent_run.request_text
    if (changed) { error.value = ''; await scroll() }
  } catch (e) { if (alive && ticket === sequence) fail(e) }
  finally { if (alive && ticket === sequence) loading.value = false }
}
async function selectSession(id: string) { if (locked.value) return; loading.value = true; await load(true, id); historyOpen.value = false }
async function update(action: 'context'|'plan'|'new'|'delete', extra: object = {}) {
  if (locked.value || !conversation.value || readOnly.value && !['new','delete'].includes(action)) return false
  const data = { action, ...extra }; const fingerprint = JSON.stringify(data)
  if (mutation?.fingerprint !== fingerprint) mutation = { fingerprint, request_id: createRequestId() }
  pending.value = true; emit('busy', true); error.value = ''; success.value = ''; sequence++
  try {
    const result = await api<RecruiterConversation>(`/applications/${props.application.id}/recruiter-assistant/workspace`, 'POST', { ...data, expected_version: conversation.value.version, request_id: mutation!.request_id }, 20000)
    if (!alive) return false
    accept(result, action !== 'plan'); mutation = null; confirmation.value = null
    success.value = action === 'context' ? '业务背景已保存' : action === 'plan' ? '面试提纲已保存' : action === 'new' ? '已开始新对话，原记录可在历史中查看' : '所选对话已删除'
    if (['new','delete'].includes(action)) { input.value = ''; contextOpen.value = false; await scroll() }
    return true
  } catch (e) { if (alive) { fail(e); await load() }; return false }
  finally { if (alive) { pending.value = false; emit('busy', false) } }
}
async function savePlan(questions: RecruiterPlanQuestion[], notes: string) { return update('plan', { questions: questions.map(q => ({ message_id: q.message_id, question: q.question })), notes }) }
async function send(action: RecruiterAction) {
  if (locked.value || !ready.value || !conversation.value || action === 'chat' && !input.value.trim()) return
  const message = action === 'chat' ? input.value.trim() : ''
  const fingerprint = JSON.stringify([action, message, context.value, useAgent.value])
  if (submission?.fingerprint !== fingerprint) submission = { fingerprint, request_id: createRequestId() }
  const body = { action, message, business_context: context.value, expected_version: conversation.value.version, request_id: submission!.request_id, agent: useAgent.value }
  const previousVersion = conversation.value.version
  pending.value = true; emit('busy', true); error.value = ''; success.value = ''; sequence++
  liveReply.value = ''; submittedText.value = message; submittedRequest.value = body.request_id; runLabel.value = '准备当前投递材料'
  try {
    const path = `/applications/${props.application.id}/recruiter-assistant/turns`
    const result = useAgent.value ? await streamApi<RecruiterConversation>(path + '/stream', body, (event, value) => {
      if (!alive) return
      if (event === 'preview') liveReply.value = String(value)
      if (event === 'reset') liveReply.value = ''
      if (event === 'progress') runLabel.value = (value as { label: string }).label
      const el = log.value
      if (el && el.scrollHeight-el.scrollTop-el.clientHeight < 120) void scroll()
    }) : await api<RecruiterConversation>(path, 'POST', body, 225000)
    if (!alive) return
    accept(result, true); if (action === 'chat') input.value = ''; submission = null; emit('results'); await scroll()
  } catch (e) {
    if (alive) {
      if (!(e instanceof ApiError && e.code === 'AI_CANCELLED')) fail(e)
      // Reconcile a lost response without submitting another paid generation.
      try {
        const result = await api<RecruiterConversation>(`/applications/${props.application.id}/recruiter-assistant`, 'GET', undefined, 15000)
        if (alive) {
          accept(result)
          if (result.version > previousVersion && result.messages.some(m => m.id === body.request_id)) { error.value = ''; if (action === 'chat') input.value = ''; submission = null; emit('results'); await scroll() }
        }
      } catch (readError) { if (alive) fail(readError) }
    }
  } finally { if (alive) { pending.value = false; liveReply.value = ''; submittedText.value = ''; runLabel.value = ''; emit('busy', false) } }
}
async function stop() {
  const run = conversation.value?.agent_run
  if (!run || run.status !== 'running' || cancelling.value) return
  cancelling.value = true
  try {
    const result = await api<RecruiterConversation>(`/applications/${props.application.id}/recruiter-assistant/cancel`, 'POST', { run_id: run.id })
    if (!alive) return
    accept(result); liveReply.value = ''; success.value = '已停止，已有对话与面试提纲保留'
  } catch (e) { if (alive) fail(e) }
  finally { if (alive) cancelling.value = false }
}
function exportConversation() { if (conversation.value) saveRecruiterText(recruiterExport(conversation.value, props.application.candidate_name, props.application.job_title, 'conversation'), props.application.candidate_name + '-招聘AI对话') }
async function copyAnswer(id: string, text: string) { try { await navigator.clipboard.writeText(text); copied.value = id } catch { error.value = '复制未完成，可使用导出对话保存内容。' } }
let readingProgress = false; let lastIdleRead = 0
async function poll() {
  if (readingProgress || document.visibilityState !== 'visible' || loading.value || historyOpen.value || confirmation.value) return
  if (pending.value && !useAgent.value) return
  if (!pending.value && !conversation.value?.processing) { if (Date.now()-lastIdleRead < 15000) return; lastIdleRead = Date.now() }
  readingProgress = true
  try { await load() } finally { readingProgress = false }
}
defineExpose({ send, savePlan, openContext: () => { contextOpen.value = true }, openHistory: () => { historyOpen.value = true }, newConversation: () => { confirmation.value = 'new' } })
onMounted(() => { void load(true); timer = setInterval(poll, 1500); document.addEventListener('visibilitychange', poll) })
onUnmounted(() => { alive = false; sequence++; clearInterval(timer); document.removeEventListener('visibilitychange', poll); emit('busy', false) })
</script>
<template>
  <section class="recruiter-chat" aria-label="招聘 AI 对话">
    <Teleport :to="toolbarTarget || 'body'" :disabled="!toolbarTarget">
    <div class="recruiter-chat-tools"><span title="依据本次授权材料提供招聘参考，发送至 DeepSeek 官方。"><Sparkles :size="14" />{{ conversation?.model.label || 'DeepSeek' }}<small>官方 · 仅你可见</small></span><div class="recruiter-chat-options"><button ref="contextToggle" class="text-link recruiter-header-action" type="button" :aria-expanded="contextOpen" aria-controls="recruiter-business-context" @click="contextOpen = !contextOpen"><SlidersHorizontal :size="13" />{{ context.trim() ? '业务背景已补充' : '补充业务背景' }}</button><button class="text-link recruiter-header-action" aria-label="刷新对话" title="刷新对话" :disabled="locked" @click="load()"><RefreshCw :size="13" /><span>刷新对话</span></button><button class="text-link recruiter-header-action" :disabled="locked" @click="historyOpen = true"><History :size="13" />对话历史</button><button class="text-link recruiter-header-action" :disabled="locked" @click="confirmation = 'new'"><Plus :size="13" />新对话</button></div></div>
    </Teleport>
    <section v-if="contextOpen" id="recruiter-business-context" class="recruiter-context" aria-label="补充企业业务背景" @keydown.esc="closeContext"><header><label for="recruiter-business-input">希望这位同事参与什么工作？</label><button type="button" class="icon-button" aria-label="收起业务背景" @click="closeContext"><X :size="14" /></button></header><textarea id="recruiter-business-input" v-model="context" :disabled="locked || readOnly" maxlength="2000" rows="2" placeholder="例如：维护订单接口，排查查询性能问题。" /><footer><small>{{ readOnly ? '历史对话的业务背景，仅供查看' : contextDirty ? '有未保存的修改；发送对话时也会保存' : '独立保存，仅作为企业需求使用' }}</small><button class="secondary" :disabled="locked || readOnly || !contextDirty" @click="update('context', { business_context: context })">保存业务背景</button></footer></section>
    <div v-if="success" class="recruiter-chat-success" role="status">{{ success }}</div><div v-if="readOnly" class="recruiter-chat-archive">正在查看历史对话 · 内容仅供阅读<button class="text-link" :disabled="locked" @click="selectSession('')">返回当前对话</button></div><div v-if="error" class="recruiter-chat-error" role="alert">{{ error }}</div>
    <p v-if="loading" role="status" class="recruiter-chat-status">正在读取历史对话…</p>
    <p v-else-if="!conversation?.model.available && conversation" class="recruiter-chat-error">{{ conversation.model.unavailable_reason }}。已保存的对话和授权材料仍可查看。</p>
    <div ref="log" class="recruiter-chat-log" role="log" aria-label="当前投递的 AI 历史对话" aria-live="polite" :aria-busy="pending || conversation?.processing">
      <div v-if="!loading && !pending && !conversation?.processing && !conversation?.messages.length" class="recruiter-chat-start"><Sparkles :size="26" /><h3>从具体经历开始了解。</h3><p>选择下方的整理任务，或直接提问。助手会读取本次投递、定位相关经历，帮你准备有依据的面试提纲。</p></div>
      <article v-for="m in conversation?.messages || []" :key="m.id" :class="['recruiter-chat-message', m.role]"><header><strong>{{ m.role === 'user' ? '你' : '同频招聘助手' }}</strong><span><template v-if="m.role === 'assistant'">{{ m.model_label }} · </template>{{ new Date(m.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</span></header><p>{{ m.text }}</p><button v-if="m.role === 'assistant'" class="text-link recruiter-copy" @click="copyAnswer(m.id, m.text)"><Copy :size="12" />{{ copied === m.id ? '已复制' : '复制回答' }}</button><p v-if="m.partial" class="recruiter-chat-source-note">材料较长，本轮仅覆盖简历前 30000 字及岗位前 12000 字。</p><details v-if="m.citations?.length" class="recruiter-chat-citations"><summary>查看原文依据 · {{ m.citations.length }} 处</summary><blockquote v-for="(c,i) in m.citations" :key="i"><small>{{ recruiterSourceLabel[c.source] }}</small>{{ c.quote }}</blockquote></details><details v-if="m.questions?.length" class="recruiter-followups"><summary>可以继续了解 · {{ m.questions.length }} 个问题</summary><div><button v-for="q in m.questions" :key="q" type="button" :disabled="locked || readOnly" @click="input = q">{{ q }}</button></div></details></article>
      <article v-if="submittedText && !conversation?.messages.some(m => m.id === submittedRequest)" class="recruiter-chat-message user recruiter-pending-message"><header><strong>你</strong><span>本次提问</span></header><p>{{ submittedText }}</p></article>
      <article v-if="preview" class="recruiter-chat-message assistant recruiter-stream-preview"><header><strong>同频招聘助手</strong><span>正在生成 · 核对依据后保存</span></header><p>{{ preview }}<span class="recruiter-stream-caret" aria-hidden="true" /></p></article>
      <section v-if="!readOnly && conversation?.agent_run" class="recruiter-agent-progress" aria-label="招聘助手执行进度">
        <header><span><Sparkles :size="14" /><strong>招聘材料助手</strong></span><button v-if="conversation.processing && conversation.agent_run.status === 'running'" type="button" class="secondary" :disabled="cancelling" @click="stop">{{ cancelling ? '正在停止…' : '停止' }}</button></header>
        <p role="status">{{ runLabel || conversation.agent_run.label }}</p>
        <details v-if="conversation.agent_run.steps.length"><summary>查看执行步骤 · {{ conversation.agent_run.steps.length }} 项</summary><ol><li v-for="(step, i) in conversation.agent_run.steps" :key="i"><span>{{ step.label }}</span><small>{{ step.status === 'completed' ? '已完成' : conversation.agent_run.status === 'running' ? '处理中' : '未完成' }}</small></li></ol></details>
        <button v-if="!conversation.processing && conversation.agent_run.status === 'completed' && conversation.messages.at(-1)?.questions?.length" type="button" class="secondary" @click="emit('review')">查看建议并整理提纲</button>
      </section>
      <p v-if="(pending || conversation?.processing) && !preview" class="recruiter-chat-status" role="status"><LoaderCircle :size="16" class="spin" />{{ runLabel || conversation?.agent_run?.label || '正在结合简历、岗位和原文依据整理回答…' }}</p>
    </div>
    <form class="recruiter-composer" @submit.prevent="send('chat')">
      <div class="recruiter-shortcuts" aria-label="招聘 AI 快捷任务"><button type="button" :disabled="locked || !ready" @click="send('summary')">整理简历精华</button><button type="button" :disabled="locked || !ready" @click="send('business')">技术与业务关联</button><button type="button" :disabled="locked || !ready" @click="send('interview')">准备面试追问</button></div>
      <div class="recruiter-input-area"><label class="sr-only" for="recruiter-question">向招聘 AI 提问</label><textarea id="recruiter-question" v-model="input" :disabled="locked || !ready" maxlength="4000" rows="2" placeholder="了解项目职责、技术细节，或准备面试追问…" @keydown.ctrl.enter.prevent="send('chat')" @keydown.meta.enter.prevent="send('chat')" /><footer><span><label class="recruiter-agent-choice"><input v-model="useAgent" type="checkbox" :disabled="locked || readOnly">材料助手</label>{{ readOnly ? '历史对话仅供阅读，返回当前对话后继续' : '仅提供建议，由你决定如何推进' }}<span class="recruiter-send-key">Ctrl / ⌘ + Enter 发送</span></span><button type="submit" class="primary" :disabled="locked || !ready || !input.trim()"><LoaderCircle v-if="pending" :size="17" class="spin" /><ArrowUp v-else :size="17" />发送</button></footer></div></form>
    <Teleport to="body">
      <div v-if="historyOpen" class="modal-backdrop" @click.self="historyOpen = false" @keydown.esc="historyOpen = false">
        <section v-dialog class="modal recruiter-history-modal" role="dialog" aria-modal="true" aria-labelledby="recruiter-history-title">
          <header><div><h2 id="recruiter-history-title">这份投递的对话历史</h2><p>对话与提纲分别保存，历史记录仅供阅读。</p></div><button class="icon-button" aria-label="关闭对话历史" @click="historyOpen = false"><X :size="18" /></button></header>
          <label><span class="sr-only">搜索对话历史</span><input v-model="historySearch" type="search" placeholder="搜索对话标题" /></label>
          <div class="recruiter-session-list"><button v-for="s in sessions" :key="s.id" :disabled="locked" :aria-pressed="conversation?.session_id === s.id" @click="selectSession(s.current ? '' : s.id)"><strong>{{ s.title }}</strong><small>{{ s.current ? '当前对话 · ' : '历史对话 · ' }}{{ s.message_count }} 条 · {{ new Date(s.updated_at).toLocaleString('zh-CN') }}</small></button><p v-if="!sessions.length">没有找到相应对话。</p></div>
          <footer><button class="secondary" :disabled="!conversation?.messages.length" @click="exportConversation"><Download :size="14" />导出所选对话</button><button class="danger" :disabled="locked" @click="historyOpen = false; confirmation = 'delete'"><Trash2 :size="14" />删除所选对话</button></footer>
        </section>
      </div>
      <div v-if="confirmation" class="modal-backdrop" @click.self="!pending && (confirmation = null)" @keydown.esc="!pending && (confirmation = null)">
        <section v-dialog class="modal recruiter-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="recruiter-confirm-title"><h2 id="recruiter-confirm-title">{{ confirmation === 'new' ? '开始新的对话？' : '删除所选对话？' }}</h2><p>{{ confirmation === 'new' ? '当前对话、业务背景和已保存的面试提纲会归入历史。新对话从这份授权材料重新开始。' : '将删除所选对话及其中保存的提纲和备注。求职者的简历、投递与双方沟通记录会保留。' }}</p><footer><button class="secondary" :disabled="pending" @click="confirmation = null">取消</button><button :class="confirmation === 'new' ? 'primary' : 'danger'" :disabled="locked" @click="update(confirmation, confirmation === 'delete' ? { session_id: conversation?.session_id } : {})">{{ pending ? '正在处理…' : confirmation === 'new' ? '保存并新建' : '确认删除对话' }}</button></footer></section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.recruiter-agent-progress{padding:13px 15px;margin:18px 0 24px;border:1px solid var(--border-soft);border-left:3px solid var(--success);border-radius:9px;background:var(--brand-faint);font-size:12px;color:var(--text-main)}
.recruiter-agent-progress header,.recruiter-agent-progress header>span{display:flex;align-items:center;gap:7px}.recruiter-agent-progress header{justify-content:space-between}.recruiter-agent-progress p{line-height:1.9;margin-top:7px;color:var(--text-muted)}.recruiter-agent-progress button{font-size:11px;min-height:29px;padding:5px 9px}.recruiter-agent-progress>button{margin-top:12px}.recruiter-agent-progress summary{cursor:pointer;color:var(--brand-ink);padding-top:10px}.recruiter-agent-progress ol{padding-left:20px;margin-top:9px}.recruiter-agent-progress li{padding:5px 0;line-height:1.7}.recruiter-agent-progress li small{margin-left:10px;color:var(--text-muted)}
.recruiter-stream-caret{display:inline-block;height:1em;width:2px;margin-left:4px;background:var(--brand);vertical-align:middle;animation:recruiter-caret .9s steps(2) infinite}@keyframes recruiter-caret{50%{opacity:0}}
.recruiter-agent-choice{display:inline-flex;flex-direction:row;align-items:center;gap:5px;margin-right:10px;color:var(--brand-ink);cursor:pointer;white-space:nowrap}.recruiter-agent-choice input{width:13px;height:13px;min-height:13px;margin:0;accent-color:var(--brand)}
@media(prefers-reduced-motion:reduce){.recruiter-stream-caret{animation:none}}
.recruiter-chat{min-width:0;min-height:0;display:flex;flex-direction:column;background:#fff}
.recruiter-chat-tools{display:flex;align-items:center;justify-content:space-between;gap:9px;padding:10px 22px 6px;font-size:11px;flex-shrink:0;flex-wrap:wrap}
.recruiter-chat-tools>span{display:flex;align-items:center;gap:6px;color:#736f68;font-weight:500}.recruiter-chat-tools>span svg{color:var(--brand-ink)}
.recruiter-chat-options{display:flex;flex-wrap:wrap;gap:7px;align-items:center}.recruiter-chat-tools .text-link{font-size:11px;min-height:28px;padding:3px 8px;gap:5px}.recruiter-chat-options button[aria-expanded=true]{background:var(--brand-soft);border-color:var(--brand-focus)}
.recruiter-chat-notice{padding:2px 22px 10px;margin:0;color:#89857d;font-size:11px;line-height:1.75;flex-shrink:0;border-bottom:1px solid var(--surface-soft)}
.recruiter-context{margin:10px 22px 0;padding:11px 13px 12px;border:1px solid var(--border-soft);border-left:3px solid #b0ada6;border-radius:8px;background:var(--brand-faint);max-height:180px;overflow:auto;flex-shrink:0}
.recruiter-context>header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:7px}.recruiter-context label{font-size:12px;color:var(--text-main)}.recruiter-context .icon-button{min-height:25px;min-width:25px;padding:4px}.recruiter-context textarea{font-size:12px;min-height:54px;max-height:100px;padding:8px 10px;resize:vertical}.recruiter-context small{display:block;margin-top:6px;font-size:10px;color:var(--text-muted)}
.recruiter-chat-error{background:#fff1f0;color:#a2353d;padding:10px 13px;margin:10px 20px 0;border:1px solid #f0cdd1;border-radius:7px;font-size:12px;overflow-wrap:anywhere;flex-shrink:0;max-height:110px;overflow:auto}
.recruiter-chat-log{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;scrollbar-width:thin;padding:24px 26px;scroll-padding:20px}
.recruiter-chat-start{padding:30px 8px 36px;max-width:520px;margin:auto;color:var(--brand-ink)}.recruiter-chat-start>svg{background:var(--brand-soft);border-radius:12px;box-sizing:content-box;padding:11px;width:24px;height:24px}
.recruiter-chat-start h3{font-size:22px;line-height:1.55;margin:17px 0 10px;color:#413d35}.recruiter-chat-start p{font-size:14px;line-height:1.95;color:#7e7a73;max-width:450px}
.recruiter-chat-message{margin-bottom:27px;min-width:0;max-width:940px;margin-inline:auto}.recruiter-chat-message header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:9px;font-size:12px}.recruiter-chat-message header>span{font-size:10px;color:#8e8a83}.recruiter-chat-message>p{font-size:14px;line-height:1.95;white-space:pre-wrap;overflow-wrap:anywhere;color:#413d35}
.recruiter-chat-message.user>p{background:var(--info-paper);border:1px solid var(--border-soft);border-radius:10px 3px 10px 10px;padding:12px 15px}.recruiter-chat-message.assistant{padding:0 4px}
.recruiter-chat-citations{margin-top:12px}.recruiter-chat-citations summary{font-size:12px;cursor:pointer}.recruiter-chat-citations blockquote{margin:10px 0;padding:12px 15px;border-left:3px solid var(--brand-focus);background:var(--surface-soft);white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.9}.recruiter-chat-citations small{display:block;margin-bottom:5px;color:#7c776e}
.recruiter-followups{display:flex;flex-direction:column;align-items:flex-start;gap:7px;margin-top:14px}.recruiter-followups>span{font-size:11px;color:#8a8780}.recruiter-followups button{text-align:left;color:var(--brand-ink);background:var(--brand-faint);font-size:12px;line-height:1.8;padding:7px 10px;border:1px solid var(--brand-edge);border-radius:7px;overflow-wrap:anywhere}.recruiter-followups button:hover:not(:disabled){background:var(--brand-soft);border-color:var(--brand-focus)}
.recruiter-chat-message>.recruiter-chat-source-note{font-size:11px;color:#8a8780}.recruiter-chat-status{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--brand-ink);padding:14px 22px;flex-shrink:0}
.recruiter-composer{margin:0 22px 18px;flex-shrink:0;border:1px solid var(--brand-edge);border-radius:11px;box-shadow:0 3px 14px color-mix(in srgb, var(--brand) 3.14%, transparent);background:#fff;overflow:hidden}.recruiter-composer:focus-within{border-color:var(--brand);box-shadow:0 0 0 2px var(--brand-soft)}
.recruiter-shortcuts{display:flex;align-items:center;gap:7px;padding:9px 11px;border-bottom:1px solid var(--brand-edge);background:var(--brand-faint);flex-wrap:wrap}
.recruiter-shortcuts button{border:1px solid var(--brand-edge);background:#fff;border-radius:6px;padding:5px 9px;color:var(--brand-ink);font-size:11px;line-height:1.6;min-height:29px}.recruiter-shortcuts button:hover:not(:disabled){background:var(--brand-soft);border-color:var(--brand-focus)}
.recruiter-input-area{padding:11px 13px 10px}.recruiter-composer textarea{display:block;min-height:56px;height:56px;max-height:110px;border:0;box-shadow:none;padding:2px;font-size:14px;line-height:1.8;background:transparent;resize:vertical;border-radius:5px}
.recruiter-composer footer{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:5px}.recruiter-composer footer>span{font-size:10px;color:#8b877f;line-height:1.7}.recruiter-send-key{display:inline-block;margin-left:11px;color:#97948e}.recruiter-composer .primary{min-height:33px;padding:6px 12px;font-size:12px;flex-shrink:0;gap:5px}
.spin{animation:recruiter-spin 1s linear infinite}@keyframes recruiter-spin{to{transform:rotate(360deg)}}
@media(max-width:1180px){.recruiter-chat-tools{padding-inline:17px}.recruiter-chat-notice{padding-inline:17px}.recruiter-composer{margin-inline:17px;margin-bottom:15px}.recruiter-chat-log{padding:21px}.recruiter-send-key{display:none}}
@media(max-width:600px){.recruiter-chat-tools{padding:8px 12px 5px;gap:6px}.recruiter-chat-tools>span{font-size:10px}.recruiter-chat-tools .text-link{font-size:10px;padding:3px 6px;min-height:26px;gap:3px}.recruiter-chat-options{gap:5px}.recruiter-chat-notice{padding:2px 12px 8px;font-size:10px}.recruiter-context{margin:8px 12px 0;max-height:155px;padding:9px 10px}.recruiter-chat-log{padding:18px 15px}.recruiter-chat-start{padding:16px 0 24px}.recruiter-chat-start h3{font-size:19px}.recruiter-chat-start p{font-size:13px}.recruiter-chat-message header{flex-wrap:wrap;gap:3px}.recruiter-chat-message>p{font-size:13px}.recruiter-composer{margin:0 11px 11px}.recruiter-shortcuts{gap:5px;padding:7px}.recruiter-shortcuts button{font-size:10px;padding:5px 6px;min-height:28px}.recruiter-input-area{padding:9px 10px}.recruiter-composer textarea{font-size:13px;min-height:52px;height:52px;max-height:96px}.recruiter-composer footer>span{font-size:9px}.recruiter-composer .primary{font-size:11px;min-height:31px;padding:5px 9px}}
@media(prefers-reduced-motion:reduce){.spin{animation:none}}
.recruiter-chat-success,.recruiter-chat-archive{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:11px;line-height:1.8;padding:8px 18px;background:#eef8f3;color:#216249;flex-shrink:0}.recruiter-chat-archive{background:var(--brand-soft);color:var(--brand-ink)}.recruiter-chat-archive .text-link{font-size:11px;min-height:28px}
.recruiter-context>footer{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:7px}.recruiter-context>footer .secondary{font-size:10px;min-height:27px;padding:4px 8px;white-space:nowrap}.recruiter-chat-message .recruiter-copy{font-size:10px;min-height:26px;margin-top:8px;padding:3px 7px}
.recruiter-history-modal{width:min(580px,100%);padding:24px;display:flex;flex-direction:column;gap:18px;max-height:85dvh}.recruiter-history-modal>header{display:flex;justify-content:space-between;gap:12px}.recruiter-history-modal h2,.recruiter-confirm-modal h2{font-size:20px}.recruiter-history-modal p,.recruiter-confirm-modal p{font-size:13px;color:var(--text-muted);line-height:1.9;margin-top:7px}.recruiter-history-modal input{font-size:13px}.recruiter-session-list{overflow:auto;min-height:0;display:grid;gap:8px}.recruiter-session-list>button{display:flex;flex-direction:column;gap:8px;padding:15px;border:1px solid var(--border-soft);border-radius:9px;text-align:left;background:var(--surface-soft)}.recruiter-session-list>button[aria-pressed=true]{background:var(--brand-soft);border-color:var(--brand)}.recruiter-session-list strong{font-size:13px;overflow-wrap:anywhere}.recruiter-session-list small{font-size:11px;color:var(--text-muted)}.recruiter-history-modal>footer,.recruiter-confirm-modal>footer{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap}.recruiter-history-modal>footer button,.recruiter-confirm-modal>footer button{font-size:12px;min-height:35px;padding:8px 12px}.recruiter-confirm-modal{width:min(470px,100%);padding:26px}.recruiter-confirm-modal>footer{margin-top:24px}

.recruiter-chat-tools{width:100%;max-width:1032px;margin:0 auto;padding:12px 28px;gap:10px;border-bottom:1px solid var(--border-soft)}
.recruiter-chat-tools>span{font-size:11px;flex-wrap:wrap}.recruiter-chat-tools>span small{font-size:10px;color:var(--text-muted);padding-left:5px}.recruiter-chat-options{gap:6px}
.recruiter-chat-log{padding:28px max(28px,calc((100% - 920px)/2));scroll-padding:28px}.recruiter-chat-message{margin-bottom:32px;max-width:none}.recruiter-chat-message>p{font-size:15px;line-height:2}.recruiter-chat-message header{font-size:12px;margin-bottom:12px}.recruiter-chat-message header>span{font-size:10px}.recruiter-chat-message.user>p{padding:13px 17px}.recruiter-chat-start{max-width:600px;padding-top:42px}.recruiter-chat-start h3{font-size:24px}.recruiter-chat-start p{font-size:14px;max-width:540px}
.recruiter-composer{width:calc(100% - 56px);max-width:960px;align-self:center;margin:0 28px 22px}.recruiter-shortcuts{padding:7px 13px;background:#fff;border-bottom:1px solid var(--border-soft);gap:8px}.recruiter-shortcuts button{font-size:11px;padding:5px 10px;background:var(--brand-faint)}.recruiter-input-area{padding:10px 16px 9px}.recruiter-composer textarea{height:44px;min-height:44px;max-height:125px;font-size:14px}.recruiter-composer footer{margin-top:4px}
.recruiter-context{width:calc(100% - 56px);max-width:960px;margin:12px auto 0}.recruiter-chat-error{max-width:960px;width:calc(100% - 56px);align-self:center;margin:10px auto 0}.recruiter-chat-success{padding:7px max(28px,calc((100% - 920px)/2));font-size:11px}
.recruiter-followups{display:block;margin-top:14px}.recruiter-followups summary{font-size:12px;color:var(--brand-ink);cursor:pointer;line-height:1.9;padding:7px 0;list-style-position:inside}.recruiter-followups>div{display:flex;flex-direction:column;align-items:flex-start;gap:7px;padding-top:6px}.recruiter-followups button{font-size:12px;padding:9px 12px;background:#fff;line-height:1.9}
@media(max-width:600px){.recruiter-chat-tools{padding:9px 12px;align-items:flex-start;gap:8px}.recruiter-chat-tools>span{font-size:10px;gap:5px}.recruiter-chat-tools>span small{display:none}.recruiter-chat-options{gap:5px}.recruiter-chat-tools .text-link{font-size:10px;padding:4px 6px;min-height:28px}.recruiter-chat-options>button:nth-child(2){min-width:28px;padding:4px}.recruiter-chat-options>button:nth-child(2)>span{display:none}.recruiter-chat-log{padding:22px 16px}.recruiter-chat-message>p{font-size:14px;line-height:1.95}.recruiter-chat-message{margin-bottom:27px}.recruiter-chat-start{padding:25px 0}.recruiter-chat-start h3{font-size:20px}.recruiter-chat-start p{font-size:13px}.recruiter-composer{width:calc(100% - 24px);margin:0 12px 12px}.recruiter-shortcuts{gap:5px;padding:8px}.recruiter-shortcuts button{font-size:10px;padding:5px 7px}.recruiter-input-area{padding:10px 12px}.recruiter-composer textarea{font-size:13px;height:52px;min-height:52px;max-height:100px}.recruiter-context,.recruiter-chat-error{width:calc(100% - 24px)}.recruiter-chat-success{padding:7px 16px}}
</style>
