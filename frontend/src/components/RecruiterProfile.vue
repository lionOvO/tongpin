<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { Check, FileCheck2, GitBranch, LayoutGrid, LoaderCircle, RefreshCw, Sparkles } from '@lucide/vue'
import RecruiterExperienceGraph from './RecruiterExperienceGraph.vue'
import { api, ApiError, state } from '../store'
import { ended } from '../hiring'
import type { ApplicationDetail } from '../hiring'
import type { ModelCatalog } from '../ai-workspace'
import { experienceStrengths, mentionedSkills } from '../recruiter-review'
import type { RecruiterCard, RecruiterReviewState, RecruiterStrength } from '../recruiter-review'

const props = defineProps<{ application: ApplicationDetail; embedded?: boolean }>()
const emit = defineEmits<{ analyzed: [] }>()
const card = ref<RecruiterCard | null>(null)
const catalog = ref<ModelCatalog | null>(null)
const modelId = ref(''); const businessContext = ref('')
const view = ref<'card' | 'map'>('map'); const selectedIndex = ref(0)
const evidenceId = useId()
const loading = ref(true); const pending = ref(false); const remoteRunning = ref(false); const error = ref('')
const showOptions = ref(false); const copiedQuestion = ref('')
const analysisFailed = ref(false)
const attemptedModel = ref('')
const available = computed(() => props.application.resume_shared && props.application.available && !ended(props.application.status))
const strengths = computed(() => experienceStrengths(card.value))
const mentioned = computed(() => mentionedSkills(card.value))
const selected = computed(() => strengths.value[selectedIndex.value] || strengths.value[0] || null)
const model = computed(() => catalog.value?.models.find(m => m.id === modelId.value))
const contextChanged = computed(() => !!card.value && businessContext.value.trim() !== card.value.business_context)
const modelChanged = computed(() => !!card.value && modelId.value !== card.value.model_id)
const blocked = computed(() => loading.value || pending.value || remoteRunning.value || !available.value)
let alive = true; let request = 0; let timer: ReturnType<typeof setInterval> | undefined

function problem(e: unknown) {
  if (!(e instanceof ApiError && ['STALE_CONTEXT', 'AUTH_REQUIRED'].includes(e.code))) error.value = e instanceof Error ? e.message : '本次分析未完成，请重试。'
}
async function load(initial = false) {
  const ticket = ++request
  try {
    const result = await api<RecruiterReviewState>(`/applications/${props.application.id}/recruiter-review`)
    if (!alive || ticket !== request || !available.value) return
    const previous = card.value?.input_hash
    const previousCreated = card.value?.created_at
    card.value = result.review; remoteRunning.value = result.running
    if (analysisFailed.value && result.review && result.review.created_at !== previousCreated) { error.value = ''; analysisFailed.value = false }
    if (initial) { businessContext.value = result.business_context; modelId.value = result.review?.model_id || catalog.value?.default_model_id || '' }
    if (result.review?.input_hash !== previous) selectedIndex.value = 0
  } catch (e) {
    if (alive && ticket === request) {
      if (e instanceof ApiError && [401, 403, 404].includes(e.status)) { card.value = null; remoteRunning.value = false }
      problem(e)
    }
  }
  finally { if (alive && ticket === request) loading.value = false }
}
async function analyze() {
  if (blocked.value || !model.value?.available) return
  const ticket = ++request; const id = props.application.id
  attemptedModel.value = model.value.label
  pending.value = true; error.value = ''; analysisFailed.value = false; copiedQuestion.value = ''
  try {
    const result = await api<RecruiterReviewState>(`/applications/${id}/recruiter-review`, 'POST', {
      expected_version: props.application.version, model_id: modelId.value,
      business_context: businessContext.value, regenerate: !!card.value,
    }, 225000)
    if (!alive || ticket !== request || !available.value) return
    card.value = result.review; remoteRunning.value = result.running; selectedIndex.value = 0
    businessContext.value = result.business_context; showOptions.value = false; emit('analyzed')
  } catch (e) {
    if (alive && ticket === request) {
      if (e instanceof ApiError && e.code === 'REVIEW_CONSENT_UNAVAILABLE') card.value = null
      problem(e); analysisFailed.value = true; showOptions.value = true; emit('analyzed')
      // A browser timeout can precede a completed server write. Reconcile without
      // replaying the paid generation or changing the selected provider.
      try {
        const current = await api<RecruiterReviewState>(`/applications/${id}/recruiter-review`, 'GET', undefined, 15000)
        if (alive && ticket === request && available.value) {
          const updated = current.review?.created_at !== card.value?.created_at
          card.value = current.review; remoteRunning.value = current.running
          if (updated && current.review) { error.value = ''; analysisFailed.value = false; emit('analyzed') }
        }
      } catch (readError) {
        if (alive && ticket === request && readError instanceof ApiError && [401, 403, 404].includes(readError.status)) { card.value = null; remoteRunning.value = false }
      }
    }
  } finally { if (alive && ticket === request) pending.value = false }
}
async function copyQuestion(text: string) {
  try { await navigator.clipboard.writeText(text); if (alive) copiedQuestion.value = text }
  catch { if (alive) error.value = '浏览器未允许复制，请选中追问文字手动复制。' }
}
function selectStrength(s: RecruiterStrength) { selectedIndex.value = strengths.value.indexOf(s); copiedQuestion.value = '' }
function refreshVisible() { if (document.visibilityState === 'visible' && available.value && !pending.value) void load() }
watch(available, value => {
  if (!value) { request++; card.value = null; remoteRunning.value = false; pending.value = false; businessContext.value = ''; error.value = ''; analysisFailed.value = false }
})
onMounted(async () => {
  try {
    const result = await api<ModelCatalog>('/recruiter/models')
    if (!alive) return
    catalog.value = result; modelId.value = result.default_model_id
    await load(true)
  } catch (e) { if (alive) { loading.value = false; problem(e) } }
  if (!alive) return
  timer = setInterval(refreshVisible, 15000); document.addEventListener('visibilitychange', refreshVisible)
})
onUnmounted(() => { alive = false; request++; clearInterval(timer); document.removeEventListener('visibilitychange', refreshVisible) })
</script>

<template>
  <section class="recruiter-profile" :class="{ 'recruiter-profile-embedded': embedded, 'profile-with-card': !!card }" aria-label="求职者个人资料卡">
    <header class="profile-header">
      <div><p class="eyebrow">经历、技术与业务的关联</p><h3>{{ embedded ? 'AI 资料卡' : '个人资料卡' }}</h3></div>
      <div class="profile-actions">
        <button v-if="card || embedded" class="secondary profile-options-toggle" :disabled="blocked" :aria-expanded="showOptions" @click="showOptions = !showOptions">分析设置</button>
        <button v-if="embedded && !card && !loading" class="primary profile-generate" :disabled="blocked || !model?.available" @click="analyze"><LoaderCircle v-if="pending || remoteRunning" :size="15" class="spin" /><Sparkles v-else :size="15" />{{ pending || remoteRunning ? '正在整理…' : '生成资料卡' }}</button>
        <button v-if="card" class="secondary profile-update" :disabled="blocked || !model?.available" @click="analyze"><LoaderCircle v-if="pending || remoteRunning" :size="14" class="spin" /><RefreshCw v-else :size="14" />{{ pending || remoteRunning ? '正在分析…' : '更新资料卡' }}</button>
      </div>
    </header>
    <p class="profile-notice">AI 依据本次授权材料整理，仅供招聘参考，所有投递都可查看，是否推进由你决定。</p>
    <div v-if="error" class="profile-error" role="alert">
      <p>{{ error }}</p>
      <template v-if="analysisFailed && available">
        <p class="profile-recovery-note">本次使用 {{ attemptedModel || '所选模型' }}。{{ card ? '更新未完成，下面保留上一次生成的资料卡。' : '本次未生成资料卡，仍可直接查看授权简历。' }}可重试，或在下方选择其他已配置的模型后再分析。</p>
        <div class="profile-recovery-actions"><button class="secondary" :disabled="blocked || !model?.available" @click="analyze">{{ pending || remoteRunning ? '正在分析…' : '重试分析' }}</button><button class="text-link" :disabled="blocked" @click="showOptions = true">选择其他模型</button></div>
      </template>
    </div>
    <p v-if="loading" class="muted" role="status">正在读取资料卡…</p>
    <div v-if="!loading && (showOptions || !card && !embedded)" class="profile-options">
      <label>分析模型<select v-model="modelId" :disabled="blocked"><option v-for="m in catalog?.models || []" :key="m.id" :value="m.id" :disabled="!m.available">{{ m.label }}{{ m.available ? '' : ' · 暂不可用' }}</option></select></label>
      <label>公司希望这位同事参与的业务（可选）<textarea v-model="businessContext" rows="3" maxlength="2000" :disabled="blocked" placeholder="例如：负责订单服务、减少重复提交，或维护运营后台。未填写时，按本次岗位要求关联。" /></label>
      <p class="profile-provider">仅发送本次授权的简历、投递时的岗位要求及你填写的业务需要至 {{ model?.provider || '所选服务' }}。</p>
      <p v-if="!model?.available" class="muted">{{ model?.unavailable_reason || '暂未配置可用模型，请检查服务器 AI 设置。' }} 已授权的简历仍可在下方直接查看。</p>
      <p v-if="contextChanged || modelChanged" class="muted">分析设置已修改，更新资料卡后应用；当前结果保留此前的模型与业务背景。</p>
      <button v-if="!card && !embedded" class="primary" :disabled="blocked || !model?.available" @click="analyze"><LoaderCircle v-if="pending || remoteRunning" :size="16" class="spin" /><Sparkles v-else :size="16" />{{ pending || remoteRunning ? '正在整理经历与依据…' : '生成个人资料卡' }}</button>
    </div>
    <div v-if="embedded && !loading && !card" class="profile-unbuilt">
      <span class="profile-unbuilt-icon"><GitBranch :size="24" /></span><div><h4>{{ pending || remoteRunning ? '正在整理经历与原文依据' : '把经历整理成清晰的技术图谱' }}</h4><p>按技术特长、实际任务和业务关联阅读，并查看每项结论的原文依据与面试追问。点击生成后开始分析。</p><span>{{ model?.label || '等待模型配置' }} · 不影响投递状态</span><p v-if="!model?.available && !loading" class="profile-model-unavailable">{{ model?.unavailable_reason || '暂未配置可用模型，可先阅读授权简历。' }}</p></div>
    </div>
    <template v-if="card">
      <p v-if="card.partial" class="notice">材料较长，本次仅覆盖简历前 30000 字和岗位前 12000 字。请结合完整原文审阅。</p>
      <div class="profile-person"><span class="profile-avatar" aria-hidden="true">{{ application.candidate_name.slice(0, 1) }}</span><div><h4>{{ application.candidate_name }}</h4><p>{{ card.overview || '从材料中的实际经历进一步了解' }}</p></div></div>
      <details v-if="card.overview_quotes.length" class="profile-overview-evidence"><summary>查看概述依据</summary><blockquote v-for="(quote, i) in card.overview_quotes" :key="i">{{ quote }}</blockquote></details>
      <div class="profile-view-bar"><h4>有经历支持的技术特长</h4><div class="profile-view-switch" role="group" aria-label="资料卡查看方式"><button type="button" :aria-pressed="view === 'map'" @click="view = 'map'"><GitBranch :size="14" />技术图谱</button><button type="button" :aria-pressed="view === 'card'" @click="view = 'card'"><LayoutGrid :size="14" />资料卡</button></div></div>
      <p v-if="!strengths.length" class="profile-empty">当前材料尚未描述具体的技术任务，可以从下方追问进一步了解。</p>
      <div v-else-if="view === 'card'" class="profile-strengths"><button v-for="(s, i) in strengths" :key="s.title" type="button" :aria-pressed="selectedIndex === i" @click="selectStrength(s)"><strong>{{ s.title }}</strong><span>{{ s.work }}</span></button></div>
      <RecruiterExperienceGraph v-else :strengths="strengths" :selected-index="selectedIndex" :evidence-id="evidenceId" @select="selectStrength" />
      <div v-if="selected" :id="evidenceId" class="recruiter-card-evidence" aria-live="polite">
        <h4><FileCheck2 :size="16" />{{ selected.title }} · 原文依据</h4><blockquote>{{ selected.resume_quote }}</blockquote><p class="profile-source">来自本次已授权简历{{ application.resume_snapshot?.revision_kind ? ' · 本人保存的修改版本' : '' }}</p>
        <div v-if="selected.business_link" class="profile-business"><h4>业务关联建议 · {{ selected.business_link.task }}</h4><p>{{ selected.business_link.reason }}</p><details><summary>查看{{ selected.business_link.source === 'job' ? '岗位原文' : '企业业务需要' }}依据</summary><blockquote>{{ selected.business_link.job_quote }}</blockquote></details></div>
        <div class="profile-question"><div><h4>值得继续了解</h4><button class="text-link" @click="copyQuestion(selected.interview_question)"><Check v-if="copiedQuestion === selected.interview_question" :size="13" />{{ copiedQuestion === selected.interview_question ? '已复制' : '复制追问' }}</button></div><p>{{ selected.interview_question }}</p></div>
      </div>
      <div v-if="mentioned.length" class="profile-mentioned"><h4>材料提及 · 具体实践待了解</h4><details v-for="s in mentioned" :key="s.title"><summary>{{ s.title }}</summary><blockquote>{{ s.resume_quote }}</blockquote><p>{{ s.interview_question }}</p><button class="text-link" @click="copyQuestion(s.interview_question)">{{ copiedQuestion === s.interview_question ? '已复制' : '复制追问' }}</button></details></div>
      <div v-if="card.open_questions.length" class="profile-open-questions"><h4>还可以了解</h4><details v-for="(q,i) in card.open_questions" :key="i"><summary>{{ q.topic }}</summary><p>{{ q.question }}</p><button class="text-link" @click="copyQuestion(q.question)">{{ copiedQuestion === q.question ? '已复制' : '复制追问' }}</button></details></div>
      <p class="profile-meta">{{ card.model_label }} · {{ new Date(card.created_at).toLocaleString('zh-CN') }} · 本次投递的材料快照</p>
    </template>
  </section>
</template>

<style scoped>
.recruiter-profile.recruiter-profile-embedded{margin:0;border:0;border-top:1px solid var(--line);border-radius:0;padding:24px 0 0;background:transparent}.recruiter-profile-embedded .profile-header h3{font-size:18px}.profile-options-toggle,.profile-generate{font-size:12px;min-height:36px;padding:7px 12px}.recruiter-profile.recruiter-profile-embedded .profile-notice{background:transparent;border:0;border-left:2px solid var(--brand-edge);border-radius:0;padding:0 0 0 10px;margin:15px 0;color:var(--text-muted);font-size:11px}.recruiter-profile-embedded .profile-options{padding:16px;background:var(--brand-faint);border:1px solid var(--line);border-radius:8px;margin:16px 0}.profile-unbuilt{display:flex;align-items:flex-start;gap:16px;padding:22px;background:var(--brand-faint);border:1px dashed var(--brand-edge);border-radius:10px}.profile-unbuilt-icon{width:44px;height:44px;display:grid;place-items:center;background:var(--brand-soft);border-radius:12px;color:var(--brand-ink);flex-shrink:0}.profile-unbuilt h4{font-size:14px}.profile-unbuilt p{font-size:12px;line-height:1.85;color:var(--text-muted);margin:7px 0}.profile-unbuilt div>span{font-size:10px;color:var(--text-muted)}.profile-model-unavailable{color:#906015!important}.profile-recovery-note{font-size:13px;line-height:1.8;margin-top:8px}.profile-recovery-actions{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:12px}.profile-recovery-actions .secondary{min-height:36px;font-size:12px;padding:7px 12px}
.recruiter-profile{border:1px solid var(--line);border-radius:12px;padding:22px;margin:22px 0;background:#fff;min-width:0}.profile-header{display:flex;justify-content:space-between;align-items:center;gap:14px}.profile-header h3{font-size:19px;margin:5px 0 0}.profile-header .eyebrow{font-size:11px}.profile-actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.profile-actions .text-link{font-size:12px}.profile-update{font-size:12px;padding:9px 13px;min-height:38px}.profile-notice{font-size:12px;color:var(--muted);background:var(--brand-faint);border-radius:6px;padding:11px 13px;margin:16px 0 20px;line-height:1.8}.profile-error{color:#a93236;background:#fff3f2;padding:12px 14px;border-radius:7px;margin:14px 0;overflow-wrap:anywhere}.profile-options{display:grid;gap:14px}.profile-options label{font-size:12px;margin:0}.profile-options select{max-width:330px}.profile-options textarea{min-height:90px;font-size:13px}.profile-options>.primary{justify-self:start;font-size:13px}.profile-provider{font-size:12px;color:var(--muted);line-height:1.8}.profile-options>.muted{font-size:12px}.profile-person{display:flex;align-items:flex-start;gap:13px;margin:22px 0 13px}.profile-avatar{display:grid;place-items:center;flex-shrink:0;width:44px;height:44px;border-radius:12px;background:var(--brand-soft);color:var(--brand-ink);font-size:20px}.profile-person h4{font-size:20px;margin:0 0 6px}.profile-person p{font-size:13px;color:var(--muted);line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere}.profile-overview-evidence{margin:10px 0}.profile-overview-evidence summary{font-size:12px;color:var(--brand-ink);cursor:pointer}.recruiter-profile blockquote{margin:12px 0 8px;padding-left:12px;border-left:2px solid var(--brand-edge);font-size:13px;line-height:1.85;white-space:pre-wrap;overflow-wrap:anywhere}.profile-view-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:24px 0 14px;flex-wrap:wrap}.profile-view-bar h4{font-size:13px}.profile-view-switch{display:flex;border:1px solid var(--line);border-radius:7px;padding:3px;gap:3px}.profile-view-switch button{display:flex;align-items:center;gap:5px;font-size:12px;padding:7px 10px;border-radius:4px;white-space:nowrap}.profile-view-switch button[aria-pressed=true]{background:var(--brand-soft);color:var(--brand-ink)}.profile-strengths{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.profile-strengths button{text-align:left;display:flex;flex-direction:column;gap:9px;min-width:0;padding:14px;border:1px solid var(--line);background:var(--brand-faint);border-radius:9px;overflow-wrap:anywhere}.profile-strengths button[aria-pressed=true]{background:var(--brand-soft);border-color:var(--brand-edge)}.profile-strengths strong{font-size:13px;font-weight:600}.profile-strengths span{font-size:12px;color:var(--muted);line-height:1.7}.profile-empty{font-size:13px;color:var(--muted);padding:14px 0}.profile-map-head{display:grid;grid-template-columns:1fr 1.45fr 1fr;gap:32px;padding:0 12px 9px;font-size:11px;color:var(--muted)}.profile-map>button{display:grid;grid-template-columns:minmax(0,1fr) 16px minmax(0,1.45fr) 16px minmax(0,1fr);align-items:center;gap:8px;width:100%;text-align:left;border:1px solid var(--line);border-radius:8px;padding:13px 12px;margin-bottom:9px;font-size:12px;line-height:1.8}.profile-map>button[aria-pressed=true]{background:var(--brand-soft);border-color:var(--brand-edge)}.profile-map>button>span{min-width:0;overflow-wrap:anywhere}.profile-map>button>svg{color:var(--text-muted)}.profile-map small{display:none}.recruiter-card-evidence{background:var(--brand-faint);border-radius:10px;margin-top:18px;padding:18px;min-width:0}.recruiter-card-evidence>h4{display:flex;align-items:center;gap:7px;color:#0d786e;font-size:13px;overflow-wrap:anywhere}.profile-source{font-size:11px;color:var(--muted)}.profile-business{border-top:1px solid var(--line);padding-top:15px;margin-top:16px}.profile-business h4,.profile-question h4{font-size:13px}.profile-business>p,.profile-question>p{font-size:13px;margin:8px 0 0;line-height:1.85;white-space:pre-wrap;overflow-wrap:anywhere}.profile-business details{margin-top:10px}.profile-business summary{color:var(--brand-ink);font-size:12px;cursor:pointer}.profile-question{border-top:1px solid var(--line);padding-top:15px;margin-top:16px}.profile-question>div{display:flex;justify-content:space-between;align-items:center;gap:12px}.profile-question .text-link{font-size:12px;display:flex;gap:4px;align-items:center;white-space:nowrap}.profile-mentioned,.profile-open-questions{margin-top:20px}.profile-mentioned h4,.profile-open-questions h4{font-size:13px;margin-bottom:9px}.profile-mentioned details,.profile-open-questions details{padding:10px 0;border-bottom:1px solid var(--line)}.profile-mentioned summary,.profile-open-questions summary{font-size:12px;cursor:pointer;color:var(--muted)}.profile-mentioned details>p,.profile-open-questions details>p{font-size:13px;line-height:1.85;margin:10px 0;overflow-wrap:anywhere}.profile-mentioned .text-link,.profile-open-questions .text-link{font-size:12px}.profile-meta{font-size:11px;color:var(--muted);margin-top:18px;overflow-wrap:anywhere}.spin{animation:profile-spin 1s linear infinite}@keyframes profile-spin{to{transform:rotate(360deg)}}
@media(max-width:1180px){.profile-strengths{grid-template-columns:repeat(2,minmax(0,1fr))}.profile-actions{gap:8px}.profile-header{flex-wrap:wrap}}
@media(max-width:650px){.recruiter-profile.recruiter-profile-embedded{padding:20px 0 0}.profile-unbuilt{padding:16px;gap:10px}.profile-unbuilt-icon{width:34px;height:34px}.recruiter-profile{padding:16px}.profile-strengths{grid-template-columns:1fr}.profile-map-head{display:none}.profile-map>button{grid-template-columns:1fr;gap:10px}.profile-map>button>svg{display:none}.profile-map small{display:block;color:var(--muted);font-size:11px}.recruiter-card-evidence{padding:14px}.profile-options select{max-width:none}.profile-question>div{align-items:flex-start}}
@media(prefers-reduced-motion:reduce){.spin{animation:none}}
</style>
