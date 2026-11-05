import { reactive, shallowRef } from 'vue'
import { api, ApiError, state } from './store'
import { sessionTab } from './session-tab'
import { createRequestId } from './request-id'
import type { ApplicationSummary } from './hiring'

export interface VideoCall {
  id: string; application_id: string; status: 'ringing' | 'accepted' | 'ended'
  direction: 'incoming' | 'outgoing'; reason: string | null; can_control: boolean
  counterpart: string; job_title: string; created_at: string; answered_at: string | null
  connected_at: string | null; ended_at: string | null; duration_seconds: number
}
type CallContext = { application_id: string; counterpart: string; job_title: string }
type Signal = { seq: number; kind: 'offer' | 'answer' | 'ice'; sdp: string | null; candidate: RTCIceCandidateInit | null }
type CallAction = 'accept' | 'decline' | 'end' | 'failed' | 'connected'
const clientId = createRequestId() // A tab owns its devices; another tab cannot take them over.
export const videoCall = reactive({ call: null as VideoCall | null, preparation: null as CallContext | null,
  stage: 'idle' as 'idle' | 'preparing' | 'ringing' | 'connecting' | 'connected' | 'ended',
  busy: false, minimized: false, error: '', networkNotice: '', microphone: true, camera: true, historyVersion: 0,
})
export const localVideo = shallowRef<MediaStream | null>(null)
export const remoteVideo = shallowRef<MediaStream | null>(null)
let peer: RTCPeerConnection | null = null
let generation = 0, after = 0, polling = false, lastCheck = 0
let pendingIce: RTCIceCandidateInit[] = []
type OutgoingSignal = { callId: string; body: { client_id: string; request_id: string; kind: Signal['kind']; sdp?: string; candidate?: RTCIceCandidateInit } }
let outgoingSignals: OutgoingSignal[] = []
let signalDelivery: { token: number; promise: Promise<void> } | null = null
let connectTimeout: ReturnType<typeof setTimeout> | undefined
let disconnectTimeout: ReturnType<typeof setTimeout> | undefined
const locallyEnded = new Set<string>()

export function videoSupportError(): string {
  if (!window.isSecureContext) return '当前地址不能使用摄像头，请通过本机 127.0.0.1 / localhost 访问；公网通话需要 HTTPS。'
  if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) return '当前浏览器不支持视频通话，请使用新版 Edge、Chrome 或 Safari。'
  return ''
}
export function mediaError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return '摄像头或麦克风权限未开启，请在浏览器地址栏的网站权限中允许访问后重试。'
  if (name === 'NotFoundError') return '没有找到摄像头或麦克风，请连接设备后重试。'
  if (name === 'NotReadableError' || name === 'AbortError') return '设备暂时无法使用，可能被其他程序占用，请关闭占用设备的程序后重试。'
  if (name === 'OverconstrainedError') return '设备不支持当前视频设置，请更换设备后重试。'
  return error instanceof Error ? error.message : '通话未能建立，请检查设备和网络后重试。'
}
function release() {
  clearTimeout(connectTimeout); clearTimeout(disconnectTimeout)
  if (peer) { peer.onconnectionstatechange = null; peer.onicecandidate = null; peer.ontrack = null; peer.close(); peer = null }
  localVideo.value?.getTracks().forEach(track => track.stop())
  remoteVideo.value?.getTracks().forEach(track => track.stop())
  localVideo.value = null; remoteVideo.value = null; pendingIce = []; after = 0
  outgoingSignals = []; signalDelivery = null
}
function abandon(call: VideoCall, action: CallAction = 'end') {
  // Keepalive is also used on pagehide/logout, outside store abort controllers.
  if (!state.csrf || !call.can_control || call.status === 'ended') return
  void fetch(`/api/video-calls/${call.id}/actions`, { method: 'POST', credentials: 'same-origin', keepalive: true,
    headers: { 'Content-Type': 'application/json', 'X-Session-Scope': state.sessionScope, 'X-Session-Tab': sessionTab(state.sessionScope), 'X-CSRF-Token': state.csrf },
    body: JSON.stringify({ client_id: clientId, action }),
  }).catch(() => { /* Server leases expire even if the browser cannot deliver this. */ })
}
export function resetVideoCalls() {
  if (videoCall.call) abandon(videoCall.call, videoCall.call.direction === 'incoming' && videoCall.call.status === 'ringing' ? 'decline' : 'end')
  generation++; release(); videoCall.call = null; videoCall.preparation = null; videoCall.stage = 'idle'
  videoCall.busy = false; videoCall.error = ''; videoCall.networkNotice = ''; videoCall.minimized = false; lastCheck = 0
}
function finish(call: VideoCall, error = '') {
  generation++; release(); videoCall.call = call; videoCall.preparation = null
  videoCall.stage = 'ended'; videoCall.busy = false; videoCall.error = error; videoCall.networkNotice = ''; videoCall.historyVersion++
}
function applyCall(call: VideoCall) {
  if (call.status === 'ended') { finish(call); return }
  if (!call.can_control && localVideo.value) { generation++; release(); videoCall.busy = false }
  videoCall.call = call
  videoCall.stage = peer?.connectionState === 'connected' ? 'connected' : call.status === 'ringing' ? 'ringing' : 'connecting'
  if (!call.can_control) videoCall.minimized = true
}
export function prepareVideoCall(application: ApplicationSummary, counterpart: string) {
  if (videoCall.stage !== 'idle' && videoCall.stage !== 'ended') { videoCall.minimized = false; return }
  generation++; release(); videoCall.call = null
  videoCall.preparation = { application_id: application.id, counterpart, job_title: application.job_title }
  videoCall.stage = 'preparing'; videoCall.minimized = false; videoCall.busy = false; videoCall.error = videoSupportError()
}
async function devices(token: number) {
  const unsupported = videoSupportError()
  if (unsupported) throw new Error(unsupported)
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true,
    video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 24, max: 30 } } })
  if (token !== generation) { stream.getTracks().forEach(track => track.stop()); return false }
  localVideo.value = stream; videoCall.microphone = true; videoCall.camera = true
  return true
}
async function command(call: VideoCall, action: CallAction) {
  return api<VideoCall>(`/video-calls/${call.id}/actions`, 'POST', { client_id: clientId, action }, 10000)
}
export async function dialVideoCall() {
  const context = videoCall.preparation
  if (!context || videoCall.busy) return
  const token = generation; videoCall.busy = true; videoCall.error = ''
  try {
    if (!await devices(token)) return
    const body = { application_id: context.application_id, client_id: clientId, request_id: createRequestId() }
    let call: VideoCall
    try { call = await api<VideoCall>('/video-calls', 'POST', body, 10000) }
    catch (e) { // Retry an uncertain create with the same idempotency key.
      if (token !== generation || e instanceof ApiError && e.status > 0 && e.status < 500) throw e
      call = await api<VideoCall>('/video-calls', 'POST', body, 10000)
    }
    if (token !== generation) { abandon(call); return }
    videoCall.preparation = null; applyCall(call)
  } catch (error) {
    if (token === generation) {
      const detail = mediaError(error)
      if (videoCall.call?.status === 'accepted') { await endVideoCall(true); videoCall.error = detail }
      else { release(); videoCall.error = detail }
    }
  } finally { if (token === generation) videoCall.busy = false }
}
export async function acceptVideoCall() {
  const call = videoCall.call
  if (!call || !call.can_control || call.status !== 'ringing' || call.direction !== 'incoming' || videoCall.busy) return
  const token = generation; videoCall.busy = true; videoCall.error = ''
  try {
    if (!await devices(token)) return
    const result = await command(call, 'accept')
    if (token !== generation) { abandon(result); return }
    applyCall(result)
    if (result.status !== 'ended' && result.can_control) await ensurePeer(token)
  } catch (error) {
    if (token === generation) {
      const detail = mediaError(error)
      if (videoCall.call?.status === 'accepted') { await endVideoCall(true); videoCall.error = detail }
      else { release(); videoCall.error = detail }
    }
  } finally { if (token === generation) videoCall.busy = false }
}
export async function endVideoCall(failed = false) {
  const call = videoCall.call
  if (!call) { resetVideoCalls(); return }
  if (call.status === 'ended' || !call.can_control) { resetVideoCalls(); return }
  const action = call.direction === 'incoming' && call.status === 'ringing' ? 'decline' : failed ? 'failed' : 'end'
  locallyEnded.add(call.id); generation++; release(); videoCall.busy = true
  const token = generation
  try { const result = await command(call, action); if (token === generation) finish(result, failed ? '连接未能建立，请检查网络后重新呼叫。' : '') }
  catch (error) {
    if (token === generation) finish({ ...call, status: 'ended', reason: failed ? 'failed' : 'ended', ended_at: new Date().toISOString() },
      `本机已结束通话，暂时无法同步到对方：${mediaError(error)}`)
  }
}
export function closeVideoCall() {
  if (videoCall.stage === 'preparing' || videoCall.stage === 'ended') resetVideoCalls()
  else videoCall.minimized = true
}
export function toggleMicrophone() {
  videoCall.microphone = !videoCall.microphone
  localVideo.value?.getAudioTracks().forEach(track => { track.enabled = videoCall.microphone })
}
export function toggleCamera() {
  videoCall.camera = !videoCall.camera
  localVideo.value?.getVideoTracks().forEach(track => { track.enabled = videoCall.camera })
}
function sendSignal(kind: Signal['kind'], payload: { sdp?: string; candidate?: RTCIceCandidateInit }, token: number) {
  const call = videoCall.call
  if (!call || token !== generation) return Promise.resolve()
  outgoingSignals.push({ callId: call.id, body: { client_id: clientId, request_id: createRequestId(), kind, ...payload } })
  return flushSignals(token)
}
function flushSignals(token: number): Promise<void> {
  if (signalDelivery?.token === token) return signalDelivery.promise
  const queue = outgoingSignals
  const send = async () => {
    while (token === generation && queue.length) {
      const next = queue[0]!
      try { await api(`/video-calls/${next.callId}/signals`, 'POST', next.body, 8000) }
      catch (error) {
        if (token !== generation) return
        if (error instanceof ApiError && error.status > 0 && error.status < 500) throw error
        // Retain the same request ID. Polling retries delivery without poisoning
        // later ICE signals or ending a healthy peer connection on a brief outage.
        videoCall.networkNotice = '通话服务暂时中断，正在尝试重新连接…'
        return
      }
      if (token !== generation) return
      queue.shift()
    }
  }
  const promise = send().finally(() => { if (signalDelivery?.promise === promise) signalDelivery = null })
  signalDelivery = { token, promise }
  return promise
}
async function ensurePeer(token: number) {
  if (peer || !localVideo.value || token !== generation) return
  // Local-first: no external STUN/TURN requests or embedded provider credentials.
  const connection = new RTCPeerConnection({ iceServers: [] })
  peer = connection
  localVideo.value.getTracks().forEach(track => connection.addTrack(track, localVideo.value!))
  connection.ontrack = event => {
    if (token !== generation) return
    if (event.streams[0]) remoteVideo.value = event.streams[0]
    else { remoteVideo.value ||= new MediaStream(); remoteVideo.value.addTrack(event.track) }
  }
  connection.onicecandidate = event => {
    if (event.candidate && token === generation) void sendSignal('ice', { candidate: event.candidate.toJSON() }, token).catch(() => {
      if (token === generation) void endVideoCall(true)
    })
  }
  connection.onconnectionstatechange = () => {
    if (token !== generation) return
    if (connection.connectionState === 'connected') {
      clearTimeout(connectTimeout); clearTimeout(disconnectTimeout); videoCall.stage = 'connected'
      const call = videoCall.call
      if (call) void command(call, 'connected').then(result => { if (token === generation) applyCall(result) }).catch(() => {})
    } else if (connection.connectionState === 'failed') void endVideoCall(true)
    else if (connection.connectionState === 'disconnected') {
      clearTimeout(disconnectTimeout)
      disconnectTimeout = setTimeout(() => { if (token === generation && connection.connectionState === 'disconnected') void endVideoCall(true) }, 8000)
    }
  }
  connectTimeout = setTimeout(() => { if (token === generation && connection.connectionState !== 'connected') void endVideoCall(true) }, 25000)
  if (videoCall.call?.direction === 'outgoing') {
    const offer = await connection.createOffer()
    if (token !== generation) return
    await connection.setLocalDescription(offer)
    if (token !== generation) return
    await sendSignal('offer', { sdp: offer.sdp }, token)
  }
}
async function receive(signal: Signal, token: number) {
  const connection = peer
  if (!connection || token !== generation) return
  if (signal.kind === 'ice') {
    if (connection.remoteDescription) await connection.addIceCandidate(signal.candidate!)
    else pendingIce.push(signal.candidate!)
  } else {
    await connection.setRemoteDescription({ type: signal.kind, sdp: signal.sdp! })
    if (token !== generation) return
    for (const candidate of pendingIce) await connection.addIceCandidate(candidate)
    pendingIce = []
    if (signal.kind === 'offer') {
      const answer = await connection.createAnswer()
      if (token !== generation) return
      await connection.setLocalDescription(answer)
      if (token !== generation) return
      await sendSignal('answer', { sdp: answer.sdp }, token)
    }
  }
}
export async function pollVideoCalls() {
  if (polling || !state.user || state.user.role === 'admin' || state.sessionScope !== 'user' || videoCall.stage === 'preparing') return
  polling = true; const token = generation
  try {
    const call = videoCall.call
    if (call && call.status !== 'ended') {
      const result = await api<{ call: VideoCall; signals: Signal[] }>(`/video-calls/${call.id}/sync`, 'POST', { client_id: clientId, after }, 8000)
      if (token !== generation) return
      applyCall(result.call)
      if (result.call.status === 'accepted' && result.call.can_control && localVideo.value) {
        await ensurePeer(token)
        await flushSignals(token)
        for (const signal of result.signals) {
          if (token !== generation) break
          await receive(signal, token); after = signal.seq
        }
        if (token === generation && peer?.connectionState === 'connected' && !videoCall.call?.connected_at) {
          const connected = await command(result.call, 'connected')
          if (token === generation) applyCall(connected)
        }
      }
      if (token === generation && !outgoingSignals.length) videoCall.networkNotice = ''
    } else if (Date.now() - lastCheck >= 2500) {
      lastCheck = Date.now()
      const calls = await api<VideoCall[]>(`/video-calls/active?client_id=${clientId}`, 'GET', undefined, 8000)
      if (token !== generation || videoCall.preparation) return
      const next = calls.find(row => !locallyEnded.has(row.id))
      calls.filter(row => locallyEnded.has(row.id)).forEach(row => abandon(row))
      if (next) { generation++; release(); videoCall.error = ''; videoCall.minimized = !next.can_control; applyCall(next) }
    }
  } catch (error) {
    if (token !== generation) return
    if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
      const call = videoCall.call
      if (call) finish({ ...call, status: 'ended', reason: 'unavailable' }, '当前通话权限已结束。')
    } else if (peer && (error instanceof DOMException || error instanceof ApiError && error.status >= 400 && error.status < 500)) void endVideoCall(true)
    else if (videoCall.call?.status !== 'ended' && videoCall.call) videoCall.networkNotice = '通话服务暂时中断，正在尝试重新连接…'
    // Temporary signaling failures retain the call; the server lease bounds recovery.
  } finally { polling = false }
}
export function callOutcome(call: VideoCall): string {
  if (call.status === 'ringing') return call.direction === 'incoming' ? '邀请你视频沟通' : '等待对方接听…'
  if (call.status === 'accepted') return '正在建立音视频连接…'
  return ({ declined: call.direction === 'outgoing' ? '对方婉拒了通话' : '已婉拒通话', cancelled: '已取消呼叫',
    missed: '未接听', disconnected: '连接中断，通话已结束', unavailable: '沟通权限已结束',
    failed: '通话连接失败', ended: '通话已结束' } as Record<string, string>)[call.reason || 'ended'] || '通话已结束'
}
export const formatCallDuration = (seconds: number) => `${Math.floor(Math.max(0, seconds) / 60).toString().padStart(2, '0')}:${Math.floor(Math.max(0, seconds) % 60).toString().padStart(2, '0')}`
