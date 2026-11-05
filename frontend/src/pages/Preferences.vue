<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { Check, ArrowUpRight } from '@lucide/vue'
import { notifyError, state, candidate, api, action } from '../store'
import type { RecordData } from '../types'
import Context from '../components/Context.vue'
import Empty from '../components/Empty.vue'
const cfg = ref<RecordData | null>(null); const values = ref<Record<string, string>>({}); const ambience = ref(''); const consent = ref(false); const history = ref<RecordData[]>([])
const targetId = computed(() => candidate.value ? state.resumeId : state.jobId)
const required = computed<RecordData[]>(() => (cfg.value?.dimensions || []).filter((d: RecordData) => d.required)); const optional = computed<RecordData[]>(() => (cfg.value?.dimensions || []).filter((d: RecordData) => !d.required))
const complete = computed(() => required.value.every((d: RecordData) => values.value[d.id] !== undefined && values.value[d.id] !== ''))
let sequence = 0
async function load() { const ticket = ++sequence; values.value = {}; consent.value = false; ambience.value = ''; try { const [c, h] = await Promise.all([api('/config/preferences'), api<RecordData[]>('/preferences')]); if (ticket !== sequence) return; cfg.value = c; history.value = h.filter(r => (candidate.value ? r.resume_id : r.job_id) === targetId.value); const prev = history.value[0]; if (prev) { values.value = Object.fromEntries(Object.entries(prev.dimensions).map(([k,v]) => [k,v === null ? '__unknown' : String(v)])); ambience.value = prev.ambience_text; consent.value = prev.share_with_counterparty } } catch(e) { if (ticket === sequence) notifyError(e) } }
onMounted(load); watch(targetId, load)
async function save() { await action(async () => { const dimensions = Object.fromEntries(Object.entries(values.value).filter(([,v]) => v !== '').map(([k,v]) => [k,v === '__unknown' ? null : v])); await api('/preferences/submit', 'POST', { side: candidate.value ? 'candidate' : 'enterprise', [candidate.value ? 'resume_id' : 'job_id']: targetId.value, dimensions, dimension_version: cfg.value!.version, ambience_text: candidate.value ? '' : ambience.value, share_with_counterparty: consent.value }); await load() }, '期待与公开设置已保存，相关投递会自动按此设置展示。') }
</script>
<template>
  <div class="page-heading"><p class="eyebrow">彼此期待 / 主动填写</p><h1>{{ candidate ? '说说你期待的工作。' : '团队偏好与氛围' }}</h1><p>先回答最在意的三个方面，再按需补充其他期待。</p></div><Context :with-resume="candidate" :hide-job="candidate" />
  <Empty v-if="!targetId" :title="candidate ? '先准备你的简历' : '先确认一个岗位'" text="偏好需要关联具体材料，才能保留对照参照。" :to="candidate ? '/resumes' : '/jobs'" />
  <div v-else-if="cfg" class="preference-layout"><form class="surface preference-form" @submit.prevent="save"><div class="detail-heading"><div><p class="eyebrow">主要期待</p><h2>最在意的三个方面</h2><p class="muted">三项均需选择；「无法判断 / 不愿透露」也是有效回答。</p></div></div><fieldset v-for="(d, i) in required" :key="d.id" class="preference-dimension"><legend><span>{{ String(i + 1).padStart(2, '0') }}</span>{{ d.name }}<small>必填</small></legend><div class="option-grid"><label v-for="o in [...d.options, '__unknown']" :key="o" :class="['option-card', { selected: values[d.id] === o }]"><input type="radio" :name="d.id" v-model="values[d.id]" :value="o" required><span>{{ o === '__unknown' ? '无法判断 / 不愿透露' : o }}</span><Check v-if="values[d.id] === o" :size="17" /></label></div></fieldset><details class="optional-preferences"><summary>更多期待 · 选填 {{ optional.length }} 项</summary><div class="form-grid"><label v-for="d in optional" :key="d.id">{{ d.name }}<select v-model="values[d.id]"><option value="">暂不填写</option><option v-for="o in d.options" :key="o">{{ o }}</option><option value="__unknown">无法判断 / 不愿透露</option></select></label></div></details><div v-if="!candidate" class="form-section"><h3>团队氛围</h3><p class="muted">由企业自行描述日常协作、沟通方式和工作节奏。</p><label><span class="sr-only">团队氛围描述</span><textarea v-model="ambience" rows="5" maxlength="2000" placeholder="例如：每周对齐目标，日常通过文档协作，遇到问题及时反馈。" /></label></div><fieldset class="expectation-visibility"><legend>谁可以看到我的期待</legend><p>{{ candidate ? '此设置用于当前简历的投递，投递时不再重复询问。' : '此设置用于当前岗位的应聘，保存后自动生效。' }}</p><div class="expectation-visibility-options"><label :class="{ selected: !consent }"><input type="radio" v-model="consent" :value="false" name="expectation-visibility"><span><strong>仅自己可见</strong><small>{{ candidate ? '保留我的期待，不向投递企业展示' : '保留团队期待，不向应聘者展示' }}</small></span></label><label :class="{ selected: consent }"><input type="radio" v-model="consent" :value="true" name="expectation-visibility"><span><strong>{{ candidate ? '公开给投递企业' : '公开给应聘者' }}</strong><small>用于双方期待对照，不公开到互联网</small></span></label></div><small>保存后统一应用于相关的有效投递。改为仅自己可见后，对方将无法继续查看期待及相关对照。</small></fieldset><div class="form-footer"><span>期待与公开设置一同保存。</span><button class="primary" :disabled="state.busy || !complete">保存我的期待<Check :size="17" /></button></div></form><aside class="preference-aside"><section class="context-card"><span class="eyebrow">由你表达</span><h3>期待可以不同，<br>依据需要清楚。</h3><p>系统直接对照双方选择，不猜测未填写的内容。差异帮助你们展开沟通，无法判断会明确保留。</p><RouterLink to="/matches" class="text-link">查看双方对照<ArrowUpRight :size="16" /></RouterLink></section><section class="context-card"><h3>当前填报</h3><p>{{ history.length ? '已有 ' + history.length + ' 次填报记录' : '还没有保存的偏好' }}</p><small>偏好口径 {{ cfg.version }}<br>有效投递自动更新；历史对照保留版本</small></section></aside></div>
</template>

<style scoped>
.expectation-visibility{margin:24px 26px;padding:20px;border:1px solid var(--brand-edge);border-radius:12px;background:var(--brand-faint);min-width:0}
.expectation-visibility legend{font-size:15px;font-weight:650;color:var(--text-main);padding:0 6px}
.expectation-visibility>p{font-size:12px;color:var(--text-muted);line-height:1.8;margin:0 0 14px}
.expectation-visibility-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.expectation-visibility-options label{display:flex;align-items:flex-start;gap:10px;padding:15px 13px;margin:0;border:1px solid var(--border-soft);border-radius:9px;background:var(--surface-paper);cursor:pointer;min-width:0}
.expectation-visibility-options label.selected{border-color:var(--brand);box-shadow:0 0 0 1px var(--brand);background:var(--surface-paper)}
.expectation-visibility-options label:focus-within{outline:2px solid var(--brand-focus);outline-offset:3px}
.expectation-visibility-options input{flex-shrink:0;width:16px;height:16px;margin:3px 0 0;accent-color:var(--brand)}
.expectation-visibility-options strong{display:block;font-size:13px;color:var(--text-main);line-height:1.7}
.expectation-visibility-options small{display:block;margin-top:5px;font-size:11px;color:var(--text-muted);line-height:1.7}
.expectation-visibility>small{display:block;margin-top:14px;font-size:11px;color:var(--text-muted);line-height:1.8}
@media(max-width:600px){.expectation-visibility{margin:22px 20px;padding:16px}.expectation-visibility-options{grid-template-columns:minmax(0,1fr)}}
</style>
