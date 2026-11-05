import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import JobFitComparison from './components/JobFitComparison.vue'
import { state } from './store'
import { all, node, renderer, textOf, type HostNode } from './test-utils/renderer'

const request = vi.hoisted(() => vi.fn())
const query = vi.hoisted(() => ({ job: 'job-one' } as Record<string,string>))
vi.mock('vue-router', () => ({ useRoute: () => ({ query }) }))
vi.mock('./store', async () => {
  const { reactive } = await import('vue')
  return { state: reactive({ epoch: 0, resumeId: 'resume-one', resumes: [], jobs: [], presentation: null, switching: false }), api: request,
    ApiError: class extends Error { constructor(message: string, public code = '', public status = 0) { super(message) } } }
})
let dispose: (() => void) | undefined
const flush = async () => { await Promise.resolve(); await nextTick(); await Promise.resolve(); await nextTick() }
const button = (root: HostNode, value: string) => all(root, 'button').find(el => textOf(el).includes(value))!
const task = (extra = {}) => ({ id: 'task-one', resume_id: 'resume-one', resume_name: '合成简历', created_at: '2026-10-17T08:00:00Z', status: 'completed', total: 1, processed: 1, errors: [], ranked_results: [], ...extra })
beforeEach(() => {
  vi.useFakeTimers(); request.mockReset(); query.job = 'job-one'
  vi.stubGlobal('Document', class {})
  vi.stubGlobal('ShadowRoot', class {})
  vi.stubGlobal('document', { visibilityState: 'visible', addEventListener: vi.fn(), removeEventListener: vi.fn() })
  Object.assign(state, { epoch: 0, resumeId: 'resume-one', switching: false,
    resumes: [{ id: 'resume-one', display_name: '合成简历', data_origin: 'synthetic' }, { id: 'resume-two', display_name: '另一简历' }],
    jobs: [{ id: 'job-one', title: '合成后端岗位', company_name: '合成公司', status: '已确认', profile: { direction: '后端', education: '本科', requirements: [] } }],
    presentation: { tier_labels: {}, banned_terms: [], enterprise_banned_terms: [] } })
  request.mockResolvedValue([])
})
afterEach(() => { dispose?.(); vi.useRealTimers(); vi.unstubAllGlobals() })
async function mount() {
  const root = node('root'), app = renderer.createApp(JobFitComparison)
  app.component('RouterLink', defineComponent({ setup: (_p, { slots }) => () => h('a', slots.default?.()) }))
  app.mount(root); dispose = () => app.unmount(); await flush(); return root
}
it('从岗位入口预选，后台任务短请求提交，重复点击不重复分析', async () => {
  const root = await mount()
  expect(textOf(root)).toContain('1 / 20 个已选')
  let finish!: (row: unknown) => void
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const pending = button(root,'分析岗位契合度').props.onClick(); await flush()
  await button(root,'正在提交').props.onClick()
  expect(request.mock.calls.filter(c => c[1] === 'POST')).toHaveLength(1)
  expect(request).toHaveBeenLastCalledWith('/compare/tasks','POST',expect.objectContaining({ resume_id:'resume-one', job_ids:['job-one'], request_id:expect.any(String) }),15000)
  finish(task({ status:'running', processed:0 })); await pending; await flush()
  expect(textOf(root)).toContain('已处理 0 / 1')
  expect(button(root,'该简历正在分析').props.disabled).toBe(true)
})
it('弹窗校验描述，添加后保留已有选择并混合提交', async () => {
  const root = await mount()
  await button(root,'添加岗位').props.onClick(); await flush()
  expect(button(root,'添加并选中').props.disabled).toBe(true)
  all(root,'input').find(n=>n.props.id==='reference-job-name')!.props['onUpdate:modelValue']('合成数据岗位')
  all(root,'textarea')[0].props['onUpdate:modelValue']('岗位职责：使用 Python 进行数据分析，任职要求熟悉 SQL，参与项目交付。')
  await flush(); expect(button(root,'添加并选中').props.disabled).toBe(false)
  request.mockResolvedValueOnce({id:'private-job',title:'合成数据岗位',personal_reference:true,status:'已确认',profile:{direction:'数据分析',education:null,requirements:[]}})
  await all(root,'form')[0].props.onSubmit({preventDefault(){}}); await flush()
  expect(textOf(root)).toContain('2 / 20 个已选')
  expect(textOf(root)).toContain('个人参照 · 仅自己可见')
  expect(all(root,'form')).toHaveLength(0)
  expect(state.jobs.filter(j=>j.id==='private-job')).toHaveLength(1)
  request.mockResolvedValueOnce(task())
  await button(root,'分析岗位契合度').props.onClick(); await flush()
  expect(request).toHaveBeenLastCalledWith('/compare/tasks','POST',expect.objectContaining({job_ids:['job-one','private-job']}),15000)
})
it('添加失败保留输入，允许重试，取消不改动原有选择', async () => {
  const root=await mount()
  await button(root,'添加岗位').props.onClick(); await flush()
  all(root,'input').find(n=>n.props.id==='reference-job-name')!.props['onUpdate:modelValue']('合成数据岗位')
  const text='岗位职责：使用 Python 进行数据分析，任职要求熟悉 SQL，参与项目交付。'
  all(root,'textarea')[0].props['onUpdate:modelValue'](text); await flush()
  request.mockRejectedValueOnce(new Error('岗位解析失败'))
  await all(root,'form')[0].props.onSubmit({preventDefault(){}}); await flush()
  expect(textOf(root)).toContain('岗位解析失败')
  expect(request).toHaveBeenLastCalledWith('/jobs/references','POST',{title:'合成数据岗位',jd:text})
  expect(button(root,'添加并选中').props.disabled).toBe(false)
  await button(root,'取消').props.onClick(); await flush()
  expect(all(root,'form')).toHaveLength(0)
  expect(textOf(root)).toContain('1 / 20 个已选')
  expect(state.jobs).toHaveLength(1)
})
it('旧记录不编造档位，完全没有依据时仅提示且不显示数值排位', async () => {
  request.mockResolvedValueOnce([task({ranked_results:[{ job_ref:1, job_title:'暂无依据岗位', dimensions:[], skill_levels:[], rank:null,
    fit_summary:{band:'unassessed',label:'暂无判断依据',reason:'暂无可判断依据',strengths:[],gaps:[],missing:['项目经历'],additional_missing:[]} },
    {job_ref:2,job_title:'旧岗位',rank:1,dimensions:[],skill_levels:[]} ]})])
  const root = await mount()
  expect(textOf(root)).toContain('暂不排位')
  expect(textOf(root)).toContain('历史记录未生成契合档位')
  expect(textOf(root)).toContain('未见相关描述项目经历')
})
it('切换简历后丢弃晚到结果，保留每份简历自己的分析历史', async () => {
  const root = await mount()
  let finish!: (row: unknown) => void
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const pending = button(root,'分析岗位契合度').props.onClick(); await flush()
  state.resumeId = 'resume-two'; request.mockResolvedValueOnce([]); await flush()
  finish(task({ status:'running' })); await pending; await flush()
  expect(textOf(root)).not.toContain('已处理')
  expect(textOf(root)).toContain('暂无分析记录')
})
it('服务端已经完成而提交响应丢失时，同一输入复用请求编号', async () => {
  const root = await mount()
  request.mockRejectedValueOnce(new Error('网络连接中断'))
  await button(root,'分析岗位契合度').props.onClick(); await flush()
  const first = request.mock.calls.find(c => c[1] === 'POST')![2]
  request.mockResolvedValueOnce(task())
  await button(root,'分析岗位契合度').props.onClick(); await flush()
  expect(request.mock.calls.filter(c => c[1] === 'POST')[1][2].request_id).toBe(first.request_id)
})
it('提交前发出的历史请求晚到时，不覆盖新任务的进度', async () => {
  let oldHistory!: (rows: unknown) => void
  request.mockImplementationOnce(() => new Promise(resolve => { oldHistory = resolve }))
  const root = await mount()
  request.mockResolvedValueOnce(task({status:'running',processed:0}))
  await button(root,'分析岗位契合度').props.onClick(); await flush()
  oldHistory([]); await flush()
  expect(textOf(root)).toContain('已处理 0 / 1')
  expect(button(root,'该简历正在分析').props.disabled).toBe(true)
})

it('只重试当前记录未完成的岗位，不受当前岗位勾选影响', async () => {
  request.mockResolvedValueOnce([task({status:'partial',errors:[{job_ref:3,job_id:'job-one',error:'档位区间错误'}]})])
  const root=await mount()
  expect(textOf(root)).toContain('合成后端岗位：档位区间错误')
  request.mockResolvedValueOnce(task({id:'retry-task',status:'running',processed:5,total:6}))
  await button(root,'仅重试未完成岗位').props.onClick(); await flush()
  expect(request).toHaveBeenLastCalledWith('/compare/tasks/task-one/retry','POST',{request_id:expect.any(String)},15000)
  expect(textOf(root)).toContain('已处理 5 / 6')
})

it('五档与证据范围同时展示，缺失项只提示不阻止已有证据排位', async () => {
  const summary={band:'high',label:'较高契合',reason:'按已有描述判断',strengths:['Python'],gaps:[],missing:['Docker'],additional_missing:[],coverage:{known:1,total:3}}
  request.mockResolvedValueOnce([task({policy_updated:true,ranked_results:[{job_ref:1,job_title:'合成岗位',rank:1,dimensions:[],skill_levels:[],fit_summary:summary}]})])
  const root=await mount()
  expect(all(root,'div').filter(e=>String(e.props.class).includes('fit-count '))).toHaveLength(5)
  expect(textOf(root)).toContain('很高契合')
  expect(textOf(root)).toContain('很低契合')
  expect(textOf(root)).toContain('1 / 3 项有可用依据')
  expect(textOf(root)).toContain('未见相关描述Docker')
  expect(textOf(root)).toContain('无需再次分析')
  expect(textOf(root)).not.toContain('待补充')
  expect(textOf(root)).toContain('1推荐顺序')
})
