<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUpRight, BriefcaseBusiness, UserRound, MoveRight, Check, Files, HeartHandshake, ScanText } from '@lucide/vue'
import { state, candidate, logout, notifyError, switchWorkspace, api } from '../store'
import type { WorkspaceRole, RecordData } from '../types'
import { origin } from '../presentation'
import PublicHome from '../components/PublicHome.vue'
const route = useRoute(); const router = useRouter()
const person = computed(() => state.user)
const preferences = ref<RecordData[]>([])
const applicationCount = ref(0); const applicationTodo = ref(0)
onMounted(async () => { if (route.path !== '/workspace') return; try { const rows = await api<RecordData[]>('/applications'); applicationCount.value = rows.length; applicationTodo.value = rows.filter(r => candidate.value ? r.status === 'invited' : r.status === 'submitted').length } catch (e) { notifyError(e) } })
const savedExpectation = computed(() => preferences.value.find(p => p.side === 'candidate' && p.owner === state.actor && state.resumes.some(r => r.id === p.resume_id)))
onMounted(async () => {
  if (route.path !== '/workspace' || !candidate.value) return
  try { preferences.value = await api<RecordData[]>('/preferences') } catch (e) { notifyError(e) }
})
function selectStep(to: string) {
  if (to === '/preferences' && candidate.value && savedExpectation.value) state.resumeId = savedExpectation.value.resume_id
}
async function start(role: WorkspaceRole) {
  if (!state.user) { await router.push({ path: '/login', query: { role } }); return }
  if (role === 'enterprise' && state.user.enterprise_status !== 'approved') { await router.push('/enterprise-verification'); return }
  try { await switchWorkspace(role); await router.push('/workspace') } catch (e) { notifyError(e) }
}
const exiting = ref(false)
async function exit() { exiting.value = true; try { await logout(); await router.push('/login') } catch (e) { notifyError(e) } finally { exiting.value = false } }
const steps = computed(() => candidate.value ? [
 { n: '01', title: '准备你的经历', text: '导入简历，让真实的任务与产出成为依据。', to: '/resumes', done: !!state.resumes.length, icon: Files },
 { n: '02', title: '表达你的期待', text: '填写方向、工作方式与成长偏好。', to: '/preferences', done: !!savedExpectation.value, icon: HeartHandshake },
 { n: '03', title: '与 AI 一起完善', text: '理解经历、对照岗位，补充后再优化表达。', to: '/ai-workspace', done: false, icon: ScanText },
] : [
 { n: '01', title: '明确岗位需要', text: '粘贴岗位描述，核对每条要求的原文。', to: '/jobs', done: state.jobs.some(j => j.status === '已确认'), icon: BriefcaseBusiness },
 { n: '02', title: '与 AI 一起了解经历', text: '整理授权简历、讨论业务关联，准备有依据的面试追问。', to: '/recruiter-ai', done: applicationCount.value > 0, icon: Files },
 { n: '03', title: '带着问题进一步沟通', text: '参考面试追问，发出邀请，再由求职者决定是否接受。', to: '/applications', done: false, icon: HeartHandshake },
])
</script>
<template>
  <PublicHome v-if="route.path === '/'" :user="state.user" :busy="state.loading || state.busy || state.switching" :exiting="exiting" :error="state.error" @start="start" @logout="exit" />
  <template v-else>
    <div class="page-heading"><p class="eyebrow">{{ candidate ? '我的求职空间' : '招聘团队 / 概览' }}</p><h1>{{ candidate ? (person?.name || '你好') + '，从你的下一步开始。' : '把合适的人与期待，放在一起。' }}</h1><p>沿着清晰的步骤推进，让每一次选择都有具体依据。</p></div>
    <section class="workspace-hero"><div><span class="pill">{{ candidate ? '经历 × 岗位 × 期待' : '岗位 × 经历 × 期待' }}</span><h2>{{ candidate ? '了解自己，也了解下一站。' : '先说清需要，再看见可能。' }}</h2><p>{{ candidate ? '每份对照都围绕你选择的具体岗位，保留原文、差距与待了解的部分。' : '从一份清楚的岗位描述开始，将要求、经历和双方偏好逐步连接。' }}</p><RouterLink :to="candidate ? '/ai-workspace' : '/jobs'" class="button primary">{{ candidate ? '进入 AI 工作区' : '管理岗位与需求' }}<ArrowUpRight :size="18" /></RouterLink></div><div class="hero-pair" aria-hidden="true"><div><BriefcaseBusiness :size="26" /><span>岗位要求</span><i /><i /></div><span>↔</span><div><UserRound :size="26" /><span>个人经历</span><i /><i /></div></div></section>
    <RouterLink to="/applications" class="surface job-row" style="margin-top:24px"><span class="job-icon"><HeartHandshake :size="21" /></span><div><h3>{{ candidate ? '我的投递与邀请' : '应聘与沟通邀请' }}</h3><p>{{ applicationCount }} 份投递 · {{ applicationTodo }} 份{{ candidate ? '邀请待回应' : '投递待处理' }}</p></div><span class="secondary workspace-card-action">查看进展<ArrowUpRight :size="16" /></span></RouterLink>
    <div class="section-heading"><h2>接下来做什么</h2><span>一次完成一件事</span></div><div class="steps-grid"><RouterLink v-for="s in steps" :key="s.n" :to="s.to" class="step-card" @click="selectStep(s.to)"><div class="step-top"><span class="step-no">{{ s.n }}</span><span v-if="s.done" class="pill teal"><Check :size="13" />{{ s.to === '/preferences' ? '已保存' : '已有材料' }}</span><component v-else :is="s.icon" :size="23" /></div><h3>{{ s.title }}</h3><p>{{ s.text }}</p><span class="secondary workspace-card-action">{{ s.done ? s.to === '/preferences' ? '查看与修改' : '查看与完善' : '开始准备' }}<MoveRight :size="17" /></span></RouterLink></div>
    <div class="section-heading"><h2>{{ candidate ? '可以了解的岗位' : '当前岗位' }}</h2><RouterLink to="/jobs" class="text-link">查看全部<ArrowUpRight :size="16" /></RouterLink></div><div class="surface"><RouterLink v-for="j in state.jobs.slice(0, 4)" :key="j.id" to="/jobs" class="job-row" @click="state.jobId = j.id"><span class="job-icon"><BriefcaseBusiness :size="21" /></span><div><h3>{{ j.title }}</h3><p>{{ j.profile.direction }} · {{ j.profile.requirements.length }} 项技能要求 · {{ origin(j.data_origin) }}</p></div><span :class="['pill', { teal: j.status === '已确认' }]">{{ j.status }}</span><ArrowUpRight :size="18" /></RouterLink><div v-if="!state.jobs.length" class="empty compact"><h3>从第一份岗位开始</h3><p>{{ candidate ? '企业确认并公开岗位后会展示在这里；也可以先到 AI 工作区完善简历。' : '创建岗位后，就可以开始整理简历和双方期待。' }}</p><RouterLink :to="candidate ? '/ai-workspace' : '/jobs'" class="text-link">{{ candidate ? '完善简历 →' : '添加岗位 →' }}</RouterLink></div></div>
  </template>
</template>

<style scoped>
.workspace-card-action {
  width:fit-content;min-height:36px;padding:7px 12px;border-radius:7px;
  font-size:12px;line-height:1.6;gap:7px;flex-shrink:0;
}
.step-card>.workspace-card-action { align-self:flex-start;margin-top:auto; }
.step-card:hover>.workspace-card-action,.job-row:hover>.workspace-card-action,
.step-card:focus-visible>.workspace-card-action,.job-row:focus-visible>.workspace-card-action {
  background:var(--brand-faint);border-color:var(--brand-focus);
}
@media(max-width:600px) {
  .job-row:has(>.workspace-card-action) { flex-wrap:wrap; }
  .job-row>.workspace-card-action { margin-left:auto; }
}
</style>
