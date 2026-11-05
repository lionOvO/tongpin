import { expect, it } from 'vitest'
import { resumeParagraphs, resumeTitle, sortedResumes } from './resume-display'
import type { Resume } from './types'

it('缩略预览限制内容量，完整阅读保留全部正文，不推断技能或经历', () => {
  const source = '教育经历\r\n某合成大学\n项目经历\n使用 Python 编写接口。\n' + '保留这一段原文。\n'.repeat(500)
  const compact = resumeParagraphs(source, true), full = resumeParagraphs(source)
  expect(compact.length).toBeLessThanOrEqual(36)
  expect(compact[0]).toEqual({ text: '教育经历', heading: true })
  expect(compact[3]).toEqual({ text: '使用 Python 编写接口。', heading: false })
  expect(full.map(row => row.text).join('\n')).toBe(source.replace(/\r/g, '').trim())
  expect(resumeParagraphs('<script>alert(1)</script>')[0]?.text).toBe('<script>alert(1)</script>')
})

it('搜索和排序不改变原始数组，同一天或缺少时间的材料顺序稳定', () => {
  const rows = [
    {id:'a',display_name:'Python 原版',created_at:'2026-10-10T00:00:00Z'},
    {id:'b',display_name:'未知时间'},
    {id:'c',display_name:'Python 新版',created_at:'2026-10-15T00:00:00Z'},
  ] as Resume[]
  expect(sortedResumes(rows,' PYTHON ','newest').map(row => row.id)).toEqual(['c','a'])
  expect(sortedResumes(rows,'','oldest').map(row => row.id)).toEqual(['a','c','b'])
  expect(rows.map(row => row.id)).toEqual(['a','b','c'])
  expect(sortedResumes(rows,'不存在','newest')).toEqual([])
})

it('只整理显示标题，不修改存储名称或补出候选人信息', () => {
  expect(resumeTitle('个人简历_周雨桐_产品经理助理.pdf')).toBe('周雨桐 · 产品经理助理')
  expect(resumeTitle('')).toBe('')
})
