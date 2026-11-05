import type { ModelProvenance } from './ai-workspace'

export interface BusinessLink { task: string; reason: string; job_quote: string; source: 'job' | 'business_context' }
export interface RecruiterStrength { title: string; work: string; evidence_kind: 'experience' | 'mentioned'; resume_quote: string; business_link: BusinessLink | null; interview_question: string }
export interface RecruiterCard extends ModelProvenance {
  overview: string; overview_quotes: string[]; strengths: RecruiterStrength[]
  open_questions: { topic: string; question: string }[]
  created_at: string; input_hash: string; partial: boolean; business_context: string; mode: string
}
export interface RecruiterReviewState { review: RecruiterCard | null; running: boolean; business_context: string }
export const experienceStrengths = (review: RecruiterCard | null) => review?.strengths.filter(s => s.evidence_kind === 'experience') || []
export const mentionedSkills = (review: RecruiterCard | null) => review?.strengths.filter(s => s.evidence_kind === 'mentioned') || []

// These labels organize existing evidence for browsing; they never add technologies,
// change candidate order or turn a bare skill mention into demonstrated experience.
const experienceDirections = [
  { id: 'data', label: '数据存储', matches: /数据库|数据存储|缓存|索引|慢查询|\b(?:MySQL|PostgreSQL|Redis|MongoDB|SQL|EXPLAIN)\b/i },
  { id: 'operations', label: '部署运维', matches: /部署|运维|容器|反向代理|\b(?:Docker|Nginx|Linux|Kubernetes|K8s|DevOps|CI\/CD)\b/i },
  { id: 'ai', label: 'AI 应用', matches: /大模型|智能体|知识库|向量|检索|\b(?:AI|RAG|LLM|Agent|Prompt|MCP|LangChain)\b/i },
  { id: 'frontend', label: '前端开发', matches: /前端|页面|交互|\b(?:Vue|React|Next\.?js|HTML|CSS|JavaScript|TypeScript)\b/i },
  { id: 'quality', label: '测试质量', matches: /测试|质量保障|自动化验证|\b(?:pytest|JUnit|Playwright|Selenium)\b/i },
  { id: 'backend', label: '后端开发', matches: /后端|接口|服务端|任务队列|异步|消息队列|\b(?:Python|FastAPI|Java|Spring|Django|Flask|Go|REST)\b|C\+\+/i },
]
export function groupExperienceStrengths(strengths: RecruiterStrength[]) {
  const groups = new Map<string, { id: string; label: string; items: { strength: RecruiterStrength; index: number }[] }>()
  strengths.forEach((strength, index) => {
    if (strength.evidence_kind !== 'experience') return
    // Prefer the named experience, rather than a different technology in its context.
    const direction = experienceDirections.find(d => d.matches.test(strength.title))
      || experienceDirections.find(d => d.matches.test(strength.work))
      || { id: 'other', label: '其他经历' }
    if (!groups.has(direction.id)) groups.set(direction.id, { id: direction.id, label: direction.label, items: [] })
    groups.get(direction.id)!.items.push({ strength, index })
  })
  return [...groups.values()]
}
