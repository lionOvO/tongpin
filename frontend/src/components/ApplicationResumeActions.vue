<script setup lang="ts">
import { ref } from 'vue'
import { Download, ArrowDownToLine } from '@lucide/vue'
import { action, api, download, state } from '../store'
import type { ApplicationDetail } from '../hiring'
import type { Resume } from '../types'
const props = defineProps<{ application: ApplicationDetail }>()
const imported = ref(false)
async function importResume() {
  await action(async () => {
    const result = await api<{ resume: Resume }>('/applications/' + props.application.id + '/resume-import', 'POST', { expected_version: props.application.version })
    state.resumes = [result.resume, ...state.resumes.filter(r => r.id !== result.resume.id)]
    state.resumeId = result.resume.id; imported.value = true
  }, '已导入，可在“简历与初筛”中使用。')
}
async function downloadResume() { await action(() => download('/applications/' + props.application.id + '/resume-download', props.application.resume_name.replace(/[\\/:*?"<>|\r\n]/g, '_') + '.txt')) }
</script>
<template>
  <div v-if="application.resume_shared && application.available" class="application-resume-tools"><button class="secondary" :disabled="state.busy" @click="downloadResume"><Download :size="15" />下载投递简历（TXT）</button><button class="secondary" :disabled="state.busy || imported" @click="importResume"><ArrowDownToLine :size="15" />{{ imported ? '已导入简历库' : '一键导入简历库' }}</button><RouterLink to="/resumes" class="text-link">前往简历与初筛 →</RouterLink></div>
</template>
<style scoped>
.application-resume-tools{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0}.application-resume-tools button{min-height:36px;font-size:12px;padding:9px 12px}.application-resume-tools .text-link{font-size:12px}
</style>
