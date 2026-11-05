<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowUpRight, ShieldCheck, Users, BriefcaseBusiness, Files, RefreshCw, X } from '@lucide/vue'
import { api, state, notifyError } from '../store'
import type { RecordData } from '../types'
const props = defineProps<{ section: 'overview' | 'accounts' | 'jobs' | 'resumes' | 'events' }>()
const loading = ref(false); const overview = ref<RecordData>({}); const items = ref<RecordData[]>([])
const offset = ref(0); const total = ref(0); const detail = ref<RecordData | null>(null)
const operation = ref<{ item: RecordData; path: string; title: string } | null>(null); const reason = ref(''); const processing = ref(false)
const titles = { overview: '平台监管概览', accounts: '账号监管', jobs: '招聘岗位监管', resumes: '求职资料监管', events: '操作记录' }
const stats = computed(() => [
  { label: '待审核企业', key: 'pending_verifications', icon: ShieldCheck, to: '/admin/enterprise-reviews', hint: '核对登记信息、执照与招聘授权' },
  { label: '平台用户', key: 'accounts', icon: Users, to: '/admin/accounts', hint: '求职者与招聘方的注册账号' },
  { label: '岗位资料', key: 'job_profiles', icon: BriefcaseBusiness, to: '/admin/jobs', hint: '包含未公开岗位及个人对照资料' },
  { label: '简历材料', key: 'resumes', icon: Files, to: '/admin/resumes', hint: '按监管职责查看，访问自动留痕' },
])
const statusLabels: Record<string, string> = { approved: '认证通过', pending: '待审核', rejected: '未通过', revoked: '认证已撤销', unsubmitted: '未提交', suspended: '已下架', cleared: '限制已解除' }
function date(value: string | number) { return new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString('zh-CN', { hour12: false }) }
let sequence = 0
async function load() {
  const ticket = ++sequence; const epoch = state.epoch; loading.value = true
  try {
    if (props.section === 'overview') {
      const value = await api('/admin/overview'); if (ticket === sequence && epoch === state.epoch) overview.value = value
    } else {
      const path = props.section === 'accounts' || props.section === 'events' ? '/admin/' + props.section : '/admin/records/' + props.section
      const result = await api<{ items: RecordData[]; total: number }>(path + '?offset=' + offset.value + '&limit=20')
      if (ticket === sequence && epoch === state.epoch) { items.value = result.items; total.value = result.total }
    }
  } catch (e) { notifyError(e) } finally { if (ticket === sequence) loading.value = false }
}
watch(() => props.section, () => { offset.value = 0; items.value = []; detail.value = null; operation.value = null; void load() }); onMounted(load)
async function inspect(item: RecordData) {
  processing.value = true; const epoch = state.epoch
  try { const value = await api('/admin/records/' + props.section + '/' + item.id); if (epoch === state.epoch) detail.value = value }
  catch (e) { notifyError(e) } finally { processing.value = false }
}
function requestAction(item: RecordData) {
  reason.value = ''
  const restoring = props.section === 'accounts' ? item.disabled : item.moderation_status === 'suspended'
  operation.value = { item, path: '/admin/' + props.section + '/' + item.id + '/' + (props.section === 'accounts' ? restoring ? 'restore' : 'suspend' : restoring ? 'restore' : 'hide'), title: props.section === 'accounts' ? restoring ? '恢复账号' : '暂停账号' : restoring ? '解除岗位限制' : '下架招聘岗位' }
}
async function execute() {
  if (!operation.value || reason.value.trim().length < 5 || processing.value) return
  processing.value = true
  try { await api(operation.value.path, 'POST', { reason: reason.value.trim() }); operation.value = null; state.success = '处理完成，操作依据已记录。'; await load() }
  catch (e) { notifyError(e) } finally { processing.value = false }
}
function page(direction: number) { offset.value += direction * 20; void load() }
</script>
<template>
  <div class="page-heading heading-action"><div><p class="eyebrow">同频内部 · 平台管理端</p><h1>{{ titles[section] }}</h1><p>维护真实企业与可信资料，让双方在清晰的边界内使用同频。</p></div><button class="secondary" :disabled="loading || processing" @click="load"><RefreshCw :size="16"/>刷新</button></div>
  <p class="admin-policy"><ShieldCheck :size="18"/><span>资料仅用于平台监管。查看原文会留存访问记录；暂停账号、下架岗位必须填写处理依据。</span></p>
  <p v-if="loading" class="loading" role="status">正在读取监管数据…</p>
  <template v-else-if="section === 'overview'">
    <div class="admin-stats"><RouterLink v-for="metric in stats" :key="metric.key" :to="metric.to" class="surface admin-stat"><div><component :is="metric.icon" :size="22"/><ArrowUpRight :size="18"/></div><small>{{ metric.label }}</small><strong>{{ overview[metric.key] ?? '—' }}</strong><p>{{ metric.hint }}</p></RouterLink></div>
    <section class="surface admin-workflow"><div><p class="eyebrow">企业准入</p><h2>先核验，再开放招聘。</h2><p>普通账号提交资质后保持待审核。工作人员核对企业登记信息、营业执照和招聘授权，审核通过后才开放招聘空间。</p><RouterLink class="primary" to="/admin/enterprise-reviews">处理企业认证<ArrowUpRight :size="17"/></RouterLink></div><ol><li><span>01</span><div><strong>确认真实企业</strong><p>核对登记信息与证明文件。</p></div></li><li><span>02</span><div><strong>确认招聘授权</strong><p>确保申请人与企业存在授权关系。</p></div></li><li><span>03</span><div><strong>持续监管与追溯</strong><p>异常时撤销认证或暂停账号，处理依据留痕。</p></div></li></ol></section>
    <p class="muted">已暂停账号 {{ overview.suspended_accounts ?? 0 }} 个 · 能力报告 {{ overview.ability_reports ?? 0 }} 份 · 岗位对照 {{ overview.fit_reports ?? 0 }} 份</p>
  </template>
  <section v-else class="surface admin-table-panel">
    <div class="list-toolbar"><strong>{{ titles[section] }}</strong><span class="muted">共 {{ total }} 条 · 每页 20 条</span></div>
    <div v-if="!items.length" class="empty"><h3>暂无记录</h3><p>{{ section === 'events' ? '查看资料和监管处理后，记录会出现在这里。' : '该环境下还没有对应数据。' }}</p></div>
    <div v-else class="admin-table-scroll"><table class="admin-table"><thead><tr><template v-if="section === 'accounts'"><th>账号</th><th>企业认证</th><th>账号状态</th></template><template v-else-if="section === 'events'"><th>操作与对象</th><th>处理依据</th><th>工作人员</th></template><template v-else><th>资料与归属</th><th>工作空间</th><th>公开状态</th></template><th>时间</th><th v-if="section !== 'events'">操作</th></tr></thead><tbody><tr v-for="item in items" :key="item.id">
      <template v-if="section === 'accounts'"><td><strong>{{ item.name }}</strong><small>{{ item.role === 'admin' ? '平台工作人员' : '普通用户' }}</small></td><td>{{ statusLabels[item.enterprise_status] }}<small>{{ item.company_name || '—' }}</small></td><td><span class="pill" :class="{ teal: !item.disabled }">{{ item.disabled ? '已暂停' : '正常' }}</span></td></template>
      <template v-else-if="section === 'events'"><td><strong>{{ item.action }}</strong><small>{{ item.resource }} · {{ item.resource_id }}</small></td><td class="admin-reason">{{ item.reason }}</td><td><small>{{ item.staff_id }}</small></td></template>
      <template v-else><td><strong>{{ item.title || item.display_name || '未命名资料' }}</strong><small>{{ item.owner_name }}</small></td><td>{{ item.workspace === 'candidate' ? '求职者' : '招聘方' }}<small>{{ item.data_origin === 'synthetic' ? '合成 / 演示资料' : '用户资料' }}</small></td><td>{{ section === 'resumes' ? '账号私有' : item.moderation_status === 'suspended' ? '平台已下架' : item.published ? '已公开' : '未公开' }}<small v-if="item.moderation_reason">{{ item.moderation_reason }}</small></td></template>
      <td class="admin-time">{{ date(item.created_at) }}</td><td v-if="section !== 'events'"><div class="admin-row-actions"><button v-if="section === 'jobs' || section === 'resumes'" class="text-link" :disabled="processing" @click="inspect(item)">查看原文</button><button v-if="section === 'accounts' && item.role !== 'admin' || section === 'jobs' && item.workspace === 'enterprise'" class="text-link" :disabled="processing" @click="requestAction(item)">{{ section === 'accounts' ? item.disabled ? '恢复账号' : '暂停账号' : item.moderation_status === 'suspended' ? '解除限制' : '下架岗位' }}</button></div></td>
    </tr></tbody></table></div>
    <div class="admin-pagination"><button class="secondary" :disabled="offset === 0 || loading" @click="page(-1)">上一页</button><span>第 {{ Math.floor(offset / 20) + 1 }} 页</span><button class="secondary" :disabled="offset + 20 >= total || loading" @click="page(1)">下一页</button></div>
  </section>
  <div v-if="detail" class="modal-backdrop" @click.self="detail = null"><section v-dialog class="modal" role="dialog" aria-modal="true" aria-labelledby="admin-detail-title"><header><h2 id="admin-detail-title">{{ detail.title || detail.display_name }} · 资料原文</h2><button class="icon-button" aria-label="关闭资料" @click="detail = null"><X :size="20"/></button></header><p class="muted">本次访问已记录，仅用于监管处理。</p><pre class="admin-source">{{ detail.text || detail.source_jd || '暂无原文' }}</pre><button class="secondary" @click="detail = null">关闭</button></section></div>
  <div v-if="operation" class="modal-backdrop" @click.self="!processing && (operation = null)"><section v-dialog class="modal" role="dialog" aria-modal="true" aria-labelledby="admin-action-title"><header><h2 id="admin-action-title">{{ operation.title }}</h2><button class="icon-button" aria-label="关闭处理" :disabled="processing" @click="operation = null"><X :size="20"/></button></header><p>处理对象：{{ operation.item.name || operation.item.title }}</p><p class="muted">{{ section === 'accounts' ? '暂停后全部登录会话失效；恢复后需要重新登录。' : '下架立即停止公开；解除限制后仍保持私有，由招聘方主动重新公开。' }}</p><form @submit.prevent="execute"><label>处理依据<textarea v-model="reason" minlength="5" maxlength="1000" required rows="4" placeholder="填写核实情况与处理原因，至少 5 个字符" :disabled="processing"/></label><div class="admin-row-actions"><button type="button" class="secondary" :disabled="processing" @click="operation = null">取消</button><button class="primary" :disabled="processing || reason.trim().length < 5">{{ processing ? '正在处理…' : '确认' + operation.title }}</button></div></form></section></div>
</template>
