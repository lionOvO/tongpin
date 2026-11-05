<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ShieldCheck, FileCheck2, ArrowUpRight, RefreshCw, LoaderCircle } from '@lucide/vue'
import { api, state, action, download, refreshIdentity, switchWorkspace } from '../store'
import type { EnterpriseStatus } from '../types'
const props = withDefaults(defineProps<{ review?: boolean }>(), { review: false })
const router = useRouter()
interface Submission { id: string; company_name: string; credit_code: string; legal_representative: string; contact_name: string; license_name: string; authorization_name: string; status: EnterpriseStatus; reason: string }
const labels: Record<EnterpriseStatus, string> = { unsubmitted: '未提交', pending: '待人工核验', approved: '认证已通过', rejected: '需补充材料', revoked: '认证已撤销' }
const status = ref<EnterpriseStatus>('unsubmitted'); const submission = ref<Submission | null>(null); const rows = ref<Submission[]>([])
const loading = ref(true); const form = ref<HTMLFormElement | null>(null); const reason = ref<Record<string, string>>({})
const reviewFeedback = ref<Record<string, { error?: string; success?: string }>>({})
const reviewing = ref<{ id: string; decision: 'approve' | 'reject' | 'revoke' } | null>(null)
const companyName = ref(''); const creditCode = ref(''); const legalRepresentative = ref(''); const contactName = ref('')
const editable = computed(() => ['unsubmitted', 'rejected', 'revoked'].includes(status.value))
async function load() {
  loading.value = true
  try {
    await refreshIdentity()
    if (props.review) rows.value = await api<Submission[]>('/enterprise-reviews')
    else {
      const result = await api<{ status: EnterpriseStatus; submission: Submission | null }>('/enterprise-verification')
      status.value = result.status; submission.value = result.submission
      if (result.submission) { companyName.value = result.submission.company_name; creditCode.value = result.submission.credit_code; legalRepresentative.value = result.submission.legal_representative; contactName.value = result.submission.contact_name }
    }
  } finally { loading.value = false }
}
onMounted(() => { void action(load) })
async function submit() {
  if (!form.value) return
  const body = new FormData(form.value)
  for (const name of ['license', 'authorization']) {
    const file = body.get(name)
    if (!(file instanceof File) || !file.size || file.size > 5 * 1024 * 1024) { state.error = '请上传营业执照和招聘授权材料，每份文件不超过 5MB。'; return }
  }
  await action(async () => { await api('/enterprise-verification', 'POST', body); await load() }, '企业资质已提交，人工核验通过后即可使用招聘空间。')
}
async function decide(row: Submission, decision: 'approve' | 'reject' | 'revoke') {
  if (state.busy || state.switching || reviewing.value) return
  const text = reason.value[row.id]?.trim() || ''
  if (text.length < 5) {
    reviewFeedback.value[row.id] = { error: decision === 'revoke' ? '请先填写撤销认证的依据，至少 5 个字符。' : '请填写核验依据或退回原因，至少 5 个字符。' }
    document.getElementById('review-reason-' + row.id)?.focus()
    return
  }
  await action(async () => {
    const epoch = state.epoch
    reviewing.value = { id: row.id, decision }
    reviewFeedback.value[row.id] = {}
    try {
      const updated = await api<Submission>('/enterprise-reviews/' + row.id, 'POST', { decision, reason: text })
      Object.assign(row, updated)
      reason.value[row.id] = ''
      reviewFeedback.value[row.id] = { success: decision === 'approve' ? '企业认证已通过。' : decision === 'revoke' ? '认证已撤销，招聘方会话已失效，公开岗位已停止展示。' : '申请已退回，申请人可补充后重新提交。' }
    } catch (error) {
      if (epoch === state.epoch) reviewFeedback.value[row.id] = { error: error instanceof Error ? error.message : '操作失败，请重试。' }
      throw error
    } finally { reviewing.value = null }
  })
}
async function enter() { try { await switchWorkspace('enterprise'); await router.replace('/workspace') } catch (e) { state.error = e instanceof Error ? e.message : '切换失败，请刷新后重试。' } }
function evidence(row: Submission, kind: 'license' | 'authorization') { void action(() => download('/enterprise-verification/' + row.id + '/files/' + kind, kind === 'license' ? row.license_name : row.authorization_name)) }
</script>
<template>
  <div class="verification-page">
    <div class="page-heading"><p class="eyebrow">{{ review ? '内部维护 / 企业真实性核验' : '企业认证 / 招聘空间' }}</p><h1>{{ review ? '让真实企业进入招聘空间。' : '先确认企业，再开始招聘。' }}</h1><p>{{ review ? '核对登记信息、营业执照及招聘授权，并记录你的核验依据。提交材料不会自动通过。' : '求职与招聘资料分别保存。企业资质经人工核验通过后，才能进入招聘空间并发布职位。' }}</p></div>
    <div class="verification-toolbar"><span class="pill" v-if="!review">{{ labels[status] }}</span><button class="secondary" :disabled="state.busy || loading" @click="action(load)"><RefreshCw :size="15" />刷新{{ review ? '申请列表' : '审核状态' }}</button></div>
    <div v-if="loading" class="loading"><LoaderCircle class="spin" />正在读取认证信息…</div>
    <template v-else-if="!review">
      <section v-if="submission" class="surface verification-record"><div class="row-between"><h2>{{ submission.company_name }}</h2><span :class="['pill', { teal: status === 'approved', amber: status === 'pending' }]">{{ labels[status] }}</span></div><dl class="verification-details"><div><dt>统一社会信用代码</dt><dd>{{ submission.credit_code }}</dd></div><div><dt>法定代表人</dt><dd>{{ submission.legal_representative }}</dd></div><div><dt>招聘联系人</dt><dd>{{ submission.contact_name }}</dd></div></dl><div class="button-row"><button class="text-link" :disabled="state.busy" @click="evidence(submission, 'license')">下载已提交营业执照</button><button class="text-link" :disabled="state.busy" @click="evidence(submission, 'authorization')">下载已提交招聘授权</button></div><p v-if="submission.reason" class="verification-reason">审核说明：{{ submission.reason }}</p><p v-if="status === 'pending'" class="muted">材料已提交。管理员需核对企业登记信息和授权关系；审核通过前，招聘空间暂不可用。</p><button v-if="status === 'approved'" class="primary" :disabled="state.busy || state.loading" @click="enter">进入招聘方空间<ArrowUpRight :size="17" /></button></section>
      <section v-if="editable" class="surface verification-form"><div class="section-heading"><h2>{{ submission ? '补充并重新提交' : '提交企业资质' }}</h2><FileCheck2 :size="23" /></div><form ref="form" @submit.prevent="submit"><fieldset class="verification-group"><legend>企业登记信息</legend><div class="verification-fields"><label>企业全称<input name="company_name" v-model="companyName" placeholder="与营业执照上的名称一致" required minlength="2" maxlength="100"></label><label>统一社会信用代码<input name="credit_code" v-model="creditCode" placeholder="营业执照上的 18 位代码" pattern="[0-9A-HJ-NPQRTUWXY]{18}" required maxlength="18"></label><label>法定代表人姓名<input name="legal_representative" v-model="legalRepresentative" required minlength="2" maxlength="100"></label><label>招聘联系人姓名<input name="contact_name" v-model="contactName" required minlength="2" maxlength="100"></label></div></fieldset><fieldset class="verification-group proofs"><legend>招聘资格材料</legend><div class="verification-fields"><label>营业执照<input name="license" type="file" accept=".pdf,.png,.jpg,.jpeg" required><small>完整、清晰的营业执照，PDF / PNG / JPG，单份不超过 5MB。</small></label><label>招聘授权材料<input name="authorization" type="file" accept=".pdf,.png,.jpg,.jpeg" required><small>证明你有权代表该企业招聘的材料，例如加盖公章的招聘授权书。单份不超过 5MB。</small></label></div></fieldset><div class="verification-privacy"><ShieldCheck :size="19" /><p>资质材料仅你本人和管理员可查看，不向其他求职者或招聘方公开。手机号绑定当前已验证账号：{{ state.user?.name }}。</p></div><button class="primary" :disabled="state.busy">提交企业资质<ArrowUpRight :size="17" /></button></form></section>
    </template>
    <template v-else>
      <div v-if="!rows.length" class="empty surface"><h3>暂无企业认证申请</h3><p>申请人提交材料后会出现在这里。</p></div>
      <article v-for="row in rows" :key="row.id" class="surface verification-record">
        <div class="row-between"><h2>{{ row.company_name }}</h2><span :class="['pill', { teal: row.status === 'approved' }]">{{ labels[row.status] }}</span></div>
        <dl class="verification-details"><div><dt>统一社会信用代码</dt><dd>{{ row.credit_code }}</dd></div><div><dt>法定代表人</dt><dd>{{ row.legal_representative }}</dd></div><div><dt>招聘联系人</dt><dd>{{ row.contact_name }}</dd></div></dl>
        <div class="button-row"><button class="text-link" :disabled="state.busy" @click="evidence(row, 'license')">下载营业执照</button><button class="text-link" :disabled="state.busy" @click="evidence(row, 'authorization')">下载招聘授权材料</button></div>
        <p v-if="row.reason" class="verification-reason">上次审核说明：{{ row.reason }}</p>
        <template v-if="['pending', 'approved'].includes(row.status)">
          <label class="verification-review-label" :for="'review-reason-' + row.id">
            {{ row.status === 'pending' ? '核验依据 / 退回原因' : '撤销认证的依据' }}
            <textarea :id="'review-reason-' + row.id" v-model="reason[row.id]" minlength="5" maxlength="1000" :disabled="state.busy"
              :aria-invalid="!!reviewFeedback[row.id]?.error" :aria-describedby="'review-help-' + row.id + (reviewFeedback[row.id]?.error ? ' review-feedback-' + row.id : '')"
              :placeholder="row.status === 'approved' ? '请填写撤销依据，例如：企业招聘授权已撤回，需暂停招聘资格。' : '请记录企业登记信息、执照及招聘授权的核验结果，或需补充的材料。'"
              @input="delete reviewFeedback[row.id]?.error" />
            <small :id="'review-help-' + row.id" class="verification-review-help">必填，至少 5 个字符。{{ row.status === 'approved' ? '撤销后将暂停该企业招聘权限及公开岗位展示，保留原有资料。' : '请记录具体依据，便于审核留痕。' }}</small>
          </label>
          <div class="button-row">
            <template v-if="row.status === 'pending'">
              <button class="primary" :disabled="state.busy" @click="decide(row, 'approve')"><LoaderCircle v-if="reviewing?.id === row.id && reviewing.decision === 'approve'" class="spin" :size="16" />{{ reviewing?.id === row.id && reviewing.decision === 'approve' ? '正在通过…' : '核验通过' }}</button>
              <button class="secondary" :disabled="state.busy" @click="decide(row, 'reject')"><LoaderCircle v-if="reviewing?.id === row.id && reviewing.decision === 'reject'" class="spin" :size="16" />{{ reviewing?.id === row.id && reviewing.decision === 'reject' ? '正在退回…' : '退回补充' }}</button>
            </template>
            <button v-else class="danger" :disabled="state.busy" @click="decide(row, 'revoke')"><LoaderCircle v-if="reviewing?.id === row.id" class="spin" :size="16" />{{ reviewing?.id === row.id ? '正在撤销…' : '撤销企业认证' }}</button>
          </div>
        </template>
        <p v-if="reviewFeedback[row.id]?.error" :id="'review-feedback-' + row.id" class="verification-review-feedback error" role="alert">{{ reviewFeedback[row.id]?.error }}</p>
        <p v-if="reviewFeedback[row.id]?.success" class="verification-review-feedback success" role="status">{{ reviewFeedback[row.id]?.success }}</p>
      </article>
    </template>
  </div>
</template>
<style scoped>
.verification-review-help { color: var(--muted); font-size: 12px; font-weight: 400; line-height: 1.7; }
.verification-review-label textarea[aria-invalid="true"] { border-color: #b83c47; }
.verification-review-feedback { margin-top: 14px; padding: 12px 14px; border-radius: 8px; font-size: 13px; line-height: 1.7; }
.verification-review-feedback.error { color: #a52d39; background: #fff2f2; border: 1px solid #efc7cb; }
.verification-review-feedback.success { color: #08786e; background: #eaf8f3; border: 1px solid #b9e2d6; }
</style>
