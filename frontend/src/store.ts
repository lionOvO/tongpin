import { reactive, computed } from 'vue'
import { sessionTab, renewSessionTab, bindSessionTab, newSessionTab } from './session-tab'
import type { Job, Resume, User, Presentation, RecordData, WorkspaceRole } from './types'
export const state = reactive({ user: null as User | null, csrf: '', actor: '', initialized: false, sessionScope: 'user' as 'user' | 'admin', jobs: [] as Job[], resumes: [] as Resume[], jobId: '', resumeId: '', presentation: null as Presentation | null, health: null as RecordData | null, busy: false, loading: false, switching: false, aiFocus: false, error: '', success: '', progress: '', epoch: 0 })
export const candidate = computed(() => state.user?.role === 'candidate')
export const job = computed(() => state.jobs.find(j => j.id === state.jobId))
export const resume = computed(() => state.resumes.find(r => r.id === state.resumeId))
export const confirmedJobs = computed(() => state.jobs.filter(j => j.status === '已确认'))
export class ApiError extends Error { constructor(message: string, public code = '', public status = 0) { super(message) } }
const controllers = new Set<AbortController>()
export function sessionHeaders() { return { 'X-Session-Scope': state.sessionScope, 'X-Session-Tab': sessionTab(state.sessionScope) } }
const identityPath = () => state.sessionScope === 'admin' ? '/auth/admin/me' : '/auth/me'
export function setSessionScope(scope: 'user' | 'admin') {
  if (scope === state.sessionScope) return
  clearWorkspace(); state.loading = true; state.user = null; state.csrf = ''; state.switching = false
  state.sessionScope = scope; state.initialized = false; initialization = null
}
function clearWorkspace() {
  state.epoch++; controllers.forEach(c => c.abort()); controllers.clear()
  state.actor = ''; state.jobs = []; state.resumes = []; state.jobId = ''; state.resumeId = ''
  state.presentation = null; state.health = null; state.busy = false; state.aiFocus = false; state.progress = ''; state.error = ''; state.success = ''
}
export function clearSession() {
  clearWorkspace()
  state.user = null; state.csrf = ''; state.loading = false; state.switching = false; state.initialized = true
}
type Session = { user: User; csrf_token: string }
function adoptSession(data: Session) {
  if (data.user.session_scope && data.user.session_scope !== state.sessionScope) throw new ApiError('登录上下文已变化', 'STALE_CONTEXT')
  state.user = data.user; state.actor = data.user.actor; state.csrf = data.csrf_token; state.initialized = true
}
export async function refreshIdentity() {
  const data = await api<Session>(identityPath())
  if (state.actor !== data.user.actor) { await synchronizeSession(); return }
  adoptSession(data)
}
// Explicit refresh reads this tab only; no account changes are broadcast to other tabs.
export async function synchronizeSession() {
  clearWorkspace(); state.csrf = ''; state.switching = true; state.loading = true
  const epoch = state.epoch
  try { adoptSession(await api<Session>(identityPath())); await refresh() }
  catch (e) { if (epoch === state.epoch) { clearSession(); notifyError(e) } }
  finally { if (epoch === state.epoch) { state.loading = false; state.switching = false } }
}
export function notifyError(error: unknown) {
  if (error instanceof ApiError && ['STALE_CONTEXT', 'AUTH_REQUIRED'].includes(error.code)) return
  state.error = error instanceof Error ? error.message : '操作未完成，请重试'
}
export async function api<T = RecordData>(path: string, method = 'GET', body?: unknown, timeoutMs = 210000, context: { tab?: string; nextTab?: string; preserveSession?: boolean } = {}): Promise<T> {
  const epoch = state.epoch
  const controller = new AbortController(); controllers.add(controller)
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch('/api' + path, { method, credentials: 'same-origin', cache: 'no-store', headers: { ...sessionHeaders(), ...(context.tab ? { 'X-Session-Tab': context.tab } : {}), ...(context.nextTab ? { 'X-New-Session-Tab': context.nextTab } : {}), ...(method !== 'GET' && state.csrf ? { 'X-CSRF-Token': state.csrf } : {}), ...(body !== undefined && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}) }, body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body), signal: controller.signal })
    const data = await response.json()
    if (epoch !== state.epoch) throw new ApiError('账号状态已变化，请重新操作', 'STALE_CONTEXT')
    if (!response.ok) {
      if (!context.preserveSession && (response.status === 401 || data.detail?.code === 'ACCOUNT_DISABLED')) clearSession()
      throw new ApiError(data.detail?.message || '请求未完成，请重试', data.detail?.code, response.status)
    }
    return data
  } catch (e) {
    if (epoch !== state.epoch && !(e instanceof ApiError)) throw new ApiError('账号状态已变化', 'STALE_CONTEXT')
    if (e instanceof ApiError) throw e
    throw new ApiError(e instanceof DOMException && e.name === 'AbortError' ? '请求超时，请检查服务状态；操作可能已在服务端完成，请刷新确认。' : '无法连接服务，请确认前后端已启动。')
  } finally { clearTimeout(timeout); controllers.delete(controller) }
}
export async function streamApi<T>(path: string, body: unknown, receive: (event: string, value: unknown) => void): Promise<T> {
  const epoch = state.epoch; const controller = new AbortController(); controllers.add(controller)
  const timer = setTimeout(() => controller.abort(), 150000)
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  try {
    const response = await fetch('/api' + path, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { ...sessionHeaders(), 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf },
      body: JSON.stringify(body), signal: controller.signal })
    if (epoch !== state.epoch) throw new ApiError('账号状态已变化', 'STALE_CONTEXT')
    if (!response.ok) {
      const data = await response.json()
      if (response.status === 401 || data.detail?.code === 'ACCOUNT_DISABLED') clearSession()
      throw new ApiError(data.detail?.message || '请求未完成', data.detail?.code, response.status)
    }
    if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new ApiError('流式连接未建立，请刷新查看任务。')
    reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''
    while (true) {
      const chunk = await reader.read()
      if (epoch !== state.epoch) throw new ApiError('账号状态已变化', 'STALE_CONTEXT')
      buffer = (buffer + decoder.decode(chunk.value, { stream: !chunk.done })).replace(/\r\n/g, '\n')
      if (buffer.length > 2_000_000) throw new ApiError('响应内容过长，请刷新查看任务。')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
        const event = block.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim()
        const raw = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
        if (!event || !raw) continue
        const value = JSON.parse(raw)
        if (event === 'error') {
          if (['AUTH_REQUIRED', 'ACCOUNT_DISABLED'].includes(value.code)) clearSession()
          throw new ApiError(value.message, value.code)
        }
        if (event === 'done') return value as T
        receive(event, value)
      }
      if (chunk.done) throw new ApiError('连接已中断，任务可能仍在后台运行，请刷新查看进度。')
    }
  } catch (error) {
    if (epoch !== state.epoch && !(error instanceof ApiError)) throw new ApiError('账号状态已变化', 'STALE_CONTEXT')
    if (error instanceof ApiError) throw error
    throw new ApiError('流式连接中断，请刷新确认后台进度；不会自动重复提交。')
  } finally {
    await reader?.cancel().catch(() => {}); clearTimeout(timer); controllers.delete(controller)
  }
}
export async function refresh() {
  const epoch = state.epoch
  const values = await Promise.all([api<Job[]>('/jobs'), api<Resume[]>('/resumes'), api<Presentation>('/config/presentation'), api<RecordData>('/health')])
  if (epoch !== state.epoch || !state.user) return
  ;[state.jobs, state.resumes, state.presentation, state.health] = values
  if (!state.jobs.some(j => j.id === state.jobId)) state.jobId = state.jobs.find(j => j.status === '已确认')?.id || state.jobs[0]?.id || ''
  if (!state.resumes.some(r => r.id === state.resumeId)) state.resumeId = state.resumes[0]?.id || ''
}
export async function action(fn: () => Promise<unknown>, message = '') {
  if (state.busy || state.switching) return
  const epoch = state.epoch
  state.busy = true; state.error = ''; state.success = ''; state.progress = ''
  try { await fn(); if (epoch === state.epoch && message) state.success = message } catch (e) { if (epoch === state.epoch) notifyError(e) } finally { if (epoch === state.epoch) { state.busy = false; state.progress = '' } }
}
let initialization: Promise<void> | null = null
export async function initialize() {
  if (state.initialized) return
  if (!initialization) {
    const epoch = state.epoch
    initialization = (async () => {
      state.loading = true
      try { adoptSession(await api<Session>(identityPath())); await refresh() }
      catch (e) { if (!(e instanceof ApiError && (e.status === 401 || e.code === 'STALE_CONTEXT'))) throw e }
      finally { if (epoch === state.epoch) { state.initialized = true; state.loading = false; initialization = null } }
    })()
  }
  await initialization
}
export type AuthPayload = { phone: string; code?: string; password?: string; role?: 'enterprise' | 'candidate' }
export async function authenticate(path: '/auth/admin/login/password' | '/auth/admin/login/phone' | '/auth/login/phone' | '/auth/login/password' | '/auth/register' | '/auth/password/reset' | '/auth/admin/password/reset', payload: AuthPayload) {
  setSessionScope(path.startsWith('/auth/admin/') ? 'admin' : 'user')
  clearSession()
  // Duplicated tabs can inherit sessionStorage. A fresh login must never rotate their source cookie.
  renewSessionTab(state.sessionScope)
  const epoch = state.epoch
  adoptSession(await api<Session>(path, 'POST', payload))
  state.loading = true
  try { await refresh() } catch (e) { if (epoch === state.epoch) notifyError(e) } finally { if (epoch === state.epoch) state.loading = false }
}
export async function switchWorkspace(role: WorkspaceRole) {
  if (state.sessionScope === 'admin') throw new ApiError('请在用户端使用普通工作空间，管理端保持独立。', 'ADMIN_WORKSPACE_FIXED', 403)
  if (!state.user) throw new ApiError('请登录后切换工作空间。', 'AUTH_REQUIRED', 401)
  if (state.switching || state.busy || state.loading) throw new ApiError('请等待当前操作完成后再切换工作空间。')
  if ((state.user.workspace_role || (candidate.value ? 'candidate' : 'enterprise')) === role) return
  clearWorkspace(); state.loading = true; state.switching = true
  const epoch = state.epoch
  const sourceTab = sessionTab(state.sessionScope), targetTab = newSessionTab()
  try {
    const data = await api<Session>('/auth/workspace', 'POST', { role }, 210000, { nextTab: targetTab })
    bindSessionTab(state.sessionScope, targetTab)
    adoptSession(data)
    await refresh()
  } catch (e) {
    // A timed-out write may have succeeded. Re-read the session; never restore cached materials.
    if (epoch === state.epoch) {
      try {
        let data: Session, recoveredTab = targetTab
        try { data = await api<Session>(identityPath(), 'GET', undefined, 210000, { tab: targetTab, preserveSession: true }) }
        catch (recovery) {
          if (!(recovery instanceof ApiError && recovery.status === 401)) throw recovery
          recoveredTab = sourceTab
          data = await api<Session>(identityPath(), 'GET', undefined, 210000, { tab: sourceTab, preserveSession: true })
        }
        bindSessionTab(state.sessionScope, recoveredTab); adoptSession(data); await refresh()
      } catch (recovery) { if (epoch === state.epoch) clearSession() }
    }
    throw e
  } finally { if (epoch === state.epoch) { state.loading = false; state.switching = false } }
}
export async function logout() {
  try { await api(state.sessionScope === 'admin' ? '/auth/admin/logout' : '/auth/logout', 'POST') } catch (e) { if (!(e instanceof ApiError && e.status === 401)) throw e }
  clearSession()
}
export async function download(path: string, filename: string) {
  const epoch = state.epoch
  const response = await fetch('/api' + path, { credentials: 'same-origin', cache: 'no-store', headers: sessionHeaders() })
  const data = response.ok ? await response.blob() : await response.json()
  if (epoch !== state.epoch) throw new ApiError('账号状态已变化', 'STALE_CONTEXT')
  if (!response.ok) {
    if ((response.status === 401 || data.detail?.code === 'ACCOUNT_DISABLED')) { clearSession() }
    throw new ApiError(data.detail?.message || '导出失败', data.detail?.code, response.status)
  }
  saveFile(data, filename)
}
export async function apiBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const epoch = state.epoch
  const controller = new AbortController(); controllers.add(controller)
  const cancel = () => controller.abort()
  signal?.addEventListener('abort', cancel, { once: true })
  if (signal?.aborted) controller.abort()
  const timer = setTimeout(cancel, 30000)
  try {
    const response = await fetch('/api' + path, { credentials: 'same-origin', cache: 'no-store', headers: sessionHeaders(), signal: controller.signal })
    if (epoch !== state.epoch) throw new ApiError('账号状态已变化', 'STALE_CONTEXT')
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      if (response.status === 401 || data.detail?.code === 'ACCOUNT_DISABLED') clearSession()
      throw new ApiError(data.detail?.message || '原文件读取失败，请重试。', data.detail?.code, response.status)
    }
    const blob = await response.blob()
    if (epoch !== state.epoch) throw new ApiError('账号状态已变化', 'STALE_CONTEXT')
    return blob
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', cancel); controllers.delete(controller)
  }
}
export function saveFile(data: Blob, filename: string) { const url = URL.createObjectURL(data); const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
