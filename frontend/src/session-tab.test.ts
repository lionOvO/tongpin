import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let storage: Map<string, string>
beforeEach(() => {
  vi.resetModules(); storage = new Map()
  vi.stubGlobal('sessionStorage', { getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string, v: string) => storage.set(k, v) })
})
afterEach(() => vi.unstubAllGlobals())

describe('标签页会话选择器', () => {
  it('刷新保留同一标签页身份，用户端与管理端各自持有标识', async () => {
    const first = await import('./session-tab')
    const user = first.sessionTab('user'), admin = first.sessionTab('admin')
    expect(user).not.toBe(admin)
    vi.resetModules()
    const reloaded = await import('./session-tab')
    expect(reloaded.sessionTab('user')).toBe(user)
    expect(reloaded.sessionTab('admin')).toBe(admin)
    expect([...storage.values()]).toEqual([user, admin])
  })
  it('另开普通标签页生成独立标识，不读取其他标签页账号', async () => {
    const first = (await import('./session-tab')).sessionTab('user')
    storage.clear(); vi.resetModules()
    expect((await import('./session-tab')).sessionTab('user')).not.toBe(first)
  })
  it('复制标签页重新登录会换用新标识，原标签页与管理端均保持原值', async () => {
    const first = await import('./session-tab')
    const user = first.sessionTab('user'), admin = first.sessionTab('admin')
    vi.resetModules()
    const duplicate = await import('./session-tab')
    expect(duplicate.sessionTab('user')).toBe(user)
    expect(duplicate.renewSessionTab('user')).not.toBe(user)
    expect(first.sessionTab('user')).toBe(user)
    expect(duplicate.sessionTab('admin')).toBe(admin)
  })
  it('存储不可用时仍保持内存隔离，非法存储值不会作为凭据使用', async () => {
    storage.set('tongpin.session-tab.user', '../wrong')
    const first = await import('./session-tab')
    expect(first.sessionTab('user')).toMatch(/^[a-f0-9-]{36}$/)
    vi.resetModules()
    vi.stubGlobal('sessionStorage', { getItem: () => { throw Error('blocked') }, setItem: () => { throw Error('blocked') } })
    const fallback = await import('./session-tab')
    expect(fallback.sessionTab('user')).toBe(fallback.sessionTab('user'))
    expect(fallback.sessionTab('user')).not.toBe(first.sessionTab('user'))
  })
})
