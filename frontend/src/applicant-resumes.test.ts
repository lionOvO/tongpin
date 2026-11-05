import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import ApplicantResumes from './components/ApplicantResumes.vue'
import { all, node, renderer, textOf, type HostNode } from './test-utils/renderer'

const request = vi.hoisted(() => vi.fn())
const download = vi.hoisted(() => vi.fn())
vi.mock('./store', async () => {
  const { reactive } = await import('vue')
  return { api: request, download, state: reactive({ epoch: 0, switching: false }) }
})
const applicant = (id: string, imported: string | null = null) => ({ id, job_id: 'job-one', candidate_name: '合成投递者' + id, resume_name: '合成简历', job_title: '后端接口开发', status: 'submitted', version: 2, created_at: '2026-10-15T00:00:00Z', imported_resume_id: imported })
const page = (items = [applicant('one'), applicant('two', 'existing')]) => ({ items, total: items.length, offset: 0, limit: 20 })
let unmount: (() => void) | undefined
beforeEach(() => {
  request.mockReset(); download.mockReset()
  vi.stubGlobal('Document', class {})
  vi.stubGlobal('ShadowRoot', class {})
  vi.stubGlobal('document', { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} })
  request.mockResolvedValue(page())
})
afterEach(() => { unmount?.(); vi.unstubAllGlobals() })
async function mount() {
  const root = node('root'); const imported = vi.fn()
  const app = renderer.createApp(ApplicantResumes, { jobId: 'job-one', jobTitle: '后端接口开发', onImported: imported })
  app.directive('dialog', {}); app.mount(root); unmount = () => app.unmount()
  await vi.waitFor(() => expect(all(root, 'article')).toHaveLength(2))
  return { root, imported }
}
const button = (root: HostNode, label: string) => all(root, 'button').find(el => textOf(el) === label)!

it('按当前岗位读取授权投递，标记已导入，按钮支持预览与下载', async () => {
  const { root } = await mount()
  expect(request.mock.calls[0]![0]).toContain('job_id=job-one')
  expect(button(root, '已导入').props.disabled).toBe(true)
  const card = all(root, 'article')[0]!
  request.mockResolvedValueOnce({ id: 'one', resume_shared: true, resume_snapshot: { name: '合成简历', text: '投递时的项目经历正文' } })
  await button(card, '查看简历').props.onClick(); await nextTick()
  expect(textOf(root)).toContain('投递时的项目经历正文')
  await button(card, '下载').props.onClick()
  expect(download).toHaveBeenCalledWith('/applications/one/resume-download', '合成简历.txt')
})

it('一键导入有进度、防重复，成功原位显示已导入并通知父页面', async () => {
  const { root, imported } = await mount()
  const card = all(root, 'article')[0]!
  let resolve!: (value: unknown) => void
  request.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const pending = button(card, '一键导入').props.onClick()
  await nextTick()
  expect(button(card, '一键导入').props.disabled).toBe(true)
  await button(card, '一键导入').props.onClick()
  expect(request).toHaveBeenCalledTimes(2)
  const resume = { id: 'imported-one', display_name: '合成简历', text: '授权版本的正文' }
  resolve({ resume, already_imported: false }); await pending; await nextTick()
  expect(button(card, '已导入').props.disabled).toBe(true)
  expect(imported).toHaveBeenCalledWith(resume)
  expect(request).toHaveBeenLastCalledWith('/applications/one/resume-import', 'POST', { expected_version: 2 })
})

it('授权失效后重新获取列表，不保留旧预览或提供再次导入入口', async () => {
  const { root, imported } = await mount()
  request.mockRejectedValueOnce(new Error('这份投递简历的授权已结束。'))
  request.mockResolvedValueOnce(page([]))
  await button(all(root, 'article')[0]!, '一键导入').props.onClick(); await nextTick()
  expect(all(root, 'article')).toHaveLength(0)
  expect(textOf(root)).toContain('授权已结束')
  expect(textOf(root)).toContain('当前暂无已授权的投递简历')
  expect(imported).not.toHaveBeenCalled()
})
