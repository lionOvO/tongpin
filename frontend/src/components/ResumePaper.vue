<script setup lang="ts">
import { computed } from 'vue'
import { resumeParagraphs, resumeTitle } from '../resume-display'
const props = defineProps<{ name: string; text: string; compact?: boolean }>()
const paragraphs = computed(() => resumeParagraphs(props.text, props.compact))
</script>

<template>
  <article :class="['resume-paper', { 'resume-paper-compact': compact }]">
    <header><span>个人简历</span><h3>{{ resumeTitle(name) }}</h3><i /></header>
    <div class="resume-paper-content"><p v-for="(line, i) in paragraphs" :key="i" :class="{ 'resume-paper-section': line.heading }">{{ line.text }}</p></div>
  </article>
</template>

<style scoped>
.resume-paper{color:#3d3932;background:#fff;padding:44px 48px;min-height:920px;width:100%;font-family:MiSans,'Microsoft YaHei',sans-serif;text-align:left;box-sizing:border-box}
.resume-paper header{padding-bottom:18px;margin-bottom:25px;border-bottom:2px solid var(--brand);position:relative}
.resume-paper header>span{color:var(--text-muted);font-size:11px;letter-spacing:.2em;font-weight:500}
.resume-paper header h3{font-size:25px;font-weight:700;line-height:1.55;margin:10px 0 0;letter-spacing:.015em;overflow-wrap:anywhere}
.resume-paper header i{position:absolute;bottom:-2px;left:0;width:50px;height:4px;background:var(--brand)}
.resume-paper-content{font-size:13px;line-height:1.95;overflow-wrap:anywhere}
.resume-paper-content p{margin:0;white-space:pre-wrap}
.resume-paper-content .resume-paper-section{font-weight:700;color:var(--text-main);font-size:14px;margin-top:22px;padding-bottom:5px;border-bottom:1px solid var(--brand-edge)}
.resume-paper-compact{min-height:100%;padding:22px 23px;font-size:9px;pointer-events:none}
.resume-paper-compact header{padding-bottom:11px;margin-bottom:14px;border-bottom-width:1px}
.resume-paper-compact header>span{font-size:7px;letter-spacing:.12em}
.resume-paper-compact header h3{font-size:14px;line-height:1.5;margin-top:5px}
.resume-paper-compact header i{width:29px;height:2px;bottom:-1px}
.resume-paper-compact .resume-paper-content{font-size:8px;line-height:1.9}
.resume-paper-compact .resume-paper-content p{margin-bottom:0}
.resume-paper-compact .resume-paper-content .resume-paper-section{font-size:9px;margin-top:12px;padding-bottom:3px}
@media(max-width:600px){.resume-paper:not(.resume-paper-compact){padding:28px 23px;min-height:650px}.resume-paper:not(.resume-paper-compact) header h3{font-size:21px}}
</style>
