<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Phone, Video } from '@lucide/vue'
import { api } from '../store'
import { videoCall, callOutcome, formatCallDuration, type VideoCall } from '../video-calls'
const props = defineProps<{ applicationId: string }>()
const rows = ref<VideoCall[]>([])
let alive = true, sequence = 0, timer: ReturnType<typeof setInterval> | undefined
async function load() {
  const ticket = ++sequence, id = props.applicationId
  try {
    const result = await api<VideoCall[]>(`/video-calls?application_id=${encodeURIComponent(id)}`, 'GET', undefined, 8000)
    if (alive && sequence === ticket && id === props.applicationId) rows.value = result.filter(row => row.status === 'ended')
  } catch { /* Text messaging remains available when call history cannot load. */ }
}
watch(() => props.applicationId, () => { rows.value = []; void load() })
watch(() => videoCall.historyVersion, load)
onMounted(() => { void load(); timer = setInterval(load, 6000) })
onBeforeUnmount(() => { alive = false; sequence++; clearInterval(timer) })
</script>
<template><div v-if="rows.length" class="conversation-call-history" aria-label="视频通话记录"><article v-for="row in rows" :key="row.id"><component :is="row.connected_at ? Phone : Video" :size="15" /><span>{{ row.direction === 'outgoing' ? '呼出' : '呼入' }} · {{ callOutcome(row) }}<small v-if="row.connected_at"> · {{ formatCallDuration(row.duration_seconds) }}</small></span><time>{{ new Date(row.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }}</time></article></div></template>
