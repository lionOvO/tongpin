import type { RouteLocationNormalized } from 'vue-router'
import type { User } from './types'

// Ordinary sessions may open the staff sign-in page, but never staff resources.
export function staffRedirect(user: User | null, to: Pick<RouteLocationNormalized, 'path' | 'meta'>) {
  if (to.path === '/admin/forgot-password') return
  if (to.path === '/admin/login') return user?.role === 'admin' ? '/admin' : undefined
  if (to.meta.admin && user?.role !== 'admin') return { path: '/admin/login', query: { redirect: to.path } }
  if (user?.role === 'admin' && !to.meta.admin && to.path !== '/forgot-password') return '/admin'
}

export function sessionScopeForPath(path: string): 'admin' | 'user' {
  return path === '/admin' || path.startsWith('/admin/') ? 'admin' : 'user'
}
