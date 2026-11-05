import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import JobReference from './components/JobReference.vue'
import { ApiError, state } from './store'
import { all, node, renderer, textOf } from './test-utils/renderer'

const request = vi.hoisted(() => vi.fn())
vi.mock('./store', async () => {
  const { reactive, computed } = await import('vue')
  const state = reactive({ epoch: 0, jobId: 'one', jobs: [] as any[], switching: false })
  return { state, confirmedJobs: computed(() => state.jobs.filter(j => j.status === '已确认')), api: request,
    ApiError: class extends Error { constructor(message: string, public code = '', public status = 0) { super(message) } } }
})
const job = (id: string) => ({ id, title: `岗位 ${id}`, status: '已确认', version: 1, source_jd: `原文 ${id}`, profile: { direction: '开发', education: '本科', requirements: [{ skill: 'Python', required_level: 2, quote: `Python 接口开发 ${id}`, hard: true }] } })
const flush = async () => { await Promise.resolve(); await nextTick(); await Promise.resolve(); await nextTick() }
let dispose: (() => void) | undefined
beforeEach(() => {
  vi.stubGlobal('Document', class {}); vi.stubGlobal('ShadowRoot', class {})
  Object.assign(state, { epoch: 0, jobId: 'one', jobs: [job('one'), job('two')], switching: false })
  request.mockReset().mockImplementation((path: string) => path === '/config/rubric' ? Promise.resolve({ skill_names: { '2': '熟悉' } }) : Promise.reject(new ApiError('样本不足', 'INSUFFICIENT_SAMPLES', 422)))
})
afterEach(() => { dispose?.(); dispose = undefined; vi.unstubAllGlobals() })
async function mount() {
  const root = node('root'), app = renderer.createApp(JobReference)
  app.component('RouterLink', defineComponent({ setup: (_p, { slots }) => () => h('a', slots.default?.()) }))
  app.mount(root); dispose = () => app.unmount(); await flush(); return root
}
it('统计样本不足时直接展示要求、程度、引用，且不需要选择简历', async () => {
  const root = await mount(), text = textOf(root)
  expect(text).toContain('岗位要求参照'); expect(text).toContain('Python 接口开发 one')
  expect(text).toContain('熟悉 · 2 级'); expect(text).toContain('暂未提供可用的同类岗位统计')
  expect(text).not.toContain('我的简历'); expect(all(root, 'select')).toHaveLength(1)
})
it('有统计时只展示所选岗位涉及技能，并注明合成数据及统计范围', async () => {
  request.mockImplementation(path => Promise.resolve(path === '/config/rubric' ? {} : [
    { id: 'a', skill: 'Python', lower_level: 1, upper_level: 3, sample_size: 20, source_type: 'B_synthetic' },
    { id: 'b', skill: '无关技能', lower_level: 1, upper_level: 2, sample_size: 20 }]))
  const root = await mount(), text = textOf(root)
  expect(text).toContain('1–3'); expect(text).toContain('20 个不同岗位')
  expect(text).toContain('合成样例统计，非真实招聘数据'); expect(text).toContain('不代表整个行业')
  expect(text).not.toContain('无关技能')
})
it('统计网络异常仍显示岗位要求，刷新后恢复', async () => {
  request.mockImplementation(path => path === '/config/rubric' ? Promise.resolve({}) : Promise.reject(new Error('offline')))
  const root = await mount()
  expect(textOf(root)).toContain('统计暂时无法加载'); expect(textOf(root)).toContain('Python 接口开发 one')
  request.mockResolvedValue([])
  await all(root, 'button').find(n => textOf(n).includes('刷新统计'))!.props.onClick(); await flush()
  expect(textOf(root)).toContain('暂未提供可用的同类岗位统计')
})
it('切换岗位后忽略旧统计，防止引用混在一起', async () => {
  let finish!: (value: unknown) => void
  request.mockImplementation(path => path === '/config/rubric' ? Promise.resolve({}) : path.includes('one') ? new Promise(resolve => { finish = resolve }) : Promise.resolve([]))
  const root = await mount(); state.jobId = 'two'; await flush()
  finish([{ id: 'old', skill: 'Python', lower_level: 4, upper_level: 4, sample_size: 99 }]); await flush()
  expect(textOf(root)).toContain('Python 接口开发 two'); expect(textOf(root)).not.toContain('99 个不同岗位')
})
it('无技能项时保留完整原文；无岗位时显示选择入口', async () => {
  state.jobs[0]!.profile.requirements = []
  const root = await mount()
  expect(textOf(root)).toContain('暂未整理技能要求'); expect(textOf(root)).toContain('原文 one')
  state.jobs = []; await flush(); expect(textOf(root)).toContain('先选择一个参照岗位')
})
it('岗位已失去访问权限时停止显示缓存原文', async () => {
  request.mockImplementation(path => path === '/config/rubric' ? Promise.resolve({}) : Promise.reject(new ApiError('不可见', 'NOT_FOUND', 404)))
  const root = await mount()
  expect(textOf(root)).toContain('这个岗位暂时无法访问'); expect(textOf(root)).not.toContain('Python 接口开发 one')
})
