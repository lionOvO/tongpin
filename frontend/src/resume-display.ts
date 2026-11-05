import type { Resume } from './types'

export type ResumeSort = 'newest' | 'oldest' | 'name'
export function resumeTitle(name: string) {
  return name.replace(/\.(pdf|txt|json)$/i, '').replace(/^个人简历[_\s-]*/, '').replace(/_/g, ' · ') || name
}
export function resumeParagraphs(text: string, compact = false) {
  // A cover uses a bounded excerpt; the reader and original-text view retain all text.
  // Text is rendered by Vue interpolation, never interpreted as HTML or AI instructions.
  const source = compact ? text.slice(0, 1800) : text
  return source.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map(text => ({ text,
    heading: /^(?:[一二三四五六七八九十\d]+[、.．\s]*)?(?:个人信息|基本信息|个人简介|求职意向|教育背景|教育经历|工作经历|工作经验|实习经历|项目经历|项目经验|专业技能|技术技能|技能特长|核心技能|自我评价|个人优势|补充说明|荣誉奖项|证书)[：:]?$/.test(text),
  })).slice(0, compact ? 36 : undefined)
}
export function sortedResumes(resumes: Resume[], query: string, sort: ResumeSort) {
  const search = query.trim().toLocaleLowerCase()
  return resumes.filter(resume => resume.display_name.toLocaleLowerCase().includes(search))
    .map((resume, index) => ({ resume, index }))
    .sort((a, b) => {
      if (sort === 'name') return a.resume.display_name.localeCompare(b.resume.display_name, 'zh-CN') || a.index - b.index
      const first = Date.parse(a.resume.created_at || ''), second = Date.parse(b.resume.created_at || '')
      if (Number.isFinite(first) && Number.isFinite(second)) return (sort === 'oldest' ? first - second : second - first) || a.index - b.index
      if (Number.isFinite(first) !== Number.isFinite(second)) return Number.isFinite(first) ? -1 : 1
      return sort === 'oldest' ? b.index - a.index : a.index - b.index
    }).map(row => row.resume)
}
export function resumeDate(value?: string) {
  if (!value || !Number.isFinite(Date.parse(value))) return '已保存'
  return new Date(value).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }) + ' 导入'
}
