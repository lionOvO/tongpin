<script setup lang="ts">
import { computed, useId } from 'vue'
import { Check, GitBranch, MousePointer2 } from '@lucide/vue'
import { groupExperienceStrengths, type RecruiterStrength } from '../recruiter-review'

const props = defineProps<{ strengths: RecruiterStrength[]; selectedIndex: number; evidenceId: string }>()
const emit = defineEmits<{ select: [strength: RecruiterStrength] }>()
const groups = computed(() => groupExperienceStrengths(props.strengths))
const hintId = useId()
</script>

<template>
  <div class="experience-graph" aria-label="核心技术经历图谱">
    <p :id="hintId" class="graph-hint"><MousePointer2 :size="14" aria-hidden="true" />点击技术经历，在下方查看原文依据、业务关联和面试追问</p>
    <div class="graph-tree">
      <div class="graph-origin"><GitBranch :size="23" aria-hidden="true" /><strong>核心技术经历</strong><span>来自已授权简历</span></div>
      <ul class="graph-directions">
        <li v-for="group in groups" :key="group.id" class="graph-direction" :class="{ 'has-selection': group.items.some(item => item.index === selectedIndex) }">
          <h5 class="graph-direction-label">{{ group.label }}</h5>
          <ul class="graph-nodes">
            <li v-for="item in group.items" :key="item.index">
              <button type="button" :aria-pressed="item.index === selectedIndex" :aria-controls="evidenceId" :aria-describedby="hintId" @click="emit('select', item.strength)">
                <span class="graph-node-title"><strong>{{ item.strength.title }}</strong><Check v-if="item.index === selectedIndex" :size="15" aria-hidden="true" /></span>
                <span class="graph-node-work">{{ item.strength.work }}</span>
              </button>
            </li>
          </ul>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.experience-graph{container-type:inline-size;min-width:0;background:var(--brand-faint);border:1px solid var(--brand-edge);border-radius:12px;padding:18px 20px 22px}
.graph-hint{display:flex;align-items:flex-start;gap:7px;font-size:12px;line-height:1.8;color:#6e6b64;margin:0 0 22px}.graph-hint svg{flex-shrink:0;margin-top:4px;color:var(--brand-ink)}
.graph-tree{display:grid;grid-template-columns:118px minmax(0,1fr);align-items:center;gap:27px;min-width:0}
.graph-origin{position:relative;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:9px;background:var(--brand-soft);border:1px solid var(--brand-edge);border-radius:18px;padding:23px 8px;text-align:center;color:var(--brand-ink)}
.graph-origin strong{font-size:14px;line-height:1.7}.graph-origin span{font-size:11px;color:var(--text-muted)}.graph-origin:after{content:'';position:absolute;left:100%;top:50%;width:28px;height:1px;background:var(--brand-edge)}
.graph-directions,.graph-nodes{list-style:none;margin:0;padding:0;min-width:0}
.graph-directions{position:relative;display:grid;gap:18px;padding-block:6px}
.graph-directions:before{content:'';position:absolute;top:0;bottom:0;left:0;width:1px;background:var(--brand-edge)}
.graph-direction{position:relative;display:grid;grid-template-columns:90px minmax(0,1fr);align-items:center;gap:15px;padding-left:19px;min-width:0}
.graph-direction:before{content:'';position:absolute;left:0;top:50%;width:19px;height:1px;background:var(--brand-edge)}
.graph-direction-label{position:relative;font-size:13px;font-weight:600;color:#5c5850;margin:0;padding:8px 0;line-height:1.8;overflow-wrap:anywhere}
.graph-direction-label:after{content:'';position:absolute;left:100%;top:50%;width:15px;height:1px;background:var(--brand-edge)}
.has-selection>.graph-direction-label{color:var(--brand-ink)}
.graph-nodes{display:grid;gap:10px}
.graph-nodes>li{min-width:0}
.graph-nodes button{position:relative;width:100%;text-align:left;background:#fff;border:1px solid #dcd9d4;border-radius:10px;padding:13px 15px;display:flex;flex-direction:column;gap:7px;min-width:0;transition:background .18s,border-color .18s,box-shadow .18s}
.graph-nodes button:hover{border-color:var(--brand-focus);box-shadow:0 3px 10px color-mix(in srgb, var(--brand) 4.71%, transparent)}
.graph-nodes button[aria-pressed=true]{background:var(--brand-soft);border-color:var(--brand-focus);box-shadow:inset 3px 0 var(--brand)}
.graph-node-title{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;color:var(--text-main)}.graph-node-title strong{font-size:14px;font-weight:650;line-height:1.75;overflow-wrap:anywhere}.graph-node-title svg{flex-shrink:0;margin-top:5px;color:var(--brand-ink)}
.graph-node-work{font-size:13px;line-height:1.8;color:#646059;white-space:pre-wrap;overflow-wrap:anywhere}
@container(max-width:620px){.graph-tree{grid-template-columns:1fr;gap:18px}.graph-origin{flex-direction:row;flex-wrap:wrap;justify-content:flex-start;padding:13px 16px;gap:9px;border-radius:10px}.graph-origin span{margin-left:auto}.graph-origin:after{display:none}.graph-direction{grid-template-columns:80px minmax(0,1fr);gap:12px;padding-left:15px}.graph-direction:before{width:15px}.graph-direction-label:after{width:12px}}
@container(max-width:380px){.graph-directions{gap:20px}.graph-direction{grid-template-columns:minmax(0,1fr);gap:8px}.graph-direction-label{padding:0}.graph-direction-label:after{display:none}.graph-direction:before{top:11px}.graph-nodes button{padding:12px}.graph-origin{padding:12px}.graph-origin span{margin-left:0}.graph-hint{margin-bottom:16px}}
@media(max-width:650px){.experience-graph{padding:15px 13px 17px}}
@media(prefers-reduced-motion:reduce){.graph-nodes button{transition:none}}
</style>
