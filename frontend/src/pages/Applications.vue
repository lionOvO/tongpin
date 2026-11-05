<script setup lang="ts">
import ResumeAttachment from "../components/ResumeAttachment.vue"
import { createRequestId } from '../request-id'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUpRight, Check, ChevronDown, Clock3, FileText, MessageSquare, RefreshCw, Search, UsersRound, X } from '@lucide/vue'
import { api, candidate, notifyError, state } from '../store'
import { applicationLabels, ended, eventLabels } from '../hiring'
import type { ApplicationDetail, ApplicationSummary, HiringAction } from '../hiring'
import RecruiterProfile from '../components/RecruiterProfile.vue'
import RecruiterApplicationDetail from '../components/RecruiterApplicationDetail.vue'
import ApplicationResumeActions from '../components/ApplicationResumeActions.vue'

const route = useRoute(); const router = useRouter()
const rows = ref<ApplicationSummary[]>([]); const selected = ref<ApplicationDetail | null>(null)
const offset = ref(0); const total = ref(0); let listSequence = 0
const search = ref(''); const filter = ref('all'); const loading = ref(false); const pending = ref(false)
const modal = ref<{ action: HiringAction; text: string; id: string; version: number; requestId: string } | null>(null)
const modalTitles: Record<HiringAction, string> = { invite: '邀请沟通', accept: '接受沟通邀请', decline: '婉拒这次邀请', reject: '暂不推进这份投递', withdraw: '撤回投递与资料授权', close: '结束本次沟通', refresh_preferences: '同步我的期待' }
const visible = computed(() => rows.value)
const expectationRows = computed(() => {
  const row = selected.value
  if (row?.preference_comparison) return row.preference_comparison.dimension_results
  const ent = row?.enterprise_preferences; const cand = row?.candidate_preferences
  return [...new Set([...Object.keys(ent?.dimensions || {}), ...Object.keys(cand?.dimensions || {})])].map(id => ({
    dimension_id: id, name: ent?.dimension_labels?.[id] || cand?.dimension_labels?.[id] || '其他期待',
    ent_quote: ent?.dimensions[id] || '尚未共享', cand_quote: cand?.dimensions[id] || '尚未共享',
    unmatched_reason: '保留已共享的原文，等待另一方补充后再对照。',
  }))
})
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch([search,filter,() => route.query.job], () => { listSequence++; offset.value = 0; clearTimeout(searchTimer); searchTimer = setTimeout(() => void load(),250) })
async function changePage(step: number) { offset.value = Math.max(0, offset.value + step * 30); selected.value = null; await router.replace({path:'/applications',query:{...route.query,application:undefined}}); await load() }
let alive = true; let sequence = 0; let timer: ReturnType<typeof setInterval> | undefined
const date = (stamp: string) => new Date(stamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
async function open(id: string) {
  if (pending.value) return
  const ticket = ++sequence; loading.value = true
  try {
    const row = await api<ApplicationDetail>('/applications/' + encodeURIComponent(id))
    if (!alive || ticket !== sequence) return
    selected.value = row
    await router.replace({ path: '/applications', query: { ...route.query, application: id } })
  } catch (e) { if (alive && ticket === sequence) { selected.value = null; notifyError(e) } }
  finally { if (alive && ticket === sequence) loading.value = false }
}
async function load(quiet = false) {
  const epoch = sequence
  try {
    const ticket = ++listSequence
    const params = new URLSearchParams({offset:String(offset.value),limit:'30',q:search.value.trim(),status:filter.value})
    if (typeof route.query.job === 'string') params.set('job_id',route.query.job)
    const page = await api<{items:ApplicationSummary[];total:number}>('/applications/page?' + params)
    if (ticket !== listSequence) return
    total.value = page.total; const list = page.items
    if (!alive || epoch !== sequence) return
    rows.value = list
    const filtering = !!search.value.trim() || filter.value !== 'all'
    if (selected.value && (!filtering || list.some(item => item.id === selected.value?.id))) {
      const detail = await api<ApplicationDetail>('/applications/' + selected.value.id)
      if (alive && epoch === sequence) selected.value = detail
    } else if (!quiet) {
      selected.value = null
      const requested = typeof route.query.application === 'string' ? route.query.application : undefined
      const id = requested && (!filtering || list.some(item => item.id === requested)) ? requested : visible.value[0]?.id
      if (id) await open(id)
    }
  } catch (e) { if (alive && !quiet) notifyError(e) }
}
function prepare(action: HiringAction) {
  if (!selected.value || pending.value) return
  modal.value = { action, text: '', id: selected.value.id, version: selected.value.version, requestId: createRequestId() }
}
async function confirm() {
  const dialog = modal.value
  if (!dialog || pending.value) return
  pending.value = true; state.error = ''
  try {
    const row = await api<ApplicationDetail>(`/applications/${dialog.id}/actions`, 'POST', { action: dialog.action, text: dialog.text, expected_version: dialog.version, request_id: dialog.requestId })
    if (!alive) return
    selected.value = row; modal.value = null; state.success = modalTitles[dialog.action] + '已完成。'; await load()
  } catch (e) { if (alive) { notifyError(e); await load(true) } }
  finally { if (alive) pending.value = false }
}
function refreshVisible() { if (document.visibilityState === 'visible' && !pending.value && !modal.value && !loading.value) void load(true) }
watch(() => route.query.application, id => { if (typeof id === 'string' && id !== selected.value?.id) void open(id) })
onMounted(async () => { await load(); if (!alive) return; timer = setInterval(refreshVisible, 30000); document.addEventListener('visibilitychange', refreshVisible) })
onUnmounted(() => { alive = false; sequence++; clearTimeout(searchTimer); listSequence++; clearInterval(timer); document.removeEventListener('visibilitychange', refreshVisible) })
</script>

<template>
  <div v-if="!candidate" class="application-desk">
    <header class="application-desk-heading"><div><p class="eyebrow">招聘工作台 / 双向选择</p><h1>应聘与邀请</h1><p>先看清经历，再决定如何进一步了解。</p></div><button class="secondary" :disabled="pending || loading" @click="load()"><RefreshCw :size="15" />刷新进展</button></header>
    <div class="application-desk-layout">
      <section class="surface application-candidate-list" aria-label="投递列表">
        <header class="application-list-heading"><h2><UsersRound :size="17" />候选人<span>{{ total }}</span></h2><span>主动投递</span></header>
        <div class="application-list-filters"><label class="application-list-search"><span class="sr-only">搜索投递</span><Search :size="15" /><input v-model="search" type="search" placeholder="搜索姓名或岗位" /></label><label><span class="sr-only">筛选进展</span><select v-model="filter"><option value="all">全部进展</option><option value="submitted">已投递</option><option value="invited">待回应邀请</option><option value="accepted">沟通中</option><option value="ended">已结束</option></select></label></div>
        <div class="application-list-items"><button v-for="r in visible" :key="r.id" :class="['application-candidate-row', { selected: selected?.id === r.id }]" :aria-current="selected?.id === r.id ? 'true' : undefined" :disabled="pending || loading" @click="open(r.id)"><div class="application-row-top"><span class="application-row-avatar" aria-hidden="true">{{ r.candidate_name.replace(/^个人简历[_\s-]*/, '').slice(0, 1) }}</span><span :class="['pill', { teal: r.status === 'accepted', amber: r.status === 'invited' }]">{{ applicationLabels[r.status] }}</span></div><strong>{{ r.candidate_name.replace(/^个人简历[_\s-]*/, '').replace(/_/g, ' · ') }}</strong><p>{{ r.job_title }}</p><span v-if="r.review_strengths?.length" class="hiring-strength-tags"><span v-for="tag in r.review_strengths.slice(0, 2)" :key="tag">{{ tag }}</span></span><div class="application-row-meta"><time>{{ date(r.created_at) }}</time><span v-if="r.unread_count" class="application-row-unread">{{ r.unread_count }} 条未读</span><span v-else><MessageSquare :size="11" />{{ r.message_count }}</span></div></button><div v-if="!visible.length" class="application-list-empty"><UsersRound :size="24" /><p>{{ search || filter !== 'all' ? '没有符合条件的投递' : '还没有收到投递' }}</p><button v-if="search || filter !== 'all'" class="secondary" @click="search = ''; filter = 'all'">清除筛选</button><RouterLink v-else to="/jobs" class="button secondary">管理公开岗位<ArrowUpRight :size="13" /></RouterLink></div></div>
        <footer v-if="total > 30" class="application-list-pagination"><button class="secondary" :disabled="offset === 0 || loading || pending" @click="changePage(-1)">上一页</button><span>{{ offset + 1 }}–{{ Math.min(offset + 30,total) }}</span><button class="secondary" :disabled="offset + 30 >= total || loading || pending" @click="changePage(1)">下一页</button></footer>
      </section>
      <section v-if="loading" class="surface application-detail-loading" role="status"><RefreshCw :size="24" class="spin" /><h2>正在读取投递资料</h2><p>简历、岗位和沟通进展会一起显示在这里。</p></section>
      <RecruiterApplicationDetail v-else-if="selected" :key="selected.id" :application="selected" :pending="pending" @prepare="prepare" @analyzed="load(true)" />
      <section v-else class="surface application-detail-loading"><FileText :size="32" /><h2>{{ visible.length ? '选择一位候选人' : '从一份主动投递开始' }}</h2><p>{{ visible.length ? '从左侧打开投递，集中查看经历、岗位与双方进展。' : '公开岗位后，这里会收到求职者主动授权的简历。' }}</p><RouterLink v-if="!visible.length && !search && filter === 'all'" to="/jobs" class="button secondary">管理并公开岗位<ArrowUpRight :size="15" /></RouterLink></section>
    </div>
  </div>
  <template v-else>
  <div class="page-heading heading-action"><div><p class="eyebrow">双向选择 / {{ candidate ? '我的进展' : '招聘进展' }}</p><h1>{{ candidate ? '我的投递' : '应聘与邀请' }}</h1><p>{{ candidate ? '看见企业的回应，由你决定是否继续了解。' : '查看主动投递的材料，向希望进一步了解的人发出邀请。' }}</p></div><button class="secondary" :disabled="pending || loading" @click="load()"><RefreshCw :size="15" />刷新进展</button></div>
  <div class="hiring-toolbar"><label><span class="sr-only">搜索投递</span><input v-model="search" type="search" :placeholder="candidate ? '搜索岗位或企业' : '搜索岗位或求职者'" /></label><label><span class="sr-only">筛选进展</span><select v-model="filter"><option value="all">全部进展</option><option value="submitted">已投递</option><option value="invited">待回应邀请</option><option value="accepted">沟通中</option><option value="ended">已结束</option></select></label><span>{{ total }} 份投递</span></div>
  <div v-if="total > 30" class="button-row"><button class="secondary" :disabled="offset === 0 || loading || pending" @click="changePage(-1)">上一页</button><span>{{ offset + 1 }}–{{ Math.min(offset + 30,total) }} / {{ total }}</span><button class="secondary" :disabled="offset + 30 >= total || loading || pending" @click="changePage(1)">下一页</button></div>
  <div v-if="!rows.length" class="empty surface"><MessageSquare :size="32" /><h3>{{ candidate ? '从一个你想了解的岗位开始' : '这里会收到求职者主动投递的简历' }}</h3><p>{{ candidate ? '查看认证企业的公开岗位，选择简历并确认授权后投递。' : '在岗位与需求中确认并公开岗位，求职者才能查看和投递。' }}</p><RouterLink to="/jobs" class="button primary">{{ candidate ? '查看企业岗位' : '管理并公开岗位' }}<ArrowUpRight :size="16" /></RouterLink></div>
  <div v-else class="hiring-layout">
    <section class="surface hiring-list" aria-label="投递列表">
      <p v-if="!visible.length" class="muted">没有符合筛选条件的投递。</p>
      <button v-for="r in visible" :key="r.id" :class="['hiring-row', { selected: selected?.id === r.id }]" :disabled="pending || loading" @click="open(r.id)">
        <span :class="['pill', { teal: r.status === 'accepted', amber: r.status === 'invited' }]">{{ applicationLabels[r.status] }}</span>
        <strong>{{ candidate ? r.job_title : r.candidate_name }}</strong><p>{{ candidate ? r.company_name || '认证企业' : r.job_title }}</p>
        <span v-if="!candidate && r.review_strengths?.length" class="hiring-strength-tags"><span v-for="tag in r.review_strengths.slice(0,3)" :key="tag">{{ tag }}</span></span>
        <p v-else-if="!candidate && r.resume_shared" class="hiring-card-state">{{ r.review_ready ? '资料卡已生成 · 可继续了解' : '可查看授权原文或生成资料卡' }}</p>
        <small>{{ date(r.updated_at) }} · {{ r.message_count }} 条沟通消息</small>
      </button>
    </section>
    <section v-if="loading" class="surface hiring-detail"><p class="muted">正在读取投递记录…</p></section>
    <section v-else-if="selected" class="surface hiring-detail">
      <header class="hiring-detail-heading"><div><p class="eyebrow">{{ selected.company_name || '认证企业' }} · {{ candidate ? '我投递的岗位' : '主动投递的求职者' }}</p><h2>{{ candidate ? selected.job_title : selected.candidate_name }}</h2><p>{{ candidate ? '简历：' + selected.resume_name : '应聘岗位：' + selected.job_title }}</p></div><span :class="['pill', { teal: selected.status === 'accepted', amber: selected.status === 'invited' }]">{{ applicationLabels[selected.status] }}</span></header>
      <p v-if="!selected.available" class="notice">岗位或账号已被暂停，当前无法继续沟通。你仍可查看自己的投递记录{{ candidate && !ended(selected.status) ? '或撤回投递' : '' }}。</p>
      <RouterLink v-if="!candidate && selected.resume_shared && selected.available" :to="{ path: '/recruiter-ai', query: { application: selected.id } }" class="text-link" style="margin-top:18px">进入招聘 AI 工作区 · 整理经历与面试追问<ArrowUpRight :size="15" /></RouterLink>
      <RecruiterProfile v-if="!candidate && selected.resume_shared && selected.available" :key="selected.id" :application="selected" @analyzed="load(true)" />
      <div class="hiring-actions"><template v-if="!ended(selected.status) && selected.available"><template v-if="candidate"><button v-if="selected.status === 'invited'" class="primary" :disabled="pending" @click="prepare('accept')"><Check :size="16" />接受沟通邀请</button><button v-if="selected.status === 'invited'" class="secondary" :disabled="pending" @click="prepare('decline')">婉拒邀请</button></template><template v-else><button v-if="selected.status === 'submitted'" class="primary" :disabled="pending" @click="prepare('invite')">邀请沟通<ArrowUpRight :size="16" /></button><button v-if="['submitted','invited'].includes(selected.status)" class="secondary" :disabled="pending" @click="prepare('reject')">暂不推进</button></template><button v-if="selected.status === 'accepted'" class="secondary" :disabled="pending" @click="prepare('close')">结束沟通</button></template><button v-if="candidate && !ended(selected.status)" class="text-link danger-link" :disabled="pending" @click="prepare('withdraw')">撤回投递与授权</button></div>
      <article v-if="selected.invitation" class="hiring-invitation"><p class="eyebrow">企业的沟通邀请 · {{ date(selected.invitation.created_at) }}</p><p class="source-text">{{ selected.invitation.text }}</p></article>
      <section class="hiring-section"><h3><Clock3 :size="17" />双方进展</h3><ol class="hiring-timeline"><li v-for="(event,i) in selected.events" :key="i"><span :class="['hiring-side', event.side]">{{ event.side === 'candidate' ? '求职者' : '企业' }}</span><div><strong>{{ eventLabels[event.action] || event.action }}</strong><p v-if="event.text">{{ event.text }}</p></div><time>{{ date(event.created_at) }}</time></li></ol></section>
      <section class="hiring-section"><h3><FileText :size="17" />{{ candidate ? '本次投递的简历' : '已授权的简历' }}</h3><p class="muted">使用投递时保存的版本，之后修改个人简历不会改变本次投递。</p><ApplicationResumeActions v-if="!candidate" :key="selected.id" :application="selected" /><ResumeAttachment v-if="selected.resume_snapshot" :key="selected.id" :name="selected.resume_snapshot.name" :text="selected.resume_snapshot.text"><p v-if="selected.resume_snapshot.revision_kind" class="muted">本人修改或优化版本，补充内容尚未外部核验。</p></ResumeAttachment><p v-else class="notice">这份投递已结束或授权暂不可用，企业不能继续查看简历正文及个人偏好。</p><p v-if="selected.introduction" class="hiring-introduction">投递留言：{{ selected.introduction }}</p><details class="hiring-resume"><summary>查看本次投递的岗位要求 · v{{ selected.job_snapshot.version }}</summary><p class="source-text">{{ selected.job_snapshot.text }}</p></details></section>
      <section class="hiring-section"><div class="row-between"><h3>双方期待</h3></div><p class="muted">{{ selected.preference_notice }}</p><RouterLink v-if="!ended(selected.status)" to="/preferences" class="text-link" @click="candidate ? state.resumeId = selected.resume_id || '' : state.jobId = selected.job_id">管理我的期待与公开范围 →</RouterLink><div v-if="expectationRows.length" class="hiring-expectations"><article v-for="d in expectationRows" :key="d.dimension_id"><h4>{{ d.name }}</h4><div><p><small>企业期待</small>{{ d.ent_quote }}</p><p><small>个人期待</small>{{ d.cand_quote }}</p></div><small>{{ d.unmatched_reason || (d.ent_quote === d.cand_quote ? '双方选择相同，可进一步了解具体安排。' : '双方选择有所不同，可以在沟通中了解原意。') }}</small></article></div><p v-if="selected.enterprise_preferences?.ambience_text" class="hiring-introduction">企业填写的团队氛围：{{ selected.enterprise_preferences.ambience_text }}</p></section>
      <section class="hiring-section hiring-message-entry"><div class="row-between"><h3><MessageSquare :size="17" />双方沟通<span v-if="selected.unread_count" class="pill amber">{{ selected.unread_count }} 条未读</span></h3><RouterLink :to="{ path: '/messages', query: { application: selected.id } }" class="button primary">{{ selected.status === 'invited' ? '查看邀请与沟通' : '进入消息中心' }}<ArrowUpRight :size="17" /></RouterLink></div><p class="muted">{{ selected.status === 'accepted' ? '在独立聊天区沟通，随时查看岗位、已授权简历和双方期待。' : '邀请和历史消息在消息中心查看；接受邀请后可开始聊天。' }}</p><p v-if="selected.last_message" class="hiring-last-message">{{ selected.last_message.side === 'candidate' ? '求职者' : '企业' }}：{{ selected.last_message.text }}</p></section>
    </section>
  </div>
  </template>
  <div v-if="modal" class="modal-backdrop" @click.self="!pending && (modal = null)"><section v-dialog class="modal" role="dialog" aria-modal="true" aria-labelledby="hiring-action-title"><header class="detail-heading"><h2 id="hiring-action-title">{{ modalTitles[modal.action] }}</h2><button class="icon-button" :disabled="pending" aria-label="关闭投递操作" @click="modal = null"><X :size="19" /></button></header><form @submit.prevent="confirm"><p v-if="modal.action === 'withdraw'" class="muted">撤回后，这个岗位的企业不能继续查看本次授权的简历正文和个人偏好。双方进展与已交换的沟通消息保留。</p><p v-else-if="modal.action === 'accept'" class="muted">接受后双方可以在本次投递下沟通。接受邀请仅表示愿意进一步了解岗位。</p><p v-else-if="modal.action === 'refresh_preferences'" class="muted">将你最新保存并同意共享的期待同步到本次投递，对方可查看。不会替对方更改期待。</p><label v-if="!['accept','refresh_preferences'].includes(modal.action)">{{ modal.action === 'invite' ? '邀请内容' : '说明（可选）' }}<textarea v-model="modal.text" rows="5" maxlength="2000" :required="modal.action === 'invite'" :minlength="modal.action === 'invite' ? 2 : undefined" :disabled="pending" :placeholder="modal.action === 'invite' ? '说明希望了解的经历、沟通方式及可商量的时间。' : '可以简要说明你的考虑。'" /></label><div class="form-footer"><button type="button" class="secondary" :disabled="pending" @click="modal = null">取消</button><button class="primary" :disabled="pending">{{ pending ? '正在保存…' : modalTitles[modal.action] }}</button></div></form></section></div>
</template>

<style scoped>

.hiring-detail .resume-attachment{padding:0;overflow:hidden;background:var(--surface-paper);border-color:var(--brand-edge);border-radius:10px}
.hiring-detail .resume-attachment>summary{display:flex;align-items:center;gap:14px;list-style:none;margin:0;padding:16px;border:0;border-radius:9px;background:var(--surface-paper);color:var(--text-main);transition:background .18s ease}
.resume-attachment>summary::-webkit-details-marker{display:none}
.hiring-detail .resume-attachment>summary:hover{background:var(--brand-faint)}
.hiring-detail .resume-attachment>summary:focus-visible{outline-offset:-3px}
.resume-attachment-icon{display:flex;align-items:center;justify-content:center;flex:0 0 48px;height:54px;border:1px solid var(--brand-edge);border-radius:9px;background:var(--brand-soft);color:var(--brand-ink)}
.resume-attachment-info{display:flex;flex-direction:column;gap:5px;flex:1;min-width:0}
.resume-attachment-info strong{font-size:14px;line-height:1.6;overflow-wrap:anywhere;color:var(--text-main)}
.resume-attachment-info>span{font-size:11px;color:var(--text-muted)}
.resume-attachment-action{display:flex;align-items:center;gap:7px;flex-shrink:0;font-size:12px;color:var(--brand-ink)}
.resume-attachment-action svg{transition:transform .18s ease}
.resume-attachment .attachment-close-label,.resume-attachment[open] .attachment-open-label{display:none}
.resume-attachment[open] .attachment-close-label{display:inline}
.resume-attachment[open] .resume-attachment-action svg{transform:rotate(180deg)}
.resume-attachment-content{border-top:1px solid var(--border-soft);padding:4px 18px 18px}
@media(max-width:600px){.hiring-detail .resume-attachment>summary{flex-wrap:wrap;gap:10px;padding:14px}.resume-attachment-icon{flex-basis:40px;height:46px}.resume-attachment-info{flex-basis:calc(100% - 50px)}.resume-attachment-action{margin-left:50px}.resume-attachment-info strong{font-size:13px}.resume-attachment-content{padding:4px 14px 16px}}
@media(prefers-reduced-motion:reduce){.hiring-detail .resume-attachment>summary,.resume-attachment-action svg{transition:none}}

.hiring-strength-tags{display:flex;gap:5px;flex-wrap:wrap;margin:10px 0}.hiring-strength-tags>span{font-size:11px;padding:3px 6px;border-radius:4px;color:var(--brand-ink);background:var(--brand-soft);overflow-wrap:anywhere}.hiring-row .hiring-card-state{font-size:11px;margin:9px 0;color:var(--muted)}
.hiring-toolbar{display:flex;align-items:center;gap:14px;margin-bottom:20px;flex-wrap:wrap}.hiring-toolbar>label:first-child{width:300px}.hiring-toolbar select{min-width:160px}.hiring-toolbar>span{margin-left:auto;font-size:12px;color:var(--muted)}
.hiring-layout{display:grid;grid-template-columns:300px minmax(0,1fr);gap:24px;align-items:start}.hiring-list{padding:9px;max-height:calc(100dvh - 230px);overflow:auto;position:sticky;top:20px}.hiring-list>.muted{padding:18px}.hiring-row{display:block;width:100%;text-align:left;padding:17px 15px;border-radius:8px;border:1px solid transparent;margin-bottom:5px}.hiring-row.selected{background:var(--brand-faint);border-color:var(--brand-edge)}.hiring-row:hover{background:var(--brand-faint)}.hiring-row strong{display:block;font-size:15px;margin-top:11px;overflow-wrap:anywhere}.hiring-row p{font-size:12px;color:var(--muted);margin:5px 0}.hiring-row small{font-size:10px;color:var(--muted)}
.hiring-detail{padding:27px 30px;min-width:0}.hiring-detail-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:18px}.hiring-detail-heading h2{font-size:25px;margin:7px 0}.hiring-detail-heading p:last-child{font-size:12px;color:var(--muted)}.hiring-actions{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:18px 0 24px}.hiring-actions .text-link{font-size:12px}.hiring-invitation{padding:18px 20px;background:var(--brand-soft);border-left:3px solid var(--brand-focus);border-radius:0 8px 8px 0}.hiring-invitation .source-text{font-size:13px;margin-top:8px}.hiring-section{border-top:1px solid var(--line);padding-top:22px;margin-top:25px}.hiring-section h3{display:flex;align-items:center;gap:8px;font-size:15px}.hiring-section>.muted{font-size:12px;margin:9px 0 13px}.hiring-section>.text-link{font-size:12px;margin:7px 0 13px}
.hiring-timeline{list-style:none;padding:0;margin:18px 0 0}.hiring-timeline li{display:flex;gap:14px;padding:13px 0;border-bottom:1px solid var(--surface-soft);align-items:flex-start}.hiring-side{font-size:10px;min-width:48px;padding:3px 6px;border-radius:4px;background:var(--surface-soft);color:#767065;text-align:center}.hiring-side.enterprise{background:var(--brand-soft);color:var(--text-muted)}.hiring-timeline li>div{flex:1;min-width:0}.hiring-timeline strong{font-size:12px}.hiring-timeline p{font-size:12px;color:var(--muted);white-space:pre-wrap;overflow-wrap:anywhere;margin-top:4px}.hiring-timeline time{font-size:10px;font-family:Consolas,monospace;color:var(--muted);white-space:nowrap}
.hiring-resume{margin-top:14px;padding:13px 15px;border:1px solid var(--line);border-radius:7px}.hiring-resume summary{font-size:12px;cursor:pointer;color:var(--brand-ink)}.hiring-resume .source-text{margin-top:15px;font-size:13px}.hiring-resume .muted{font-size:11px;margin-top:12px}.hiring-introduction{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.9;margin-top:15px}.hiring-section .row-between>.text-link{font-size:11px}.hiring-expectations{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}.hiring-expectations article{padding:15px;background:var(--brand-faint);border-radius:8px}.hiring-expectations h4{font-size:12px;margin-bottom:11px}.hiring-expectations article>div{display:grid;grid-template-columns:1fr 1fr;gap:12px}.hiring-expectations p{font-size:12px;overflow-wrap:anywhere}.hiring-expectations p>small{display:block;font-size:10px;margin-bottom:5px;color:var(--muted)}.hiring-expectations article>small{display:block;font-size:10px;color:var(--muted);margin-top:12px}.hiring-messages{max-height:460px;overflow:auto;scrollbar-width:thin;margin-top:16px}.hiring-messages article{padding:14px 16px;border-radius:8px;background:var(--brand-soft);margin:12px 24px 12px 0}.hiring-messages article.candidate{background:var(--surface-soft);margin:12px 0 12px 24px}.hiring-messages small{font-size:10px;color:var(--muted)}.hiring-messages p{font-size:13px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere}.hiring-composer{margin-top:16px}.hiring-composer>.primary{margin:12px 0 0 auto;display:flex}
@media(max-width:1100px){.hiring-layout{grid-template-columns:240px minmax(0,1fr);gap:16px}.hiring-detail{padding:23px 20px}.hiring-expectations{grid-template-columns:1fr}}
@media(max-width:760px){.hiring-layout{grid-template-columns:1fr}.hiring-list{position:static;max-height:280px}.hiring-toolbar>label:first-child{width:100%}.hiring-toolbar>span{margin-left:0;font-size:11px}.hiring-detail{padding:20px 16px}.hiring-detail-heading{flex-wrap:wrap}.hiring-detail-heading h2{font-size:21px}.hiring-timeline li{gap:8px;flex-wrap:wrap}.hiring-timeline time{margin-left:56px}.hiring-section .row-between{flex-wrap:wrap;gap:10px}}
</style>
