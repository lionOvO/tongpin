<script setup lang="ts">
import { state, candidate, confirmedJobs } from '../store'
import { watch } from 'vue'
const props = defineProps<{ withResume?: boolean; allJobs?: boolean; hideJob?: boolean }>()
watch(() => [props.hideJob, props.allJobs, state.jobId, confirmedJobs.value], () => {
  if (!props.hideJob && !props.allJobs && !confirmedJobs.value.some(j => j.id === state.jobId)) state.jobId = confirmedJobs.value[0]?.id || ''
}, { immediate: true })
</script>
<template><div class="context-bar"><label v-if="!hideJob">{{ candidate ? '参照岗位' : '当前岗位' }}<select v-model="state.jobId" :disabled="state.busy"><option value="" disabled>请先添加岗位</option><option v-for="j in allJobs ? state.jobs : confirmedJobs" :key="j.id" :value="j.id">{{ j.title }}{{ j.status !== '已确认' ? ' · 待确认' : '' }}</option></select></label><label v-if="withResume">我的简历<select v-model="state.resumeId" :disabled="state.busy"><option value="" disabled>请先导入简历</option><option v-for="r in state.resumes" :key="r.id" :value="r.id">{{ r.display_name }}</option></select></label><slot /></div></template>
