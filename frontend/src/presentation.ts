import type { Presentation, RecordData } from './types'
export function relation(tier: string, cfg: Presentation, candidate = false, job = '') {
  const label = cfg.tier_labels[tier] || '证据不足'
  return candidate && tier !== 'insufficient' && job ? `${tier} · ${label}（相对 ${job}）` : label
}
export function rationale(value: string, cfg: Presentation, candidate = false, job = '') {
  return String(value || '').replace(/\bB[1-5]\b/g, t => candidate && job ? `${t}（相对 ${job}）` : cfg.tier_labels[t] || '证据不足').replace(/\binsufficient\b/g, cfg.tier_labels.insufficient).replace(/[，；]换算待确认/g, '')
}
// Display derived explanations only. Original quotes and safety checks stay intact.
export function resultExplanation(value: string, cfg: Presentation, candidate = false, job = '') {
  const constraint = /^(不能|不可|不得|不应|不允许|禁止|不猜测|不推断|不作推断|缺失不代表|未描述不代表|未提及不代表)/
  const display = rationale(value, cfg, candidate, job)
  const sourceStart = display.indexOf('；简历写明：')
  const explanation = sourceStart < 0 ? display : display.slice(0, sourceStart)
  const source = sourceStart < 0 ? '' : display.slice(sourceStart)
  const filtered = (explanation.match(/[^；;。\n]+[；;。\n]*/g) || []).filter(part => {
    const text = part.trim()
    const prefix = text.match(/^(锚点特征[：:]\s*)/)?.[0] || ''
    return !constraint.test(text.slice(prefix.length))
  }).join('').trim().replace(/[；;]+$/, '')
  return filtered + (filtered ? source : source.replace(/^；/, ''))
}
export function violations(value: unknown, cfg: Presentation, enterprise = true) {
  const text = String(value ?? '').replaceAll('系统不设合格线', '')
  return [...cfg.banned_terms, ...(enterprise ? cfg.enterprise_banned_terms : [])].some(t => text.includes(t)) || (enterprise && /\d\s*[%％]/.test(text))
}
export function reportSafe(r: RecordData, cfg: Presentation, candidate: boolean) {
  const texts = [r.display_name, r.job_title]
  for (const d of r.dimensions || []) texts.push(d.name, rationale(d.rationale, cfg, candidate, r.job_title), rationale(d.cross_band_reason, cfg, candidate, r.job_title), ...d.evidence)
  for (const s of r.skill_levels || []) texts.push(s.skill, s.requirement_quote, ...s.evidence, ...(s.anchor_hits || []).map((a: RecordData) => a.feature))
  if (!candidate) for (const q of [...(r.open_questions || []), ...(r.followups || [])]) texts.push(q.item, q.hint, q.question)
  return texts.every(t => !violations(t, cfg, !candidate))
}
export function origin(value: string) { return value === 'synthetic' ? '合成示例' : '用户导入' }
export function date(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
