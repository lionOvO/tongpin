<script setup lang="ts">
import ResumeAttachment from "../components/ResumeAttachment.vue"
import { createRequestId } from '../request-id'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowUpRight, Check, ChevronDown, FileText, MessageSquare, PanelRightClose, PanelRightOpen, RefreshCw, Search, Send, Video, X } from '@lucide/vue'
import { api, ApiError, candidate } from '../store'
import { applicationLabels, ended, eventLabels } from '../hiring'
import type { ApplicationDetail, ApplicationSummary, HiringAction } from '../hiring'
import { acknowledgeConversation, chatEnabled, conversationPreview, inbox, refreshInbox, loadMoreInbox, setInboxQuery } from '../messages'
import type { RecruiterReviewState } from '../recruiter-review'
import { prepareVideoCall } from '../video-calls'
import VideoCallHistory from '../components/VideoCallHistory.vue'

const route = useRoute(); const router = useRouter()
const search = ref(''); const onlyUnread = ref(false)
const searchMatches = ref<Set<string> | null>(null); const searching = ref(false)
const selected = ref<ApplicationDetail | null>(null); const opening = ref(false); const pending = ref(false)
const error = ref(''); const connectionError = ref(false); const input = ref('')
const log = ref<HTMLElement | null>(null); const composer = ref<HTMLTextAreaElement | null>(null)
const detailElement = ref<HTMLElement | null>(null); const detailsToggle = ref<HTMLButtonElement | null>(null)
const compactQuery = window.matchMedia('(max-width:760px)')
const drawerQuery = window.matchMedia('(max-width:1299px)'); const drawerMode = ref(drawerQuery.matches)
const mobile = ref(compactQuery.matches); const mobilePane = ref<'list' | 'chat'>('list')
const showDetails = ref(window.innerWidth >= 1300)
const drafts = new Map<string, string>(); const questions = ref<string[]>([])
const request = ref<{ id: string; text: string; requestId: string } | null>(null)
const actionDialog = ref<{ action: HiringAction; text: string; id: string; version: number; requestId: string } | null>(null)
const actionNames: Partial<Record<HiringAction,string>> = { invite: '邀请沟通', accept: '接受邀请', decline: '婉拒邀请' }
const side = computed(() => candidate.value ? 'candidate' : 'enterprise')
const unread = computed(() => inbox.unread)
const visible = computed(() => inbox.rows.filter(r => !onlyUnread.value || !!r.unread_count))
const canSend = computed(() => !!selected.value && chatEnabled(selected.value))
const counterpart = computed(() => selected.value ? candidate.value ? selected.value.company_name || '认证企业' : selected.value.candidate_name : '')
const expectations = computed(() => {
  const row = selected.value
  if (row?.preference_comparison) return row.preference_comparison.dimension_results
  const ent = row?.enterprise_preferences; const cand = row?.candidate_preferences
  return [...new Set([...Object.keys(ent?.dimensions || {}), ...Object.keys(cand?.dimensions || {})])].map(id => ({
    dimension_id: id, name: ent?.dimension_labels?.[id] || cand?.dimension_labels?.[id] || '其他期待',
    ent_quote: ent?.dimensions[id] || '尚未共享', cand_quote: cand?.dimensions[id] || '尚未共享',
  }))
})
const time = (stamp: string) => new Date(stamp).toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' })
function highlight(text:string) {
  const query = search.value.trim().toLocaleLowerCase()
  if (!query) return [{text,match:false}]
  const parts:{text:string;match:boolean}[] = []; const lower = text.toLocaleLowerCase(); let offset = 0
  while (offset < text.length) {
    const index = lower.indexOf(query,offset)
    if (index < 0) { parts.push({text:text.slice(offset),match:false}); break }
    if (index > offset) parts.push({text:text.slice(offset,index),match:false})
    parts.push({text:text.slice(index,index+query.length),match:true}); offset = index + query.length
  }
  return parts
}
let alive = true; let sequence = 0; let polling = false; let reading = false; let timer: ReturnType<typeof setInterval> | undefined
let searchTimer: ReturnType<typeof setTimeout> | undefined; let searchSequence = 0
watch(search, query => {
  clearTimeout(searchTimer); const ticket = ++searchSequence
  searching.value = true
  searchTimer = setTimeout(async () => {
    setInboxQuery(query)
    try { await refreshInbox() }
    catch (e) { if (alive && ticket === searchSequence) problem(e) }
    finally { if (alive && ticket === searchSequence) searching.value = false }
  },250)
})
async function moreConversations() { searching.value = true; try { await loadMoreInbox() } catch (e) { problem(e) } finally { searching.value = false } }
function problem(e: unknown) {
  if (e instanceof ApiError && ['STALE_CONTEXT','AUTH_REQUIRED'].includes(e.code)) return
  error.value = e instanceof Error ? e.message : '操作未完成，请重试。'
}
function viewport(event: MediaQueryListEvent) { mobile.value = event.matches; showDetails.value = false; if (!event.matches) void markRead() }
function drawerViewport(event:MediaQueryListEvent) { drawerMode.value = event.matches }
function closeDetails() { showDetails.value = false; void nextTick(() => detailsToggle.value?.focus()) }
function detailsKeyboard(event:KeyboardEvent) {
  if (!showDetails.value || !drawerMode.value || actionDialog.value) return
  if (event.key === 'Escape') { event.preventDefault(); closeDetails(); return }
  if (event.key !== 'Tab') return
  const elements = [...(detailElement.value?.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],summary,[tabindex="0"]') || [])].filter(el => !!(el.offsetWidth || el.offsetHeight))
  const first = elements[0]; const last = elements[elements.length-1]
  if (!detailElement.value?.contains(document.activeElement) || event.shiftKey && document.activeElement === first) { event.preventDefault(); (event.shiftKey ? last : first)?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
watch([showDetails,drawerMode], async ([show,drawer]) => { if (show && drawer) { await nextTick(); detailElement.value?.querySelector<HTMLElement>('button')?.focus() } })
function rememberDraft() { if (selected.value) drafts.set(selected.value.id, input.value) }
async function moveToLatest(force = false) {
  const nearBottom = !log.value || log.value.scrollHeight - log.value.scrollTop - log.value.clientHeight < 100
  await nextTick()
  if (alive && (force || nearBottom) && log.value) log.value.scrollTop = log.value.scrollHeight
}
async function markRead() {
  const row = selected.value
  if (!row || reading || document.visibilityState !== 'visible' || mobile.value && mobilePane.value !== 'chat' || !row.unread_count) return
  reading = true
  try {
    const result = await api<ApplicationDetail>(`/messages/conversations/${row.id}/read`, 'POST', {
      message_count: row.messages.length, invitation_at: row.invitation?.created_at || null,
    }, 15000)
    if (alive && selected.value?.id === row.id) {
      // A concurrent poll can have newer messages. Never overwrite them with a read response.
      if (selected.value.version <= result.version) selected.value = result
      acknowledgeConversation(row.id, result.unread_count || 0)
    }
  } catch (e) { if (alive && e instanceof ApiError && [403,404].includes(e.status)) { selected.value = null; questions.value = []; problem(e) } }
  finally { reading = false }
}
async function loadQuestions(row: ApplicationDetail, ticket: number) {
  questions.value = []
  if (candidate.value || !row.resume_shared || !row.available) return
  try {
    const result = await api<RecruiterReviewState>(`/applications/${row.id}/recruiter-review`, 'GET', undefined, 15000)
    if (alive && ticket === sequence && selected.value?.id === row.id && selected.value.resume_shared) {
      questions.value = [...new Set([...(result.review?.strengths || []).map(s => s.interview_question), ...(result.review?.open_questions || []).map(q => q.question)])].slice(0,10)
    }
  } catch { /* Existing questions are optional; this never generates or transmits AI analysis. */ }
}
async function open(id: string, enter = true) {
  if (pending.value) return
  rememberDraft(); const ticket = ++sequence; opening.value = true; error.value = ''; questions.value = []
  selected.value = null; showDetails.value = !mobile.value && window.innerWidth >= 1300
  if (enter) mobilePane.value = 'chat'
  try {
    const row = await api<ApplicationDetail>('/applications/' + encodeURIComponent(id), 'GET', undefined, 15000)
    if (!alive || ticket !== sequence) return
    selected.value = row; input.value = drafts.get(id) || ''; request.value = null; opening.value = false
    await router.replace({ path:'/messages', query:{ application:id } })
    await moveToLatest(true)
    if (search.value.trim()) log.value?.querySelector('mark')?.scrollIntoView({block:'center'})
    resizeComposer(); await markRead(); void loadQuestions(row,ticket)
  } catch (e) { if (alive && ticket === sequence) problem(e) }
  finally { if (alive && ticket === sequence) opening.value = false }
}
async function refresh() {
  if (polling || opening.value || pending.value || !alive || document.visibilityState !== 'visible') return
  polling = true; const ticket = sequence
  try {
    await refreshInbox()
    if (!alive || ticket !== sequence) return
    connectionError.value = false
    if (selected.value) {
      const row = await api<ApplicationDetail>('/applications/' + selected.value.id, 'GET', undefined, 15000)
      if (!alive || ticket !== sequence || pending.value) return
      const changed = row.messages.length !== selected.value.messages.length
      const wasNear = !log.value || log.value.scrollHeight - log.value.scrollTop - log.value.clientHeight < 100
      selected.value = row
      if (!row.resume_shared || !row.available) questions.value = []
      if (changed) await moveToLatest(wasNear)
      await markRead()
    }
  } catch (e) {
    if (alive && ticket === sequence) {
      connectionError.value = true
      if (e instanceof ApiError && [401,403,404].includes(e.status)) { selected.value = null; questions.value = []; problem(e) }
    }
  } finally { polling = false }
}
async function send() {
  const row = selected.value; const text = input.value.trim()
  if (!row || !canSend.value || pending.value || text.length < 2) return
  if (request.value?.id !== row.id || request.value.text !== text) request.value = { id:row.id, text, requestId:createRequestId() }
  pending.value = true; error.value = ''; const ticket = ++sequence
  try {
    const result = await api<ApplicationDetail>(`/applications/${row.id}/messages`, 'POST', {
      text, expected_version:row.version, request_id:request.value.requestId,
    },15000)
    if (!alive || ticket !== sequence) return
    selected.value = result; input.value = ''; drafts.delete(row.id); request.value = null
    acknowledgeConversation(row.id); await moveToLatest(true); resizeComposer(); await refreshInbox()
  } catch (e) {
    if (alive && ticket === sequence) {
      problem(e)
      try {
        const latest = await api<ApplicationDetail>('/applications/' + row.id, 'GET', undefined, 15000)
        if (alive && ticket === sequence) { selected.value = latest; if (!latest.resume_shared) questions.value = [] }
      } catch { /* Retain unsent input for a safe, idempotent retry. */ }
    }
  } finally { if (alive && ticket === sequence) pending.value = false }
}
function prepare(action: HiringAction) {
  if (!selected.value || pending.value) return
  actionDialog.value = { action, text:'', id:selected.value.id, version:selected.value.version, requestId:createRequestId() }
}
async function confirmAction() {
  const dialog = actionDialog.value
  if (!dialog || pending.value) return
  pending.value = true; error.value = ''; const ticket = ++sequence
  try {
    const result = await api<ApplicationDetail>(`/applications/${dialog.id}/actions`, 'POST', {
      action:dialog.action, text:dialog.text, expected_version:dialog.version, request_id:dialog.requestId,
    },15000)
    if (!alive || ticket !== sequence) return
    selected.value = result; actionDialog.value = null
    if (!result.resume_shared) questions.value = []
    await refreshInbox(); await markRead()
  } catch (e) {
    if (alive && ticket === sequence) {
      problem(e)
      try {
        const latest = await api<ApplicationDetail>('/applications/' + dialog.id, 'GET', undefined, 15000)
        if (alive && ticket === sequence) {
          selected.value = latest
          if (!latest.resume_shared || !latest.available) questions.value = []
          if (e instanceof ApiError && e.status === 409) actionDialog.value = null
        }
      } catch { /* Keep the same request id for a retry when the outcome is unknown. */ }
    }
  }
  finally { if (alive && ticket === sequence) { pending.value = false; void refresh() } }
}
async function useQuestion(text: string) {
  if (!canSend.value || pending.value) return
  const value = input.value.trim() ? input.value.trim() + '\n' + text : text
  if (drawerMode.value) showDetails.value = false
  if (value.length > 2000) { error.value = '输入内容最多 2000 字，请精简后再加入追问。'; return }
  input.value = value; await nextTick(); resizeComposer(); composer.value?.focus()
}
function resizeComposer() { const el = composer.value; if (el) { el.style.height = 'auto'; el.style.height = Math.min(112,Math.max(44,el.scrollHeight)) + 'px' } }
function keyboard(event: KeyboardEvent) { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); void send() } }
function visibility() { if (document.visibilityState === 'visible') { void markRead(); void refresh() } }
watch(input, rememberDraft)
watch(() => route.query.application, id => { if (typeof id === 'string' && id !== selected.value?.id && !opening.value) void open(id) })
onMounted(async () => {
  try {
    await refreshInbox()
    if (!alive) return
    const requested = typeof route.query.application === 'string' ? route.query.application : undefined
    const id = requested || (!mobile.value ? inbox.rows[0]?.id : undefined)
    if (id) await open(id, !!requested || !mobile.value)
  } catch (e) { if (alive) { connectionError.value = true; problem(e) } }
  if (!alive) return
  timer = setInterval(refresh,5000); document.addEventListener('visibilitychange',visibility); compactQuery.addEventListener('change',viewport); drawerQuery.addEventListener('change',drawerViewport); document.addEventListener('keydown',detailsKeyboard)
})
onUnmounted(() => { setInboxQuery(''); alive = false; sequence++; searchSequence++; drafts.clear(); clearInterval(timer); clearTimeout(searchTimer); document.removeEventListener('visibilitychange',visibility); compactQuery.removeEventListener('change',viewport); drawerQuery.removeEventListener('change',drawerViewport); document.removeEventListener('keydown',detailsKeyboard) })
</script>

<template>
  <section :class="['messages-workspace', { 'messages-chat-open': mobilePane === 'chat', 'messages-show-details': showDetails }]">
    <header class="messages-toolbar"><div><MessageSquare :size="23" /><h1>消息中心</h1><span v-if="unread" class="pill amber">{{ unread }} 条未读</span></div><button class="secondary" :disabled="pending || opening" @click="refresh"><RefreshCw :size="15" />刷新消息</button></header>
    <p v-if="connectionError" class="messages-connection" role="status">连接暂时中断，正在尝试重新连接。未发送的文字会保留在当前页面。</p>
    <p v-if="error" class="messages-error" role="alert">{{ error }}<button aria-label="关闭消息提示" @click="error = ''"><X :size="16" /></button></p>
    <div class="messages-layout">
      <aside class="messages-list" aria-label="会话列表"><div class="messages-list-tools"><label><span class="sr-only">搜索会话或消息</span><Search :size="16" /><input v-model="search" type="search" maxlength="100" placeholder="搜索姓名、企业、岗位或消息" /></label><button :aria-pressed="onlyUnread" @click="onlyUnread = !onlyUnread">{{ onlyUnread ? '仅看未读' : '全部会话' }}<ChevronDown :size="14" /></button><small role="status">{{ searching ? '搜索历史消息…' : inbox.total + ' 个会话' }}</small></div>
        <div class="messages-list-scroll"><button v-for="row in visible" :key="row.id" :class="['conversation-row',{selected:selected?.id === row.id}]" :disabled="pending" @click="open(row.id)"><span class="conversation-avatar">{{ (candidate ? row.company_name || '企' : row.candidate_name).slice(0,1) }}</span><span class="conversation-row-content"><span class="conversation-name"><strong>{{ candidate ? row.company_name || '认证企业' : row.candidate_name }}</strong><time>{{ time(row.last_message?.created_at || row.updated_at) }}</time></span><span class="conversation-job">{{ row.job_title }}</span><span class="conversation-preview">{{ conversationPreview(row) }}</span><span class="conversation-status">{{ applicationLabels[row.status] }}</span></span><span v-if="row.unread_count" class="conversation-unread" :aria-label="row.unread_count + ' 条未读'">{{ row.unread_count > 99 ? '99+' : row.unread_count }}</span></button><button v-if="inbox.rows.length < inbox.total" class="secondary full" :disabled="searching" @click="moreConversations">加载更多会话 · 已显示 {{ inbox.rows.length }} / {{ inbox.total }}</button><div v-if="!visible.length && !searching" class="messages-list-empty"><MessageSquare :size="27" /><h3>{{ inbox.rows.length ? '没有符合条件的会话' : '还没有沟通会话' }}</h3><p>{{ inbox.rows.length ? '试试其他关键词，或查看全部会话。' : '企业发出邀请后，会话会出现在这里。' }}</p><RouterLink to="/applications" class="text-link">{{ candidate ? '查看我的投递' : '查看应聘与邀请' }} →</RouterLink></div></div>
      </aside>
      <section class="messages-chat" aria-label="双方聊天区">
        <div v-if="opening" class="messages-empty" role="status">正在读取沟通记录…</div>
        <template v-else-if="selected">
          <header class="conversation-heading"><button class="icon-button conversation-back" aria-label="返回会话列表" @click="mobilePane = 'list'; showDetails = false"><ArrowLeft :size="20" /></button><div><h2>{{ counterpart }}</h2><p>{{ selected.job_title }}<span>{{ applicationLabels[selected.status] }}</span></p></div><button class="conversation-video-button" :disabled="!canSend || pending" :title="canSend ? '发起视频通话' : '双方接受沟通后开启视频通话'" aria-label="发起视频通话" @click="prepareVideoCall(selected, counterpart)"><Video :size="17" /><span>视频通话</span></button><button ref="detailsToggle" class="icon-button" :aria-label="showDetails ? '收起沟通资料' : '查看沟通资料'" :title="showDetails ? '收起沟通资料' : '查看沟通资料'" :aria-expanded="showDetails" @click="showDetails = !showDetails"><component :is="showDetails ? PanelRightClose : PanelRightOpen" :size="20" /></button></header>
          <div ref="log" class="conversation-log" role="log" aria-label="双方历史消息" tabindex="0">
            <div v-if="selected.invitation" class="conversation-invitation"><span>企业的沟通邀请 · {{ time(selected.invitation.created_at) }}</span><p><component :is="part.match ? 'mark' : 'span'" v-for="(part,partIndex) in highlight(selected.invitation.text)" :key="partIndex">{{ part.text }}</component></p><div v-if="candidate && selected.status === 'invited' && selected.available"><button class="primary" :disabled="pending" @click="prepare('accept')"><Check :size="15" />接受邀请</button><button class="secondary" :disabled="pending" @click="prepare('decline')">婉拒邀请</button></div></div>
            <div v-if="!selected.invitation && !selected.messages.length" class="conversation-welcome"><MessageSquare :size="31" /><h3>{{ canSend ? '从具体的工作聊起' : '等待沟通邀请' }}</h3><p>{{ candidate ? '企业发出邀请后，你可以决定是否开始沟通。' : '先发出邀请，由求职者决定是否开始沟通。' }}</p><button v-if="!candidate && selected.status === 'submitted' && selected.available" class="primary" :disabled="pending" @click="prepare('invite')">邀请沟通<ArrowUpRight :size="16" /></button></div>
            <article v-for="(message,index) in selected.messages" :key="index" :class="['conversation-message',{mine:message.side === side}]"><span class="conversation-message-avatar">{{ message.side === side ? '我' : (counterpart || '同').slice(0,1) }}</span><div><small>{{ message.side === side ? '我' : counterpart }} · {{ time(message.created_at) }}</small><p><component :is="part.match ? 'mark' : 'span'" v-for="(part,partIndex) in highlight(message.text)" :key="partIndex">{{ part.text }}</component></p><span v-if="message.side === side" class="message-sent"><Check :size="12" />已发送</span></div></article>
            <VideoCallHistory :application-id="selected.id" />
          </div>
          <form v-if="canSend" class="conversation-composer" @submit.prevent="send"><label class="sr-only" for="human-chat-input">沟通内容</label><textarea id="human-chat-input" ref="composer" v-model="input" rows="2" maxlength="2000" :disabled="pending" placeholder="聊聊工作安排、具体职责和双方期待…" @input="resizeComposer" @keydown="keyboard" /><div><small>{{ input.length }}/2000 · Ctrl / ⌘ + Enter 发送</small><button class="primary" :disabled="pending || input.trim().length < 2"><Send :size="16" />{{ pending ? '正在发送…' : error && request ? '重试发送' : '发送消息' }}</button></div></form>
          <div v-else class="conversation-locked" role="status">{{ !selected.available ? '岗位或账号暂不可用，当前不能继续沟通。' : ended(selected.status) ? '这次投递已结束，可以回看历史消息。' : selected.status === 'invited' ? candidate ? '接受邀请后即可开始聊天。' : '等待求职者回应邀请后即可开始聊天。' : '企业发出邀请、求职者接受后开启聊天。' }}</div>
        </template>
        <div v-else class="messages-empty"><MessageSquare :size="38" /><h2>留出空间，好好聊聊。</h2><p>选择一条会话，查看邀请和历史记录。</p><button v-if="mobile" class="secondary" @click="mobilePane = 'list'">查看会话列表</button></div>
      </section>
      <button v-if="showDetails && selected" class="conversation-details-scrim" aria-label="关闭沟通资料遮罩" @click="closeDetails" />
      <aside v-if="showDetails && selected" ref="detailElement" class="conversation-details" :role="drawerMode ? 'dialog' : 'complementary'" :aria-modal="drawerMode ? true : undefined" aria-label="本次投递的沟通资料"><header><h2>本次沟通资料</h2><button class="icon-button" aria-label="关闭沟通资料" @click="closeDetails"><X :size="18" /></button></header><div class="conversation-details-scroll"><p class="conversation-material-note">资料来自本次投递时保存的版本。</p><section><h3>岗位与进展</h3><strong>{{ selected.job_title }}</strong><p>{{ selected.company_name || '认证企业' }}</p><div class="conversation-progress-actions"><span :class="['pill', { teal: selected.status === 'accepted', amber: selected.status === 'invited' }]">{{ applicationLabels[selected.status] }}</span><RouterLink :to="{path:'/applications',query:{application:selected.id}}" class="button secondary conversation-progress-link">查看投递详情<ArrowUpRight :size="15" /></RouterLink></div><details><summary>岗位原文</summary><p class="source-text">{{ selected.job_snapshot.text }}</p></details></section>
          <section><h3><FileText :size="16" />{{ candidate ? '本次共享的简历' : '已授权的简历' }}</h3><ResumeAttachment v-if="selected.resume_snapshot" :key="selected.id" :name="selected.resume_snapshot.name" :text="selected.resume_snapshot.text" /><p v-else>本次简历授权已结束或暂不可用。</p></section>
          <section><h3>双方期待</h3><article v-for="value in expectations" :key="value.dimension_id" class="conversation-expectation"><h4>{{ value.name }}</h4><p><small>企业</small>{{ value.ent_quote }}</p><p><small>求职者</small>{{ value.cand_quote }}</p></article><p v-if="!expectations.length">双方尚未都提供共享期待，可先沟通。</p><p v-if="selected.enterprise_preferences?.ambience_text">团队氛围：{{ selected.enterprise_preferences.ambience_text }}</p></section>
          <section v-if="!candidate && questions.length"><h3>面试追问参考</h3><p>仅招聘方可见；放入输入框后，由你确认发送。</p><article v-for="question in questions" :key="question" class="conversation-question"><p>{{ question }}</p><button class="text-link" :disabled="!canSend || pending" @click="useQuestion(question)">放入输入框<ArrowUpRight :size="14" /></button></article></section>
          <section><h3>双方进展记录</h3><ol class="conversation-events"><li v-for="(event,index) in selected.events" :key="index"><strong>{{ eventLabels[event.action] || event.action }}</strong><small>{{ time(event.created_at) }}</small><p v-if="event.text">{{ event.text }}</p></li></ol></section>
        </div></aside>
    </div>
    <div v-if="actionDialog" class="modal-backdrop" @click.self="!pending && (actionDialog = null)"><section v-dialog class="modal" role="dialog" aria-modal="true" aria-labelledby="conversation-action-title"><header class="detail-heading"><h2 id="conversation-action-title">{{ actionNames[actionDialog.action] }}</h2><button class="icon-button" aria-label="关闭邀请操作" :disabled="pending" @click="actionDialog = null"><X :size="18" /></button></header><form @submit.prevent="confirmAction"><p v-if="actionDialog.action === 'accept'" class="muted">接受表示愿意进一步了解岗位，之后可以在消息中心沟通。</p><label v-else>{{ actionDialog.action === 'invite' ? '邀请内容' : '说明（可选）' }}<textarea v-model="actionDialog.text" rows="4" maxlength="2000" :required="actionDialog.action === 'invite'" :minlength="actionDialog.action === 'invite' ? 2 : undefined" :disabled="pending" /></label><div class="form-footer"><button type="button" class="secondary" :disabled="pending" @click="actionDialog = null">取消</button><button class="primary" :disabled="pending">{{ pending ? '正在保存…' : actionNames[actionDialog.action] }}</button></div></form></section></div>
  </section>
</template>
