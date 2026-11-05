<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { ArrowRight, ArrowUpRight, ArrowDown, BriefcaseBusiness, Check, ChevronLeft, ChevronRight, FileText, GitBranch, HeartHandshake, MessageSquare, Pause, Play, RotateCcw, Send, ShieldCheck, Sparkles, UserRound, Quote, CheckCheck } from '@lucide/vue'
import type { User, WorkspaceRole } from '../types'
import { storyPeople, editSteps, journeySteps } from '../public-story'
import { mountStoryMotion } from '../public-motion'
import PublicMeeting from './PublicMeeting.vue'
import '../public-home.css'
import '../public-stage.css'
import '../public-meeting.css'

defineProps<{ user: User | null; busy: boolean; exiting: boolean; error: string }>()
const emit = defineEmits<{ start: [role: WorkspaceRole]; logout: [] }>()
const selectedPerson = ref(0)
const person = computed(() => storyPeople[selectedPerson.value]!)
const replay = ref(0)
const heroView = ref<'meeting' | 'profile'>('meeting')
const relationship = ref(0)
const evidence = computed(() => person.value.evidence[relationship.value]!)
const enterpriseTab = ref(0)
const enterpriseEvidence = ref(0)
const enterpriseQuote = computed(() => person.value.evidence[enterpriseEvidence.value]!)
const editing = ref(0)
const playing = ref(true)
const editProject = computed(() => person.value.evidence[person.value.editEvidence]!)
const adopted = computed(() => editing.value === 4)
const journey = ref(0)
const demoMessage = ref('')
const sentMessages = ref<string[]>([])
// Browser zoom changes the CSS viewport too. Keep ordinary laptop heights in
// the animated stage; only genuinely short/narrow windows use document flow.
const documentFlowQuery = '(max-width: 1000px), (max-height: 639px)'
const reduced = ref(window.matchMedia('(prefers-reduced-motion: reduce)').matches)
const mobile = ref(window.matchMedia(documentFlowQuery).matches)
const storyTrack = ref<HTMLElement>()
const chapterIds = ['tp-main', 'tp-connect', 'tp-edit', 'tp-company', 'tp-journey']
const chapterNames = ['个人资料', '了解岗位', 'AI 协作', '企业视角', '双向选择']
const motionEnabled = computed(() => !reduced.value && !mobile.value)
const activeScene = ref(0)
const scenes: HTMLElement[] = []
const inView = new Set<number>()
const manualScenes = new Set<number>()
let observer: IntersectionObserver | undefined
let frame = 0
let timer: ReturnType<typeof setTimeout> | undefined
let motionQuery: MediaQueryList
let mobileQuery: MediaQueryList
let scrollMotion: ReturnType<typeof mountStoryMotion> | undefined
const enterpriseTabs = ['技术强项', '代表项目', '可参与业务', '面试追问']
function setScene(el: unknown, index: number) { if (el instanceof HTMLElement) scenes[index] = el }
function selectRelationship(index: number) {
  relationship.value = index; manualScenes.add(1)
  scenes[1]?.classList.add('tp-manual-links')
}
function setJourney(index: number) {
  journey.value = index; manualScenes.add(4)
  scenes[4]?.classList.add('tp-manual-journey')
}
function setEdit(index: number) { playing.value = false; editing.value = index; manualScenes.add(2) }
function setEnterprise(index: number) { enterpriseTab.value = index; manualScenes.add(3) }
function replayHero() { replay.value++; scrollMotion?.replayHero() }
function setHeroView(view: 'meeting' | 'profile') { heroView.value = view; replayHero() }
function switchPerson(index: number) {
  heroView.value = 'profile'
  selectedPerson.value = index; relationship.value = 0; enterpriseEvidence.value = 0
  enterpriseTab.value = 0; editing.value = 0; journey.value = 0
  sentMessages.value = []; demoMessage.value = ''; manualScenes.clear()
  scenes[1]?.classList.remove('tp-manual-links'); scenes[4]?.classList.remove('tp-manual-journey')
  playing.value = !reduced.value; scheduleEdit(); replayHero()
}
function sendDemo() {
  if (!demoMessage.value.trim()) return
  sentMessages.value.push(demoMessage.value.trim()); demoMessage.value = ''
}
function jump(id: string) {
  const index = chapterIds.indexOf(id)
  if (motionEnabled.value && index >= 0) scrollMotion?.jump(index)
  else if (motionEnabled.value && id === 'tp-next') scrollMotion?.jump(5)
  else document.getElementById(id)?.scrollIntoView({ behavior: reduced.value ? 'instant' : 'smooth', block: 'start' })
  if (index === 0) replayHero()
}
function updateMotion() {
  reduced.value = motionQuery.matches; mobile.value = mobileQuery.matches
  if (reduced.value) playing.value = false
  scrollMotion?.refresh()
  scheduleEdit(); scheduleScroll()
}
function scheduleEdit() {
  clearTimeout(timer)
  if (!playing.value || reduced.value || !inView.has(2) || document.hidden || editing.value === 4) return
  timer = setTimeout(() => { editing.value++; if (editing.value === 4) playing.value = false; scheduleEdit() }, 6500)
}
function togglePlayback() {
  if (!playing.value && editing.value === 4) editing.value = 0
  manualScenes.add(2)
  playing.value = !playing.value
}
watch([playing, editing], scheduleEdit)
function readScroll() {
  frame = 0
  if (motionEnabled.value) return
  const height = window.innerHeight
  let nearest = Infinity
  for (const [index, section] of scenes.entries()) {
    if (!section || !inView.has(index)) continue
    const rect = section.getBoundingClientRect()
    const distance = Math.abs(rect.top - height * .25)
    if (distance < nearest) { activeScene.value = index; nearest = distance }
  }
}
function scheduleScroll() { if (!frame) frame = requestAnimationFrame(readScroll) }
onMounted(() => {
  motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  mobileQuery = window.matchMedia(documentFlowQuery)
  updateMotion()
  scrollMotion = mountStoryMotion(storyTrack.value!, scenes, () => motionEnabled.value, (index, progress, active) => {
    if (activeScene.value !== active || !inView.has(active)) {
      activeScene.value = active; inView.clear(); inView.add(active); scheduleEdit()
    }
    if (manualScenes.has(index)) return
    if (index === 1) relationship.value = Math.min(2, Math.floor(progress * 3))
    if (index === 2) editing.value = Math.min(4, Math.floor(progress * 5))
    if (index === 3) enterpriseTab.value = Math.min(3, Math.floor(progress * 4))
    if (index === 4) journey.value = Math.min(3, Math.floor(progress * 4))
  })
  motionQuery.addEventListener('change', updateMotion); mobileQuery.addEventListener('change', updateMotion)
  observer = new IntersectionObserver(entries => {
    if (motionEnabled.value) return
    for (const entry of entries) {
      const index = scenes.indexOf(entry.target as HTMLElement)
      if (entry.isIntersecting && (index !== 2 || entry.intersectionRatio >= .25)) inView.add(index); else inView.delete(index)
    }
    scheduleScroll(); scheduleEdit()
  }, { threshold: [0, .15, .25, .35] })
  scenes.forEach(scene => observer?.observe(scene))
  window.addEventListener('scroll', scheduleScroll, { passive: true })
  window.addEventListener('resize', scheduleScroll, { passive: true })
  document.addEventListener('visibilitychange', scheduleEdit)
})
onBeforeUnmount(() => {
  observer?.disconnect(); cancelAnimationFrame(frame); clearTimeout(timer)
  scrollMotion?.destroy()
  motionQuery?.removeEventListener('change', updateMotion); mobileQuery?.removeEventListener('change', updateMotion)
  window.removeEventListener('scroll', scheduleScroll); window.removeEventListener('resize', scheduleScroll)
  document.removeEventListener('visibilitychange', scheduleEdit)
})
</script>

<template>
  <div class="tp-public" :class="{ 'tp-fixed': motionEnabled }">
    <a class="tp-skip" href="#tp-main">跳到首页内容</a>
    <header class="tp-header">
      <RouterLink to="/" class="tp-brand" aria-label="同频首页" @click="jump('tp-main')"><span>同</span><strong>同频<small>TONGPIN</small></strong></RouterLink>
      <nav class="tp-sections" aria-label="了解同频">
        <button v-for="(label, index) in chapterNames" :key="label" :aria-current="activeScene === index ? 'location' : undefined" @click="jump(chapterIds[index]!)">{{ label }}</button>
      </nav>
      <nav class="tp-account" aria-label="账号入口">
        <template v-if="user"><RouterLink to="/workspace" class="tp-btn tp-btn-small">工作空间 <ArrowUpRight :size="15" /></RouterLink><button :disabled="busy || exiting" class="tp-login" @click="emit('logout')">退出登录</button></template>
        <template v-else><RouterLink to="/login" class="tp-login">登录</RouterLink><RouterLink to="/register" class="tp-btn tp-btn-small">注册账号 <ArrowUpRight :size="15" /></RouterLink></template>
      </nav>
    </header>

    <main id="tp-main">
      <div ref="storyTrack" class="tp-story-track">
      <div class="tp-story-stage">
      <div v-if="motionEnabled" class="tp-stage-bridge" aria-hidden="true">
        <div class="tp-transition-paper" />
        <div class="tp-transition-identity">
          <span class="tp-demo-label">同一份经历 · 合成演示</span>
          <span class="tp-avatar">{{ person.initials }}</span><strong>{{ person.name }}</strong><p>{{ person.role }}</p>
          <div class="tp-transfer-skills"><span v-for="e in person.evidence" :key="e.label">{{ e.skill }}</span></div>
          <div class="tp-transfer-captions"><span>经历与岗位，建立关联</span><span>带着项目经历，与 AI 协作</span><span>展开经历，让企业看见</span><span>带着双方期待，开始沟通</span></div>
        </div>
      </div>
      <section :ref="el => setScene(el, 0)" class="tp-hero-track" aria-labelledby="tp-title">
      <div class="tp-hero tp-wrap">
        <div class="tp-hero-copy">
          <p class="tp-kicker"><span /> 从了解，走向同频</p>
          <h1 id="tp-title">让经历被看见。<br><em>让选择有回响。</em></h1>
          <p class="tp-intro">你做过的事，值得被认真理解。<br>把个人经历、岗位需要与双方期待连在一起，<br class="tp-desktop-break">从一份资料，走向一次有依据的相遇。</p>
          <div class="tp-entry-actions">
            <button class="tp-btn" :disabled="busy || exiting" @click="emit('start', 'candidate')"><UserRound :size="19" />我要求职<ArrowUpRight :size="18" /></button>
            <button class="tp-btn tp-btn-outline" :disabled="busy || exiting" @click="emit('start', 'enterprise')"><BriefcaseBusiness :size="19" />我要招聘<ArrowUpRight :size="18" /></button>
          </div>
          <p class="tp-entry-note"><ShieldCheck :size="15" />个人资料由你授权分享 · 招聘需企业认证</p>
          <div v-if="error" class="tp-error" role="alert">{{ error }}</div>
          <div class="tp-person-picker">
            <p>从一份具体经历，看看同频怎么做 <span class="tp-picker-demo">合成示例</span></p>
            <div aria-label="选择合成人物示例"><button v-for="(p, i) in storyPeople" :key="p.id" :aria-pressed="selectedPerson === i" @click="switchPerson(i)"><span>{{ p.initials }}</span>{{ p.shortRole }}</button></div>
          </div>
        </div>
        <div class="tp-hero-art" :class="{ 'tp-show-meeting': heroView === 'meeting' }">
          <div class="tp-hero-view-switch" aria-label="首页演示视图"><button :aria-pressed="heroView === 'meeting'" @click="setHeroView('meeting')"><HeartHandshake :size="15" />双向相遇</button><button :aria-pressed="heroView === 'profile'" @click="setHeroView('profile')"><FileText :size="15" />个人资料演示</button></div>
          <div class="tp-hero-visual">
          <PublicMeeting v-if="heroView === 'meeting'" :key="'meeting-' + replay" />
          <div v-show="heroView === 'profile'" :key="selectedPerson + '-' + replay" class="tp-profile-visual" aria-label="经历片段整理为个人资料卡">
          <div class="tp-art-orbit" aria-hidden="true"><span /><span /><span /></div>
          <div class="tp-fragments" aria-hidden="true">
            <div class="tp-fragment tp-fragment-one"><GitBranch :size="16" /><span>项目经历<strong>{{ person.evidence[1]!.project }}</strong></span></div>
            <div class="tp-fragment tp-fragment-two"><span>使用的技术<strong>{{ person.evidence[0]!.skill }}</strong></span><span class="tp-small-dot" /></div>
            <div class="tp-fragment tp-fragment-three"><FileText :size="16" /><span>工作片段<strong>{{ person.work }}</strong></span></div>
          </div>
          <article class="tp-person-card">
            <div class="tp-card-overline"><span>个人资料 / PROFILE</span><span class="tp-demo-label">合成示例</span></div>
            <div class="tp-person-heading"><span class="tp-avatar">{{ person.initials }}</span><div><h2>{{ person.name }}</h2><p>{{ person.role }}</p></div><span class="tp-card-seal"><Check :size="14" />经历已整理</span></div>
            <p class="tp-person-summary">{{ person.work }}</p>
            <div class="tp-card-skills"><span v-for="e in person.evidence" :key="e.label">{{ e.skill }}</span></div>
            <div class="tp-card-project"><small>一段值得展开的经历</small><h3>{{ person.evidence[1]!.project }}</h3><p>{{ person.evidence[1]!.quote }}</p><div><span class="tp-evidence-mark" />保留原文依据<ArrowDown :size="14" /></div></div>
            <div class="tp-card-bottom"><HeartHandshake :size="17" /><span>从具体经历，发现合作的可能</span></div>
          </article>
          </div>
          </div>
          <div class="tp-art-caption"><span><span class="tp-small-dot" />{{ heroView === 'meeting' ? '彼此了解，让选择有回响' : motionEnabled ? '滚动继续，或重播整理过程' : '碎片有序，经历清晰' }}</span><button class="tp-replay" @click="replayHero"><RotateCcw :size="14" />{{ heroView === 'meeting' ? '重播相遇' : '重新整理' }}</button></div>
        </div>
        <button class="tp-scroll-cue" @click="jump('tp-connect')">向下，看看如何相遇<ArrowDown :size="17" /></button>
      </div>
      </section>

      <div class="tp-demo-banner"><span class="tp-demo-label">互动演示</span><p>以下人物、岗位与沟通均为合成示例。你可以放心点击；真实资料和操作在登录后由你掌握。</p></div>

      <section id="tp-connect" :ref="el => setScene(el, 1)" class="tp-chapter tp-connect" aria-labelledby="tp-connect-title">
        <div class="tp-wrap tp-story-layout">
          <div class="tp-chapter-copy"><p class="tp-kicker">01 / 了解岗位</p><h2 id="tp-connect-title">不是几个关键词，<br>是做过的事<br><em>与需要做的事。</em></h2><p>把经历放在具体岗位旁边。<br>每一条关联，都能回到简历里的原话。</p>
            <ol class="tp-relation-list"><li v-for="(e, i) in person.evidence" :key="e.label"><button :aria-pressed="relationship === i" @click="selectRelationship(i)"><span>0{{ i + 1 }}</span><div><strong>{{ e.label }}</strong><small>{{ e.requirement }}</small></div><ArrowUpRight :size="17" /></button></li></ol>
            <small class="tp-chapter-hint">滚动逐项查看，也可以点击切换依据</small>
          </div>
          <div class="tp-scene-figure tp-connection-figure">
            <div class="tp-figure-top"><span><span class="tp-small-dot" />经历与岗位，逐项关联</span><span class="tp-demo-label">合成示例</span></div>
            <div class="tp-connection-head"><div><UserRound :size="18" /><strong>{{ person.name }}</strong><small>个人经历</small></div><span>↔</span><div><BriefcaseBusiness :size="18" /><strong>{{ person.job }}</strong><small>{{ person.company }} · 演示岗位</small></div></div>
            <div class="tp-connection-rows">
              <div v-for="(e, i) in person.evidence" :key="e.label" :style="{ '--link': `var(--link-${i}, 1)` }" :class="['tp-connected-pair', { active: relationship === i }]"><svg class="tp-connection-lines" viewBox="0 0 100 12" preserveAspectRatio="none" aria-hidden="true"><path pathLength="100" :class="{ active: relationship === i }" d="M 0 6 H 100" /></svg><button :aria-pressed="relationship === i" @click="selectRelationship(i)"><small>项目 / 工作片段</small><strong>{{ e.project }}</strong><span>{{ e.skill }}</span></button><span class="tp-link-node" aria-hidden="true"><Check :size="12" /></span><button :aria-pressed="relationship === i" @click="selectRelationship(i)"><small>岗位需要</small><strong>{{ e.requirement }}</strong><span>查看关联依据 <ArrowUpRight :size="12" /></span></button></div>
            </div>
            <div class="tp-quote-panel" aria-live="polite" aria-atomic="true"><Transition name="tp-evidence" mode="out-in"><div :key="selectedPerson + 'quote' + relationship" class="tp-quote-content"><div><Quote :size="17" /><strong>简历里的这句话</strong><span>{{ evidence.label }}</span></div><blockquote>“{{ evidence.quote }}”</blockquote><p>{{ evidence.relation }}</p></div></Transition></div>
            <p class="tp-figure-foot">关联帮助你理解岗位；是否投递，由你决定。</p>
          </div>
        </div>
      </section>

      <section id="tp-edit" :ref="el => setScene(el, 2)" class="tp-chapter tp-edit" aria-labelledby="tp-edit-title">
        <div class="tp-wrap">
          <div class="tp-wide-heading"><div><p class="tp-kicker">02 / 与 AI 一起完善</p><h2 id="tp-edit-title">把做过的事，<em>说得更清楚。</em></h2></div><p>建议先看，修改再定。<br>每一次采纳，都由你确认。</p></div>
          <div class="tp-edit-demo">
            <div class="tp-demo-toolbar"><span><Sparkles :size="18" />AI 协作 · {{ person.name }}的项目描述</span><button class="tp-control" :disabled="reduced" :aria-pressed="playing && !reduced" @click="togglePlayback"><Pause v-if="playing && !reduced" :size="15" /><Play v-else :size="15" />{{ reduced ? '已减少动态效果' : playing ? '暂停演示' : '播放演示' }}</button></div>
            <ol class="tp-edit-steps" aria-label="AI 修改演示步骤"><li v-for="(step, i) in editSteps" :key="step"><button :aria-current="editing === i ? 'step' : undefined" :aria-pressed="editing === i" @click="setEdit(i)"><span><Check v-if="i < editing" :size="14" /><template v-else>{{ i + 1 }}</template></span>{{ step }}</button></li></ol>
            <div class="tp-edit-panels">
              <div class="tp-editor-pane"><div class="tp-pane-caption"><span>项目描述</span><span>{{ adopted ? '演示预览 · 已更新' : '演示草稿' }}</span></div><div class="tp-document"><div class="tp-document-head"><span>{{ person.initials }}</span><div><strong>{{ person.name }}</strong><p>{{ person.role }}</p></div><FileText :size="24" /></div><hr><small>项目经历</small><h3>{{ editProject.project }}</h3><p :class="['tp-selected-text', { updated: adopted }]">{{ adopted ? person.after : person.before }}</p><div class="tp-document-rule" /><div class="tp-document-rule short" /><div class="tp-document-note"><CheckCheck v-if="adopted" :size="16" /><span>{{ adopted ? '表达已更新，事实保持原意。' : '选中这段经历，看看如何说清楚。' }}</span></div></div></div>
              <div class="tp-assistant-pane"><div class="tp-pane-caption"><span><Sparkles :size="15" />同频助手</span><span class="tp-demo-label">建议示例</span></div>
                <Transition name="tp-panel" mode="out-in"><div class="tp-edit-stage" :key="selectedPerson + ':' + editing" :data-step="editing" :aria-live="playing ? 'off' : 'polite'">
                  <span class="tp-stage-number">0{{ editing + 1 }} / 05</span>
                  <template v-if="editing === 0"><h3>从一段具体经历开始。</h3><p>已选中「{{ editProject.project }}」的项目描述。</p><blockquote>“{{ person.before }}”</blockquote><p class="tp-stage-note">接下来，让 AI 帮你梳理表达。</p></template>
                  <template v-else-if="editing === 1"><h3>保留事实，理顺表达。</h3><p>{{ person.suggestion }}</p><div class="tp-suggestion-note"><ShieldCheck :size="18" />建议基于已有内容，不补造工作成果。</div></template>
                  <template v-else-if="editing === 2"><h3>改了什么，一起看清。</h3><div class="tp-diff before"><small>修改前</small><p>{{ person.before }}</p></div><div class="tp-diff after"><small>建议表达</small><p>{{ person.after }}</p></div></template>
                  <template v-else-if="editing === 3"><h3>最后一步，由你决定。</h3><p>{{ person.after }}</p><button class="tp-btn" @click="setEdit(4)"><Check :size="17" />采纳这版表达（演示）</button><small>只更新本页演示，不会修改你的真实简历。</small></template>
                  <template v-else><span class="tp-success-icon"><Check :size="23" /></span><h3>这段经历，更清楚了。</h3><p>左侧预览已更新。正式使用时，你可以继续核对草稿，再决定保存。</p><button class="tp-inline-action" @click="setEdit(2)">再看看修改前后 <ArrowRight :size="16" /></button></template>
                </div></Transition>
                <div class="tp-step-controls"><button class="tp-control" :disabled="editing === 0" aria-label="上一步修改演示" @click="setEdit(editing - 1)"><ChevronLeft :size="17" />上一步</button><span>{{ editing + 1 }} / 5</span><button class="tp-control" :disabled="editing === 4" aria-label="下一步修改演示" @click="setEdit(editing + 1)">下一步<ChevronRight :size="17" /></button></div>
              </div>
            </div>
            <p class="tp-edit-foot">滚动推进，点击步骤可停下细看；播放时每步停留约 6.5 秒。不会发起真实 AI 请求。</p>
          </div>
        </div>
      </section>

      <section id="tp-company" :ref="el => setScene(el, 3)" class="tp-chapter tp-company" aria-labelledby="tp-company-title">
        <div class="tp-wrap"><div class="tp-wide-heading"><div><p class="tp-kicker">03 / 换到企业的视角</p><h2 id="tp-company-title">看见一个人，<br><em>从理解一段经历开始。</em></h2></div><p>技术、项目与业务连起来。<br>把还想了解的部分，变成一次好提问。</p></div>
          <div class="tp-employer-card"><header><span class="tp-avatar">{{ person.initials }}</span><div><h3>{{ person.name }}<small>{{ person.role }}</small></h3><p>{{ person.work }}</p></div><span class="tp-demo-label">企业阅读 · 合成示例</span></header>
            <div class="tp-employer-body"><nav aria-label="企业阅读视角"><button v-for="(tab, i) in enterpriseTabs" :key="tab" :aria-pressed="enterpriseTab === i" @click="setEnterprise(i)"><component :is="[GitBranch, FileText, BriefcaseBusiness, MessageSquare][i]" :size="18" />{{ tab }}<ArrowUpRight :size="15" /></button></nav>
              <div class="tp-employer-content"><div class="tp-employer-label"><h4>{{ enterpriseTabs[enterpriseTab] }}</h4><span>{{ enterpriseTab === 2 ? '业务关联建议' : enterpriseTab === 3 ? '从经历出发的问题' : '有原文支持的信息' }}</span></div>
                <div class="tp-strength-items"><button v-for="(e, i) in person.evidence" :key="e.label" :aria-pressed="enterpriseEvidence === i" @click="enterpriseEvidence = i"><span class="tp-strength-order">0{{ i + 1 }}</span><span><strong>{{ enterpriseTab === 0 ? e.skill : enterpriseTab === 1 ? e.project : enterpriseTab === 2 ? e.requirement : e.question }}</strong><small>{{ enterpriseTab === 0 ? e.project : enterpriseTab === 1 ? e.quote : enterpriseTab === 2 ? e.relation : '点击查看这道追问来自哪段经历' }}</small></span><ArrowUpRight :size="17" /></button></div>
                <div class="tp-employer-source" aria-live="polite"><span><Quote :size="17" />对应的经历依据</span><p>“{{ enterpriseQuote.quote }}”</p><small>{{ enterpriseTab === 3 ? '围绕具体任务展开交流，继续了解职责、过程与判断。' : '资料卡帮助理解经历，是否进一步沟通由招聘团队决定。' }}</small></div>
              </div>
            </div>
          </div>
          <p class="tp-company-note"><span />每位投递者都能被查看。AI 整理信息，双方作出选择。</p>
        </div>
      </section>

      <section id="tp-journey" :ref="el => setScene(el, 4)" class="tp-chapter tp-journey" aria-labelledby="tp-journey-title">
        <div class="tp-wrap"><div class="tp-wide-heading"><div><p class="tp-kicker">04 / 双向选择</p><h2 id="tp-journey-title">投递是开始，<br><em>彼此愿意，才走近一步。</em></h2></div><p>从一份授权简历，到一次沟通邀请。<br>双方期待始终和这份岗位放在一起。</p></div>
          <div class="tp-journey-demo"><ol class="tp-journey-track" aria-label="双向选择演示进展"><li v-for="(step, i) in journeySteps" :key="step"><button :aria-current="journey === i ? 'step' : undefined" :aria-pressed="journey === i" :class="{ complete: i < journey }" @click="setJourney(i)"><span><Check v-if="i < journey" :size="16" /><template v-else>0{{ i + 1 }}</template></span><strong>{{ step }}</strong></button></li></ol>
            <div class="tp-journey-layout"><aside class="tp-shared-context"><span class="tp-demo-label">始终关联的资料</span><BriefcaseBusiness :size="25" /><h3>{{ person.job }}</h3><p>{{ person.company }} · 演示企业</p><hr><div><UserRound :size="17" /><span><small>{{ person.name }}的期待</small><p>{{ person.expectation }}</p></span></div><div><BriefcaseBusiness :size="17" /><span><small>团队的期待</small><p>{{ person.teamExpectation }}</p></span></div><span class="tp-context-note"><ShieldCheck :size="14" />真实期待由本人填写并授权共享</span></aside>
              <div class="tp-journey-stage" :data-step="journey"><div class="tp-conversation-head"><span><MessageSquare :size="18" />{{ person.name }} ↔ {{ person.company }}</span><span class="tp-demo-label">流程演示</span></div>
                <Transition name="tp-journey-panel" mode="out-in"><div v-if="journey < 3" :key="journey" class="tp-invitation-state" aria-live="polite"><span class="tp-journey-icon"><component :is="[FileText, Send, HeartHandshake][journey]" :size="30" /></span><small>{{ ['求职者主动选择', '企业认真回应', '邀请由求职者决定'][journey] }}</small><h3>{{ ['从这个岗位，开始了解。', '这段经历，值得聊一聊。', '期待相近，再进一步。'][journey] }}</h3><p>{{ ['选择简历，核对共享内容后，主动向这家企业投递。', '企业查看授权资料，带着具体的问题发出沟通邀请。', '求职者查看岗位与邀请，自主决定是否接受。'][journey] }}</p><button class="tp-btn" @click="setJourney(journey + 1)">{{ ['演示：主动投递', '演示：发出沟通邀请', '演示：接受邀请'][journey] }}<ArrowRight :size="17" /></button><span v-if="journey > 0" class="tp-journey-receipt"><Check :size="14" />{{ journey === 1 ? '演示投递已送达，资料仅向这家企业共享' : '演示邀请已发出，等待求职者回应' }}</span></div>
                <div v-else key="chat" class="tp-chat-demo"><div class="tp-chat-status"><CheckCheck :size="14" />演示邀请已接受 · 双方开始沟通</div><div class="tp-chat-message"><span class="tp-chat-avatar">企</span><div><small>{{ person.company }}</small><p>{{ person.opening }}</p></div></div><div class="tp-chat-message mine"><div><small>{{ person.name }}</small><p>可以的。我也想了解这个岗位的具体安排，以及团队怎样协作。</p></div><span class="tp-chat-avatar">{{ person.initials }}</span></div><div v-for="(message, i) in sentMessages" :key="i" class="tp-chat-message mine"><div><small>你 · 演示消息</small><p>{{ message }}</p></div><span class="tp-chat-avatar">你</span></div><form class="tp-demo-composer" @submit.prevent="sendDemo"><label class="sr-only" for="tp-demo-message">试写一条演示消息</label><input id="tp-demo-message" v-model="demoMessage" maxlength="200" placeholder="试写一句你想了解的问题…" autocomplete="off"><button type="submit" class="tp-btn" :disabled="!demoMessage.trim()" aria-label="发送演示消息"><Send :size="17" /></button></form><p class="tp-local-note">演示消息仅在本页显示，不会发送给任何人。</p></div></Transition>
              </div>
            </div>
          </div>
        </div>
      </section>

      </div>
      </div>
      <section id="tp-next" class="tp-final"><div class="tp-wrap"><p class="tp-kicker">下一次相遇，从了解开始</p><h2>找到同频的人，<br>也让同频的人找到你。</h2><div class="tp-entry-actions"><button class="tp-btn" :disabled="busy || exiting" @click="emit('start', 'candidate')">准备我的经历<ArrowUpRight :size="19" /></button><button class="tp-btn tp-btn-outline" :disabled="busy || exiting" @click="emit('start', 'enterprise')">了解候选人<ArrowUpRight :size="19" /></button></div><p>选择有据可循，决定始终在你。</p></div></section>
    </main>
    <footer class="tp-footer tp-wrap"><RouterLink to="/" class="tp-brand" @click="jump('tp-main')"><span>同</span><strong>同频<small>TONGPIN</small></strong></RouterLink><p>让每一份期待，都被看见。</p><RouterLink to="/login">进入同频 <ArrowUpRight :size="16" /></RouterLink></footer>
  </div>
</template>
