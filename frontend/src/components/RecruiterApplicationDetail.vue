<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowUpRight, BriefcaseBusiness, Check, Clock3, FileText, HeartHandshake, MessageSquare, ShieldCheck, Sparkles, UserRound } from '@lucide/vue'
import { state } from '../store'
import { applicationLabels, ended, eventLabels } from '../hiring'
import type { ApplicationDetail, HiringAction } from '../hiring'
import ResumeAttachment from './ResumeAttachment.vue'
import RecruiterProfile from './RecruiterProfile.vue'
import ApplicationResumeActions from './ApplicationResumeActions.vue'
import '../applications-recruiter.css'

const props = defineProps<{ application: ApplicationDetail; pending: boolean }>()
const emit = defineEmits<{ prepare: [action: HiringAction]; analyzed: [] }>()
const tabs = [
  { id: 'overview', label: '资料概览', icon: UserRound },
  { id: 'materials', label: '简历与岗位', icon: FileText },
  { id: 'expectations', label: '双方期待', icon: HeartHandshake },
  { id: 'history', label: '进展记录', icon: Clock3 },
] as const
type Tab = typeof tabs[number]['id']
const active = ref<Tab>('overview')
const name = computed(() => props.application.candidate_name.replace(/^个人简历[_\s-]*/, '').replace(/_/g, ' · '))
const date = (stamp: string) => new Date(stamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const canContinue = computed(() => props.application.available && !ended(props.application.status))
const preview = computed(() => props.application.resume_snapshot?.text.trim().slice(0, 650) || '')
const expectations = computed(() => {
  const row = props.application
  if (row.preference_comparison) return row.preference_comparison.dimension_results
  const ent = row.enterprise_preferences, cand = row.candidate_preferences
  return [...new Set([...Object.keys(ent?.dimensions || {}), ...Object.keys(cand?.dimensions || {})])].map(id => ({
    dimension_id: id, name: ent?.dimension_labels?.[id] || cand?.dimension_labels?.[id] || '其他期待',
    ent_quote: ent?.dimensions[id] || '尚未共享', cand_quote: cand?.dimensions[id] || '尚未共享',
    unmatched_reason: '保留已共享的原文，另一方共享后可继续对照。',
  }))
})
const stage = computed(() => props.application.status === 'submitted' ? 0 : props.application.status === 'invited' ? 1 : props.application.status === 'accepted' ? 2 : -1)
const nextStep = computed(() => !props.application.available ? '岗位或账号暂不可用，仍可查看已保留的进展。'
  : ended(props.application.status) ? '本次流程已结束，历史进展与已交换的消息仍可查看。'
  : props.application.status === 'submitted' ? '先了解授权经历，感兴趣时发出沟通邀请。'
  : props.application.status === 'invited' ? '邀请已发出，等待求职者自主回应。'
  : '双方已接受沟通，可以进一步讨论职责、项目和工作安排。')
function tabKey(event: KeyboardEvent, index: number) {
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
    : event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : -1
  if (next < 0) return
  event.preventDefault(); active.value = tabs[next]!.id
  document.getElementById(`application-${props.application.id}-tab-${active.value}`)?.focus()
}
</script>

<template>
  <section class="application-dossier" aria-label="候选人投递详情">
    <header class="dossier-heading">
      <div class="dossier-identity"><span class="dossier-avatar" aria-hidden="true">{{ name.slice(0, 1) }}</span><div><p class="dossier-caption">主动投递的求职者</p><h2>{{ name }}</h2><p class="dossier-job"><BriefcaseBusiness :size="15" /><span>{{ application.job_title }}</span></p></div></div>
      <div class="dossier-heading-actions">
        <span :class="['pill', { teal: application.status === 'accepted', amber: application.status === 'invited' }]">{{ applicationLabels[application.status] }}</span>
        <div><RouterLink v-if="application.resume_shared && canContinue" :to="{ path: '/recruiter-ai', query: { application: application.id } }" class="button secondary"><Sparkles :size="15" />招聘 AI 工作区</RouterLink><button v-if="canContinue && application.status === 'submitted'" class="primary" :disabled="pending" @click="emit('prepare', 'invite')">邀请沟通<ArrowUpRight :size="16" /></button><RouterLink v-else-if="application.status === 'accepted' && application.available" :to="{ path: '/messages', query: { application: application.id } }" class="button primary"><MessageSquare :size="16" />进入沟通<span v-if="application.unread_count" class="dossier-unread">{{ application.unread_count }}</span></RouterLink></div>
      </div>
    </header>
    <div class="dossier-context"><span><Clock3 :size="13" />{{ date(application.created_at) }} 投递</span><span><ShieldCheck :size="13" />{{ application.resume_snapshot ? '已授权本次简历' : '简历授权已结束或不可用' }}</span><span>{{ application.company_name || '认证企业' }}</span></div>
    <p v-if="!application.available" class="notice dossier-unavailable">岗位或账号已被暂停，当前无法继续沟通，仍可查看已保留的投递记录。</p>

    <div class="dossier-workspace">
      <div class="dossier-main">
        <nav class="dossier-tabs" role="tablist" aria-label="候选人资料分区"><button v-for="(tab, i) in tabs" :id="`application-${application.id}-tab-${tab.id}`" :key="tab.id" role="tab" :aria-selected="active === tab.id" :aria-controls="`application-${application.id}-panel-${tab.id}`" :tabindex="active === tab.id ? 0 : -1" @click="active = tab.id" @keydown="tabKey($event, i)"><component :is="tab.icon" :size="15" />{{ tab.label }}<small v-if="tab.id === 'history'">{{ application.events.length }}</small></button></nav>

        <div v-show="active === 'overview'" :id="`application-${application.id}-panel-overview`" class="dossier-panel dossier-overview" role="tabpanel" :aria-labelledby="`application-${application.id}-tab-overview`" tabindex="0">
          <section v-if="preview" class="dossier-glance"><header><div><p class="dossier-caption">从求职者提供的材料开始</p><h3>简历速览</h3></div><button class="secondary" @click="active = 'materials'">阅读完整简历<ArrowUpRight :size="14" /></button></header><p class="dossier-resume-excerpt">{{ preview }}{{ (application.resume_snapshot?.text.length || 0) > 650 ? '…' : '' }}</p><footer><FileText :size="13" />授权简历原文节选 · {{ application.resume_name }}</footer></section>
          <article v-if="application.introduction" class="dossier-cover-note"><h3>求职者的投递留言</h3><p>{{ application.introduction }}</p></article>
          <RecruiterProfile v-if="application.resume_shared && canContinue" :application="application" embedded @analyzed="emit('analyzed')" />
          <div v-else class="dossier-empty"><ShieldCheck :size="28" /><h3>当前简历授权不可用</h3><p>授权结束后，企业不能继续查看简历原文和个人期待。你仍可在进展记录中查看双方已发生的互动。</p><button class="secondary" @click="active = 'history'">查看进展记录</button></div>
        </div>

        <div v-show="active === 'materials'" :id="`application-${application.id}-panel-materials`" class="dossier-panel" role="tabpanel" :aria-labelledby="`application-${application.id}-tab-materials`" tabindex="0">
          <section class="dossier-document"><header><FileText :size="20" /><div><h3>本次投递的简历</h3><p>投递时保存的版本，之后修改个人简历不会改变本次材料。</p></div></header><template v-if="application.resume_snapshot"><ResumeAttachment :key="application.id" :name="application.resume_snapshot.name" :text="application.resume_snapshot.text" /><p v-if="application.resume_snapshot.revision_kind" class="notice">{{ application.resume_snapshot.revision_kind === 'user_edited_material' ? '本人手动修改版本' : '已保存的优化版本' }}，其中本人补充尚未外部核验。</p></template><p v-else class="notice">本次授权暂不可用，无法继续查看简历正文。</p></section>
          <section class="dossier-document dossier-job-document"><header><BriefcaseBusiness :size="20" /><div><h3>{{ application.job_snapshot.title || application.job_title }}</h3><p>本次投递的岗位要求 · v{{ application.job_snapshot.version }}</p></div></header><p class="source-text dossier-resume-full">{{ application.job_snapshot.text }}</p></section>
        </div>

        <div v-show="active === 'expectations'" :id="`application-${application.id}-panel-expectations`" class="dossier-panel" role="tabpanel" :aria-labelledby="`application-${application.id}-tab-expectations`" tabindex="0">
          <header class="dossier-section-heading"><div><h3>双方期待，放在一起看</h3><p>{{ application.preference_notice }}</p></div></header>
          <div v-if="expectations.length" class="dossier-expectations"><div class="dossier-expectation-legend"><span>期待方向</span><span>企业期待</span><span>个人期待</span></div><article v-for="d in expectations" :key="d.dimension_id"><h4>{{ d.name }}</h4><p><small>企业期待</small>{{ d.ent_quote }}</p><p><small>个人期待</small>{{ d.cand_quote }}</p><footer>{{ d.unmatched_reason || (d.ent_quote === d.cand_quote ? '双方选择相同，可进一步了解具体安排。' : '双方选择有所不同，可以在沟通中了解原意。') }}</footer></article></div>
          <div v-else class="dossier-empty"><HeartHandshake :size="30" /><h3>等待双方共享期待</h3><p>可以先了解经历、发出沟通邀请，也可以填写团队期待并设置公开范围。</p></div>
          <p v-if="application.enterprise_preferences?.ambience_text" class="dossier-cover-note">团队氛围：{{ application.enterprise_preferences.ambience_text }}</p>
          <RouterLink v-if="!ended(application.status)" to="/preferences" class="button secondary" @click="state.jobId = application.job_id">管理团队期待与公开范围<ArrowUpRight :size="15" /></RouterLink>
        </div>

        <div v-show="active === 'history'" :id="`application-${application.id}-panel-history`" class="dossier-panel" role="tabpanel" :aria-labelledby="`application-${application.id}-tab-history`" tabindex="0">
          <header class="dossier-section-heading"><div><h3>本次投递的进展</h3><p>投递、邀请与回应按发生时间保留。</p></div></header>
          <ol class="dossier-timeline"><li v-for="(event, i) in application.events" :key="i"><span class="dossier-timeline-dot" aria-hidden="true"><Check :size="12" /></span><div><header><strong>{{ eventLabels[event.action] || event.action }}</strong><time>{{ date(event.created_at) }}</time></header><span>{{ event.side === 'candidate' ? '求职者' : '企业' }}</span><p v-if="event.text">{{ event.text }}</p></div></li></ol>
        </div>
      </div>

      <aside class="dossier-rail" aria-label="投递状态与常用操作">
        <section class="dossier-rail-section dossier-next"><h3>当前进展</h3><ol v-if="stage >= 0" class="dossier-stage-track"><li v-for="(label, i) in ['收到投递', '发出邀请', '双方沟通']" :key="label" :class="{ complete: i < stage, current: i === stage }"><span><Check v-if="i < stage" :size="12" /><span v-else>{{ i + 1 }}</span></span>{{ label }}</li></ol><p>{{ nextStep }}</p><RouterLink v-if="application.status === 'invited'" :to="{ path: '/messages', query: { application: application.id } }" class="button secondary">查看已发邀请<ArrowUpRight :size="14" /></RouterLink><RouterLink v-else-if="ended(application.status)" :to="{ path: '/messages', query: { application: application.id } }" class="button secondary">查看历史沟通<ArrowUpRight :size="14" /></RouterLink></section>
        <section class="dossier-rail-section dossier-material-tools"><h3><FileText :size="16" />简历操作</h3><p>仅使用本次投递授权的材料。</p><ApplicationResumeActions :key="application.id" :application="application" /><p v-if="!application.resume_shared || !application.available" class="dossier-rail-muted">当前授权不可用，无法下载或导入。</p></section>
        <section v-if="application.invitation" class="dossier-rail-section dossier-invitation"><h3>已发出的沟通邀请</h3><time>{{ date(application.invitation.created_at) }}</time><p>{{ application.invitation.text }}</p><button class="secondary" @click="active = 'history'">查看完整邀请<ArrowUpRight :size="13" /></button></section>
        <section v-if="application.last_message" class="dossier-rail-section dossier-message-preview"><h3><MessageSquare :size="16" />最近沟通</h3><p>{{ application.last_message.side === 'candidate' ? '求职者' : '企业' }}：{{ application.last_message.text }}</p><RouterLink :to="{ path: '/messages', query: { application: application.id } }" class="button secondary">查看消息<span v-if="application.unread_count"> · {{ application.unread_count }} 条未读</span><ArrowUpRight :size="14" /></RouterLink></section>
        <details v-if="canContinue" class="dossier-other-actions"><summary>其他流程操作</summary><p>操作会记录在本次投递的进展中。</p><button v-if="['submitted', 'invited'].includes(application.status)" class="danger" :disabled="pending" @click="emit('prepare', 'reject')">暂不推进这份投递</button><button v-if="application.status === 'accepted'" class="danger" :disabled="pending" @click="emit('prepare', 'close')">结束本次沟通</button></details>
      </aside>
    </div>
  </section>
</template>
