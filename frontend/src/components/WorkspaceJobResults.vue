<script setup lang="ts">
import { computed } from 'vue'
import { ArrowUpRight, LoaderCircle, BriefcaseBusiness } from '@lucide/vue'
import type { Workspace } from '../ai-workspace'
const props = defineProps<{ assistance: NonNullable<Workspace['job_assistance']>; locked: boolean }>()
const emit = defineEmits<{ optimize: [jobId: string]; discuss: [] }>()
const comparison = computed(() => props.assistance.comparison)
const active = computed(() => ['queued', 'running'].includes(comparison.value?.status || ''))
const visible = computed(() => new Set(props.assistance.jobs.map(j => j.id)))
</script>
<template>
  <section v-if="assistance.jobs.length || comparison" class="ai-job-results" aria-label="助手岗位查询与契合度结果">
    <header><span><BriefcaseBusiness :size="17" /><strong>{{ comparison ? '岗位契合度对照' : '找到的岗位' }}</strong></span><RouterLink to="/compare" class="text-link">完整分析<ArrowUpRight :size="14" /></RouterLink></header>
    <template v-if="comparison">
      <div class="ai-comparison-progress" role="status"><LoaderCircle v-if="active" :size="15" class="spin" /><strong>{{ active ? '后台分析中' : comparison.status === 'failed' ? '分析未完成' : comparison.status === 'partial' ? '部分岗位已完成' : comparison.status === 'interrupted' ? '任务已中断' : '分析已完成' }}</strong><span>{{ comparison.processed }} / {{ comparison.total }} 个岗位</span></div>
      <progress v-if="active" :max="comparison.total || 1" :value="comparison.processed" aria-label="岗位分析进度" />
      <p class="ai-small-note">{{ comparison.notice }}</p>
      <article v-for="result in comparison.ranked_results" :key="result.job_id" class="ai-job-result" :data-band="result.fit_summary.band">
        <span class="ai-job-rank">{{ result.rank ? '#' + result.rank : '—' }}</span><div><small>{{ result.company_name || '岗位参照' }}</small><h3>{{ result.job_title }}</h3><span class="ai-fit-band">{{ result.fit_summary.label }}</span><p>{{ result.fit_summary.reason }}</p><details><summary>查看相符之处与差距</summary><p v-if="result.fit_summary.strengths.length">相符之处：{{ result.fit_summary.strengths.join('、') }}</p><p v-if="result.fit_summary.gaps.length">现有差距：{{ result.fit_summary.gaps.join('、') }}</p><p v-if="result.fit_summary.missing.length">当前材料未说明：{{ result.fit_summary.missing.join('、') }}。仅供了解，可跳过。</p></details><button type="button" class="secondary" :disabled="locked" @click="emit('optimize', result.job_id)">针对岗位优化<ArrowUpRight :size="13" /></button></div>
      </article>
      <p v-if="comparison.unavailable_count" class="ai-small-note">部分岗位已变更或不再公开，相关旧结果已隐藏。</p>
      <p v-for="(error, i) in comparison.errors" :key="i" class="ai-small-note" role="status">{{ error.error }}</p>
      <button v-if="!active && comparison.ranked_results.length" type="button" class="secondary" :disabled="locked" @click="emit('discuss')">和助手讨论这些结果</button>
    </template>
    <details v-if="assistance.jobs.length" :open="!comparison"><summary>{{ assistance.jobs.length }} 个可见岗位</summary><div class="ai-found-jobs"><article v-for="job in assistance.jobs" :key="job.id"><div><small>{{ job.company }}</small><strong>{{ job.title }}</strong></div><button type="button" class="secondary" :disabled="locked || !visible.has(job.id)" @click="emit('optimize', job.id)">针对岗位优化<ArrowUpRight :size="13" /></button></article></div></details>
  </section>
</template>
