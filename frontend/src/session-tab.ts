import { createRequestId } from './request-id'
type Scope = 'user' | 'admin'
const tabs: Partial<Record<Scope, string>> = {}
const key = (scope: Scope) => `tongpin.session-tab.${scope}`
const valid = (value: string | null): value is string => !!value && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)

export const newSessionTab = createRequestId
export function bindSessionTab(scope: Scope, tab: string) {
  tabs[scope] = tab
  try { sessionStorage.setItem(key(scope), tab) } catch { /* Keep isolation in memory if storage is blocked. */ }
  return tab
}
export function sessionTab(scope: Scope): string {
  if (tabs[scope]) return tabs[scope]!
  let saved: string | null = null
  try { saved = sessionStorage.getItem(key(scope)) } catch { /* No shared-cookie fallback. */ }
  return bindSessionTab(scope, valid(saved) ? saved : newSessionTab())
}
export const renewSessionTab = (scope: Scope) => bindSessionTab(scope, newSessionTab())
