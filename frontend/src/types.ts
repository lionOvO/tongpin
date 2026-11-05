export type RecordData = Record<string, any>
export interface Presentation { version: string; bias_notice: string; footer: string; banned_terms: string[]; enterprise_banned_terms: string[]; tier_labels: Record<string, string>; preference_labels: Record<string, string> }
export interface Requirement { skill: string; required_level: number; quote: string; hard: boolean }
export interface Job { id: string; title: string; source_jd: string; status: string; version: number; published?: boolean; accepts_applications?: boolean; personal_reference?: boolean; company_name?: string; moderation_status?: 'suspended' | 'cleared'; moderation_reason?: string; data_origin: string; profile: { direction: string; education: string | null; requirements: Requirement[] } }
export type WorkspaceRole = 'candidate' | 'enterprise'
export type EnterpriseStatus = 'unsubmitted' | 'pending' | 'approved' | 'rejected' | 'revoked'
export interface User { id: string; actor: string; role: WorkspaceRole | 'admin'; session_scope?: 'user' | 'admin'; workspace_role?: WorkspaceRole; available_roles?: WorkspaceRole[]; enterprise_status?: EnterpriseStatus; name: string; has_password?: boolean }
export interface Resume { id: string; display_name: string; text: string; data_origin: string; created_at?: string; supplement_notice?: boolean; source_application_id?: string; application_job_id?: string; application_job_title?: string; original_file?: { name: string; media_type: string; size: number } }
export interface Person { actor: string; name: string; subtitle: string }
