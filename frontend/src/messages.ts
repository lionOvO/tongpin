import { reactive } from 'vue'
import { api, state } from './store'
import type { ApplicationSummary } from './hiring'

export const inbox = reactive({ rows: [] as ApplicationSummary[], revision: 0, total: 0, unread: 0, query: '' })
type InboxPage = { items: ApplicationSummary[]; total: number; unread_total: number }
let pending: Promise<ApplicationSummary[]> | null = null
export function clearInbox() { inbox.rows = []; inbox.total = 0; inbox.unread = 0; inbox.query = ''; inbox.revision++; pending = null }
export function setInboxQuery(query: string) { clearInbox(); inbox.query = query.trim() }
export async function loadMoreInbox() {
  const revision = inbox.revision
  const page = await api<InboxPage>(`/messages/conversations/page?offset=${inbox.rows.length}&q=${encodeURIComponent(inbox.query)}`, 'GET', undefined, 15000)
  if (revision !== inbox.revision) return
  const ids = new Set(inbox.rows.map(r => r.id))
  inbox.rows.push(...page.items.filter(r => !ids.has(r.id))); inbox.total = page.total; inbox.unread = page.unread_total
}
export async function refreshInbox() {
  if (!state.user || state.user.role === 'admin' || state.sessionScope !== 'user') return []
  if (pending) return pending
  const revision = inbox.revision
  const task = api<InboxPage>('/messages/conversations/page?q=' + encodeURIComponent(inbox.query), 'GET', undefined, 15000).then(page => {
    if (revision === inbox.revision) { inbox.total = page.total; inbox.unread = page.unread_total }
    return page.items
  })
  pending = task
  try {
    const rows = await task
    if (revision === inbox.revision) { const ids = new Set(rows.map(r => r.id)); inbox.rows = [...rows, ...inbox.rows.filter(r => !ids.has(r.id))] }
    return rows
  } finally { if (pending === task) pending = null }
}
export function acknowledgeConversation(id: string, unreadCount = 0) {
  inbox.revision++
  const row = inbox.rows.find(r => r.id === id)
  if (row) { inbox.unread = Math.max(0, inbox.unread - (row.unread_count || 0) + unreadCount); row.unread_count = unreadCount }
}
export function conversationPreview(row: ApplicationSummary): string {
  return row.last_message?.text || row.invitation?.text || '还没有开始沟通'
}
export function chatEnabled(row: ApplicationSummary): boolean { return row.available && row.status === 'accepted' }
