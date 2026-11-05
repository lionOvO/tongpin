import type { ModelOption, ModelProvenance } from './ai-workspace'
export type RecruiterAction = 'chat' | 'summary' | 'business' | 'interview'
export interface RecruiterChatMessage extends ModelProvenance {
  id: string; role: 'user' | 'assistant'; text: string; created_at: string; partial?: boolean
  action?: RecruiterAction
  citations?: { source: 'resume' | 'job' | 'business_context'; quote: string }[]; questions?: string[]
}
export interface RecruiterPlanQuestion { message_id: string; question: string; citations?: NonNullable<RecruiterChatMessage['citations']> }
export interface RecruiterSession { id: string; title: string; message_count: number; updated_at: string; current: boolean }
export interface RecruiterConversation {
  version: number; session_id: string; archived: boolean; sessions: RecruiterSession[]
  messages: RecruiterChatMessage[]; business_context: string; processing: boolean; model: ModelOption
  plan: RecruiterPlanQuestion[]; notes: string
  agent_run?: { id: string; status: 'running'|'completed'|'failed'|'cancelled'|'interrupted'; label: string;
    preview: string; request_text: string; engine: string; steps: { tool: string; label: string; status: string }[] } | null
}
export const recruiterSourceLabel = { resume: '已授权简历', job: '投递时的岗位要求', business_context: '企业业务说明（非求职者经历）' }
export const recruiterActionLabel: Record<RecruiterAction, string> = { chat: '对话分析', summary: '简历精华', business: '技术与业务关联', interview: '面试追问' }
export function recruiterResults(conversation: RecruiterConversation | null) {
  return (conversation?.messages || []).flatMap((message, index, messages) => message.role !== 'assistant' ? [] : [{
    ...message, action: message.action || messages[index - 1]?.action || 'chat' as RecruiterAction,
  }]).reverse()
}
export function recruiterQuestions(conversation: RecruiterConversation | null): RecruiterPlanQuestion[] {
  const seen = new Set<string>()
  return recruiterResults(conversation).flatMap(message => (message.questions || []).flatMap(question => {
    if (seen.has(question)) return []
    seen.add(question)
    return [{ message_id: message.id, question, citations: message.citations || [] }]
  }))
}
export function recruiterExport(conversation: RecruiterConversation, name: string, job: string, kind: 'conversation' | 'plan') {
  const lines = [`# ${kind === 'plan' ? '面试提纲' : '招聘 AI 对话'}`, name, `应聘岗位：${job}`, '仅供招聘沟通参考；AI 内容依据授权材料整理，建议由招聘方核对。', '']
  if (kind === 'conversation') {
    if (conversation.business_context) lines.push('## 企业业务背景', conversation.business_context, '')
    for (const message of conversation.messages) {
      lines.push(`## ${message.role === 'user' ? '你' : '同频招聘助手'} · ${message.created_at}`, message.text)
      for (const citation of message.citations || []) lines.push(`${recruiterSourceLabel[citation.source]}：${citation.quote}`)
      if (message.questions?.length) lines.push('可继续了解：', ...message.questions.map(q => '- ' + q))
      lines.push('')
    }
  } else {
    conversation.plan.forEach((item, index) => {
      lines.push(`## ${index + 1}. ${item.question}`)
      for (const citation of item.citations || []) lines.push(`${recruiterSourceLabel[citation.source]}：${citation.quote}`)
      lines.push('')
    })
    if (conversation.notes) lines.push('## 招聘方沟通备注（个人记录）', conversation.notes)
  }
  return lines.join('\n')
}
export function saveRecruiterText(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob(['\ufeff', text], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = filename.replace(/[\\/:*?"<>|\r\n]/g, '_') + '.md'
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
