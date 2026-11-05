<script setup lang="ts">
import ResumeAttachment from "../components/ResumeAttachment.vue"
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Sparkles, RefreshCw, ArrowUpRight, Maximize2, Minimize2, Search, Users, MessagesSquare, ChevronDown, Check, X } from '@lucide/vue'
import { api, ApiError, state } from '../store'
import { ended, type ApplicationSummary, type ApplicationDetail } from '../hiring'
import RecruiterChat from '../components/RecruiterChat.vue'
import RecruiterProfile from '../components/RecruiterProfile.vue'
import RecruiterResults from '../components/RecruiterResults.vue'
import ApplicationResumeActions from '../components/ApplicationResumeActions.vue'
import type { RecruiterConversation, RecruiterAction, RecruiterPlanQuestion } from '../recruiter-assistant'
const route = useRoute(); const router = useRouter()
const rows = ref<ApplicationSummary[]>([]); const selected = ref<ApplicationDetail | null>(null)
const query = ref(''); const historyOnly = ref(false); const loading = ref(true); const busy = ref(false); const error = ref('')
const tab = ref<'chat' | 'profile' | 'materials' | 'results'>('chat')
const conversation = ref<RecruiterConversation | null>(null)
const chat = ref<InstanceType<typeof RecruiterChat> | null>(null)
const chatToolbarTarget = ref<HTMLElement | null>(null)
const resultsPanel = ref<InstanceType<typeof RecruiterResults> | null>(null)
const resultUpdated = ref(false)
function requestAnalysis(action: RecruiterAction) { tab.value = 'chat'; void chat.value?.send(action) }
function showResults() { tab.value = 'results'; resultUpdated.value = false }
async function savePlan(questions: RecruiterPlanQuestion[], notes: string) { if (await chat.value?.savePlan(questions, notes)) { await nextTick(); resultsPanel.value?.resetToSaved() } }
const focused = ref(false)
watch(focused, value => { state.aiFocus = value })
const candidatesOpen = ref(false)
const candidateMedia = window.matchMedia('(max-width:1180px)')
const compactCandidates = ref(candidateMedia.matches)
function changeCandidateLayout(event: MediaQueryListEvent) { compactCandidates.value = event.matches; candidatesOpen.value = false }
const candidateToggle = ref<HTMLButtonElement | null>(null)
const authorized = computed(() => rows.value.filter(r => r.resume_shared && r.available && !ended(r.status)))
const historyCount = computed(() => authorized.value.filter(r => !!r.ai_message_count).length)
async function toggleCandidates() {
  candidatesOpen.value = !candidatesOpen.value
  if (candidatesOpen.value) { await nextTick(); document.getElementById('recruiter-ai-search')?.focus() }
}
async function closeCandidates() { if (candidatesOpen.value) { candidatesOpen.value = false; await nextTick(); candidateToggle.value?.focus() } }

const visible = computed(() => authorized.value.filter(r => (!historyOnly.value || !!r.ai_message_count)
  && `${r.candidate_name} ${r.job_title}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))
let alive = true; let sequence = 0
function fail(e: unknown) { if (!(e instanceof ApiError && ['AUTH_REQUIRED','STALE_CONTEXT'].includes(e.code))) error.value = e instanceof Error ? e.message : '工作区暂时无法连接，请重试。' }
async function open(id: string) {
  if (busy.value) return
  const ticket = ++sequence; loading.value = true; selected.value = null; conversation.value = null; error.value = ''
  try {
    const result = await api<ApplicationDetail>(`/applications/${id}`)
    if (!alive || ticket !== sequence) return
    if (!result.resume_shared || !result.available || ended(result.status)) throw new Error('这份投递的简历授权已结束或暂停，请选择其他投递。')
    selected.value = result; tab.value = 'chat'; resultUpdated.value = false; closeCandidates()
    if (route.query.application !== id) await router.replace({ path: '/recruiter-ai', query: { application: id } })
  } catch (e) { if (alive && ticket === sequence) fail(e) }
  finally { if (alive && ticket === sequence) loading.value = false }
}
async function list() {
  if (busy.value) return
  error.value = ''
  try {
    const result = await api<ApplicationSummary[]>('/applications')
    if (!alive) return
    rows.value = result
    if (!selected.value) { const id = typeof route.query.application === 'string' ? route.query.application : visible.value[0]?.id; if (id) await open(id) }
  } catch (e) { if (alive) fail(e) }
  finally { if (alive) loading.value = false }
}
function unavailable() { const id = selected.value?.id; selected.value = null; rows.value = rows.value.filter(r => r.id !== id); busy.value = false; error.value = '这份投递的授权或访问权限已变化，请刷新投递后重新选择。' }
function updateHistory(count: number) { const row = rows.value.find(r => r.id === selected.value?.id); if (row) row.ai_message_count = count }
watch(() => route.query.application, id => { if (typeof id === 'string' && id !== selected.value?.id) void open(id) })
onMounted(() => { void list(); candidateMedia.addEventListener('change', changeCandidateLayout) })
onUnmounted(() => { alive = false; sequence++; state.aiFocus = false; candidateMedia.removeEventListener('change', changeCandidateLayout) })
</script>

<template>
  <div :class="['recruiter-ai-page', { 'recruiter-ai-focused': focused, 'recruiter-ai-selecting': candidatesOpen }]" @keydown.esc="closeCandidates">
    <h1 v-if="selected && !focused" class="sr-only">招聘 AI 工作区</h1>
    <header v-if="!selected || focused" class="recruiter-ai-heading">
      <div class="recruiter-ai-title"><span class="recruiter-ai-mark" aria-hidden="true"><Sparkles :size="20" /></span><div><h1>招聘 AI 工作区</h1></div></div>
      <div class="recruiter-ai-heading-actions">
        <button v-if="!focused" class="secondary" aria-label="刷新投递" title="刷新投递" :disabled="busy || loading" @click="list"><RefreshCw :size="14" /><span>刷新投递</span></button>
        <button v-if="selected" class="secondary" :aria-pressed="focused" @click="focused = !focused; candidatesOpen = false; tab = 'chat'"><component :is="focused ? Minimize2 : Maximize2" :size="14" />{{ focused ? '返回工作台' : '专注对话' }}</button>
      </div>
    </header>
    <p v-if="error" class="notice recruiter-ai-error" role="alert">{{ error }}</p>
    <div class="recruiter-ai-layout">
      <aside id="recruiter-ai-candidates" class="recruiter-ai-candidates" aria-label="选择招聘 AI 的投递材料" :inert="focused || compactCandidates && !candidatesOpen">
        <header>
          <div class="recruiter-list-title"><h2>材料与候选人</h2><span>{{ authorized.length }} 份授权投递</span><button v-if="compactCandidates" class="icon-button" aria-label="收起候选人列表" @click="closeCandidates"><X :size="15" /></button></div>
          <div class="recruiter-candidate-search"><Search :size="15" aria-hidden="true" /><label class="sr-only" for="recruiter-ai-search">搜索姓名或岗位</label><input id="recruiter-ai-search" v-model="query" type="search" placeholder="搜索姓名或岗位" /></div>
          <div class="recruiter-list-filter" role="group" aria-label="投递对话筛选"><button type="button" :aria-pressed="!historyOnly" @click="historyOnly = false">全部投递</button><button type="button" :aria-pressed="historyOnly" @click="historyOnly = true">已有对话 <span>{{ historyCount }}</span></button></div>
        </header>
        <section v-if="selected" class="recruiter-current-materials" aria-label="当前投递的材料"><h3>本次对话材料</h3><ResumeAttachment v-if="selected.resume_snapshot" :key="selected.id" :name="selected.resume_snapshot.name" :text="selected.resume_snapshot.text" /><details><summary>岗位原文</summary><div class="recruiter-source-preview"><strong>{{ selected.job_title }}</strong><p>{{ selected.job_snapshot.text }}</p></div><button class="text-link" @click="tab = 'materials'">放大阅读岗位</button></details></section>
        <div class="recruiter-ai-candidate-list">
          <p v-if="loading && !rows.length" class="recruiter-ai-list-empty">正在读取投递…</p><p v-else-if="!visible.length" class="recruiter-ai-list-empty">{{ historyOnly ? '暂无符合条件的 AI 对话。' : '暂无符合条件的已授权投递。' }}</p>
          <button v-for="r in visible" :key="r.id" class="recruiter-candidate" type="button" :disabled="busy || loading" :aria-pressed="selected?.id === r.id" @click="open(r.id)">
            <span class="recruiter-candidate-avatar" aria-hidden="true">{{ r.candidate_name.slice(0,1) }}</span>
            <span class="recruiter-candidate-copy"><strong>{{ r.candidate_name }}</strong><span>{{ r.job_title }}</span><small><MessagesSquare :size="12" />{{ r.ai_message_count ? '已有 AI 对话 · ' + r.ai_message_count + ' 条' : '尚未开始 AI 对话' }}</small></span>
            <Check v-if="selected?.id === r.id" class="recruiter-candidate-check" :size="14" aria-hidden="true" />
          </button>
        </div>
        <footer><RouterLink to="/applications" class="text-link">查看全部投递<ArrowUpRight :size="14" /></RouterLink><p>对话与提纲按投递保存</p></footer>
      </aside>
      <section v-if="selected" class="recruiter-ai-content" :aria-busy="loading">
        <header class="recruiter-ai-subject"><button v-if="!focused && compactCandidates" ref="candidateToggle" class="secondary recruiter-candidate-toggle" aria-label="切换候选人" :aria-expanded="candidatesOpen" aria-controls="recruiter-ai-candidates" @click="toggleCandidates"><Users :size="15" /><span>切换候选人</span><ChevronDown :size="12" /></button><span class="recruiter-subject-avatar" aria-hidden="true">{{ selected.candidate_name.slice(0,1) }}</span><div class="recruiter-subject-name"><h2 :title="selected.candidate_name">{{ selected.candidate_name }}</h2><p :title="selected.job_title">{{ selected.job_title }}</p></div><div ref="chatToolbarTarget" v-show="tab === 'chat' || tab === 'results'" class="recruiter-subject-toolbar" /><div class="recruiter-subject-actions"><RouterLink :to="{ path: '/applications', query: { application: selected.id } }" class="text-link recruiter-header-action">查看投递<ArrowUpRight :size="14" /></RouterLink><button v-if="!focused" class="secondary recruiter-header-action" aria-label="专注对话" @click="focused = true; candidatesOpen = false; tab = 'chat'"><Maximize2 :size="14" /><span>专注对话</span></button></div></header>
        <div class="recruiter-ai-tabs" role="group" aria-label="招聘 AI 工作区视图"><button type="button" :aria-pressed="tab === 'chat'" @click="tab = 'chat'">AI 对话</button><button type="button" :aria-pressed="tab === 'profile'" @click="tab = 'profile'" aria-label="资料卡与技术图谱">资料卡 / 技术图谱</button><button type="button" :aria-pressed="tab === 'materials'" @click="tab = 'materials'">授权材料</button><button type="button" aria-label="分析与面试提纲" :aria-pressed="tab === 'results'" @click="showResults">分析与面试提纲<span v-if="resultUpdated" class="recruiter-result-dot" aria-label="有新分析结果" /></button></div>
        <div v-show="tab === 'chat' || tab === 'results'" :class="['recruiter-ai-workbench', { 'workbench-results': tab === 'results' }]">
          <RecruiterChat ref="chat" :key="selected.id" :application="selected" :toolbar-target="chatToolbarTarget" @busy="busy = $event" @unavailable="unavailable" @history="updateHistory" @change="conversation = $event" @results="resultUpdated = true" @review="showResults" />
          <RecruiterResults ref="resultsPanel" :key="selected.id + '-results'" :conversation="conversation" :busy="busy" :expanded="tab === 'results'" @expand="tab = tab === 'results' ? 'chat' : 'results'" :name="selected.candidate_name" :job="selected.job_title" @request="requestAnalysis" @save="savePlan" />
        </div>
        <div v-if="tab === 'profile'" class="recruiter-ai-profile"><RecruiterProfile :key="selected.id" :application="selected" /></div>
        <div v-if="tab === 'materials'" class="recruiter-ai-materials"><header class="recruiter-materials-heading"><h3>本次投递的授权材料</h3><p>对话和分析使用这次投递保留的版本。</p></header><ApplicationResumeActions :key="selected.id" :application="selected" /><section><h4>求职者简历</h4><p class="source-text">{{ selected.resume_snapshot?.text }}</p></section><section><h4>投递时的岗位要求</h4><p class="source-text">{{ selected.job_snapshot.text }}</p></section></div>
      </section>
      <section v-else class="recruiter-ai-empty"><Sparkles :size="30" /><h2>{{ loading ? '正在读取工作区…' : '选择一份已授权的投递简历' }}</h2><p>逐一了解每位求职者的技术经历，整理值得沟通的问题。</p><button v-if="visible.length" class="secondary recruiter-empty-select" @click="toggleCandidates">选择候选人<Users :size="15" /></button><RouterLink to="/applications" class="text-link">前往应聘与邀请<ArrowUpRight :size="15" /></RouterLink></section>
    </div>
  </div>
</template>

<style scoped>
.recruiter-ai-page{--recruiter-ink:#3a362d;min-width:0;min-height:0;display:flex;flex:1;flex-direction:column}
.recruiter-ai-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px;flex-shrink:0}
.recruiter-ai-title{display:flex;align-items:center;gap:9px;min-width:0}.recruiter-ai-mark{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;background:var(--brand-soft);color:var(--brand-ink)}
.recruiter-ai-heading h1{font-family:MiSans,'Microsoft YaHei',sans-serif;font-size:18px;line-height:1.6;letter-spacing:0;color:var(--recruiter-ink)}
.recruiter-ai-heading-actions{display:flex;gap:8px;flex-shrink:0}.recruiter-ai-heading-actions .secondary{min-height:32px;padding:6px 10px;font-size:11px}
.recruiter-ai-error{margin:0 0 12px;max-height:100px;overflow:auto;flex-shrink:0}
.recruiter-ai-layout{display:grid;grid-template-columns:214px minmax(0,1fr);grid-template-rows:minmax(0,1fr);flex:1;min-width:0;min-height:0;overflow:hidden;background:white;border:1px solid var(--border-soft);border-radius:13px;box-shadow:0 4px 18px #3f3b3304}
.recruiter-ai-candidates{display:flex;min-width:0;min-height:0;flex-direction:column;background:var(--brand-faint);border-right:1px solid var(--border-soft)}
.recruiter-ai-selecting .recruiter-ai-layout{grid-template-columns:214px minmax(0,1fr)}.recruiter-ai-selecting .recruiter-ai-candidates{display:flex}
.recruiter-ai-candidates>header{padding:12px 11px 11px;border-bottom:1px solid var(--border-soft);flex-shrink:0}
.recruiter-list-title{display:flex;align-items:center;gap:5px;margin-bottom:11px;flex-wrap:wrap}.recruiter-list-title h2{font-size:13px}.recruiter-list-title>span{margin-left:auto;font-size:10px;color:var(--text-muted)}.recruiter-list-title .icon-button{padding:4px;min-height:26px;min-width:26px}
.recruiter-candidate-search{position:relative}.recruiter-candidate-search>svg{position:absolute;left:11px;top:12px;color:var(--text-muted)}.recruiter-candidate-search input{padding-left:33px;font-size:12px;min-height:39px}
.recruiter-list-filter{display:flex;gap:5px;margin-top:12px;padding:3px;border:1px solid var(--border-soft);background:var(--surface-soft);border-radius:8px}.recruiter-list-filter button{flex:1;font-size:11px;padding:6px 4px;border:1px solid transparent;border-radius:6px;color:var(--text-muted)}.recruiter-list-filter button[aria-pressed=true]{background:#fff;color:var(--brand-ink);border-color:var(--brand-edge);font-weight:600}.recruiter-list-filter span{margin-left:4px}
.recruiter-ai-candidate-list{overflow:auto;flex:1;min-height:0;overscroll-behavior:contain;scrollbar-width:thin;padding:10px}.recruiter-candidate{display:flex;align-items:flex-start;gap:10px;width:100%;position:relative;padding:12px 9px;margin-bottom:7px;text-align:left;border:1px solid transparent;border-radius:9px}.recruiter-candidate[aria-pressed=true]{background:var(--brand-soft);border-color:var(--brand-edge);box-shadow:inset 3px 0 var(--brand)}.recruiter-candidate:hover:not(:disabled){background:var(--brand-soft);border-color:var(--brand-edge)}
.recruiter-candidate-avatar{display:grid;place-items:center;background:#fff;border:1px solid var(--border-soft);border-radius:8px;width:31px;height:35px;flex-shrink:0;color:var(--brand-ink);font-size:15px}.recruiter-candidate-copy{display:flex;flex-direction:column;gap:7px;min-width:0}.recruiter-candidate-copy strong{font-size:13px;line-height:1.7;overflow-wrap:anywhere;padding-right:9px;color:var(--recruiter-ink)}.recruiter-candidate-copy>span{font-size:11px;line-height:1.8;color:var(--text-muted)}.recruiter-candidate-copy small{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--text-muted)}.recruiter-candidate-check{position:absolute;right:8px;top:16px;color:var(--brand-ink)}
.recruiter-ai-candidates>footer{padding:12px 16px;border-top:1px solid var(--border-soft);flex-shrink:0}.recruiter-ai-candidates>footer .text-link{width:100%;font-size:11px;min-height:32px}.recruiter-ai-candidates>footer p{font-size:10px;line-height:1.8;color:var(--text-muted);margin-top:7px;text-align:center}.recruiter-ai-list-empty{padding:20px 12px;font-size:12px;line-height:1.9;color:var(--text-muted)}
.recruiter-ai-content{display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden;background:#fff}
.recruiter-ai-subject{display:flex;align-items:center;gap:12px;padding:13px 24px;border-bottom:1px solid var(--border-soft);flex-shrink:0}.recruiter-candidate-toggle{font-size:11px;padding:6px 9px;min-height:32px;flex-shrink:0;margin-right:3px}.recruiter-candidate-toggle[aria-expanded=true]{background:var(--brand-soft)}
.recruiter-subject-avatar{display:grid;place-items:center;width:32px;height:35px;border-radius:9px;background:var(--brand-soft);color:var(--brand-ink);font-size:17px;flex-shrink:0}.recruiter-ai-subject>.recruiter-subject-name{min-width:140px;flex:1}.recruiter-ai-subject h2{font-size:15px;line-height:1.6;letter-spacing:0;overflow-wrap:anywhere}.recruiter-ai-subject p{font-size:11px;line-height:1.7;color:var(--text-muted);margin-top:2px}.recruiter-subject-actions>.text-link{font-size:11px;min-height:31px;padding:5px 9px;flex-shrink:0}
.recruiter-ai-tabs{display:flex;gap:21px;padding:0 24px;background:#fff;border-bottom:1px solid var(--border-soft);flex-shrink:0;overflow-x:auto;scrollbar-width:thin}.recruiter-ai-tabs button{position:relative;font-size:12px;min-height:43px;padding:10px 1px;border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;color:var(--text-muted);box-shadow:none;flex-shrink:0;white-space:nowrap}.recruiter-ai-tabs button[aria-pressed=true]{color:var(--brand-ink);border-bottom-color:var(--brand);background:transparent;font-weight:650}.recruiter-ai-tabs button:hover{color:var(--brand-ink);background:var(--brand-faint)}.recruiter-result-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--brand);margin-left:7px;vertical-align:middle}
.recruiter-ai-workbench{display:grid;grid-template-columns:minmax(0,1fr) clamp(288px,23vw,350px);grid-template-rows:minmax(0,1fr);flex:1;min-width:0;min-height:0;overflow:hidden}.recruiter-ai-workbench>.recruiter-results{display:flex;border-left:1px solid var(--border-soft)}.recruiter-ai-workbench.workbench-results{grid-template-columns:minmax(0,1fr)}.recruiter-ai-workbench.workbench-results>.recruiter-results{border-left:0}.recruiter-ai-workbench.workbench-results>.recruiter-chat{display:none}.recruiter-ai-content :deep(.recruiter-chat){flex:1;min-height:0}
.recruiter-ai-profile,.recruiter-ai-materials{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;scrollbar-width:thin}.recruiter-ai-profile{padding:0 24px 24px}.recruiter-ai-profile :deep(.recruiter-profile){max-width:1100px;margin:24px auto 0;border:0;padding:0;box-shadow:none}.recruiter-ai-profile :deep(.profile-header),.recruiter-ai-profile :deep(.profile-actions){flex-wrap:wrap;gap:12px}
.recruiter-ai-materials{padding:28px max(24px,calc((100% - 1000px)/2))}.recruiter-materials-heading{padding-bottom:18px;margin-bottom:20px;border-bottom:1px solid var(--border-soft)}.recruiter-materials-heading h3{font-size:18px}.recruiter-materials-heading p{font-size:12px;color:var(--text-muted);line-height:1.9;margin-top:6px}.recruiter-ai-materials section{margin-bottom:28px}.recruiter-ai-materials h4{font-size:14px;margin-bottom:12px}.recruiter-ai-materials .source-text{padding:22px;border:1px solid var(--border-soft);border-left:3px solid var(--brand-edge);border-radius:8px;background:var(--surface-soft);white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:2}
.recruiter-ai-empty{padding:40px;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;gap:18px;min-width:0;min-height:0;color:var(--brand-ink)}.recruiter-ai-empty h2{font-size:21px;color:var(--recruiter-ink)}.recruiter-ai-empty p{font-size:14px;line-height:1.9;color:var(--text-muted)}.recruiter-empty-select{display:flex}
.recruiter-ai-focused .recruiter-ai-layout{grid-template-columns:minmax(0,1fr)}.recruiter-ai-focused .recruiter-ai-candidates{display:none}.recruiter-ai-focused .recruiter-ai-workbench{grid-template-columns:minmax(0,1fr)}.recruiter-ai-focused .recruiter-ai-workbench>.recruiter-results{display:none}
@media(max-width:1180px){.recruiter-ai-layout{grid-template-columns:minmax(0,1fr)}.recruiter-ai-candidates{display:none}.recruiter-ai-selecting .recruiter-ai-layout{grid-template-columns:minmax(0,1fr)}.recruiter-ai-selecting .recruiter-ai-content,.recruiter-ai-selecting .recruiter-ai-empty{display:none}.recruiter-ai-candidates{border:0}.recruiter-ai-selecting .recruiter-candidate{padding:16px;gap:12px}.recruiter-ai-subject{padding-inline:17px}.recruiter-ai-tabs{padding-inline:17px;gap:17px}}
@media(max-width:600px){.recruiter-ai-heading{gap:8px;margin-bottom:9px}.recruiter-ai-mark{display:none}.recruiter-ai-heading h1{font-size:16px;white-space:nowrap}.recruiter-ai-heading-actions{gap:6px}.recruiter-ai-heading-actions .secondary{font-size:10px;min-height:30px;padding:5px 7px;gap:4px}.recruiter-ai-heading-actions .secondary>span{display:none}.recruiter-ai-layout{border-radius:10px}.recruiter-ai-subject{padding:12px;gap:8px;flex-wrap:wrap}.recruiter-candidate-toggle{font-size:10px;min-height:28px;padding:5px 6px;margin-right:0}.recruiter-candidate-toggle>span{display:none}.recruiter-subject-avatar{width:27px;height:30px;font-size:15px}.recruiter-ai-subject h2{font-size:13px}.recruiter-ai-subject p{font-size:10px}.recruiter-subject-actions>.text-link{font-size:10px;min-height:28px;padding:4px 6px;gap:3px}.recruiter-ai-tabs{padding-inline:12px;gap:15px}.recruiter-ai-tabs button{font-size:11px;min-height:39px;padding-block:9px}.recruiter-ai-materials{padding:20px 14px}.recruiter-ai-materials .source-text{padding:16px;font-size:13px}.recruiter-ai-profile{padding:0 14px 18px}.recruiter-ai-empty{padding:24px}.recruiter-ai-empty h2{font-size:18px}}
@media(prefers-reduced-motion:no-preference){.recruiter-ai-tabs button{transition:color .16s,border-color .16s}.recruiter-candidate{transition:background .16s,border-color .16s}}
.recruiter-subject-actions{display:flex;align-items:center;gap:8px;flex-shrink:0}.recruiter-subject-actions>.icon-button{min-width:31px;min-height:31px;padding:6px}.recruiter-subject-actions>.secondary{min-height:31px;padding:6px 9px;font-size:11px;gap:5px}.recruiter-ai-subject{padding-block:11px}
@media(max-width:600px){.recruiter-subject-actions{gap:5px}.recruiter-subject-actions>.secondary{min-height:28px;min-width:28px;padding:5px}.recruiter-subject-actions>.secondary span{display:none}.recruiter-subject-actions>.icon-button{display:none}.recruiter-subject-actions>.text-link{font-size:10px;min-height:28px;padding:4px 6px}.recruiter-ai-subject{padding-block:12px}}

.recruiter-current-materials{padding:12px 11px;border-bottom:1px solid var(--border-soft);max-height:42%;overflow:auto;scrollbar-width:thin;flex-shrink:0}.recruiter-current-materials h3{font-size:10px;font-weight:500;color:var(--text-muted);margin-bottom:9px}.recruiter-current-materials details{background:#fff;border:1px solid var(--border-soft);border-radius:7px;margin-top:7px;overflow:hidden}.recruiter-current-materials summary{cursor:pointer;font-size:12px;color:var(--text-main);line-height:1.8;padding:9px 10px;list-style-position:inside}.recruiter-current-materials summary>span{font-size:9px;color:#357b69;margin-left:7px}.recruiter-source-preview{padding:0 11px 11px}.recruiter-source-preview strong{font-size:11px;line-height:1.8}.recruiter-source-preview p{font-size:11px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere;margin-top:7px;max-height:180px;overflow:auto}.recruiter-current-materials .text-link{font-size:10px;margin:0 10px 10px;padding:4px 6px;min-height:26px}.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-chat-tools){padding:9px 16px;max-width:none}.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-chat-options){gap:5px}.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-chat-log){padding:24px max(20px,calc((100% - 840px)/2))}.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-composer){width:calc(100% - 32px);margin-inline:16px;margin-bottom:16px}.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-chat-message>p){font-size:14px;line-height:1.95}.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-context){width:calc(100% - 32px)}
@media(min-width:1181px) and (max-width:1440px){.recruiter-ai-layout{grid-template-columns:200px minmax(0,1fr)}.recruiter-ai-subject{padding-inline:18px}.recruiter-ai-tabs{padding-inline:18px;gap:16px}.recruiter-candidate-avatar{width:25px;height:29px;font-size:13px}.recruiter-candidate{gap:7px}.recruiter-candidate-copy strong{font-size:12px}.recruiter-candidate-copy small{font-size:9px}}
@media(max-width:980px){.recruiter-ai-workbench{grid-template-columns:minmax(0,1fr)}.recruiter-ai-workbench>.recruiter-results{display:none}.recruiter-ai-workbench.workbench-results>.recruiter-results{display:flex}.recruiter-current-materials{display:none}}
@media(max-width:600px){.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-chat-tools){padding:9px 12px}.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-chat-log){padding:20px 16px}.recruiter-ai-workbench:not(.workbench-results) :deep(.recruiter-composer){width:calc(100% - 24px);margin-inline:12px;margin-bottom:12px}}

.recruiter-ai-subject{gap:12px;flex-wrap:wrap}.recruiter-subject-name h2,.recruiter-subject-name p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.recruiter-subject-toolbar{min-width:0;flex:0 1 auto}.recruiter-subject-toolbar :deep(.recruiter-chat-tools){width:auto;max-width:none;margin:0;padding:0;border:0;gap:13px;flex-wrap:nowrap;justify-content:flex-end}.recruiter-subject-toolbar :deep(.recruiter-chat-tools>span){white-space:nowrap;flex-wrap:nowrap}.recruiter-subject-toolbar :deep(.recruiter-chat-options){flex-wrap:nowrap;gap:5px}.recruiter-subject-toolbar :deep(.recruiter-chat-tools .text-link){white-space:nowrap;font-size:10px;padding:4px 7px;min-height:29px}
@media(max-width:1600px){.recruiter-subject-toolbar :deep(.recruiter-chat-tools>span small){display:none}.recruiter-subject-toolbar :deep(.recruiter-chat-tools){gap:9px}.recruiter-subject-toolbar :deep(.recruiter-chat-tools>span){font-size:10px}}
@media(max-width:1320px){.recruiter-subject-toolbar{order:4;flex-basis:100%;padding-top:8px;border-top:1px solid var(--border-soft)}.recruiter-subject-toolbar :deep(.recruiter-chat-tools){justify-content:space-between}}
@media(max-width:600px){.recruiter-ai-subject{gap:8px}.recruiter-ai-subject>.recruiter-subject-name{min-width:80px}.recruiter-subject-toolbar{padding-top:9px}.recruiter-subject-toolbar :deep(.recruiter-chat-tools){flex-wrap:wrap;gap:7px}.recruiter-subject-toolbar :deep(.recruiter-chat-tools .text-link){font-size:10px;min-height:28px;padding:4px 6px}}
</style>
