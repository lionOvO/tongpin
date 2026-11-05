import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApplicationSummary } from './hiring'

const mock = vi.hoisted(() => ({ api: vi.fn(), state: { csrf: 'csrf', sessionScope: 'user', user: { role: 'candidate' } as { role: string } | null } }))
vi.mock('./store', () => ({ ...mock, ApiError: class extends Error { constructor(message: string, public code = '', public status = 0) { super(message) } } }))
import { videoCall, localVideo, prepareVideoCall, dialVideoCall, resetVideoCalls, pollVideoCalls, videoSupportError } from './video-calls'

const application = { id: 'application', job_title: '接口开发', status: 'accepted', available: true } as ApplicationSummary
const call = { id: 'call', application_id: 'application', status: 'ringing', direction: 'outgoing', can_control: true, counterpart: '招聘团队', job_title: '接口开发' }
const media = () => {
  const tracks = [{ stop: vi.fn(), enabled: true }, { stop: vi.fn(), enabled: true }]
  return { tracks, stream: { getTracks: () => tracks, getAudioTracks: () => [tracks[0]], getVideoTracks: () => [tracks[1]] } as unknown as MediaStream }
}
const getUserMedia = vi.fn(), fetchMock = vi.fn()
beforeEach(() => {
  vi.stubGlobal('window', { isSecureContext: true, RTCPeerConnection: vi.fn() })
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
  vi.stubGlobal('fetch', fetchMock.mockResolvedValue({ ok: true }))
  resetVideoCalls(); mock.api.mockReset(); getUserMedia.mockReset(); fetchMock.mockClear()
  mock.state.user = { role: 'candidate' }; mock.state.sessionScope = 'user'
})
afterEach(() => { resetVideoCalls(); vi.unstubAllGlobals() })

describe('视频通话的设备授权和异步取消', () => {
  it('打开准备界面不会请求设备，被拒绝后不会通知对方', async () => {
    prepareVideoCall(application, '招聘团队')
    expect(getUserMedia).not.toHaveBeenCalled()
    getUserMedia.mockRejectedValue(new DOMException('Denied', 'NotAllowedError'))
    await dialVideoCall()
    expect(videoCall.error).toContain('权限未开启')
    expect(videoCall.busy).toBe(false)
    expect(mock.api).not.toHaveBeenCalled()
  })
  it('取消后迟到的授权立即关闭所有设备，不创建通话', async () => {
    const { stream, tracks } = media()
    let grant!: (stream: MediaStream) => void
    getUserMedia.mockReturnValue(new Promise(resolve => { grant = resolve }))
    prepareVideoCall(application, '招聘团队')
    const pending = dialVideoCall()
    resetVideoCalls(); grant(stream); await pending
    tracks.forEach(track => expect(track.stop).toHaveBeenCalledOnce())
    expect(localVideo.value).toBeNull(); expect(videoCall.stage).toBe('idle')
    expect(mock.api).not.toHaveBeenCalled()
  })
  it('已取消的呼叫请求迟到时补发结束通知，保持界面关闭', async () => {
    const { stream, tracks } = media()
    let created!: (value: unknown) => void
    getUserMedia.mockResolvedValue(stream)
    mock.api.mockReturnValue(new Promise(resolve => { created = resolve }))
    prepareVideoCall(application, '招聘团队'); const pending = dialVideoCall()
    await vi.waitFor(() => expect(mock.api).toHaveBeenCalledOnce())
    resetVideoCalls(); created(call); await pending
    expect(videoCall.stage).toBe('idle'); expect(videoCall.call).toBeNull()
    tracks.forEach(track => expect(track.stop).toHaveBeenCalledOnce())
    expect(fetchMock).toHaveBeenCalledWith('/api/video-calls/call/actions', expect.objectContaining({ keepalive: true, body: expect.stringContaining('"action":"end"') }))
  })
  it('退出或切换账号立即释放设备，并尝试结束已建立的呼叫', async () => {
    const { stream, tracks } = media()
    getUserMedia.mockResolvedValue(stream); mock.api.mockResolvedValue(call)
    prepareVideoCall(application, '招聘团队'); await dialVideoCall(); resetVideoCalls()
    tracks.forEach(track => expect(track.stop).toHaveBeenCalledOnce())
    expect(fetchMock).toHaveBeenCalledOnce(); expect(videoCall.stage).toBe('idle')
  })
  it('未登录与管理端不轮询通话，也不会打开设备', async () => {
    mock.state.user = null; await pollVideoCalls()
    mock.state.user = { role: 'admin' }; await pollVideoCalls()
    mock.state.user = { role: 'candidate' }; mock.state.sessionScope = 'admin'; await pollVideoCalls()
    expect(mock.api).not.toHaveBeenCalled(); expect(getUserMedia).not.toHaveBeenCalled()
  })
  it('公网 HTTP 给出访问方式提示，本机安全上下文允许通话', () => {
    expect(videoSupportError()).toBe('')
    vi.stubGlobal('window', { isSecureContext: false })
    expect(videoSupportError()).toContain('公网通话需要 HTTPS')
  })
})
