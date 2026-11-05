import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import Resumes from './pages/Resumes.vue'
import { state } from './store'
import { all, node, renderer, textOf, type HostNode } from './test-utils/renderer'

const request = vi.hoisted(() => vi.fn())
const download = vi.hoisted(() => vi.fn())
vi.mock('./store', async () => {
  const { computed, reactive } = await import('vue')
  const state = reactive({ busy: false, switching: false, epoch: 0, error: '', success: '', jobId: '', resumeId: '', resumes: [] as any[] })
  return {
    state, candidate: computed(() => true), job: computed(() => null), api: request,
    refresh: vi.fn(), notifyError: vi.fn(), download,
    action: async (fn: () => Promise<unknown>) => {
      if (state.busy) return
      state.busy = true
      try { await fn() } catch (error) { state.error = (error as Error).message }
      finally { state.busy = false }
    },
  }
})
let unmount: (() => void) | undefined
beforeEach(() => {
  request.mockReset()
  download.mockReset()
  Object.assign(state, { busy: false, switching: false, epoch: 0, error: '', success: '', jobId: '', resumeId: 'one',
    resumes: ['one', 'two'].map(id => ({ id, display_name: '合成简历' + id, text: '使用 Python 开发后端接口的项目经历。', data_origin: 'synthetic' })) })
})
afterEach(() => unmount?.())
async function mount() {
  const root = node('root')
  const app = renderer.createApp(Resumes)
  app.component('RouterLink', defineComponent({ setup: (_props, { slots }) => () => h('a', slots.default?.()) }))
  app.directive('dialog', {})
  app.mount(root); unmount = () => app.unmount()
  await nextTick()
  return root
}
const button = (root: HostNode, text: string) => all(root, 'button').find(el => textOf(el) === text)!
const remove = (root: HostNode, id = 'one') => all(root, 'button').find(el => el.props['aria-label'] === '删除简历：合成简历' + id)!
const dialog = (root: HostNode) => all(root, 'section').find(el => el.props.role === 'dialog')

it('每份简历有删除入口，确认前清楚说明历史保留，取消不发请求', async () => {
  const root = await mount()
  expect(all(root, 'button').filter(el => el.props['aria-label']?.startsWith('删除简历：'))).toHaveLength(2)
  await remove(root).props.onClick(); await nextTick()
  expect(textOf(dialog(root)!)).toContain('合成简历one')
  expect(textOf(dialog(root)!)).toContain('已有 AI 对话、分析报告和已授权的投递快照保留')
  await button(root, '取消').props.onClick(); await nextTick()
  expect(dialog(root)).toBeUndefined()
  expect(request).not.toHaveBeenCalled()
  expect(state.resumes).toHaveLength(2)
})

it('删除有进度且防重复，更新当前简历选择，最后一份删除后显示导入入口', async () => {
  const root = await mount()
  await remove(root).props.onClick(); await nextTick()
  let finish!: (value: unknown) => void
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const pending = button(root, '确认删除').props.onClick()
  await nextTick()
  expect(button(root, '正在删除…').props.disabled).toBe(true)
  await button(root, '正在删除…').props.onClick()
  expect(request).toHaveBeenCalledTimes(1)
  finish({ id: 'one', deleted: true })
  await pending; await nextTick()
  expect(request).toHaveBeenLastCalledWith('/resumes/one', 'DELETE')
  expect(dialog(root)).toBeUndefined()
  expect(state.resumeId).toBe('two')
  expect(state.resumes.map(r => r.id)).toEqual(['two'])
  await remove(root, 'two').props.onClick(); await nextTick()
  request.mockResolvedValueOnce({ id: 'two', deleted: true })
  await button(root, '确认删除').props.onClick(); await nextTick()
  expect(state.resumeId).toBe('')
  expect(state.resumes).toHaveLength(0)
  expect(textOf(root)).toContain('导入第一份简历')
})

it('服务端失败保留简历与弹窗，在弹窗内解释错误并允许重试', async () => {
  const root = await mount()
  await remove(root).props.onClick(); await nextTick()
  request.mockRejectedValueOnce(new Error('暂时无法删除，请重试。'))
  await button(root, '确认删除').props.onClick(); await nextTick()
  expect(textOf(dialog(root)!)).toContain('暂时无法删除，请重试。')
  expect(state.resumes).toHaveLength(2)
  expect(button(root, '确认删除').props.disabled).toBe(false)
  request.mockResolvedValueOnce({ id: 'one', deleted: true })
  await button(root, '确认删除').props.onClick(); await nextTick()
  expect(dialog(root)).toBeUndefined()
  expect(state.resumes.map(r => r.id)).toEqual(['two'])
})

it('从封面进入完整阅读，原文保持不变，下载仍调用现有接口', async () => {
  const root = await mount()
  const cover = all(root, 'button').find(el => el.props['aria-label'] === '预览简历：合成简历one')!
  await cover.props.onClick(); await nextTick()
  expect(dialog(root)?.props['aria-labelledby']).toBe('resume-reader-title')
  await button(root, '分析文本').props.onClick(); await nextTick()
  expect(textOf(dialog(root)!)).toContain(state.resumes[0]!.text)
  await button(root, '下载文本').props.onClick()
  expect(download).toHaveBeenCalledWith('/resumes/one/download', '合成简历one.txt')
  expect(state.resumes[0]!.text).toBe('使用 Python 开发后端接口的项目经历。')
})

it('卡片和列表切换保留所有简历和原有操作', async () => {
  const root = await mount()
  await all(root, 'button').find(el => el.props['aria-label'] === '列表视图')!.props.onClick(); await nextTick()
  expect(all(root, 'div').some(el => el.props.class?.includes('resume-collection-list'))).toBe(true)
  expect(all(root, 'button').filter(el => el.props['aria-label']?.startsWith('下载简历：'))).toHaveLength(2)
  expect(all(root, 'button').filter(el => el.props['aria-label']?.startsWith('删除简历：'))).toHaveLength(2)
  expect(all(root, 'a').filter(el => textOf(el).includes('与 AI 完善'))).toHaveLength(2)
})
