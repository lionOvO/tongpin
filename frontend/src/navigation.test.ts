import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { staffRedirect, sessionScopeForPath } from './navigation'
import type { User } from './types'

const user = (role: User['role']): User => ({ id: 'test', actor: role + ':test', role, name: '合成账号' })
const staffPage = { path: '/admin/accounts', meta: { admin: true } }

describe('工作人员入口与普通会话', () => {
  it.each([null, user('candidate'), user('enterprise')])('非管理员可留在管理登录页，但不能进入监管页面：%j', async account => {
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/workspace', component: {} }, { path: '/admin/login', component: {} },
      { path: '/admin/accounts', component: {}, meta: { admin: true } },
    ] })
    router.beforeEach(to => staffRedirect(account, to))
    await router.push('/admin/login')
    expect(router.currentRoute.value.path).toBe('/admin/login')
    await router.push('/admin/accounts')
    expect(router.currentRoute.value.path).toBe('/admin/login')
    expect(router.currentRoute.value.query.redirect).toBe('/admin/accounts')
    await router.push('/workspace')
    expect(router.currentRoute.value.path).toBe('/workspace')
  })
  it('已登录管理员进入管理概览，仍可修改密码', () => {
    const staff = user('admin')
    expect(staffRedirect(staff, { path: '/admin/login', meta: {} })).toBe('/admin')
    expect(staffRedirect(staff, { path: '/workspace', meta: {} })).toBe('/admin')
    expect(staffRedirect(staff, staffPage)).toBeUndefined()
    expect(staffRedirect(staff, { path: '/forgot-password', meta: {} })).toBeUndefined()
  })
})

it.each(['/admin', '/admin/login', '/admin/accounts', '/admin/forgot-password'])('管理端路径选择独立会话：%s', path => expect(sessionScopeForPath(path)).toBe('admin'))
it.each(['/', '/workspace', '/login', '/forgot-password', '/enterprise-verification', '/administrator'])('用户端路径选择普通会话：%s', path => expect(sessionScopeForPath(path)).toBe('user'))
