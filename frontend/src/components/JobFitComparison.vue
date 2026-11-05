<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowUpRight, Check, Plus, RefreshCw, Search, Sparkles } from '@lucide/vue'
import { api, ApiError, state } from '../store'
import { createRequestId } from '../request-id'
import { relation, violations } from '../presentation'
import type { Job, RecordData } from '../types'
import AddReferenceJob from './AddReferenceJob.vue'

const route = useRoute()
const search = ref(''), selected = ref<string[]>([]), addingJob = ref(false)
const history = ref<RecordData[]>([]), viewed = ref(''), submitting = ref(false), loading = ref(false), error = ref('')
const bands = [{ id: 'very_high', label: '很高契合' }, { id: 'high', label: '较高契合' }, { id: 'medium', label: '一般契合' }, { id: 'low', label: '较低契合' }, { id: 'very_low', label: '很低契合' }]
const runs = computed(() => history.value.filter(r => r.resume_id === state.resumeId))
const run = computed(() => runs.value.find(r => r.id === viewed.value))
const active = computed(() => runs.value.find(r => ['queued', 'running'].includes(r.status)))
const jobs = computed(() => state.jobs.filter(j => j.status === '已确认'))
const filtered = computed(() => jobs.value.filter(j => `${j.title} ${j.company_name || ''} ${j.profile.direction}`.toLowerCase().includes(search.value.toLowerCase().trim())))
const selectable = computed(() => filtered.value.filter(j => !selected.value.includes(j.id)).slice(0, Math.max(0, 20 - selected.value.length)))
function selectAll() { selected.value = [...selected.value, ...selectable.value.map(j => j.id)] }
const ready = computed(() => !!state.resumeId && !submitting.value && !active.value && !state.switching && selected.value.length > 0)
function addedReference(job: Job) {
  state.jobs = [job, ...state.jobs.filter(j => j.id !== job.id)]
  if (!selected.value.includes(job.id) && selected.value.length < 20) selected.value.push(job.id)
  search.value = ''; addingJob.value = false
}
const canRetry = computed(() => !!run.value && ['partial', 'failed', 'interrupted'].includes(run.value.status) && !submitting.value && !active.value && !state.switching)
const failedTitle = (e: RecordData) => state.jobs.find(j => j.id === e.job_id)?.title || (e.job_ref ? '岗位 ' + e.job_ref : '分析任务')
const results = computed(() => (run.value?.ranked_results || []).filter((r: RecordData) => !!state.presentation && [r.job_title, r.basis_statement || '', ...r.dimensions.map((d: RecordData) => d.name)].every(t => !violations(t, state.presentation!, false))))
const label = (tier: string, title: string) => relation(tier, state.presentation!, true, title)
const date = (s: string) => new Date(s).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
const status = (s: string) => ({ queued: '等待分析', running: '分析中', completed: '已完成', partial: '部分完成', failed: '未完成', interrupted: '已中断' }[s] || '历史记录')
let alive = true, sequence = 0, timer: ReturnType<typeof setTimeout> | undefined
let attempt: { fingerprint: string; request_id: string } | undefined
function chooseDefault() { if (!runs.value.some(r => r.id === viewed.value)) viewed.value = (active.value || runs.value[0])?.id || '' }
async function load(quiet = false) {
  const ticket = ++sequence, epoch = state.epoch, resumeId = state.resumeId
  if (!quiet) loading.value = true
  try {
    const rows = await api<RecordData[]>('/compare/runs', 'GET', undefined, 15000)
    if (!alive || ticket !== sequence || epoch !== state.epoch || resumeId !== state.resumeId) return
    history.value = rows; chooseDefault(); error.value = ''; if (attempt && rows.some(r => r.request_id === attempt?.request_id)) attempt = undefined
  } catch (e) { if (alive && ticket === sequence && epoch === state.epoch) error.value = e instanceof Error ? e.message : '无法获取分析记录。' }
  finally { if (alive && ticket === sequence) { loading.value = false; schedule() } }
}
function schedule() {
  clearTimeout(timer)
  if (alive && (active.value || error.value)) timer = setTimeout(() => { if (document.visibilityState !== 'hidden') void load(true); else schedule() }, 4000)
}
function visibility() { if (document.visibilityState === 'visible') void load(true) }
async function submit(retryId?: string) {
  if (retryId ? !canRetry.value : !ready.value) return
  const body = retryId ? {} : { resume_id: state.resumeId, job_ids: [...selected.value] }
  const endpoint = retryId ? `/compare/tasks/${encodeURIComponent(retryId)}/retry` : '/compare/tasks'
  const fingerprint = endpoint + JSON.stringify(body), epoch = state.epoch, resumeId = state.resumeId
  if (attempt?.fingerprint !== fingerprint) attempt = { fingerprint, request_id: createRequestId() }
  sequence++; clearTimeout(timer); loading.value = false
  submitting.value = true; error.value = ''
  try {
    const row = await api<RecordData>(endpoint, 'POST', { ...body, request_id: attempt.request_id }, 15000)
    if (!alive || epoch !== state.epoch || resumeId !== state.resumeId) return
    sequence++; loading.value = false
    history.value = [row, ...history.value.filter(r => r.id !== row.id)]; viewed.value = row.id; attempt = undefined
  } catch (e) {
    if (!alive || epoch !== state.epoch || resumeId !== state.resumeId) return
    error.value = e instanceof Error ? e.message : '未能提交分析。'
    if (e instanceof ApiError && e.status > 0) attempt = undefined
    // Keep the request id on uncertain network errors: retry cannot charge twice.
  } finally { if (alive && epoch === state.epoch && resumeId === state.resumeId) { submitting.value = false; schedule() } }
}
function selectQueryJob() {
  const id = typeof route.query.job === 'string' ? route.query.job : ''
  if (jobs.value.some(j => j.id === id)) selected.value = [id]
}
onMounted(() => {
  const id = typeof route.query.resume === 'string' ? route.query.resume : ''
  if (state.resumes.some(r => r.id === id)) state.resumeId = id
  selectQueryJob(); void load(); document.addEventListener('visibilitychange', visibility)
})
watch(() => [state.resumeId, state.epoch], () => { sequence++; submitting.value = false; viewed.value = ''; attempt = undefined; error.value = ''; void load() })
watch(() => route.query.job, selectQueryJob)
watch(jobs, () => { selected.value = selected.value.filter(id => jobs.value.some(j => j.id === id)) })
onUnmounted(() => { alive = false; sequence++; clearTimeout(timer); document.removeEventListener('visibilitychange', visibility) })
</script>

<template>
  <div class="job-fit">
    <section class="fit-builder surface" aria-labelledby="fit-builder-title">
      <div class="fit-builder-heading">
        <div><p class="eyebrow">从经历出发，整理选择</p><h2 id="fit-builder-title">一份简历，对照目标岗位</h2><p>技术强项、项目经历和岗位需求放在一起看。</p></div>
        <div class="fit-resume-field">
          <label class="fit-resume">用于分析的简历<select v-model="state.resumeId" :disabled="submitting" :aria-describedby="!state.resumes.length ? 'fit-resume-hint' : undefined"><option value="" disabled>请选择简历</option><option v-for="r in state.resumes" :key="r.id" :value="r.id">{{ r.display_name }}{{ r.data_origin === 'synthetic' ? ' · 合成示例' : '' }}</option></select></label>
          <div v-if="!state.resumes.length" class="fit-resume-help">
            <span id="fit-resume-hint">还没有简历？先导入一份，再开始分析。</span>
            <RouterLink to="/resumes" class="button secondary small fit-resume-import">导入简历<ArrowUpRight :size="14" /></RouterLink>
          </div>
        </div>
      </div>
      <div class="fit-search">
        <label><Search :size="18" /><input v-model="search" placeholder="搜索岗位、公司或技术方向" aria-label="搜索目标岗位" /></label>
        <button class="secondary fit-add-job" type="button" :disabled="selected.length >= 20 || submitting || state.switching" title="粘贴岗位描述，添加仅自己可见的岗位参照" @click="addingJob = true"><Plus :size="17" />添加岗位</button>
      </div>
      <div class="fit-selection-controls"><span aria-live="polite">{{ selected.length }} / 20 个已选</span><div><button class="secondary small" :disabled="!selectable.length" title="选中当前搜索结果，最多选择 20 个岗位" @click="selectAll"><Check :size="15" />{{ search.trim() ? '全选搜索结果' : '全选岗位' }}</button><button class="secondary small" :disabled="!selected.length" @click="selected = []">清空选择</button></div></div>
      <div class="fit-job-grid"><label v-for="j in filtered" :key="j.id" class="fit-job-option" :class="{ chosen: selected.includes(j.id) }"><input v-model="selected" type="checkbox" :value="j.id" :disabled="!selected.includes(j.id) && selected.length >= 20" :aria-label="'选择岗位：' + j.title" /><div><small>{{ j.personal_reference ? '个人参照 · 仅自己可见' : j.company_name || '招聘岗位' }}</small><strong>{{ j.title }}</strong><span>{{ j.profile.direction }}<template v-if="j.profile.education"> · {{ j.profile.education }}</template></span><div class="fit-skills"><span v-for="s in j.profile.requirements.slice(0,3)" :key="s.skill">{{ s.skill }}</span></div></div><Check v-if="selected.includes(j.id)" class="fit-chosen-mark" :size="16" /></label></div>
      <p v-if="!filtered.length" class="fit-empty">{{ jobs.length ? '没有匹配的岗位，试试其他关键词，或添加你想了解的岗位。' : '还没有可分析的岗位。点击“添加岗位”粘贴描述，或前往查看已发布岗位。' }}</p>
      <div class="fit-submit"><p>每次可选择 1–20 个岗位，已有岗位和个人参照可以一起分析。<br />默认使用 DeepSeek 官方，任务在后台进行，可离开后继续查看。</p><button class="primary" :disabled="!ready" @click="submit()"><Sparkles :size="17" />{{ submitting ? '正在提交…' : active ? '该简历正在分析' : '分析岗位契合度' }}</button></div>
    </section>

    <section class="fit-results" aria-labelledby="fit-results-title">
      <div class="fit-results-heading"><div><p class="eyebrow">选择有据可循</p><h2 id="fit-results-title">契合度与推荐顺序</h2></div><div class="fit-history"><label>分析历史<select v-model="viewed" :disabled="!runs.length"><option v-if="!runs.length" value="">暂无分析记录</option><option v-for="r in runs" :key="r.id" :value="r.id">{{ date(r.created_at) }} · {{ r.total || r.ranked_results.length }} 个岗位 · {{ status(r.status) }}</option></select></label><button class="secondary small" :disabled="loading" @click="load()"><RefreshCw :size="15" />刷新</button></div></div>
      <p v-if="error" role="alert" class="feedback error">{{ error }} 可刷新核对后台进度；重新提交会复用同一次未确认的请求。</p>
      <div v-if="active" class="fit-progress" role="status"><span class="fit-pulse"></span><div><strong>{{ status(active.status) }} · 已处理 {{ active.processed }} / {{ active.total }} 个岗位</strong><p>已完成的结果会逐步显示。可以切换页面，回来查看；无需重复点击。</p></div></div>
      <template v-if="run">
        <p class="fit-run-note">{{ run.resume_name || '所选简历' }} · {{ date(run.created_at) }} · {{ status(run.status) }}<span v-if="run.model"> · {{ run.mode === 'demo' ? '本地演示规则' : run.model.id === 'deepseek' ? 'DeepSeek 官方' : run.model.label }}</span><span v-if="run.data_origin === 'synthetic'"> · 合成示例</span><br />依据本次保存的简历与岗位版本，仅按已有证据归纳；缺失项只提示，不参与判定。<span v-if="run.policy_updated"> 已有记录已按五档规则更新，无需再次分析。</span></p>
        <div v-if="results.some((r: RecordData) => r.fit_summary)" class="fit-band-counts"><div v-for="b in bands" :key="b.id" :class="['fit-count', b.id]"><strong>{{ results.filter((r: RecordData) => r.fit_summary?.band === b.id).length }}</strong><span>{{ b.label }}</span></div></div>
        <p v-if="results.some((r: RecordData) => r.fit_summary?.band === 'unassessed')" class="fit-unassessed-note">{{ results.filter((r: RecordData) => r.fit_summary?.band === 'unassessed').length }} 个岗位暂无可判断的技术或项目依据，单独列示，不记作低契合。</p>
        <article v-for="r in results" :key="r.job_ref" class="fit-result-card surface" :class="r.fit_summary?.band || 'legacy'">
          <div class="fit-result-top"><span class="fit-position">{{ r.fit_summary?.band === 'unassessed' ? '—' : r.rank || '—' }}<small>{{ r.fit_summary?.band === 'unassessed' ? '暂不排位' : '推荐顺序' }}</small></span><div class="fit-result-title"><small>{{ r.company_name || (r.personal_reference ? '个人岗位参照' : '自选岗位') }}</small><h3>{{ r.job_title }}</h3><p>{{ r.fit_summary?.reason || '历史记录未生成契合档位，可重新分析查看。' }}</p></div><span :class="['fit-band', r.fit_summary?.band]">{{ r.fit_summary?.label || '历史结果' }}</span></div>
          <div v-if="r.fit_summary" class="fit-findings"><p v-if="r.fit_summary.coverage" class="fit-coverage"><strong>本次判断范围</strong>{{ r.fit_summary.coverage.known }} / {{ r.fit_summary.coverage.total }} 项有可用依据<span v-if="r.fit_summary.missing.length"> · 仅代表已描述的方面</span></p><p v-if="r.fit_summary.strengths.length"><strong>相符之处</strong>{{ r.fit_summary.strengths.join('、') }}</p><p v-if="r.fit_summary.gaps.length"><strong>现有差距</strong>{{ r.fit_summary.gaps.join('、') }}</p><p v-if="r.fit_summary.missing.length"><strong>未见相关描述</strong>{{ r.fit_summary.missing.join('、') }}</p><p v-if="r.fit_summary.additional_missing.length"><strong>其他信息提示</strong>{{ r.fit_summary.additional_missing.join('、') }}（仅提示）</p></div>
          <details class="fit-evidence"><summary>查看判断依据<span>经历原文与岗位要求</span></summary><div class="fit-evidence-content"><section v-for="d in r.dimensions" :key="d.dimension_id"><h4>{{ d.name }}<span>{{ label(d.tier,r.job_title) }}</span></h4><p>{{ d.rationale }}</p><blockquote v-for="(q,n) in d.evidence" :key="n"><small>简历原文</small>{{ q }}</blockquote><p v-if="!d.evidence.length" class="muted">现有描述不足，无法据此判断。</p></section><section v-for="(s,n) in r.skill_levels" :key="'skill-' + n"><h4>{{ s.skill }}<span>{{ label(s.tier,r.job_title) }}</span></h4><blockquote><small>岗位原文{{ s.hard ? ' · 主要要求' : '' }}</small>{{ s.requirement_quote }}</blockquote><blockquote v-for="(q,i) in s.evidence" :key="i"><small>简历原文</small>{{ q }}</blockquote><p v-if="!s.evidence.length" class="muted">尚未找到相应经历依据。</p></section></div></details>
          <div v-if="r.job_id && jobs.some(j => j.id === r.job_id)" class="fit-result-actions"><RouterLink :to="{ path: '/jobs', query: { job: r.job_id } }" class="button secondary small">查看岗位<ArrowUpRight :size="15" /></RouterLink><RouterLink :to="{ path: '/ai-workspace', query: { job: r.job_id, resume: state.resumeId } }" class="button secondary small">与 AI 讨论差距<ArrowUpRight :size="15" /></RouterLink></div>
        </article>
        <p v-for="(e,i) in run.errors" :key="i" class="feedback error">{{ failedTitle(e) }}：{{ e.error }}</p>
        <div v-if="canRetry" class="fit-retry"><p>保留已完成结果，仅重新分析失败或未完成的岗位。</p><button class="secondary" @click="submit(run.id)"><RefreshCw :size="16" />仅重试未完成岗位</button></div>
        <p v-if="!results.length && !['queued','running'].includes(run.status)" class="fit-empty">{{ run.message || '本次未生成可展示结果，请重新分析。' }}</p>
      </template>
      <div v-else class="fit-empty surface"><Sparkles :size="28" /><h3>{{ loading ? '正在加载分析记录…' : '下一步，从目标岗位开始' }}</h3><p>选择简历与岗位，按已有经历了解契合程度与推荐顺序。</p></div>
      <details class="fit-policy"><summary>契合度怎样判断？</summary><p>按“很高、较高、一般、较低、很低”五档展示。有依据的主要技能与项目经历逐项对照后，取中间档位；偶数项采用靠低的一档。没有主要技能要求时，使用其他已列明的技能。未见相关描述的项目只提示，不计入判断，也不当作能力低。</p><p>同档位并列，缺失项数量不参与排名。完全没有可判断的技术或项目依据时，单独显示“暂无判断依据”，不编造档位。每项结果同时展示判断范围；它只代表已有描述，不代表所有岗位要求都已得到确认。专业、学业及其他实践信息单独提示。</p></details>
    </section>
    <AddReferenceJob v-if="addingJob" @close="addingJob = false" @added="addedReference" />
  </div>
</template>

<style scoped>
.job-fit{display:grid;gap:32px}.fit-builder{overflow:hidden}.fit-builder-heading{display:grid;grid-template-columns:1fr minmax(250px,38%);gap:28px;padding:28px;background:linear-gradient(115deg,var(--brand-faint),#fff);border-bottom:1px solid var(--brand-edge)}.fit-builder-heading h2,.fit-results h2{margin:4px 0 10px;font-size:23px}.fit-builder-heading p{margin:0;color:#6b675f}.fit-resume,.fit-history label{display:grid;align-content:center;gap:9px;font-size:13px;font-weight:600}.fit-resume select{width:100%}
.fit-resume-field{display:grid;align-content:center;gap:10px;min-width:0}.fit-resume-help{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.fit-resume-help>span{font-size:12px;line-height:1.7;color:var(--text-muted)}.job-fit .fit-resume-import{flex-shrink:0;min-height:32px;padding:6px 10px;font-size:12px;gap:5px}
.fit-search{display:flex;align-items:center;gap:14px;padding:20px 28px}.fit-search label{display:flex;flex-direction:row;align-items:center;gap:8px;flex:1;min-width:0}.fit-search label svg{flex-shrink:0}.fit-add-job{flex-shrink:0;white-space:nowrap}.fit-selection-controls{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:0 28px 18px}.fit-selection-controls>span{font-size:12px;color:var(--text-muted)}.fit-selection-controls>div{display:flex;gap:10px;flex-wrap:wrap}.fit-search input{width:100%}.fit-search>span{font-size:12px;white-space:nowrap;color:#6d6962}.fit-job-grid{padding:0 28px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;max-height:420px;overflow:auto}.fit-job-option{position:relative;display:flex;flex-direction:row;align-items:flex-start;gap:12px;padding:18px;border:1px solid #dcdad6;border-radius:10px;background:#fff;cursor:pointer;transition:background .16s,border-color .16s,box-shadow .16s}.fit-job-option:hover{border-color:var(--brand-focus);box-shadow:0 3px 12px color-mix(in srgb, var(--text-main) 7.06%, transparent)}.fit-job-option.chosen{background:var(--brand-faint);border-color:var(--brand)}.fit-job-option input{margin-top:4px;flex-shrink:0}.fit-job-option>div{min-width:0;display:grid;gap:7px}.fit-job-option small{color:#6e6b64;font-size:12px}.fit-job-option strong{font-size:16px;line-height:1.5;overflow-wrap:anywhere;padding-right:12px}.fit-job-option div>span{font-size:12px;color:#6b675f}.fit-chosen-mark{position:absolute;top:18px;right:12px;color:var(--brand-ink)}.fit-skills{display:flex;gap:5px;flex-wrap:wrap}.fit-skills span{padding:3px 7px;background:var(--surface-soft);border-radius:4px;font-size:11px;color:#5e594e}.fit-submit{display:flex;gap:20px;justify-content:space-between;align-items:center;padding:22px 28px;margin-top:24px;border-top:1px solid var(--border-soft);background:var(--brand-faint)}.fit-submit p{font-size:12px;line-height:1.8;margin:0;color:#6d6960}.fit-submit button{flex-shrink:0}.fit-results-heading{display:flex;gap:20px;justify-content:space-between;align-items:center;margin-bottom:20px}.fit-history{display:flex;align-items:end;gap:10px}.fit-history select{max-width:340px}.fit-progress{display:flex;align-items:center;gap:15px;padding:18px 22px;border:1px solid var(--brand-focus);background:var(--brand-faint);border-radius:10px;margin-bottom:18px}.fit-progress strong{font-size:15px}.fit-progress p{margin:5px 0 0;font-size:12px;color:#6a6760}.fit-pulse{width:10px;height:10px;background:var(--brand);border-radius:50%;animation:fit-pulse 1.6s ease-in-out infinite}.fit-run-note{font-size:12px;color:#6c6962;line-height:1.9}.fit-band-counts{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:18px 0}.fit-count{display:flex;align-items:center;gap:12px;border:1px solid var(--border-soft);border-radius:9px;padding:16px 20px;background:#fff}.fit-count strong{font-size:26px}.fit-count span{font-size:13px}.fit-count.very_high{border-top:3px solid #08665a}.fit-count.high{border-top:3px solid #428c80}.fit-count.medium{border-top:3px solid #736e64}.fit-count.low{border-top:3px solid #b9781e}.fit-count.very_low{border-top:3px solid #a9634b}.fit-result-card{margin:14px 0;overflow:hidden;border-left:4px solid #aca9a3}.fit-result-card.very_high{border-left-color:#08665a}.fit-result-card.high{border-left-color:#428c80}.fit-result-card.medium{border-left-color:#736e64}.fit-result-card.low{border-left-color:#b9781e}.fit-result-card.very_low{border-left-color:#a9634b}.fit-result-top{display:flex;gap:22px;padding:24px;align-items:start}.fit-position{font-size:30px;font-weight:700;color:var(--text-muted);display:grid;gap:4px;text-align:center;min-width:58px}.fit-position small{font-size:10px;color:#7a766d;font-weight:400;white-space:nowrap}.fit-result-title{flex:1;min-width:0}.fit-result-title>small{color:#716e69;font-size:12px}.fit-result-title h3{font-size:19px;margin:6px 0 10px;overflow-wrap:anywhere}.fit-result-title p{font-size:14px;color:#646057;margin:0;line-height:1.8}.fit-band{background:var(--surface-soft);color:#625e55;padding:6px 12px;font-size:12px;border-radius:5px;white-space:nowrap;font-weight:700}.fit-band.very_high{background:#d9f0e9;color:#075a4e}.fit-band.high{background:#e9f4ef;color:#35665a}.fit-band.medium{background:#f0efed;color:#646057}.fit-band.low{background:#fff0d7;color:#88520a}.fit-band.very_low{background:#faece4;color:#8a4e3a}.fit-unassessed-note{font-size:13px;line-height:1.8;padding:13px 17px;border-left:3px solid #b2afaa;background:var(--brand-faint);color:#6b675f}.fit-coverage{padding-bottom:9px;border-bottom:1px solid var(--surface-soft)}.fit-coverage>span{color:#7e7a73}.fit-findings{margin:0 24px 18px 104px;display:grid;gap:9px}.fit-findings p{margin:0;font-size:13px;color:#5e5a51;line-height:1.7}.fit-findings strong{display:inline-block;margin-right:14px;color:#403c34;font-weight:600}.fit-evidence{border-top:1px solid var(--border-soft)}.fit-evidence>summary{cursor:pointer;padding:16px 24px;color:var(--brand-ink);font-weight:600;font-size:13px}.fit-evidence>summary span{margin-left:18px;color:#7e7b74;font-size:11px;font-weight:400}.fit-evidence-content{padding:0 24px 24px;display:grid;gap:16px}.fit-evidence-content section{padding:18px;background:var(--brand-faint);border:1px solid var(--border-soft);border-radius:8px;min-width:0}.fit-evidence-content h4{margin:0 0 10px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.fit-evidence-content h4 span{font-size:12px;font-weight:400;color:#6b675f}.fit-evidence-content p{font-size:13px;line-height:1.8}.fit-evidence-content blockquote{font-size:13px;line-height:1.8;margin:12px 0 0;padding:10px 14px;background:#fff;border-left:2px solid var(--brand-focus);overflow-wrap:anywhere}.fit-evidence-content blockquote small{display:block;color:#7f7b74;font-size:11px}.fit-result-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:10px;padding:14px 24px;border-top:1px solid var(--border-soft)}.fit-empty{text-align:center;padding:32px 20px;color:#716e67;font-size:14px;line-height:1.8}.fit-empty h3{color:#403c34}.fit-empty svg{color:var(--brand-ink)}.fit-policy{font-size:12px;line-height:1.9;color:#6d6960;margin-top:24px}.fit-policy summary{cursor:pointer;color:var(--brand-ink);font-weight:600}.fit-policy p{max-width:920px}.fit-retry{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:18px 22px;margin:16px 0;background:#fff;border:1px solid var(--border-soft);border-radius:10px}.fit-retry p{margin:0;font-size:13px;color:#6d6960}.feedback{overflow-wrap:anywhere}@keyframes fit-pulse{50%{opacity:.4;transform:scale(.8)}}@media(min-width:1600px){.fit-job-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:800px){.fit-builder-heading{grid-template-columns:1fr;padding:22px;gap:18px}.fit-search{padding:18px;flex-wrap:wrap}.fit-search{gap:10px}.fit-search label{flex-basis:calc(100% - 120px)}.fit-add-job{padding:10px 12px;font-size:12px}.fit-job-grid{grid-template-columns:1fr;padding:0 18px;max-height:380px}.fit-selection-controls{padding:0 18px 18px;flex-wrap:wrap}.fit-selection-controls>div{gap:8px}.fit-submit{flex-direction:column;align-items:stretch;padding:20px}.fit-submit button{justify-content:center}.fit-results-heading{flex-direction:column;align-items:stretch}.fit-history label{flex:1;min-width:0}.fit-history select{width:100%;max-width:100%}.fit-band-counts{grid-template-columns:1fr 1fr;gap:9px}.fit-count{padding:12px 16px}.fit-count:last-child{grid-column:1/-1}.fit-result-top{padding:20px 16px;gap:12px;flex-wrap:wrap}.fit-result-title{flex-basis:calc(100% - 75px)}.fit-result-title h3{font-size:17px}.fit-result-top>.fit-band{margin-left:70px}.fit-findings{margin:0 18px 20px}.fit-evidence>summary{padding:15px 18px}.fit-evidence>summary span{display:block;margin:5px 0 0 17px}.fit-evidence-content{padding:0 14px 18px}}@media(prefers-reduced-motion:reduce){.fit-pulse{animation:none}.fit-job-option{transition:none}}
</style>
