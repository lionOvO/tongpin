import { expect, it, vi } from 'vitest'
import { h, nextTick, reactive } from 'vue'
import { recruiterExport, recruiterQuestions, recruiterResults, type RecruiterConversation } from './recruiter-assistant'
import RecruiterResults from './components/RecruiterResults.vue'
import { all, node, renderer, textOf } from './test-utils/renderer'

function conversation(): RecruiterConversation {
  return { version: 1, session_id: 'one', archived: false, sessions: [], processing: false, business_context: '维护订单服务', plan: [], notes: '', model: { available: true } as RecruiterConversation['model'], messages: [
    { id: 'u1', role: 'user', action: 'interview', text: '准备面试追问', created_at: '2026-10-20' },
    { id: 'a1', role: 'assistant', text: '围绕接口的实现过程沟通。', created_at: '2026-10-20', questions: ['如何核对接口结果？'], citations: [{ source: 'resume', quote: '使用 Python 开发订单接口。' }] },
    { id: 'u2', role: 'user', text: '继续了解', created_at: '2026-10-20' },
    { id: 'a2', role: 'assistant', action: 'chat', text: '可以了解验证方法。', created_at: '2026-10-20', questions: ['如何核对接口结果？', '如何验证参数校验？'], citations: [{ source: 'job', quote: '维护订单服务' }] },
  ] }
}
it('历史回答兼容旧动作字段，按最新结果显示，追问去重并保留确切来源', () => {
  const data = conversation()
  expect(recruiterResults(data).map(m => m.action)).toEqual(['chat', 'interview'])
  const questions = recruiterQuestions(data)
  expect(questions.map(q => q.question)).toEqual(['如何核对接口结果？', '如何验证参数校验？'])
  expect(questions[0]).toMatchObject({ message_id: 'a2', citations: data.messages[3]!.citations })
  expect(data.messages).toHaveLength(4)
})
it('导出对话包含业务背景、原文与追问，提纲只包含人工选择的内容', () => {
  const data = conversation(); data.plan = [recruiterQuestions(data)[1]!]; data.notes = '核对接口测试的过程。'
  const history = recruiterExport(data, '陈予安', '后端开发', 'conversation')
  expect(history).toContain('维护订单服务'); expect(history).toContain('使用 Python 开发订单接口。')
  const plan = recruiterExport(data, '陈予安', '后端开发', 'plan')
  expect(plan).toContain('如何验证参数校验？'); expect(plan).toContain('招聘方沟通备注（个人记录）')
  expect(plan).not.toContain('如何核对接口结果？')
})
it('新回答与轮询不覆盖未保存的面试提纲，切换会话时加载对应提纲', async () => {
  vi.stubGlobal('Document', class {}); vi.stubGlobal('ShadowRoot', class {})
  const props = reactive({ conversation: conversation(), busy: false, name: '陈予安', job: '后端开发' })
  const root = node('root'); const app = renderer.createApp({ render: () => h(RecruiterResults, props) }); app.mount(root)
  try {
    const button = (label: string) => all(root, 'button').find(el => textOf(el) === label)!
    button('加入提纲').props.onClick(); await nextTick()
    const note = all(root, 'textarea')[0]!
    note.props['onUpdate:modelValue']('尚未保存的沟通重点'); await nextTick()
    props.conversation = { ...props.conversation, version: 2 }; await nextTick()
    expect(textOf(root)).toContain('有未保存的修改')
    expect((all(root, 'textarea')[0] as unknown as { value: string }).value).toBe('尚未保存的沟通重点')
    props.conversation = { ...conversation(), session_id: 'another', notes: '另一份对话的备注' }; await nextTick()
    expect((all(root, 'textarea')[0] as unknown as { value: string }).value).toBe('另一份对话的备注')
    expect(textOf(root)).not.toContain('有未保存的修改')
  } finally { app.unmount(); vi.unstubAllGlobals() }
})
