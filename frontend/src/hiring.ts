export type ApplicationStatus = 'submitted' | 'invited' | 'accepted' | 'declined' | 'rejected' | 'withdrawn' | 'closed'
export type HiringAction = 'invite' | 'accept' | 'decline' | 'reject' | 'withdraw' | 'close' | 'refresh_preferences'
export const applicationLabels: Record<ApplicationStatus, string> = { submitted: '已投递', invited: '待回应邀请', accepted: '已接受 · 沟通中', declined: '已婉拒邀请', rejected: '企业暂不推进', withdrawn: '已撤回', closed: '沟通已结束' }
export const eventLabels: Record<string, string> = { apply: '投递简历', invite: '发出沟通邀请', accept: '接受邀请', decline: '婉拒邀请', reject: '暂不推进', withdraw: '撤回投递', close: '结束沟通', refresh_preferences: '同步本人期待' }
export const ended = (status: ApplicationStatus) => ['declined', 'rejected', 'withdrawn', 'closed'].includes(status)
export interface SharedExpectations { dimensions: Record<string, string | null>; dimension_labels: Record<string, string>; dimension_version: string; ambience_text: string }
export interface HiringChatMessage { side: 'candidate' | 'enterprise'; text: string; created_at: string }
export interface ApplicationSummary { id: string; job_id: string; job_title: string; company_name: string; candidate_name: string; resume_name: string; status: ApplicationStatus; version: number; available: boolean; resume_shared: boolean; created_at: string; updated_at: string; message_count: number; invitation: { text: string; created_at: string } | null; review_strengths?: string[]; review_ready?: boolean; ai_message_count?: number; unread_count?: number; last_message?: HiringChatMessage | null }
export function applicationByJob(rows: ApplicationSummary[]): Map<string, ApplicationSummary> {
  const result = new Map<string, ApplicationSummary>()
  for (const row of rows) {
    const previous = result.get(row.job_id)
    if (!previous || ended(previous.status) && !ended(row.status)
      || ended(previous.status) === ended(row.status) && row.created_at > previous.created_at) result.set(row.job_id, row)
  }
  return result
}
export interface ApplicationDetail extends ApplicationSummary {
  resume_id: string | null; resume_snapshot: { name: string; text: string; revision_kind?: string; self_reported_paragraphs: string[] } | null
  job_snapshot: { title: string; text: string; version: number }; introduction: string
  events: { action: string; side: 'candidate' | 'enterprise'; text: string; created_at: string }[]
  messages: { side: 'candidate' | 'enterprise'; text: string; created_at: string }[]
  candidate_preferences: SharedExpectations | null; enterprise_preferences: SharedExpectations | null
  preference_comparison: { dimension_results: { dimension_id: string; name: string; ent_quote: string; cand_quote: string; unmatched_reason: string }[] } | null
  preference_notice: string
}
