import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import RecruiterProfile from './components/RecruiterProfile.vue'
import { all, node, renderer, textOf, type HostNode } from './test-utils/renderer'
import type { ApplicationDetail } from './hiring'
import { ApiError } from './store'
import type { RecruiterStrength } from './recruiter-review'

const request = vi.hoisted(() => vi.fn())
vi.mock('./store', async () => {
  const { reactive } = await import('vue')
  return {
    state: reactive({ epoch: 0 }), api: request,
    ApiError: class extends Error { constructor(message: string, public code = '', public status = 0) { super(message) } },
  }
})
const oldCard = {
  overview: '旧资料卡的经历概述', overview_quotes: [], strengths: [] as RecruiterStrength[], open_questions: [],
  created_at: '2026-10-14T00:00:00Z', input_hash: 'snapshot', partial: false, business_context: '',
  mode: 'real', model_id: 'deepseek', model_label: 'DeepSeek',
}
const result = (review = oldCard, running = false) => ({ review, running, business_context: '' })
let unmount: (() => void) | undefined
beforeEach(() => {
  request.mockReset()
  vi.stubGlobal('Document', class {})
  vi.stubGlobal('ShadowRoot', class {})
  vi.stubGlobal('document', { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} })
  request.mockImplementation(async (path: string) => path === '/recruiter/models' ? {
    default_model_id: 'deepseek', models: [
      { id: 'deepseek', label: 'DeepSeek', available: true, provider: 'DeepSeek 官方' },
      { id: 'relay-gpt-61', label: 'GPT 6.1', available: true, provider: '中转站' },
    ],
  } : result())
})
afterEach(() => { unmount?.(); unmount = undefined; vi.unstubAllGlobals() })
async function mount() {
  const root = node('root')
  const application = { id: 'synthetic-one', candidate_name: '合成求职者', status: 'accepted', available: true, resume_shared: true, version: 1 } as ApplicationDetail
  const app = renderer.createApp(RecruiterProfile, { application })
  app.mount(root); unmount = () => app.unmount()
  await vi.waitFor(() => expect(textOf(root)).toContain(oldCard.overview))
  return root
}
const button = (root: HostNode, label: string) => all(root, 'button').find(el => textOf(el) === label)!

it('超时保留旧卡并展示模型选择；只有用户选择后才向新模型发起分析', async () => {
  const root = await mount()
  request.mockRejectedValueOnce(new ApiError('所选模型服务响应超时。', 'AI_PROVIDER_TIMEOUT', 502))
  await button(root, '更新资料卡').props.onClick(); await nextTick()
  expect(textOf(root)).toContain('更新未完成，下面保留上一次生成的资料卡。')
  expect(textOf(root)).toContain(oldCard.overview)
  expect(all(root, 'select')).toHaveLength(1)
  const posts = () => request.mock.calls.filter(call => call[1] === 'POST')
  expect(posts()).toHaveLength(1)
  expect(posts()[0]![2].model_id).toBe('deepseek')
  expect(posts()[0]![3]).toBe(225000)
  all(root, 'select')[0]!.props['onUpdate:modelValue']('relay-gpt-61')
  await nextTick()
  expect(posts()).toHaveLength(1)
  expect(textOf(root)).toContain('本次使用 DeepSeek。')
  request.mockResolvedValueOnce(result({ ...oldCard, overview: '新的经历概述', model_id: 'relay-gpt-61', model_label: 'GPT 6.1', created_at: '2026-10-15T00:00:00Z' }))
  await button(root, '重试分析').props.onClick(); await nextTick()
  expect(posts()).toHaveLength(2)
  expect(posts()[1]![2].model_id).toBe('relay-gpt-61')
  expect(textOf(root)).toContain('新的经历概述')
  expect(textOf(root)).not.toContain('服务响应超时')
})

it('浏览器丢失更新响应时读取服务端已完成的新卡，不重复生成', async () => {
  const root = await mount()
  request.mockRejectedValueOnce(new ApiError('请求超时'))
  request.mockResolvedValueOnce(result({ ...oldCard, overview: '服务端已完成的新卡', created_at: '2026-10-15T00:00:00Z' }))
  await button(root, '更新资料卡').props.onClick(); await nextTick()
  expect(textOf(root)).toContain('服务端已完成的新卡')
  expect(textOf(root)).not.toContain('请求超时')
  expect(button(root, '更新资料卡').props.disabled).toBe(false)
  expect(request.mock.calls.filter(call => call[1] === 'POST')).toHaveLength(1)
})

it('服务端仍在处理时禁止重复提交', async () => {
  const root = await mount()
  request.mockRejectedValueOnce(new ApiError('请求超时'))
  request.mockResolvedValueOnce(result(oldCard, true))
  await button(root, '更新资料卡').props.onClick(); await nextTick()
  expect(button(root, '重试分析')).toBeUndefined()
  for (const el of all(root, 'button').filter(el => textOf(el) === '正在分析…')) {
    expect(el.props.disabled).toBe(true)
    await el.props.onClick()
  }
  expect(request.mock.calls.filter(call => call[1] === 'POST')).toHaveLength(1)
})

it('默认图谱只展示具体经历，节点与原文、业务和追问联动，切换视图不调用模型', async () => {
  const strength = (title: string, quote: string, kind: 'experience' | 'mentioned' = 'experience'): RecruiterStrength => ({
    title, work: `${title}的实际工作`, resume_quote: quote, evidence_kind: kind,
    interview_question: `请介绍${title}的实现过程`,
    business_link: kind === 'experience' ? { task: `${title}相关业务`, reason: `可进一步了解${title}`, job_quote: '合成岗位原文', source: 'job' } : null,
  })
  const fixture = { ...oldCard, strengths: [
    strength('Python 与 FastAPI 接口开发', '合成接口原文'),
    strength('MySQL 查询优化', '合成查询原文'),
    strength('Docker 服务部署', '合成部署原文'),
    strength('Rust', '仅提及 Rust', 'mentioned'),
    strength('设备现场调试', '合成现场原文'),
  ] }
  request.mockImplementation(async (path: string) => path === '/recruiter/models'
    ? { default_model_id: 'deepseek', models: [{ id: 'deepseek', label: 'DeepSeek', available: true }] }
    : result(fixture))
  const root = await mount()
  expect(button(root, '技术图谱').props['aria-pressed']).toBe(true)
  expect(all(root, 'h5').map(textOf)).toEqual(['后端开发', '数据存储', '部署运维', '其他经历'])
  const nodeButtons = () => all(root, 'button').filter(b => b.props['aria-controls'])
  expect(nodeButtons()).toHaveLength(4)
  expect(nodeButtons().some(b => textOf(b).includes('Rust'))).toBe(false)
  await nodeButtons()[1]!.props.onClick(); await nextTick()
  const evidence = () => all(root, 'div').find(el => el.props.class === 'recruiter-card-evidence')!
  expect(textOf(evidence())).toContain('合成查询原文')
  expect(textOf(evidence())).toContain('MySQL 查询优化相关业务')
  expect(textOf(evidence())).toContain('请介绍MySQL 查询优化的实现过程')
  expect(evidence().props.id).toBe(nodeButtons()[1]!.props['aria-controls'])
  expect(nodeButtons()[1]!.props['aria-pressed']).toBe(true)
  const before = request.mock.calls.length
  await button(root, '资料卡').props.onClick(); await nextTick()
  expect(textOf(evidence())).toContain('合成查询原文')
  await button(root, '技术图谱').props.onClick(); await nextTick()
  expect(nodeButtons()[1]!.props['aria-pressed']).toBe(true)
  expect(request.mock.calls).toHaveLength(before)
})

it('只提及技能时不创建空图谱或推定技术经历', async () => {
  request.mockImplementation(async (path: string) => path === '/recruiter/models'
    ? { default_model_id: 'deepseek', models: [] }
    : result({ ...oldCard, strengths: [{ title: 'Python', work: '材料仅提及 Python', evidence_kind: 'mentioned', resume_quote: '了解 Python', business_link: null, interview_question: '请介绍实际使用场景' }] }))
  const root = await mount()
  expect(textOf(root)).toContain('当前材料尚未描述具体的技术任务')
  expect(textOf(root)).toContain('材料提及 · 具体实践待了解')
  expect(all(root, 'button').filter(b => b.props['aria-controls'])).toHaveLength(0)
})
