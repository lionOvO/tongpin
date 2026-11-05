import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { all, node, renderer, textOf, type HostNode } from './test-utils/renderer'
import EnterpriseVerification from './pages/EnterpriseVerification.vue'
import { state } from './store'

const request = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: vi.fn() }) }))
vi.mock('./store', async () => {
  const { reactive } = await import('vue')
  const state = reactive({ busy: false, switching: false, epoch: 0, error: '', success: '' })
  return {
    state, api: request, refreshIdentity: vi.fn(), download: vi.fn(), switchWorkspace: vi.fn(),
    action: async (fn: () => Promise<unknown>) => {
      if (state.busy) return
      state.busy = true
      try { await fn() } catch (error) { state.error = (error as Error).message }
      finally { state.busy = false }
    },
  }
})

const focus = vi.fn()
let unmount: (() => void) | undefined
const submission = (id: string) => ({ id, company_name: '合成企业' + id, status: 'approved', reason: '上次人工核验通过' })
beforeEach(() => {
  request.mockReset(); focus.mockClear()
  state.busy = false; state.switching = false; state.error = ''
  vi.stubGlobal('Document', class {})
  vi.stubGlobal('ShadowRoot', class {})
  vi.stubGlobal('document', { getElementById: () => ({ focus }), activeElement: null })
  request.mockImplementation(async () => [submission('one'), submission('two')])
})
afterEach(() => { unmount?.(); vi.unstubAllGlobals() })
async function mount() {
  const root = node('root')
  const app = renderer.createApp(EnterpriseVerification, { review: true })
  app.mount(root); unmount = () => app.unmount()
  await vi.waitFor(() => expect(all(root, 'article')).toHaveLength(2))
  return { root, card: all(root, 'article')[0]! }
}
function revoke(card: HostNode) { return all(card, 'button').find(el => textOf(el).includes('撤销'))! }
async function fill(card: HostNode, text: string) {
  const input = all(card, 'textarea')[0]!
  input.props['onUpdate:modelValue'](text)
  input.props.onInput()
  await nextTick()
}

it('空白或过短依据在当前卡片显示错误并聚焦，不发送撤销请求', async () => {
  const { root, card } = await mount()
  for (const value of ['', '撤回', '     ']) {
    await fill(card, value)
    await revoke(card).props.onClick()
    await nextTick()
    expect(textOf(card)).toContain('请先填写撤销认证的依据，至少 5 个字符。')
    expect(all(card, 'textarea')[0]!.props['aria-invalid']).toBe(true)
    expect(textOf(all(root, 'article')[1]!)).not.toContain('请先填写')
  }
  expect(request).toHaveBeenCalledTimes(1) // Only the initial list read.
  expect(focus).toHaveBeenCalledTimes(3)
})

it('撤销显示进度且防止重复提交，成功原位更新卡片并保留其他企业', async () => {
  const { root, card } = await mount()
  await fill(card, '  企业招聘授权已撤回  ')
  let finish!: (value: unknown) => void
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const pending = revoke(card).props.onClick()
  await nextTick()
  expect(textOf(revoke(card))).toBe('正在撤销…')
  expect(revoke(card).props.disabled).toBe(true)
  await revoke(card).props.onClick()
  expect(request).toHaveBeenCalledTimes(2)
  expect(request).toHaveBeenLastCalledWith('/enterprise-reviews/one', 'POST', { decision: 'revoke', reason: '企业招聘授权已撤回' })
  finish({ ...submission('one'), status: 'revoked', reason: '企业招聘授权已撤回' })
  await pending; await nextTick()
  expect(all(root, 'article')[0]).toBe(card)
  expect(textOf(card)).toContain('认证已撤销，招聘方会话已失效，公开岗位已停止展示。')
  expect(all(card, 'textarea')).toHaveLength(0)
  expect(textOf(all(root, 'article')[1]!)).toContain('认证已通过')
  expect(state.busy).toBe(false)
})

it('接口失败时在当前卡片说明原因，保留填写内容并允许重试', async () => {
  const { card } = await mount()
  await fill(card, '企业招聘授权已撤回')
  request.mockRejectedValueOnce(new Error('服务暂时不可用，请重试。'))
  await revoke(card).props.onClick(); await nextTick()
  expect(textOf(card)).toContain('服务暂时不可用，请重试。')
  expect(textOf(card)).toContain('认证已通过')
  expect(revoke(card).props.disabled).toBe(false)
  request.mockResolvedValueOnce({ ...submission('one'), status: 'revoked', reason: '企业招聘授权已撤回' })
  await revoke(card).props.onClick(); await nextTick()
  expect(request).toHaveBeenLastCalledWith('/enterprise-reviews/one', 'POST', { decision: 'revoke', reason: '企业招聘授权已撤回' })
  expect(textOf(card)).not.toContain('服务暂时不可用')
  expect(textOf(card)).toContain('认证已撤销')
})
