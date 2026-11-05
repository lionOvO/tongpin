import { describe, it, expect } from 'vitest'
import { currentDraft, sourceLabel, findingLabel, noteSaved } from './ai-workspace'
import type { Draft, Workspace } from './ai-workspace'
describe('AI 工作区的依据与草稿', () => {
  it('跳过因补充材料而过期的草稿，保存状态不冒充待确认', () => {
    const drafts: Draft[] = [
      { id: 'original', status: 'saved', rewrites: [] }, { id: 'stale', status: 'outdated', rewrites: [] },
    ]
    expect(currentDraft(drafts)?.id).toBe('original')
    expect(currentDraft([{ id: 'stale', status: 'outdated', rewrites: [] }])).toBeUndefined()
    expect(drafts.map(d => d.id)).toEqual(['original', 'stale'])
  })
  it('补充只显示对应本人消息已保存，助手消息不能获得保存标记', () => {
    const workspace = { notes: [{ message_id: 'user-message' }] } as Workspace
    expect(noteSaved(workspace, 'user-message')).toBe(true)
    expect(noteSaved(workspace, 'assistant-message')).toBe(false)
  })
  it('不将未说明当作低能力；补充引用单独标记', () => {
    expect(findingLabel('missing')).toBe('材料尚未说明')
    expect(sourceLabel([{ id: 'N1', kind: 'supplement', label: '本人补充 · 未外部核验', text: '我负责测试。' }], 'N1')).toBe('本人补充 · 未外部核验')
    expect(sourceLabel([], 'foreign')).toBe('来源已不可用')
  })
})
