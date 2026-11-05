<script setup lang="ts">
import ResumeAttachment from "./ResumeAttachment.vue"
import { createRequestId } from '../request-id'
import { computed, onUnmounted, ref } from 'vue'
import { ArrowUpRight, Send, X } from '@lucide/vue'
import { api, ApiError, state } from '../store'
import { ended } from '../hiring'
import type { Job } from '../types'
import type { ApplicationDetail, ApplicationSummary } from '../hiring'

const props = defineProps<{ job: Job; existingApplication?: ApplicationSummary | null }>()
const emit = defineEmits<{ close: []; submitted: [application: ApplicationDetail]; duplicate: [] }>()
const resumeId = ref(state.resumeId || state.resumes[0]?.id || '')
const consent = ref(false); const introduction = ref(''); const pending = ref(false)
const error = ref(''); const requestId = createRequestId()
const selected = computed(() => state.resumes.find(r => r.id === resumeId.value))
const duplicate = ref(!!props.existingApplication); const existingId = ref(props.existingApplication?.id || '')
const progressLink = computed(() => ({ path: '/applications', query: existingId.value ? { application: existingId.value } : { job: props.job.id } }))
let alive = true
onUnmounted(() => { alive = false })
async function submit() {
  if (pending.value || duplicate.value || !consent.value || !selected.value) return
  pending.value = true; error.value = ''
  try {
    const row = await api<ApplicationDetail>('/applications', 'POST', { job_id: props.job.id, resume_id: resumeId.value,
      expected_job_version: props.job.version, consent_resume: consent.value,
      introduction: introduction.value, request_id: requestId })
    if (alive) emit('submitted', row)
  } catch (e) {
    if (!alive || e instanceof ApiError && ['STALE_CONTEXT', 'AUTH_REQUIRED'].includes(e.code)) return
    if (e instanceof ApiError && e.code === 'APPLICATION_EXISTS') {
      duplicate.value = true; error.value = ''; emit('duplicate')
      try {
        const rows = await api<ApplicationSummary[]>('/applications')
        if (alive) existingId.value = rows.find(r => r.job_id === props.job.id && !ended(r.status))?.id || ''
      } catch { /* The job-filtered progress link remains usable after a transient read failure. */ }
    } else error.value = e instanceof Error ? e.message : '投递未完成，请重试。'
  }
  finally { if (alive) pending.value = false }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="!pending && emit('close')"><section v-dialog class="modal apply-dialog" role="dialog" aria-modal="true" aria-labelledby="apply-title"><header class="detail-heading"><div><p class="eyebrow">{{ job.company_name || '认证企业' }}</p><h2 id="apply-title">{{ duplicate ? '已投递' : '投递' }}：{{ job.title }}</h2><p class="muted apply-intro">本次仅向这个岗位所属企业共享所选简历。AI 分析不会自动投递。</p></div><button class="icon-button" aria-label="关闭投递窗口" :disabled="pending" @click="emit('close')"><X :size="19" /></button></header>
    <p v-if="error" class="feedback error" role="alert">{{ error }}</p>
    <div v-if="duplicate" class="apply-duplicate" role="status"><p>你已投递该企业的这个岗位，可以查看现有进展，无需重复投递。</p><div class="form-footer"><button class="secondary" type="button" @click="emit('close')">关闭</button><RouterLink :to="progressLink" class="button primary">查看投递进展</RouterLink></div></div><form v-else-if="state.resumes.length" @submit.prevent="submit"><label>选择投递的简历<select v-model="resumeId" :disabled="pending" required><option v-for="resume in state.resumes" :key="resume.id" :value="resume.id">{{ resume.display_name }}</option></select></label><ResumeAttachment v-if="selected" :key="selected.id" :name="selected.display_name" :text="selected.text" note="投递前核对 · 点击查看共享正文" /><label>投递留言（可选）<textarea v-model="introduction" :disabled="pending" maxlength="2000" rows="3" placeholder="简要说明你想了解的工作与相关经历。" /></label><fieldset class="apply-authorizations"><legend class="sr-only">投递资料授权</legend><label class="check authorization-row"><input v-model="consent" type="checkbox" required :disabled="pending" /><span>我同意向 {{ job.company_name || '该认证企业' }} 共享所选简历正文、展示姓名和投递留言。<small class="authorization-kind">必选</small></span></label></fieldset><p class="apply-preference-note">求职期待自动沿用“我的期待”中的公开设置。<RouterLink to="/preferences" @click="state.resumeId = resumeId; emit('close')">管理公开范围<ArrowUpRight :size="12" /></RouterLink></p><p class="muted">投递会保存当前版本；后续修改简历不会自动替换。你可以在“我的投递”撤回授权。</p><div class="form-footer"><button type="button" class="secondary" :disabled="pending" @click="emit('close')">取消</button><button class="primary" :disabled="pending || !consent || !resumeId"><Send :size="15" />{{ pending ? '正在投递…' : '确认授权并投递' }}</button></div></form><div v-else class="empty compact"><h3>先准备一份简历</h3><p>导入简历后再选择要共享的材料。</p><RouterLink to="/resumes" class="button primary">去导入简历</RouterLink></div>
  </section></div>
</template>

<style scoped>
.apply-dialog{max-width:710px}.apply-dialog>.detail-heading{align-items:flex-start}.apply-dialog>.detail-heading>div{min-width:0}.apply-dialog>.detail-heading>.icon-button{flex-shrink:0;margin-top:12px}.apply-dialog .apply-intro{font-size:12px;line-height:1.8;margin:10px 0 0;overflow-wrap:anywhere}.apply-dialog form>label{margin:16px 0}.apply-dialog details{border:1px solid var(--line);border-radius:7px;padding:12px 14px;margin:15px 0}.apply-dialog summary{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--brand-ink);cursor:pointer}.apply-dialog details>.source-text{max-height:250px;overflow:auto;font-size:12px;margin-top:14px}.apply-authorizations{min-width:0;margin:20px 0 16px;padding:0;border:1px solid var(--line);border-radius:8px;background:#fff}.apply-dialog .authorization-row{margin:0;padding:13px 15px;font-size:12px;align-items:flex-start;gap:10px;line-height:1.8;cursor:pointer}.authorization-row+.authorization-row{border-top:1px solid var(--line)}.apply-dialog .authorization-row input{flex-shrink:0;margin:3px 0 0}.authorization-row>span{min-width:0;overflow-wrap:anywhere}.authorization-kind{display:inline-block;margin-left:7px;font-size:10px;color:var(--muted);white-space:nowrap}.apply-dialog form>.muted{font-size:11px}.apply-dialog>.feedback{margin:16px 26px 0}.apply-duplicate{padding:22px 26px 28px}.apply-duplicate>p{font-size:13px;line-height:1.8;color:var(--muted)}.apply-duplicate .form-footer{margin-top:20px}@media(max-width:760px){.apply-dialog>.feedback{margin-inline:20px}.apply-duplicate{padding:20px}}
.apply-preference-note{font-size:12px;line-height:1.8;color:var(--text-muted);margin:12px 0;display:flex;align-items:center;flex-wrap:wrap;gap:5px 10px}.apply-preference-note a{display:inline-flex;align-items:center;gap:3px;color:var(--brand-ink);text-decoration:underline;text-underline-offset:3px}
</style>
