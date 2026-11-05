import { beforeEach, describe, expect, it, vi } from 'vitest'

const channels = new Map<string, FakeChannel>()
class FakeChannel {
  onmessage: (() => void) | null = null
  postMessage = vi.fn()
  constructor(name: string) { channels.set(name, this) }
}
vi.stubGlobal('BroadcastChannel', FakeChannel)
const { state, setSessionScope, clearSession, initialize, api, logout } = await import('./store')
const response = (data: unknown) => ({ok:true,status:200,json:async () => data})
const user = (scope: 'user' | 'admin') => ({id:scope,actor:scope+':test',role:scope==='admin' ? 'admin' : 'candidate',session_scope:scope,name:'合成账号'})
beforeEach(() => {
  setSessionScope('user'); clearSession()
  channels.forEach(c => c.postMessage.mockClear())
  vi.stubGlobal('fetch', vi.fn((path: string) => Promise.resolve(response(path.endsWith('/me') ? {user:user(state.sessionScope),csrf_token:state.sessionScope+'-csrf'} : path==='/api/jobs' || path==='/api/resumes' ? [] : {}))))
})

describe('管理端与用户端独立会话', () => {
  it('不再订阅全局登录广播，其他标签页登录不能替换当前身份', () => {
    state.user=user('user') as any;state.actor='user:test';state.csrf='user-csrf'
    expect(channels.size).toBe(0)
    expect(fetch).not.toHaveBeenCalled();expect(state.user?.id).toBe('user')
  })
  it('管理页面重新读取独立身份，接口请求携带管理范围', async () => {
    state.resumes=[{id:'user-private'}] as any
    setSessionScope('admin')
    expect(state.user).toBeNull();expect(state.resumes).toEqual([])
    await initialize()
    expect(state.user?.role).toBe('admin')
    expect(fetch).toHaveBeenCalledWith('/api/auth/admin/me', expect.objectContaining({headers:expect.objectContaining({'X-Session-Scope':'admin','X-Session-Tab':expect.any(String)})}))
    await api('/admin/overview')
    expect(fetch).toHaveBeenLastCalledWith('/api/admin/overview', expect.objectContaining({headers:expect.objectContaining({'X-Session-Scope':'admin','X-Session-Tab':expect.any(String)})}))
  })
  it('管理端退出使用专用接口及标签页标识，不广播退出通知', async () => {
    setSessionScope('admin');await initialize();await logout()
    expect(fetch).toHaveBeenLastCalledWith('/api/auth/admin/logout',expect.objectContaining({headers:expect.objectContaining({'X-Session-Scope':'admin','X-CSRF-Token':'admin-csrf','X-Session-Tab':expect.any(String)})}))
    expect(channels.size).toBe(0)
  })
  it('切换端后拒绝旧端迟到响应，旧初始化不能清空新端加载状态', async () => {
    let resolve!: (r: unknown) => void
    state.initialized=false
    vi.stubGlobal('fetch',vi.fn((path: string) => path==='/api/auth/me' ? new Promise(r => {resolve=r}) : Promise.resolve(response(path.endsWith('/me') ? {user:user('admin'),csrf_token:'admin-csrf'} : []))))
    const old=initialize()
    setSessionScope('admin')
    const current=initialize()
    resolve(response({user:user('user'),csrf_token:'old-csrf'}))
    await Promise.all([old,current])
    expect(state.user?.role).toBe('admin');expect(state.csrf).toBe('admin-csrf');expect(state.loading).toBe(false)
  })
})
