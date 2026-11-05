import { describe, expect, it } from 'vitest'
import cfg from '../../config/presentation.json'
import { relation, rationale, resultExplanation, violations, reportSafe } from './presentation'
describe('两端呈现纪律', () => {
  it('企业端转换全部关系符号，保留部分证据不足及范围说明', () => {
    const text = rationale('部分证据不足；B2 — B4，换算待确认', cfg)
    expect(text).toBe('部分证据不足；低于要求 2 级 — 相符')
    expect(violations(text,cfg)).toBe(false)
  })
  it('求职者的关系符号始终有具体岗位参照', () => {
    expect(relation('B4',cfg,true,'后端工程师')).toContain('（相对 后端工程师）')
    expect(relation('B4',cfg,true,'')).toBe('相符')
    expect(rationale('B4',cfg,true,'后端工程师')).toBe('B4（相对 后端工程师）')
  })
  it('仅允许固定否定短语，拦截百分比和企业结果禁词', () => {
    expect(violations(cfg.bias_notice,cfg)).toBe(false)
    for (const text of ['系统设置合格线','评级 B4','匹配度 88%','分位 75％']) expect(violations(text,cfg)).toBe(true)
    expect(violations('岗位 B4（相对 后端）',cfg,false)).toBe(false)
  })
  it('不篡改原文来绕过禁词，也检查面试准备与锚点特征', () => {
    const base = { display_name:'示例',job_title:'后端工程师',dimensions:[],skill_levels:[],open_questions:[],followups:[] }
    expect(reportSafe(base,cfg,false)).toBe(true)
    expect(reportSafe({...base,skill_levels:[{ skill:'Python',requirement_quote:'合格线',evidence:[] }]},cfg,false)).toBe(false)
    expect(reportSafe({...base,open_questions:[{ item:'技能',hint:'评级 B5' }]},cfg,false)).toBe(false)
  })
  it('旧报告去掉推断约束，保留专业和项目信息缺口', () => {
    const major = '简历描述支持 insufficient；锚点特征：专业缺失或未在已评审映射表覆盖；不能猜测为无关专业；简历写明：无可定位原文'
    expect(resultExplanation(major,cfg)).toBe('简历描述支持 证据不足；锚点特征：专业缺失或未在已评审映射表覆盖；简历写明：无可定位原文')
    expect(resultExplanation('未能定位对口项目；缺失不代表没有项目',cfg)).toBe('未能定位对口项目')
    expect(resultExplanation('实习时长未描述；不猜测时长或职责',cfg)).toBe('实习时长未描述')
    expect(resultExplanation('锚点特征：不得推断未提及的技能',cfg)).toBe('')
  })
  it('保留说明的句号与引用中的约束措辞', () => {
    expect(resultExplanation('专业信息缺失。不能猜测为无关专业。请补充专业名称。',cfg)).toBe('专业信息缺失。请补充专业名称。')
    const value = '锚点特征：未能定位项目；缺失不代表没有项目；简历写明：参与需求审查；不能猜测客户需求'
    expect(resultExplanation(value,cfg)).toBe('锚点特征：未能定位项目；简历写明：参与需求审查；不能猜测客户需求')
  })
  it('显示清理不能绕过原始报告的呈现检查', () => {
    const value = '不能猜测合格线'
    expect(resultExplanation(value,cfg)).toBe('')
    const report = {display_name:'示例',job_title:'后端工程师',dimensions:[{name:'项目',rationale:value,cross_band_reason:'',evidence:[]}],skill_levels:[]}
    expect(reportSafe(report,cfg,false)).toBe(false)
  })
})
