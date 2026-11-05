<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ShieldCheck, FileCheck2, Fingerprint, LockKeyhole, History, BriefcaseBusiness, UserRound, ArrowRight, Pause, Play } from '@lucide/vue'
import '../admin-entry.css'

const scene = ref(0); const paused = ref(false); const reduced = ref(false); const onScreen = ref(true)
const root = ref<HTMLElement | null>(null)
const scenes = [
  { title: '先核验，再开放招聘', text: '登记信息、营业执照与招聘授权，一起核对。', label: '企业核验', icon: ShieldCheck },
  { title: '共享有授权，访问有边界', text: '岗位与个人资料分开管理，按职责查看原文。', label: '资料边界', icon: LockKeyhole },
  { title: '每一次处理，都有据可查', text: '核实情况、记录依据，保留操作与处理对象。', label: '操作追溯', icon: History },
]
const playing = computed(() => !paused.value && !reduced.value && onScreen.value)
let timer: ReturnType<typeof setTimeout> | undefined
let media: MediaQueryList; let observer: IntersectionObserver | undefined
function schedule() {
  clearTimeout(timer)
  if (playing.value && document.visibilityState === 'visible') timer = setTimeout(() => { scene.value = (scene.value + 1) % scenes.length; schedule() }, 6500)
}
function select(index: number) { paused.value = true; scene.value = index }
function preference() { reduced.value = media.matches; schedule() }
function focusForm(event: FocusEvent) {
  if (event.target instanceof HTMLElement && event.target.closest('.auth-page-admin form')) paused.value = true
}
watch(playing, schedule)
onMounted(() => {
  media = window.matchMedia('(prefers-reduced-motion: reduce)'); preference()
  media.addEventListener('change', preference)
  document.addEventListener('visibilitychange', schedule); document.addEventListener('focusin', focusForm)
  observer = new IntersectionObserver(entries => { onScreen.value = entries[0]?.isIntersecting ?? false }, { threshold: .1 })
  if (root.value) observer.observe(root.value)
})
onBeforeUnmount(() => {
  clearTimeout(timer); observer?.disconnect(); media?.removeEventListener('change', preference)
  document.removeEventListener('visibilitychange', schedule); document.removeEventListener('focusin', focusForm)
})
</script>

<template>
  <section ref="root" class="admin-entry-story" :class="{ 'is-reduced': reduced }" aria-label="同频管理端工作导览">
    <p class="admin-entry-eyebrow"><span />同频 · 平台监管</p>
    <h1>让真实相遇，<br>从<span>信任开始。</span></h1>
    <p class="admin-entry-intro">从企业准入到资料边界，<br>把每一次核验，连接成可信的相遇。</p>
    <div class="admin-entry-canvas">
      <div class="admin-entry-fragments" aria-hidden="true"><span v-for="(label, i) in ['企业登记信息', '营业执照材料', '招聘授权文件']" :key="label" :style="{ '--fragment': i }"><FileCheck2 :size="18" />{{ label }}</span></div>
      <div class="admin-entry-board">
        <div class="admin-entry-board-head"><span><Fingerprint :size="17" />可信运营台</span><small>工作流程演示</small></div>
        <div class="admin-entry-scene-window">
          <Transition name="admin-entry-switch" mode="out-in">
            <div :key="scene" class="admin-entry-scene" :aria-label="scenes[scene]!.label">
              <template v-if="scene === 0"><div class="admin-entry-verification"><span class="admin-entry-shield"><ShieldCheck :size="37" /></span><div><strong>企业身份与招聘授权</strong><small>工作人员核实后开放招聘空间</small></div></div><div class="admin-entry-documents"><div v-for="label in ['登记信息', '营业执照', '招聘授权']" :key="label"><FileCheck2 :size="19" /><span>{{ label }}</span></div></div><p class="admin-entry-annotation"><LockKeyhole :size="13" />核验由工作人员完成</p></template>
              <template v-else-if="scene === 1"><div class="admin-entry-permissions"><div><BriefcaseBusiness :size="24" /><strong>企业岗位</strong><small>确认后主动公开</small></div><span><LockKeyhole :size="20" /></span><div><UserRound :size="24" /><strong>个人资料</strong><small>求职者授权共享</small></div></div><p class="admin-entry-annotation"><ShieldCheck :size="13" />管理端按监管职责访问，查看留痕</p></template>
              <template v-else><div class="admin-entry-audit"><div v-for="(label, i) in ['核实情况', '填写依据', '保存记录']" :key="label"><span>{{ i + 1 }}</span><FileCheck2 v-if="i === 1" :size="20" /><History v-else-if="i === 2" :size="20" /><ShieldCheck v-else :size="20" /><strong>{{ label }}</strong><ArrowRight v-if="i < 2" :size="14" /></div></div><p class="admin-entry-annotation"><Fingerprint :size="13" />处理对象、工作人员与依据关联保存</p></template>
            </div>
          </Transition>
        </div>
        <div class="admin-entry-caption"><strong>{{ scenes[scene]!.title }}</strong><p>{{ scenes[scene]!.text }}</p></div>
      </div>
    </div>
    <div class="admin-entry-controls"><div class="admin-entry-scene-buttons" role="group" aria-label="切换管理端演示"><button v-for="(item, i) in scenes" :key="item.label" :aria-pressed="scene === i" @click="select(i)"><component :is="item.icon" :size="14" />{{ item.label }}<i v-if="scene === i && playing" :key="scene" class="admin-entry-progress" aria-hidden="true" /></button></div><button v-if="!reduced" class="admin-entry-play" :aria-label="paused ? '播放流程演示' : '暂停流程演示'" :title="paused ? '播放流程演示' : '暂停流程演示'" @click="paused = !paused"><Play v-if="paused" :size="15" /><Pause v-else :size="15" /></button></div>
    <p class="admin-entry-staff"><ShieldCheck :size="16" /><span>专门的工作人员账号<small>管理权限由平台维护者授予。</small></span></p>
  </section>
</template>
