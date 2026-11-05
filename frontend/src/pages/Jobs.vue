<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ApplyDialog from '../components/ApplyDialog.vue'
import { applicationByJob, ended } from '../hiring'
import type { ApplicationDetail, ApplicationSummary } from '../hiring'
import { Plus, ArrowUpRight, Trash2, RefreshCw, Eye, LockKeyhole, Pencil, Inbox, Check, FileText } from '@lucide/vue'
import { notifyError, state, candidate, job, api, action, refresh } from '../store'
import { origin } from '../presentation'
import type { Job, RecordData } from '../types'
import Empty from '../components/Empty.vue'
import JobRequirements from '../components/JobRequirements.vue'
const route = useRoute(); const router = useRouter(); const applicationJob = ref<Job | null>(null)
const applications = ref<ApplicationSummary[]>([]); const refreshing = ref(false); const checkingApplication = ref(false)
const duplicateApplication = ref<ApplicationSummary | null>(null)
const applicationIndex = computed(() => applicationByJob(applications.value))
const selectedApplication = computed(() => job.value ? applicationIndex.value.get(job.value.id) : undefined)
let alive = true
onUnmounted(() => { alive = false; sequence++ })
async function refreshApplications() {
  if (!candidate.value) return
  const rows = await api<ApplicationSummary[]>('/applications')
  if (alive) applications.value = rows
}
async function refreshJobs() {
  refreshing.value = true
  try { await Promise.all([refresh(), refreshApplications()]) }
  finally { if (alive) refreshing.value = false }
}
async function prepareApplication(target: Job) {
  if (state.busy || refreshing.value || checkingApplication.value) return
  checkingApplication.value = true; state.error = ''
  try {
    await refreshApplications()
    if (!alive) return
    const existing = applicationIndex.value.get(target.id)
    duplicateApplication.value = existing && !ended(existing.status) ? existing : null
    applicationJob.value = target
  } catch (e) { if (alive) notifyError(e) }
  finally { if (alive) checkingApplication.value = false }
}
function duplicateFound() { void refreshApplications().catch(() => {}) }

function selectRequestedJob() {
  const id = route.query.job; const resume = route.query.resume
  if (typeof id === 'string' && state.jobs.some(j => j.id === id)) state.jobId = id
  if (candidate.value && typeof resume === 'string' && state.resumes.some(r => r.id === resume)) state.resumeId = resume
}
watch(() => [route.query.job, route.query.resume], selectRequestedJob)
onMounted(async () => { try { await refreshJobs(); if (alive) selectRequestedJob() } catch (e) { if (alive) notifyError(e) } })
async function applied(row: ApplicationDetail) { applications.value = [row, ...applications.value.filter(r => r.id !== row.id)]; applicationJob.value = null; state.success = '已投递，企业可在应聘与邀请中查看你授权的资料。'; await router.push({ path: '/applications', query: { application: row.id } }) }
const search = ref(''); const tab = ref('profile'); const creating = ref(false)
const editingProfile = ref(false)
const title = ref(''); const jd = ref(''); const dataOrigin = ref('real'); const manual = ref(false); const direction = ref('后端开发')
const profile = ref<Job['profile']>({ direction: '', education: null, requirements: [] })
const briefEdits = ref<Record<string,RecordData>>({})
const questions = ref<RecordData[]>([]); const answers = ref<Record<string, string>>({}); const briefs = ref<RecordData[]>([]); const diagnosis = ref<RecordData | null>(null); const coverage = ref<RecordData | null>(null)
const filtered = computed(() => state.jobs.filter(j => j.title.includes(search.value) || j.profile.direction.includes(search.value)))
let sequence = 0
async function load() {
  profile.value = job.value ? structuredClone(JSON.parse(JSON.stringify(job.value.profile))) : { direction: '', education: null, requirements: [] }
  editingProfile.value = !!job.value && job.value.status !== '已确认'
  questions.value = []; briefs.value = []; diagnosis.value = null; coverage.value = null
  const id = job.value?.id; const ticket = ++sequence
  if (!id || candidate.value) return
  try { const [q, b, c] = await Promise.all([api('/requirements/clarify', 'POST', { job_id: id }), api<RecordData[]>('/requirements/brief/' + id), api('/requirements/coverage/' + id)])
    if (ticket !== sequence) return
    questions.value = q.questions; briefs.value = b; coverage.value = c
    briefEdits.value = Object.fromEntries(profile.value.requirements.map(r => { const saved = b[0]?.requirements.find((item:RecordData) => item.origin === 'JD原文' && item.content === r.skill); return [r.skill,{custom:saved?.basis === '逐项确认',type:saved?.type || (r.hard ? '硬性' : '加分'),priority:saved?.priority || 'P1'}] }))
    answers.value = Object.fromEntries(q.questions.map((x: RecordData) => [x.id, b[0]?.clarification_qa?.[x.id] || x.options.at(-1)]))
  } catch (e) { if (ticket === sequence) notifyError(e) }
}
watch(() => [state.jobId, job.value?.version], load); onMounted(load)
async function create() { await action(async () => { const j = await api<Job>('/jobs', 'POST', { title: title.value, jd: jd.value, data_origin: dataOrigin.value, ...(manual.value ? { manual_profile: { direction: direction.value, education: null, requirements: [] } } : {}) }); state.jobId = j.id; await refresh(); creating.value = false; title.value = ''; jd.value = '' }, '岗位已创建，请核对原文并确认画像。') }
async function confirm() { const j = job.value; if (!j) return; await action(async () => { await api('/jobs/' + j.id + '/confirm', 'PUT', { expected_version: j.version, profile: profile.value }); await refresh() }, '画像已保存为新版本，历史报告保留原快照。') }
async function publish() { const j = job.value; if (!j) return; await action(async () => { await api('/jobs/' + j.id + '/visibility', 'PUT', { published: !j.published }); await refresh() }, j.published ? '岗位已设为私有，已有授权对照保留历史记录。' : '岗位已公开，求职者可查看、分析并主动投递。') }
function cancelProfile() { if (job.value) profile.value = structuredClone(JSON.parse(JSON.stringify(job.value.profile))); editingProfile.value = false }
async function saveBrief() { if (!job.value) return; await action(async () => { await api('/requirements/brief', 'POST', { job_id: job.value!.id, answers: answers.value, requirement_overrides:Object.entries(briefEdits.value).filter(([,r])=>r.custom).map(([skill,r])=>({skill,type:r.type,priority:r.priority})) }); await load() }, '用人需求已保存。') }
</script>
<template>
  <div class="page-heading heading-action"><div><p class="eyebrow">{{ candidate ? '了解下一站' : '招聘工作台 / 第一步' }}</p><h1>{{ candidate ? '查看岗位，了解具体要求。' : '岗位与用人需求' }}</h1><p>{{ candidate ? '原文、要求和参照始终放在一起。' : '先把需要说清楚，让后续分析有明确的参照。' }}</p></div><button v-if="!candidate" class="primary" @click="creating = true"><Plus :size="18" />新建岗位</button></div>
  <div class="list-detail"><section class="surface list-panel"><div class="list-toolbar"><button class="text-link" :disabled="state.busy || refreshing || checkingApplication" @click="action(refreshJobs)"><RefreshCw :size="13" />刷新岗位</button><label class="sr-only" for="job-search">搜索岗位</label><input id="job-search" v-model="search" type="search" placeholder="搜索岗位名称或技术方向"><small>{{ filtered.length }} 个岗位</small></div><button v-for="j in filtered" :key="j.id" :class="['select-row', { selected: j.id === state.jobId }]" @click="state.jobId = j.id" :disabled="state.busy || refreshing || checkingApplication"><span class="row-main"><strong>{{ j.title }}</strong><span>{{ candidate ? j.accepts_applications ? j.company_name || '认证企业公开岗位' : j.personal_reference ? '私人岗位参照 · 无法投递' : '公开岗位 · 暂不可投递' : j.profile.direction }} · {{ origin(j.data_origin) }}</span></span><span :class="['pill', { teal: j.status === '已确认' || candidate && applicationIndex.has(j.id) }]">{{ candidate && applicationIndex.has(j.id) ? applicationIndex.get(j.id)?.status === 'withdrawn' ? '已撤回' : '已投递' : j.status }}</span></button><Empty v-if="!filtered.length" title="还没有符合条件的岗位" :text="candidate ? '企业确认并公开岗位后，会出现在这里。' : '试试其他关键词，或新建一个岗位。'" /></section>
  <section v-if="job" class="surface detail-panel job-detail-panel"><div class="detail-heading"><div><p class="detail-metadata"><span>{{ job.company_name || (candidate ? '岗位资料' : '我的岗位') }}</span><span>{{ origin(job.data_origin) }}</span><span>画像 v{{ job.version }}</span></p><h2>{{ job.title }}</h2></div><span :class="['pill', { teal: job.status === '已确认' || candidate && !!selectedApplication }]">{{ candidate && selectedApplication ? selectedApplication.status === 'withdrawn' ? '已撤回' : '已投递' : job.status }}</span></div><section v-if="!candidate" class="job-visibility" aria-label="岗位发布与投递"><div class="job-publication-state"><component :is="job.published ? Eye : LockKeyhole" :size="19" /><div><strong>{{ job.published ? '岗位已公开' : '岗位仅自己可见' }}</strong><span>{{ job.published ? '求职者可查看原文并主动投递' : '确认岗位要求后，可主动公开招聘' }}</span></div></div><div class="job-publication-actions"><RouterLink :to="{ path: '/applications', query: { job: job.id } }" class="secondary"><Inbox :size="16" />查看此岗位投递</RouterLink><button class="secondary" :disabled="state.busy || job.status !== '已确认' || job.moderation_status === 'suspended'" :title="job.status !== '已确认' ? '先确认岗位要求，再公开岗位' : job.moderation_status === 'suspended' ? '平台已暂停此岗位公开' : undefined" @click="publish"><component :is="job.published ? LockKeyhole : Eye" :size="16" />{{ job.published ? '设为私有' : '公开岗位' }}</button></div></section><div v-if="job.moderation_status === 'suspended'" class="feedback error" role="alert">平台已暂停此岗位公开。处理依据：{{ job.moderation_reason }}。请联系平台工作人员处理。</div><div class="tabs" role="tablist" aria-label="岗位详情"><button :class="{ active: tab === 'profile' }" role="tab" :aria-selected="tab === 'profile'" @click="tab = 'profile'">{{ candidate ? '要求与原文' : '核对岗位画像' }}</button><button v-if="!candidate" :class="{ active: tab === 'needs' }" role="tab" :aria-selected="tab === 'needs'" @click="tab = 'needs'">澄清用人需求</button><button :class="{ active: tab === 'jd' }" role="tab" :aria-selected="tab === 'jd'" @click="tab = 'jd'">岗位原文</button></div>
    <div v-if="tab === 'jd'" class="detail-body"><div class="reading-heading"><FileText :size="19" /><div><h3>岗位描述原文</h3><p>保留原始内容，便于随时核对。</p></div></div><p class="source-text job-original">{{ job.source_jd }}</p></div>
    <div v-else-if="tab === 'profile'" class="detail-body"><div v-if="candidate"><JobRequirements :profile="job.profile" /><div class="button-row"><RouterLink v-if="selectedApplication && !ended(selectedApplication.status)" :to="{ path: '/applications', query: { application: selectedApplication.id } }" class="button primary">已投递 · 查看进展<ArrowUpRight :size="17" /></RouterLink><button v-else-if="job.accepts_applications" class="primary" :disabled="state.busy || refreshing || checkingApplication" @click="prepareApplication(job)">{{ checkingApplication ? '正在核对投递…' : selectedApplication ? '重新投递' : '投递这个岗位' }}<ArrowUpRight :size="17" /></button><RouterLink v-if="selectedApplication && ended(selectedApplication.status)" :to="{ path: '/applications', query: { application: selectedApplication.id } }" class="text-link">查看上次投递 →</RouterLink><RouterLink :to="{ path: '/ai-workspace', query: { job: job.id } }" class="button primary">与 AI 对照这个岗位<ArrowUpRight :size="17" /></RouterLink><RouterLink :to="{ path: '/compare', query: { job: job.id, resume: state.resumeId || undefined } }" class="button secondary">分析岗位契合度<ArrowUpRight :size="17" /></RouterLink><RouterLink to="/fit" class="text-link">查看量规对照 →</RouterLink></div></div>
    <section v-else-if="!editingProfile" class="job-profile-saved"><header class="section-control"><div><h3><Check :size="17" />已保存的岗位要求</h3><p>查看具体要求与出处，需要调整时再进入编辑。</p></div><button class="secondary" :disabled="state.busy" @click="editingProfile = true"><Pencil :size="15" />编辑岗位要求</button></header><JobRequirements :profile="job.profile" /></section><form v-else class="job-profile-editor" @submit.prevent="confirm"><header class="section-control"><div><h3><Pencil :size="17" />{{ job.status === '已确认' ? '编辑岗位要求' : '核对并确认岗位要求' }}</h3><p>核对技能和对应原文，保存后生成新的画像版本。</p></div><span class="editing-label">编辑中</span></header><div class="form-grid"><label>技术方向<input v-model="profile.direction" required></label><label>学历要求<select v-model="profile.education"><option :value="null">未指定</option><option v-for="v in ['大专','本科','硕士','博士']" :key="v">{{ v }}</option></select></label></div><div class="form-section-title"><h3>逐项核对技能要求</h3><small>引用须来自右侧岗位原文</small></div><div class="profile-evidence"><div><article v-for="(r, i) in profile.requirements" :key="i" class="requirement-card"><div class="form-grid"><label>技能名称<input v-model="r.skill" required></label><label>要求的行为等级<select v-model.number="r.required_level"><option v-for="n in 4" :value="n" :key="n">{{ n }} 级</option></select></label></div><label>对应岗位原文<textarea v-model="r.quote" required rows="3" /></label><div class="row-between"><label class="check"><input v-model="r.hard" type="checkbox">主要要求</label><button type="button" class="icon-button" @click="profile.requirements.splice(i, 1)" :aria-label="'移除要求 ' + (i + 1)"><Trash2 :size="16" /></button></div></article><button type="button" class="secondary full" @click="profile.requirements.push({ skill: '', required_level: 2, hard: true, quote: '' })"><Plus :size="16" />补充技能要求</button></div><aside class="source-panel"><small>岗位描述原文</small><p class="source-text">{{ job.source_jd }}</p></aside></div><div class="form-footer"><small>保存生成新版本，历史报告保留原快照。</small><div class="button-row"><button v-if="job.status === '已确认'" type="button" class="secondary" :disabled="state.busy" @click="cancelProfile">取消编辑</button><button class="primary" :disabled="state.busy"><Check :size="16" />确认并保存画像</button></div></div></form></div>
    <div v-else class="detail-body"><form @submit.prevent="saveBrief"><div class="form-grid"><label v-for="q in questions" :key="q.id">{{ q.question }}<select v-model="answers[q.id]"><option v-for="o in q.options" :key="o">{{ o }}</option></select></label></div><div class="form-section"><h3>逐项确认技能要求</h3><p class="muted">默认根据澄清回答整理；需要区分不可妥协项与可培养项时，勾选对应技能单独设置。</p><article v-for="r in profile.requirements" :key="r.skill" class="requirement-card"><template v-if="briefEdits[r.skill]"><label class="check"><input v-model="briefEdits[r.skill].custom" type="checkbox">单独确认 {{ r.skill }}</label><div v-if="briefEdits[r.skill].custom" class="form-grid"><label>需求类型<select v-model="briefEdits[r.skill].type"><option>硬性</option><option>加分</option><option>可培养</option></select></label><label>了解优先级<select v-model="briefEdits[r.skill].priority"><option>P0</option><option>P1</option><option>P2</option></select></label></div></template></article></div><div class="form-footer"><span>允许选择「不清楚 / 跳过」。</span><button class="primary" :disabled="state.busy || job.status !== '已确认' || job.moderation_status === 'suspended'">保存用人需求</button></div></form><div v-if="briefs[0]" class="table-wrap"><table><thead><tr><th>要求</th><th>来源 / 类型</th><th>优先顺序 / 覆盖</th></tr></thead><tbody><tr v-for="(r, i) in briefs[0].requirements" :key="i"><td>{{ r.content }}<small>{{ r.jd_quote }}</small></td><td>{{ r.source_tag }} · {{ r.type }}</td><td>{{ r.priority }}<small>{{ r.assessable ? '有描述判据' : '需要沟通确认' }}</small></td></tr></tbody></table></div><p v-if="coverage" class="muted">{{ coverage.message }}<span v-for="(r,i) in coverage.uncovered" :key="i"> · {{ r.content }}</span></p><button class="secondary" :disabled="state.busy" @click="action(async () => { diagnosis = await api('/requirements/diagnose', 'POST', { job_id: job!.id }) })">检查岗位要求</button><template v-if="diagnosis"><article v-for="(f,i) in diagnosis.findings" :key="i" class="requirement-card"><h3>{{ f.type }}</h3><p>{{ f.statement }}</p><blockquote>{{ f.jd_quote }}</blockquote></article><p v-if="!diagnosis.findings.length" class="notice">未发现可确定的问题。</p><p v-if="!diagnosis.benchmark_available" class="muted">同类岗位样本不足，未进行同级基准诊断。</p></template></div>
  </section><Empty v-else title="从一个具体岗位开始" text="选中岗位查看详情，或粘贴 JD 创建新岗位。" />
  </div>
  <ApplyDialog v-if="applicationJob" :job="applicationJob" :existing-application="duplicateApplication" @close="applicationJob = null" @submitted="applied" @duplicate="duplicateFound" />
  <div v-if="creating" class="modal-backdrop" @click.self="!state.busy && (creating = false)"><section v-dialog class="modal" role="dialog" aria-modal="true" aria-labelledby="new-job-title"><div class="detail-heading"><h2 id="new-job-title">新建岗位</h2><button class="icon-button" @click="creating = false" :disabled="state.busy" aria-label="关闭新建岗位">×</button></div><form @submit.prevent="create"><label>岗位名称<input v-model="title" minlength="2" maxlength="100" required autofocus placeholder="例如：Python 后端工程师"></label><label>完整岗位描述<textarea v-model="jd" minlength="20" maxlength="30000" required rows="9" placeholder="粘贴职责、要求与工作内容，至少 20 个字符。" /></label><label>数据来源<select v-model="dataOrigin"><option value="real">用户自行导入</option><option value="synthetic">合成 / 演示数据</option></select></label><label class="check"><input v-model="manual" type="checkbox">手工录入基础画像（不调用 AI）</label><label v-if="manual">技术方向<select v-model="direction"><option v-for="d in ['后端开发','前端开发','全栈开发','数据与算法','测试与质量','基础设施']" :key="d">{{ d }}</option></select></label><div class="form-footer"><span>创建后还需确认画像。</span><button class="primary" :disabled="state.busy">创建并整理岗位</button></div></form></section></div>
</template>
