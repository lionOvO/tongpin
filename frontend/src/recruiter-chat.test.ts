import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import RecruiterChat from './components/RecruiterChat.vue'
import { all, node, renderer, textOf, type HostNode } from './test-utils/renderer'
import type { ApplicationDetail } from './hiring'
import type { RecruiterConversation } from './recruiter-assistant'
import { ApiError } from './store'
const request = vi.hoisted(() => vi.fn())
const stream = vi.hoisted(() => vi.fn())
vi.mock('./store', () => ({ api: request, streamApi: stream, ApiError: class extends Error { constructor(message: string, public code = '', public status = 0) { super(message) } } }))
const initial = (): RecruiterConversation => ({ version: 0, session_id: 'current', archived: false, sessions: [], plan: [], notes: '', messages: [], processing: false, business_context: '', model: { id: 'deepseek', label: 'DeepSeek Flash', available: true } as RecruiterConversation['model'] })
const completed = (id: string): RecruiterConversation => ({ ...initial(), version: 1, messages: [
  { id, role: 'user', text: '整理这份简历', created_at: '2026-10-15T01:00:00Z' },
  { id: 'answer', role: 'assistant', text: '合成简历描述使用 Python 开发接口。', created_at: '2026-10-15T01:00:01Z', model_id: 'deepseek', model_label: 'DeepSeek Flash', citations: [{ source: 'resume', quote: '项目：使用 Python 开发接口。' }], questions: ['具体负责哪些接口？'] },
] })
let unmount: (() => void) | undefined
beforeEach(() => {
  request.mockReset(); request.mockResolvedValue(initial()); stream.mockReset(); stream.mockResolvedValue(initial())
  vi.stubGlobal('Document', class {}); vi.stubGlobal('ShadowRoot', class {})
  vi.stubGlobal('document', { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} })
})
afterEach(() => { unmount?.(); unmount = undefined; vi.unstubAllGlobals() })
async function mount(onUnavailable = vi.fn()) {
  const root = node('root')
  const app = renderer.createApp(RecruiterChat, { application: { id: 'synthetic-one' } as ApplicationDetail, onUnavailable })
  app.mount(root); unmount = () => app.unmount()
  await vi.waitFor(() => expect(textOf(root)).toContain('从具体经历开始了解。')); await nextTick(); return root
}
const button = (root: HostNode, label: string) => all(root, 'button').find(el => textOf(el) === label)!
const posts = () => stream.mock.calls

it('打开工作区不自动调用模型，快捷任务生成带引文回答，追问只填写输入框', async () => {
  const root = await mount(); expect(posts()).toHaveLength(0)
  expect(all(root, 'textarea')).toHaveLength(1)
  await button(root, '补充业务背景').props.onClick(); await nextTick()
  const field = (id: string) => all(root, 'textarea').find(el => el.props.id === id)!
  field('recruiter-business-input').props['onUpdate:modelValue']('维护订单接口。')
  field('recruiter-question').props['onUpdate:modelValue']('尚未发送的问题')
  await all(root, 'button').find(el => el.props['aria-label'] === '收起业务背景')!.props.onClick(); await nextTick()
  expect(all(root, 'textarea')).toHaveLength(1)
  stream.mockImplementationOnce(async (_p, body) => completed(body.request_id))
  await button(root, '整理简历精华').props.onClick(); await nextTick()
  expect(posts()).toHaveLength(1)
  expect(posts()[0]![1]).toEqual({ action: 'summary', message: '', business_context: '维护订单接口。', expected_version: 0, request_id: expect.any(String), agent: true })
  expect(posts()[0]![0]).toBe('/applications/synthetic-one/recruiter-assistant/turns/stream')
  expect(textOf(root)).toContain('项目：使用 Python 开发接口。')
  expect((field('recruiter-question') as HostNode & { value: string }).value).toBe('尚未发送的问题')
  await button(root, '具体负责哪些接口？').props.onClick(); await nextTick()
  expect((field('recruiter-question') as HostNode & { value: string }).value).toBe('具体负责哪些接口？')
  expect(posts()).toHaveLength(1)
})

it('生成期间防重复提交；失败保留旧对话并复用请求编号重试', async () => {
  const root = await mount()
  let reject!: (error: Error) => void
  stream.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
  const pending = button(root, '准备面试追问').props.onClick()
  await nextTick(); expect(button(root, '技术与业务关联').props.disabled).toBe(true)
  await button(root, '准备面试追问').props.onClick(); expect(posts()).toHaveLength(1)
  request.mockResolvedValueOnce(initial()); reject(new ApiError('DeepSeek 响应超时。', 'AI_PROVIDER_TIMEOUT', 502))
  await pending; await nextTick()
  expect(textOf(root)).toContain('DeepSeek 响应超时。')
  const key = posts()[0]![1].request_id
  stream.mockResolvedValueOnce(completed(key))
  await button(root, '准备面试追问').props.onClick(); await nextTick()
  expect(posts()).toHaveLength(2); expect(posts()[1]![1].request_id).toBe(key)
  expect(textOf(root)).toContain('合成简历描述使用 Python')
})

it('发送响应丢失先恢复服务端记录，不再次调用模型', async () => {
  const root = await mount()
  stream.mockImplementationOnce(async (_p, body) => {
    request.mockResolvedValueOnce(completed(body.request_id)); throw new ApiError('请求超时')
  })
  await button(root, '整理简历精华').props.onClick(); await nextTick()
  expect(textOf(root)).toContain('合成简历描述使用 Python')
  expect(textOf(root)).not.toContain('请求超时')
  expect(posts()).toHaveLength(1)
})

it('流式预览与正式结果分离，成功后移除临时预览', async () => {
  const root = await mount()
  all(root, 'textarea').find(el => el.props.id === 'recruiter-question')!.props['onUpdate:modelValue']('了解项目职责')
  let finish!: (value: RecruiterConversation) => void
  stream.mockImplementationOnce((_path, _body, emit) => {
    emit('preview', '正在阅读授权项目。')
    return new Promise(resolve => { finish = resolve })
  })
  // The form submit handler is the shared chat send path.
  const sending = all(root, 'form')[0]!.props.onSubmit({ preventDefault() {} })
  await nextTick()
  expect(textOf(root)).toContain('正在阅读授权项目。')
  expect(textOf(root)).toContain('核对依据后保存')
  finish(completed(posts()[0]![1].request_id)); await sending; await nextTick()
  expect(textOf(root)).not.toContain('正在阅读授权项目。')
  expect(textOf(root)).toContain('合成简历描述使用 Python')
})

it('取消材料助手后保留普通对话路径', async () => {
  const root = await mount()
  const choice = all(root, 'input').find(el => el.props.type === 'checkbox')!
  choice.props['onUpdate:modelValue'](false); await nextTick()
  request.mockImplementationOnce(async (_path, _method, body) => completed(body.request_id))
  await button(root, '整理简历精华').props.onClick(); await nextTick()
  expect(stream).not.toHaveBeenCalled()
  expect(request.mock.calls.at(-1)![0]).toBe('/applications/synthetic-one/recruiter-assistant/turns')
  expect(request.mock.calls.at(-1)![2].agent).toBe(false)
  expect(textOf(root)).toContain('合成简历描述使用 Python')
})

it('重新进入恢复历史，授权失效清空回答并通知父页面', async () => {
  const root = await mount(); unmount?.()
  const root2 = node('root'); const unavailable = vi.fn()
  request.mockResolvedValueOnce(completed('saved'))
  const app = renderer.createApp(RecruiterChat, { application: { id: 'synthetic-one' } as ApplicationDetail, onUnavailable: unavailable })
  app.mount(root2); unmount = () => app.unmount()
  await vi.waitFor(() => expect(textOf(root2)).toContain('合成简历描述使用 Python'))
  expect(posts()).toHaveLength(0)
  request.mockRejectedValueOnce(new ApiError('授权已结束', 'REVIEW_CONSENT_UNAVAILABLE', 403))
  await button(root2, '刷新对话').props.onClick(); await nextTick()
  expect(unavailable).toHaveBeenCalledOnce()
  expect(textOf(root2)).not.toContain('合成简历描述使用 Python')
  expect(textOf(root)).not.toContain('合成简历描述使用 Python')
})
