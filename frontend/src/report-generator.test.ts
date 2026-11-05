import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import ReportGenerator from './components/ReportGenerator.vue'
import { all, node, renderer, textOf, type HostNode } from './test-utils/renderer'
const request = vi.hoisted(() => vi.fn())
vi.mock('./store', async () => {
  const { reactive } = await import('vue')
  return { api: request, state: reactive({ epoch: 0, busy: false }), ApiError: class ApiError extends Error { constructor(message: string, public code = '', public status = 0) { super(message) } } }
})
const task = (status = 'running') => ({ id: 'task-one', job_id: 'job', resume_ids: ['resume'], request_id: 'request-one',
  model: { label: 'DeepSeek Flash' }, status, processed: status === 'running' ? 0 : 1, report_ids: [], errors: [], message: '未生成新报告，请查看失败原因。' })
let unmount: (() => void) | undefined
beforeEach(() => { request.mockReset(); request.mockResolvedValue([]); vi.stubGlobal('Document', class {}); vi.stubGlobal('ShadowRoot', class {}); vi.stubGlobal('document', { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} }) })
afterEach(() => { unmount?.(); vi.unstubAllGlobals() })
async function mount() {
  const root = node('root'); const app = renderer.createApp(ReportGenerator, { jobId: 'job', selected: ['resume'], disabled: false })
  app.component('RouterLink', defineComponent({ setup: (_p, { slots }) => () => h('a', slots.default?.()) }))
  app.mount(root); unmount = () => app.unmount(); await vi.waitFor(() => expect(request).toHaveBeenCalled()); await nextTick(); return root
}
const button = (root: HostNode, label: string) => all(root, 'button').find(el => textOf(el) === label)!

it('提交短请求后显示后台进度并防重复生成，刷新页面恢复进行中任务', async () => {
  const root = await mount(); request.mockResolvedValueOnce(task())
  await button(root, '生成能力报告').props.onClick(); await nextTick()
  expect(request).toHaveBeenLastCalledWith('/assessment-tasks', 'POST', expect.objectContaining({ job_id: 'job', resume_ids: ['resume'], request_id: expect.any(String) }), 15000)
  expect(textOf(root)).toContain('可以离开此页')
  expect(button(root, '报告生成中…').props.disabled).toBe(true)
  unmount?.(); request.mockResolvedValue([task()])
  const restored = await mount(); await vi.waitFor(() => expect(textOf(restored)).toContain('正在生成能力报告'))
  expect(button(restored, '报告生成中…').props.disabled).toBe(true)
})

it('模型超时展示真实失败原因，零报告不会报成功', async () => {
  request.mockResolvedValue([{ ...task('failed'), errors: [{ code: 'AI_PROVIDER_TIMEOUT', message: 'DeepSeek 响应超时，未生成新报告。' }] }])
  const root = await mount(); await vi.waitFor(() => expect(textOf(root)).toContain('DeepSeek 响应超时'))
  expect(textOf(root)).toContain('已生成 0 份')
  expect(button(root, '生成能力报告').props.disabled).toBe(false)
})

it('提交回执丢失先查询任务，无法确认时重试复用请求编号', async () => {
  const root = await mount()
  request.mockRejectedValueOnce(new Error('请求超时')).mockResolvedValueOnce([])
  await button(root, '生成能力报告').props.onClick(); await nextTick()
  const key = request.mock.calls.find(c => c[1] === 'POST')![2].request_id
  request.mockResolvedValueOnce(task())
  await button(root, '生成能力报告').props.onClick(); await nextTick()
  const posts = request.mock.calls.filter(c => c[1] === 'POST')
  expect(posts).toHaveLength(2); expect(posts[1]![2].request_id).toBe(key)
})
