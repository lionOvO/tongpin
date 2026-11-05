export interface Source { id: string; kind: 'resume' | 'job' | 'supplement'; label: string; text: string }
export interface ModelOption { id: string; label: string; provider: string; model: string; protocol: string; available: boolean; unavailable_reason: string; external: boolean }
export interface ModelCatalog { default_model_id: string; models: ModelOption[] }
export interface ModelProvenance { model_id?: string; model_label?: string; model?: string; provider?: string; protocol?: string }
export interface Finding { topic: string; status: 'supported' | 'partial' | 'missing'; observation: string; advice: string; citations: { source_id: string; quote: string }[] }
export interface Draft extends ModelProvenance { id: string; status: 'pending' | 'saved' | 'outdated'; saved_resume_id?: string; rewrites: { source_id: string; before: string; after: string; reason: string; citations: { source_id: string; quote: string }[] }[] }
export interface Message extends ModelProvenance { id: string; role: 'user' | 'assistant'; text: string; action?: string; questions?: string[]; created_at: string; material_epoch?: number }
export interface WorkspaceSummary { id: string; title: string; created_at: string; resume_id: string; job_id: string | null; version: number; updated_at?: string; message_count?: number; preview?: string }
export interface Workspace extends WorkspaceSummary {
  agent_run?: { id: string; engine: string; preview?: string; request_text?: string; status: 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'; label: string; steps: { tool: string; label: string; status: 'running' | 'completed' }[] } | null
  job_assistance?: { jobs: { ref: string; id: string; title: string; company: string }[]; comparison: {
    id: string; status: string; total: number; processed: number; message: string; notice: string; unavailable_count?: number;
    ranked_results: { job_id: string; job_title: string; company_name?: string; rank: number | null; fit_summary: { band: string; label: string; reason: string; strengths: string[]; gaps: string[]; missing: string[] } }[];
    errors: { error: string }[]
  } | null }
  messages: Message[]; notes: { id: string; message_id: string; text: string; kind: string }[]; drafts: Draft[]
  analysis: ({ findings: Finding[]; questions: string[]; sources: Source[]; created_at: string; partial: boolean } & ModelProvenance) | null
  resume: { id: string; name: string; text: string; revision: boolean; revision_kind?: string | null }; job: { id: string; title: string; text: string; personal_reference: boolean } | null
  sources: Source[]; model_ready: boolean; processing: boolean; truncated: boolean; last_error: string
  model_id: string; selected_model: ModelOption
  material_epoch?: number
  pending_materials?: { session_id: string; resume: { id: string; name: string; text: string }; job: { id: string; title: string; text: string } | null } | null
}
export const findingLabel = (status: Finding['status']) => ({ supported: '已有描述支持', partial: '仍需补充', missing: '材料尚未说明' })[status]
export const sourceLabel = (sources: Source[], id: string) => sources.find(s => s.id === id)?.label || '来源已不可用'
export const currentDraft = (drafts: Draft[]) => [...drafts].reverse().find(d => d.status !== 'outdated')
export const noteSaved = (workspace: Workspace, messageId: string) => workspace.notes.some(n => n.message_id === messageId)
