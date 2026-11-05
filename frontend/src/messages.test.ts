import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApplicationSummary } from './hiring'

const mock = vi.hoisted(() => ({ api:vi.fn(), state:{user:{role:'candidate'} as {role:string}|null,sessionScope:'user'} }))
vi.mock('./store', () => mock)
import { acknowledgeConversation, chatEnabled, clearInbox, conversationPreview, inbox, refreshInbox, loadMoreInbox, setInboxQuery } from './messages'
const page = (items: ApplicationSummary[]) => ({items,total:items.length,unread_total:items.reduce((sum,r)=>sum+(r.unread_count || 0),0)})
const row = (id:string, unread=1) => ({id,status:'accepted',available:true,unread_count:unread}) as ApplicationSummary
beforeEach(() => { clearInbox(); mock.api.mockReset(); mock.state.user={role:'candidate'}; mock.state.sessionScope='user' })

describe('消息中心的未读和账号切换', () => {
  it('全局未读包含未加载会话，加载更多后刷新保留历史页', async () => {
    mock.api.mockResolvedValueOnce({items:[row('new',2)],total:40,unread_total:9}); await refreshInbox()
    expect(inbox.unread).toBe(9)
    mock.api.mockResolvedValueOnce({items:[row('older',7)],total:40,unread_total:9}); await loadMoreInbox()
    expect(mock.api.mock.calls[1][0]).toContain('offset=1')
    mock.api.mockResolvedValueOnce({items:[row('new',2)],total:40,unread_total:9}); await refreshInbox()
    expect(inbox.rows.map(r=>r.id)).toEqual(['new','older'])
    acknowledgeConversation('older'); expect(inbox.unread).toBe(2)
  })
  it('切换搜索范围丢弃迟到的旧分页，查询词发到服务器', async () => {
    inbox.rows=[row('old')]
    let resolve!:(value:unknown)=>void
    mock.api.mockReturnValueOnce(new Promise(r=>{resolve=r})); const old=loadMoreInbox()
    setInboxQuery('历史消息')
    mock.api.mockResolvedValueOnce({items:[row('found')],total:1,unread_total:4}); await refreshInbox()
    resolve({items:[row('wrong-query')],total:99,unread_total:99}); await old
    expect(inbox.rows.map(r=>r.id)).toEqual(['found']); expect(inbox.unread).toBe(4)
    expect(mock.api.mock.calls[1][0]).toContain(encodeURIComponent('历史消息'))
  })
  it('账号切换后丢弃旧账号的迟到列表', async () => {
    let resolve!:(value:ApplicationSummary[])=>void
    mock.api.mockReturnValueOnce(new Promise(r => { resolve=(rows)=>r(page(rows)) }))
    const old = refreshInbox(); clearInbox()
    mock.api.mockResolvedValueOnce(page([row('new-account')])); await refreshInbox()
    resolve([row('old-account')]); await old
    expect(inbox.rows.map(r=>r.id)).toEqual(['new-account'])
  })
  it('阅读后的徽标不会被先前发出的旧列表恢复', async () => {
    inbox.rows=[row('chat')]
    let resolve!:(value:ApplicationSummary[])=>void
    mock.api.mockReturnValueOnce(new Promise(r => { resolve=(rows)=>r(page(rows)) }))
    const refresh=refreshInbox(); acknowledgeConversation('chat')
    resolve([row('chat',4)]); await refresh
    expect(inbox.rows[0].unread_count).toBe(0)
  })
  it('正常刷新合并请求，错误后仍可以重试', async () => {
    mock.api.mockRejectedValueOnce(new Error('网络中断'))
    await expect(refreshInbox()).rejects.toThrow('网络中断')
    mock.api.mockResolvedValueOnce(page([row('chat',2)]))
    await Promise.all([refreshInbox(),refreshInbox()])
    expect(mock.api).toHaveBeenCalledTimes(2); expect(inbox.rows[0].unread_count).toBe(2)
  })
  it('管理端和未登录状态不加载用户会话', async () => {
    mock.state.sessionScope='admin'; await refreshInbox()
    mock.state.sessionScope='user'; mock.state.user={role:'admin'}; await refreshInbox()
    mock.state.user=null; await refreshInbox()
    expect(mock.api).not.toHaveBeenCalled()
  })
  it('只有已接受且有效的会话可发消息，预览优先显示最近消息', () => {
    expect(chatEnabled(row('chat'))).toBe(true)
    for(const status of ['submitted','invited','withdrawn','closed']) expect(chatEnabled({...row('chat'),status} as ApplicationSummary)).toBe(false)
    expect(chatEnabled({...row('chat'),available:false})).toBe(false)
    expect(conversationPreview({...row('chat'),invitation:{text:'邀请',created_at:''},last_message:{side:'enterprise',text:'最新消息',created_at:''}})).toBe('最新消息')
    expect(conversationPreview(row('chat'))).toBe('还没有开始沟通')
  })
})
