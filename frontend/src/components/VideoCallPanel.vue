<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowUpRight, BriefcaseBusiness, Maximize2, Mic, MicOff, Minimize2, Phone, PhoneOff, Video, VideoOff, Volume2, X } from '@lucide/vue'
import { state } from '../store'
import { videoCall as call, localVideo, remoteVideo, dialVideoCall, acceptVideoCall, endVideoCall, closeVideoCall,
  toggleCamera, toggleMicrophone, resetVideoCalls, pollVideoCalls, callOutcome, formatCallDuration } from '../video-calls'
import '../video-calls.css'

const router = useRouter()
const localElement = ref<HTMLVideoElement | null>(null), remoteElement = ref<HTMLVideoElement | null>(null)
const soundBlocked = ref(false), clock = ref(Date.now())
const visible = computed(() => call.stage !== 'idle')
const context = computed(() => call.call || call.preparation)
const incoming = computed(() => call.call?.status === 'ringing' && call.call.direction === 'incoming')
const otherTab = computed(() => !!call.call && !call.call.can_control && call.call.status !== 'ended')
const duration = computed(() => call.stage === 'ended' ? formatCallDuration(call.call?.duration_seconds || 0)
  : call.call?.connected_at ? formatCallDuration((clock.value - Date.parse(call.call.connected_at)) / 1000) : '')
const status = computed(() => otherTab.value ? '通话正在另一个窗口进行' : call.stage === 'preparing' ? call.busy ? '请允许浏览器使用摄像头和麦克风…' : '准备一次面对面的沟通'
  : call.stage === 'connected' ? `正在通话 · ${duration.value || '00:00'}` : call.call ? callOutcome(call.call) : '')
let pollTimer: ReturnType<typeof setInterval> | undefined
let clockTimer: ReturnType<typeof setInterval> | undefined
let previousFocus: HTMLElement | null = null
watch([visible, () => call.minimized], async ([shown, minimized]) => {
  if (shown && !minimized) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    document.querySelector<HTMLElement>('.video-call-dialog button')?.focus()
  } else if (!shown && previousFocus?.isConnected) previousFocus.focus()
})
watch([localVideo, localElement], ([stream, element]) => {
  if (element) { element.srcObject = stream; if (stream) void element.play().catch(() => {}) }
})
watch([remoteVideo, remoteElement], async ([stream, element]) => {
  soundBlocked.value = false
  if (element) { element.srcObject = stream; if (stream) try { await element.play() } catch { soundBlocked.value = true } }
})
async function playSound() { try { await remoteElement.value?.play(); soundBlocked.value = false } catch { soundBlocked.value = true } }
function keyboard(event: KeyboardEvent) {
  if (!visible.value || call.minimized) return
  if (event.key === 'Escape') { event.preventDefault(); closeVideoCall(); return }
  if (event.key !== 'Tab') return
  const controls = [...document.querySelectorAll<HTMLElement>('.video-call-dialog button:not([disabled])')].filter(el => el.offsetWidth > 0)
  const first = controls[0], last = controls[controls.length - 1]
  if (!document.querySelector('.video-call-dialog')?.contains(document.activeElement) || event.shiftKey && document.activeElement === first) { event.preventDefault(); (event.shiftKey ? last : first)?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
function goConversation() {
  const id = context.value?.application_id
  call.minimized = true
  if (id) void router.push({ path: '/messages', query: { application: id } })
}
// Session rotation/logout releases tracks immediately, including late permission responses.
watch(() => [state.actor, state.sessionScope, state.epoch], resetVideoCalls, { flush: 'sync' })
onMounted(() => {
  void pollVideoCalls(); pollTimer = setInterval(pollVideoCalls, 900); clockTimer = setInterval(() => { clock.value = Date.now() }, 1000)
  document.addEventListener('keydown', keyboard); window.addEventListener('pagehide', resetVideoCalls)
})
onBeforeUnmount(() => {
  clearInterval(pollTimer); clearInterval(clockTimer); resetVideoCalls()
  document.removeEventListener('keydown', keyboard); window.removeEventListener('pagehide', resetVideoCalls)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" v-show="!call.minimized" class="video-call-backdrop">
      <section class="video-call-dialog" role="dialog" aria-modal="true" aria-labelledby="video-call-title" aria-describedby="video-call-status">
        <header class="video-call-heading"><div><span class="video-call-eyebrow"><Video :size="15" />同频 · 视频沟通</span><h2 id="video-call-title">{{ context?.counterpart }}</h2></div><button class="video-call-icon" :aria-label="call.stage === 'preparing' || call.stage === 'ended' ? '关闭视频通话' : '最小化视频通话'" @click="closeVideoCall"><component :is="call.stage === 'preparing' || call.stage === 'ended' ? X : Minimize2" :size="20" /></button></header>
        <div class="video-call-context"><BriefcaseBusiness :size="16" /><span>{{ context?.job_title }}</span><button @click="goConversation">查看沟通资料<ArrowUpRight :size="14" /></button></div>
        <div class="video-call-stage" :class="{ 'video-call-is-live': call.stage === 'connected' }">
          <video ref="remoteElement" class="video-call-remote" autoplay playsinline :aria-label="'对方视频：' + context?.counterpart" />
          <div v-if="!remoteVideo || call.stage === 'ended'" class="video-call-placeholder"><span class="video-call-avatar">{{ context?.counterpart?.slice(0, 1) || '同' }}</span><strong>{{ context?.counterpart }}</strong><p>{{ call.stage === 'preparing' ? '开启设备后发出邀请，由对方决定是否接听。' : call.stage === 'ended' ? '期待下一次有准备的交流。' : incoming ? '对方希望与你进一步了解岗位和经历。' : '正在等待对方加入这次沟通。' }}</p><span v-if="call.stage === 'ringing'" class="video-call-pulse" aria-hidden="true"><i /><i /><i /></span></div>
          <div v-if="localVideo" class="video-call-self"><video ref="localElement" autoplay playsinline muted aria-label="我的视频预览" /><div v-if="!call.camera" class="video-call-camera-off"><VideoOff :size="22" /><span>摄像头已关闭</span></div><small>我<MicOff v-if="!call.microphone" :size="12" /></small></div>
          <button v-if="soundBlocked && call.stage !== 'ended'" class="video-call-sound" @click="playSound"><Volume2 :size="16" />点击播放对方声音</button>
          <p id="video-call-status" class="video-call-status" role="status"><span :class="{ live: call.stage === 'connected' }" />{{ status }}</p>
        </div>
        <p v-if="call.error" class="video-call-error" role="alert">{{ call.error }}</p>
        <p v-if="call.networkNotice" class="video-call-network" role="status">{{ call.networkNotice }}</p>
        <footer class="video-call-footer">
          <template v-if="call.stage === 'preparing'"><p>双方同意后开始沟通，本次不录音、不录像。</p><div><button class="secondary" @click="closeVideoCall">取消</button><button class="primary" :disabled="call.busy" @click="dialVideoCall"><Video :size="17" />{{ call.busy ? '正在准备设备…' : '开启设备并呼叫' }}</button></div></template>
          <template v-else-if="call.stage === 'ended'"><p>{{ call.call?.connected_at ? '本次通话时长 ' + duration : '你仍可在消息中心继续文字沟通。' }}</p><button class="primary" @click="closeVideoCall">完成</button></template>
          <template v-else-if="otherTab"><p>请回到发起或接听通话的窗口操作。</p><button class="secondary" @click="call.minimized = true">收起</button></template>
          <template v-else-if="incoming"><p>接听时才会请求摄像头和麦克风权限。</p><div><button class="video-call-decline" @click="endVideoCall()"><PhoneOff :size="18" />婉拒</button><button class="video-call-answer" :disabled="call.busy" @click="acceptVideoCall"><Phone :size="18" />{{ call.busy ? '正在开启设备…' : '接听视频' }}</button></div></template>
          <template v-else><div class="video-call-device-controls"><button :disabled="!localVideo" :aria-pressed="!call.microphone" :aria-label="call.microphone ? '关闭麦克风' : '开启麦克风'" @click="toggleMicrophone"><component :is="call.microphone ? Mic : MicOff" :size="20" /><span>{{ call.microphone ? '麦克风' : '已静音' }}</span></button><button :disabled="!localVideo" :aria-pressed="!call.camera" :aria-label="call.camera ? '关闭摄像头' : '开启摄像头'" @click="toggleCamera"><component :is="call.camera ? Video : VideoOff" :size="20" /><span>{{ call.camera ? '摄像头' : '已关闭' }}</span></button></div><button class="video-call-decline" :disabled="call.busy" @click="endVideoCall()"><PhoneOff :size="18" />{{ call.stage === 'ringing' ? '取消呼叫' : '结束通话' }}</button></template>
        </footer>
      </section>
    </div>
    <button v-if="visible && call.minimized" class="video-call-dock" @click="call.minimized = false"><span class="video-call-dock-icon"><Video :size="21" /></span><span><strong>{{ context?.counterpart }}</strong><small>{{ status }}</small></span><Maximize2 :size="17" /></button>
  </Teleport>
</template>
