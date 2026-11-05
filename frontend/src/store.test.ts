import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => {} })
vi.stubGlobal('BroadcastChannel', undefined)
const { api, state, clearSession, logout, download, apiBlob, notifyError, ApiError, action, authenticate, switchWorkspace, synchronizeSession, sessionHeaders, setSessionScope } = await import('./store')
const response = (data: unknown, ok = true, status = 200) => ({ ok, status, json: async () => data })
beforeEach(() => { setSessionScope('user'); clearSession(); state.user = {id:'a',actor:'enterprise:a',role:'enterprise',name:'138****0000'}; state.actor = 'enterprise:a'; state.csrf = 'nonce-a' })
afterEach(() => vi.restoreAllMocks())
describe('接口与视角隔离', () => {
  const candidateUser = {id:'a',actor:'candidate:a',role:'candidate',workspace_role:'candidate',enterprise_status:'approved',available_roles:['enterprise','candidate'],name:'138****0000'}
  const workspaceResponse = (path: string) => path === '/api/jobs' ? [{id:'candidate-target-job'}] : path === '/api/resumes' ? [{id:'candidate-resume'}] : path === '/api/config/presentation' ? {version:'public'} : {status:'ok'}
  it('切换前清空上一空间资料，用服务端身份及新校验值加载新空间', async () => {
    state.jobs=[{id:'enterprise-private'}] as any;state.resumes=[{id:'enterprise-resume'}] as any;state.jobId='enterprise-private';state.resumeId='enterprise-resume'
    let resolve!: (r:unknown) => void
    const fetch=vi.fn((path: string, options?: unknown) => path === '/api/auth/workspace' ? new Promise(r => {resolve=r}) : Promise.resolve(response(workspaceResponse(path))))
    vi.stubGlobal('fetch',fetch)
    const pending=switchWorkspace('candidate')
    expect(state.jobs).toEqual([]);expect(state.resumes).toEqual([]);expect(state.jobId).toBe('');expect(state.switching).toBe(true)
    expect(fetch.mock.calls[0]![1]).toMatchObject({method:'POST',headers:{'X-CSRF-Token':'nonce-a'},body:JSON.stringify({role:'candidate'})})
    const sentHeaders = (fetch.mock.calls[0]![1] as any).headers
    expect(sentHeaders['X-New-Session-Tab']).not.toBe(sentHeaders['X-Session-Tab'])
    resolve(response({user:candidateUser,csrf_token:'candidate-csrf'}));await pending
    expect(sessionHeaders()['X-Session-Tab']).toBe(sentHeaders['X-New-Session-Tab'])
    expect((fetch.mock.calls[1]![1] as any).headers['X-Session-Tab']).toBe(sentHeaders['X-New-Session-Tab'])
    expect(state.user?.actor).toBe('candidate:a');expect(state.csrf).toBe('candidate-csrf')
    expect(state.jobs[0]?.id).toBe('candidate-target-job');expect(state.resumes[0]?.id).toBe('candidate-resume');expect(state.switching).toBe(false)
  })
  it('企业认证未通过时遵守服务端拒绝，不会改成招聘身份或恢复旧缓存', async () => {
    state.user={...candidateUser,role:'candidate',workspace_role:'candidate',enterprise_status:'pending'} as any;state.actor='candidate:a';state.jobs=[{id:'old-candidate-job'}] as any
    vi.stubGlobal('fetch',vi.fn((path: string) => Promise.resolve(path==='/api/auth/workspace' ? response({detail:{code:'ENTERPRISE_VERIFICATION_REQUIRED',message:'请先完成企业认证'}},false,403) : path==='/api/auth/me' ? response({user:state.user,csrf_token:'current-csrf'}) : response(path==='/api/jobs' || path==='/api/resumes' ? [] : {}))))
    await expect(switchWorkspace('enterprise')).rejects.toMatchObject({code:'ENTERPRISE_VERIFICATION_REQUIRED'})
    expect(state.user?.role).toBe('candidate');expect(state.jobs).toEqual([]);expect(state.switching).toBe(false)
  })
  it('切换请求断网后重新读取服务端最终身份，不按旧身份回滚', async () => {
    state.jobs=[{id:'old-private'}] as any
    vi.stubGlobal('fetch',vi.fn((path: string) => path==='/api/auth/workspace' ? Promise.reject(new Error('uncertain-network')) : Promise.resolve(response(path==='/api/auth/me' ? {user:candidateUser,csrf_token:'rotated'} : workspaceResponse(path)))))
    await expect(switchWorkspace('candidate')).rejects.toThrow('无法连接服务')
    expect(state.user?.actor).toBe('candidate:a');expect(state.jobs[0]?.id).toBe('candidate-target-job');expect(state.csrf).toBe('rotated')
  })
  it('手动刷新本标签页身份会丢弃旧请求和材料', async () => {
    let oldResolve!: (r:unknown) => void
    vi.stubGlobal('fetch',vi.fn((path: string) => path==='/api/assessments' ? new Promise(r => {oldResolve=r}) : Promise.resolve(response(path==='/api/auth/me' ? {user:candidateUser,csrf_token:'refreshed-csrf'} : workspaceResponse(path)))))
    const old=api('/assessments');state.jobs=[{id:'old-secret'}] as any
    await synchronizeSession();oldResolve(response([{id:'old-report'}]))
    await expect(old).rejects.toMatchObject({code:'STALE_CONTEXT'})
    expect(state.user?.role).toBe('candidate');expect(state.csrf).toBe('refreshed-csrf');expect(state.jobs[0]?.id).toBe('candidate-target-job')
  })
  it('切换时会话失效会清空资料，不能伪造切换成功', async () => {
    state.jobs=[{id:'secret'}] as any
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({detail:{code:'AUTH_REQUIRED',message:'请重新登录'}},false,401)))
    await expect(switchWorkspace('candidate')).rejects.toMatchObject({code:'AUTH_REQUIRED'})
    expect(state.user).toBeNull();expect(state.jobs).toEqual([]);expect(state.csrf).toBe('');expect(state.switching).toBe(false)
  })
  it('密码登录先清空旧账号材料，失败时不会保留旧身份或密码', async () => {
    state.jobs = [{id:'old-private'}] as any
    const previousTab = sessionHeaders()['X-Session-Tab']
    let resolve!: (r:unknown) => void
    vi.stubGlobal('fetch',vi.fn(() => new Promise(r => { resolve=r })))
    const pending=authenticate('/auth/login/password',{phone:'13800000301',password:'Wrong password'})
    expect(sessionHeaders()['X-Session-Tab']).not.toBe(previousTab)
    expect(state.user).toBeNull(); expect(state.jobs).toEqual([])
    resolve(response({detail:{code:'PASSWORD_INVALID',message:'手机号或密码不正确'}},false,400))
    await expect(pending).rejects.toMatchObject({code:'PASSWORD_INVALID'})
    expect(state.user).toBeNull(); expect(state.csrf).toBe('')
    expect(JSON.stringify(state)).not.toContain('Wrong password')
  })
  it('注册响应晚于身份切换时，不能回填旧注册账号', async () => {
    let resolve!: (r:unknown) => void
    vi.stubGlobal('fetch',vi.fn(() => new Promise(r => { resolve=r })))
    const pending=authenticate('/auth/register',{phone:'13800000301',code:'123456',password:'Register password',role:'enterprise'})
    clearSession(); state.user={id:'new',actor:'candidate:new',role:'candidate',name:'139****0000'}
    resolve(response({user:{id:'old',actor:'enterprise:old',role:'enterprise',name:'138****0000'},csrf_token:'old-csrf'}))
    await expect(pending).rejects.toMatchObject({code:'STALE_CONTEXT'})
    expect(state.user?.id).toBe('new'); expect(state.csrf).toBe('')
  })
  it('旧视角的错误不会覆盖当前视角的反馈', () => {
    state.error = '当前请求错误'
    notifyError(new ApiError('旧请求','STALE_CONTEXT'))
    expect(state.error).toBe('当前请求错误')
  })
  it('保留服务端错误说明和冲突代码', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({ detail:{ code:'VERSION_CONFLICT',message:'画像已更新' } },false,409)))
    await expect(api('/jobs/x/confirm','PUT',{})).rejects.toMatchObject({ code:'VERSION_CONFLICT',status:409,message:'画像已更新' })
  })
  it('拒绝将旧身份的迟到响应写入当前工作空间', async () => {
    let resolve!: (r: unknown) => void
    vi.stubGlobal('fetch',vi.fn(() => new Promise(r => { resolve = r })))
    const pending = api('/assessments'); state.epoch++; state.actor = 'candidate:lin'
    resolve(response([{ display_name:'旧企业数据' }]))
    await expect(pending).rejects.toMatchObject({code:'STALE_CONTEXT'})
  })
  it('切换身份前立即清除岗位、简历和选择状态', async () => {
    state.jobs = [{ id:'private-job' }] as any; state.resumes = [{ id:'private-resume' }] as any
    state.jobId='private-job'; state.resumeId='private-resume'
    vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')))
    clearSession()
    expect(state.jobs).toEqual([]); expect(state.resumes).toEqual([]); expect(state.jobId).toBe(''); expect(state.resumeId).toBe('')
    expect(state.user).toBeNull(); expect(state.csrf).toBe('')
  })
  it('写操作使用会话校验，不发送可伪造的演示身份', async () => {
    const fetch = vi.fn().mockResolvedValue(response({id:'created'})); vi.stubGlobal('fetch',fetch)
    await api('/jobs', 'POST', {title:'岗位'})
    const options = fetch.mock.calls[0]![1]
    expect(options.headers['X-CSRF-Token']).toBe('nonce-a'); expect(options.headers['X-Demo-Actor']).toBeUndefined()
    expect(options.headers['X-Session-Tab']).toBe(sessionHeaders()['X-Session-Tab'])
    expect(options.credentials).toBe('same-origin'); expect(options.cache).toBe('no-store')
  })
  it('登录过期立即清空账号材料和配置', async () => {
    state.jobs = [{id:'secret'}] as any; state.presentation = {version:'private'} as any
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({detail:{code:'AUTH_REQUIRED',message:'请登录'}},false,401)))
    await expect(api('/jobs')).rejects.toMatchObject({status:401})
    expect(state.user).toBeNull(); expect(state.jobs).toEqual([]); expect(state.presentation).toBeNull()
  })
  it('账号被平台暂停时立即清除旧资料和会话', async () => {
    state.jobs = [{id:'private-before-suspension'}] as any
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({detail:{code:'ACCOUNT_DISABLED',message:'账号已暂停'}},false,403)))
    await expect(api('/jobs')).rejects.toMatchObject({code:'ACCOUNT_DISABLED'})
    expect(state.user).toBeNull();expect(state.jobs).toEqual([]);expect(state.csrf).toBe('')
  })
  it('普通账号被管理端登录拒绝后不能沿用此前身份', async () => {
    state.jobs = [{id:'ordinary-private'}] as any
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({detail:{code:'ADMIN_REQUIRED',message:'仅限工作人员'}},false,403)))
    await expect(authenticate('/auth/admin/login/password',{phone:'13800000301',password:'ordinary-password'})).rejects.toMatchObject({code:'ADMIN_REQUIRED'})
    expect(state.user).toBeNull();expect(state.jobs).toEqual([]);expect(state.csrf).toBe('')
  })
  it('退出失败保留会话并明确提示，不能假装已退出', async () => {
    vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')))
    await expect(logout()).rejects.toThrow('无法连接服务')
    expect(state.user?.id).toBe('a')
  })
  it('退出成功清除账号及所有页面数据', async () => {
    state.jobs = [{id:'secret'}] as any
    const previousTab = sessionHeaders()['X-Session-Tab']
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({message:'已退出'})))
    await logout(); expect(state.user).toBeNull(); expect(state.jobs).toEqual([])
    expect(sessionHeaders()['X-Session-Tab']).toBe(previousTab)
  })
  it('账号变化后旧操作不能回填成功提示', async () => {
    let resolve!: () => void
    const pending = action(() => new Promise<void>(r => {resolve=r}), '旧账号成功')
    clearSession(); state.success='当前账号'; resolve(); await pending
    expect(state.success).toBe('当前账号'); expect(state.busy).toBe(false)
  })
  it('账号变化后不允许旧账号导出下载', async () => {
    let resolve!: (r:unknown) => void
    vi.stubGlobal('fetch',vi.fn(() => new Promise(r => {resolve=r})))
    const pending=download('/audit/export','audit.md'); clearSession()
    expect(fetch).toHaveBeenCalledWith('/api/audit/export', expect.objectContaining({headers:sessionHeaders()}))
    resolve({ok:true,blob:async () => new Blob(['旧账号资料'])})
    await expect(pending).rejects.toMatchObject({code:'STALE_CONTEXT'})
  })
  it('空间切换被拒绝时只恢复源标签页，不能采用其他账号的共享会话', async () => {
    state.user = candidateUser as any; state.actor = candidateUser.actor
    const originalTab = sessionHeaders()['X-Session-Tab']
    const originalUser = state.user
    vi.stubGlobal('fetch',vi.fn((path: string, options: any) => Promise.resolve(
      path==='/api/auth/workspace' ? response({detail:{code:'ENTERPRISE_VERIFICATION_REQUIRED',message:'未认证'}},false,403)
        : path==='/api/auth/me' ? options.headers['X-Session-Tab']===originalTab
          ? response({user:originalUser,csrf_token:'original-csrf'})
          : response({detail:{code:'AUTH_REQUIRED',message:'新空间尚未签发'}},false,401)
        : response(path==='/api/jobs' || path==='/api/resumes' ? [] : {})
    )))
    await expect(switchWorkspace('enterprise')).rejects.toMatchObject({code:'ENTERPRISE_VERIFICATION_REQUIRED'})
    expect(sessionHeaders()['X-Session-Tab']).toBe(originalTab)
    expect(state.user?.id).toBe(originalUser?.id)
    expect(state.csrf).toBe('original-csrf')
  })
})


describe('私有 PDF 字节读取', () => {
  it('使用当前标签页身份读取原文件，禁止缓存', async () => {
    const blob = new Blob(['synthetic PDF'])
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: true, blob: async () => blob}))
    expect(await apiBlob('/resumes/test/original')).toBe(blob)
    expect(fetch).toHaveBeenCalledWith('/api/resumes/test/original', expect.objectContaining({credentials: 'same-origin', cache: 'no-store', headers: sessionHeaders(), signal: expect.any(AbortSignal)}))
  })
  it('读取完字节前身份变化时丢弃原文件', async () => {
    let resolve!: (blob: Blob) => void
    let reading!: () => void
    const started = new Promise<void>(r => {reading = r})
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: true, blob: () => {reading(); return new Promise<Blob>(r => {resolve = r})}}))
    const pending = apiBlob('/resumes/test/original')
    await started; clearSession(); resolve(new Blob(['previous account']))
    await expect(pending).rejects.toMatchObject({code: 'STALE_CONTEXT'})
  })
  it('关闭预览会中止原文件读取', async () => {
    vi.stubGlobal('fetch', vi.fn((_path: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const abort = new AbortController()
    const pending = apiBlob('/resumes/test/original', abort.signal); abort.abort()
    await expect(pending).rejects.toMatchObject({name: 'AbortError'})
  })
  it('失效会话清空资料，不能把错误响应当作 PDF', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({detail: {code:'AUTH_REQUIRED',message:'请重新登录'}}, false, 401)))
    await expect(apiBlob('/resumes/test/original')).rejects.toMatchObject({code: 'AUTH_REQUIRED',status: 401})
    expect(state.user).toBeNull()
  })
})
