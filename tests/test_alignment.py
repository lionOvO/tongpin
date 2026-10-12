import copy
import itertools
import json
import re
from pathlib import Path

import pytest

from app.agents import AgentGateway, AnchoredEvaluationOutput
from app.deterministic import (d4_result, dimension_result, evidence_skills, gpa_tier,
    internship_result, major_result, parse_jd, presentation_violations, project_result,
    rationale_for_display, rating_config, skill_tier)
from app.errors import DomainError
from app.security import redact

ROOT = Path(__file__).resolve().parents[1]
RUBRIC = rating_config()
MAJORS = json.loads((ROOT / 'config/major_domain_map.json').read_text(encoding='utf-8'))
PRESENTATION = json.loads((ROOT / 'config/presentation.json').read_text(encoding='utf-8'))
PROFILE = {'direction':'后端开发', 'education':'本科', 'requirements':[{'skill':'Python', 'required_level':3, 'quote':'熟练使用 Python', 'hard':True}]}


def skill(text, name='Python'):
    return next(s for s in evidence_skills(text) if s['skill'] == name)


def test_discipline_1_ordinal_only_schema_rejects_fractional_and_micro_tiers():
    for invalid in ['B4.5', 'B4+', 'B4±0.1', 'B3–B4']:
        with pytest.raises(ValueError):
            AnchoredEvaluationOutput.model_validate({'skills':[], 'dimensions':[{'dimension_id':'D3', 'tier':invalid, 'evidence':[], 'rationale':'简历描述'}]})
    assert set(RUBRIC['anchors']['D3']) == {'B1','B2','B3','B4','B5'}


def test_discipline_2_no_quote_means_insufficient_not_lowest():
    row = dimension_result('D3', 'B5', [], ['声称多个项目'])
    assert row['tier'] == 'insufficient' and not row['tier_range']
    assert gpa_tier('获国家奖学金，没有成绩和排名') is None
    assert skill_tier(0, 4) == 'insufficient'
    assert skill('自评精通 Python')['evidence_level'] == 0


def test_discipline_3_no_level_inflation_and_jd_default_one():
    jd = parse_jd('岗位要求：Python、Docker；熟悉 Redis，了解 Java；熟练 React。')
    levels = {r['skill']:r['required_level'] for r in jd['requirements']}
    assert levels == {'Python':1, 'Docker':1, 'Redis':2, 'Java':1, 'React':3}
    assert skill('熟悉 Python')['evidence_level'] == 0
    assert skill('课程项目使用 Python 实现数据统计')['evidence_level'] == 2
    assert skill('自评精通 Python\n课程项目使用 Python 实现数据统计')['evidence_level'] == 2
    assert skill('技能：Redis', 'Redis')['evidence_level'] == 1


def test_discipline_4_all_sensitive_attributes_excluded_from_rating():
    base = '专业：软件工程，本科\n技能：Python\n课程项目使用 Python 实现数据统计'
    sensitive = '\n性别：男\n年龄：25\n民族：汉\n婚育：未婚\n政治面貌：党员\n院校层次：985、211、双一流\nQS 排名：20'
    assert redact(base + sensitive) == redact(base)
    assert evidence_skills(redact(base + sensitive)) == evidence_skills(redact(base))
    assert major_result(redact(base + sensitive), PROFILE, MAJORS) == major_result(base, PROFILE, MAJORS)


def test_discipline_5_every_reason_contains_tier_features_and_source_quotes(client):
    reports = client.get('/assessments').json()
    assert reports
    for report in reports:
        for row in report['dimensions']:
            assert row['tier'] in row['rationale']
            assert '锚点特征：' in row['rationale'] and '简历写明：' in row['rationale']
            assert row['anchor_hits']
            if row['tier'] != 'insufficient':
                assert row['evidence'] and all(q in row['rationale'] for q in row['evidence'])
            if row['tier_range']:
                assert row['cross_band_reason'] and '跨档依据：' in row['rationale']


def test_discipline_6_explicit_absence_vs_unmentioned_or_incomplete():
    basic = '专业：软件工程，本科\n技能：Python\n'
    assert internship_result(basic+'无实习经历', PROFILE)['tier'] == 'B1'
    assert project_result(basic+'无相关项目', PROFILE)['tier'] == 'B1'
    assert internship_result(basic, PROFILE)['tier'] == 'insufficient'
    assert internship_result('无实习经历', PROFILE)['tier'] == 'insufficient'
    assert project_result('无相关项目', PROFILE)['tier'] == 'insufficient'


def test_discipline_7_evidence_voice_and_candidate_interview_boundary(client):
    for text, function in [('专业：软件工程，本科', lambda t:major_result(t, PROFILE, MAJORS)),
                           ('后端开发实习 6 个月，主导 Python API 服务', lambda t:internship_result(t, PROFILE)),
                           ('排名 25/100', gpa_tier)]:
        row = function(text)
        conclusion = row['rationale'].split('；简历写明：')[0]
        assert conclusion.startswith('简历描述')
        assert not any(term in conclusion for term in ['具备','掌握','精通','确实','证实','认定'])
    candidate = {'X-Demo-Actor':'candidate:lin'}
    resume = client.get('/resumes', headers=candidate).json()[0]
    job = client.get('/jobs', headers=candidate).json()[0]
    response = client.post('/fit/analyze', json={'resume_id':resume['id'], 'job_id':job['id']}, headers=candidate)
    assert response.status_code == 200
    assert 'open_questions' not in response.json() and not response.json().get('followups')


def test_discipline_8_independent_anchors_original_and_self_contained_requirements():
    source = (ROOT / RUBRIC['source']).read_text(encoding='utf-8')
    for dimension, anchors in RUBRIC['anchors'].items():
        assert len(anchors) == 5
        for tier, anchor in anchors.items():
            assert anchor
            assert not re.search(r'同上|分数|得分|评分|[±]', anchor)
            assert all(reference == tier for reference in re.findall(r'B[1-5]', anchor))
            assert RUBRIC['evidence_requirements'][dimension][tier]['requirement'] != '同上'
            if dimension != 'D4':
                assert anchor in source.replace('**','').replace('`','')
    assert set(RUBRIC['insufficient_anchors']) == {'D1','D2','D3','D4','D5'}
    assert len(RUBRIC['general_disciplines']) == 8
    assert len(MAJORS['domains']) == 8
    assert RUBRIC['status'] == '上游已对齐、未冻结'


@pytest.mark.parametrize('value,tier', [(90,'B5'),(89.9,'B4'),(75,'B4'),(74.9,'B3'),(60,'B3'),(59.9,'B2'),(40,'B2'),(39.9,'B1')])
def test_d2_authoritative_boundary_values(value, tier):
    assert gpa_tier(f'百分位 {value}')['tier'] == tier


def test_d2_rank_priority_conservative_gpa_and_one_step_award():
    assert gpa_tier('排名 25/100；GPA 4.0/4.0')['tier'] == 'B4'
    assert gpa_tier('排名 50/100')['normalized_value'] == 50
    assert gpa_tier('GPA 3.8')['tier'] == 'B4'
    assert '换算待确认' in gpa_tier('GPA 3.8')['rationale']
    assert '非统计百分位' in gpa_tier('GPA 3.8')['rationale']
    assert gpa_tier('排名前25%')['tier'] == 'B4'
    assert gpa_tier('百分位 45\n获得国家奖学金\n获得校级荣誉')['tier'] == 'B3'
    assert gpa_tier('获得国家奖学金') is None


@pytest.mark.parametrize('text,level,feature', [
    ('技能：Python',1,'技能名'),
    ('课程项目使用 Python 实现数据统计',2,'任务与对象'),
    ('项目使用 Python 实现登录服务，功能已上线',3,'功能上线'),
    ('项目使用 Python 实现报名功能，被 200 位用户使用',3,'被他人使用'),
    ('项目使用 Python 构建工具，作品链接 https://example.test/demo',3,'作品链接'),
    ('使用 Python 设计交易系统架构',4,'架构设计'),
    ('项目使用 Python 优化接口性能，从 800ms 至 120ms',4,'性能优化并量化'),
    ('使用 Python 开发开源项目，贡献 PR 被合并',4,'开源贡献'),
    ('主讲 Python 技术分享，讲授异步任务开发',4,'技术分享或教学'),
    ('发表 Python 相关专利论文',4,'专利论文'),
])
def test_skill_anchors_require_actual_feature_and_literal_quote(text, level, feature):
    row = skill(text)
    assert row['evidence_level'] == level
    assert row['evidence'] and all(q in text for q in row['evidence'])
    assert any(feature in h['feature'] and h['quote'] in row['evidence'] for h in row['anchor_hits'])


def test_isolated_keywords_or_self_report_cannot_promote_skill():
    assert skill('熟悉 Python；上线、用户、100ms、量化')['evidence_level'] == 0
    assert skill('课程项目使用 Python 实现登录接口，记录 100ms')['evidence_level'] == 2
    assert skill('Python 架构设计、性能优化、开源贡献、技术分享、论文')['evidence_level'] == 1
    assert skill('计划使用 Python 开发系统并上线')['evidence_level'] == 0


def hard_skill(tier, hard=True):
    return {'tier':tier, 'hard':hard, 'required_level':3, 'evidence':[] if tier=='insufficient' else ['使用 Python 实现统计功能']}


def test_d4_hard_only_lower_median_and_all_unknown():
    assert d4_result([hard_skill('B2'),hard_skill('B4'),hard_skill('B5',False)])['tier'] == 'B2'
    row = d4_result([hard_skill('insufficient'),hard_skill('insufficient')])
    assert row['tier'] == 'insufficient' and not row['tier_range']
    assert d4_result([])['tier'] == 'insufficient'


@pytest.mark.parametrize('values', [['B4','insufficient'], ['B2','B4','insufficient'], ['B4','B4','B4','insufficient'], ['B3','insufficient','insufficient']])
def test_d4_partial_missing_interval_equals_all_possible_lower_medians(values):
    known = [int(v[1]) for v in values if v != 'insufficient']
    count = values.count('insufficient')
    possibilities = [sorted(known+list(missing))[(len(values)-1)//2] for missing in itertools.product(range(2,6), repeat=count)]
    row = d4_result([hard_skill(v) for v in values])
    assert row['tier_range'] == [f'B{min(possibilities)}',f'B{max(possibilities)}']
    assert '部分证据不足' in row['rationale'] and row['cross_band_reason']


def test_d3_interval_has_two_independently_supported_features():
    text = '参与 Python 后端项目，协助边缘任务，使用 Python 实现统计功能'
    row = project_result(text, PROFILE)
    assert row['tier_range'] == ['B3','B4'] and row['cross_band_reason']
    assert text in row['rationale'] and '角色边缘' in row['rationale']


@pytest.mark.parametrize('dimension,tier,text', [
    ('D1','B5','专业：软件工程，本科\n辅修：数学'),
    ('D1','B4','专业：软件工程，本科'),
    ('D1','B3','专业：人工智能，本科'),
    ('D1','B2','专业：自动化，本科'),
    ('D1','B1','专业：工商管理（信息化方向），本科'),
    ('D3','B5','主导交易项目，使用 Python 实现交易功能，支撑日均 3000 单\n参与检索项目，使用 Python 实现检索功能'),
    ('D3','B4','参与后端项目，使用 Python 实现统计功能'),
    ('D3','B3','Python 后端项目，协助边缘任务'),
    ('D3','B2','课程练手项目：Python 语法练习'),
    ('D3','B1','专业：软件工程，本科\n技能：Python\n无相关项目'),
    ('D5','B5','后端开发实习 6 个月，主导 Python 核心接口开发'),
    ('D5','B4','后端开发实习 3 个月，使用 Python 开发接口'),
    ('D5','B3','后端开发实习 2 个月，使用 Python 开发接口'),
    ('D5','B2','有销售实习，与岗位领域无关'),
    ('D5','B1','专业：软件工程，本科\n技能：Python\n无实习经历'),
])
def test_dimension_anchor_execution(dimension,tier,text):
    function = {'D1':lambda t:major_result(t, PROFILE, MAJORS), 'D3':lambda t:project_result(t, PROFILE), 'D5':lambda t:internship_result(t, PROFILE)}[dimension]
    row = function(text)
    assert row['tier'] == tier and row['evidence'] and row['anchor_hits']


def test_d5_missing_duration_not_inferred_from_output_keywords():
    assert internship_result('后端开发实习，使用 Python 开发功能已上线', PROFILE)['tier'] == 'insufficient'
    assert internship_result('后端开发实习 8 个月，参与 Python 接口开发', PROFILE)['tier'] == 'insufficient'


def test_same_project_repeated_cannot_create_two_project_anchor():
    text = '主导交易项目，使用 Python 实现交易功能\n参与交易项目，使用 Python 完成订单处理，日均 3000 单'
    assert project_result(text, PROFILE)['tier'] != 'B5'


def test_bias_notices_each_have_both_elements_and_single_source_blacklist(client):
    for key in ['bias_notice','footer']:
        assert '可能存在偏差' in PRESENTATION[key] and '系统不设合格线' in PRESENTATION[key]
    cfg = client.get('/config/presentation').json()
    cfg['version'] = 'notice-incomplete';cfg['footer'] = '系统不设合格线'
    assert client.put('/config/presentation',json=cfg).status_code == 400
    assert presentation_violations('系统不设合格线', PRESENTATION) == []
    assert presentation_violations('不设合格线', PRESENTATION) == ['合格线']
    for term in PRESENTATION['banned_terms']+PRESENTATION['enterprise_banned_terms']:
        assert presentation_violations(term, PRESENTATION)
    assert presentation_violations('87％', PRESENTATION)


def test_report_issuance_rejects_missing_notice(client, monkeypatch):
    service = client.app.state.service
    original_get = service.config.get
    def corrupt_notice(name):
        cfg = copy.deepcopy(original_get(name))
        if name == 'presentation':cfg['footer'] = '系统不设合格线'
        return cfg
    monkeypatch.setattr(service.config,'get',corrupt_notice)
    report = client.get('/assessments').json()[0]
    result = client.post('/assessments',json={'job_id':report['job_id'],'resume_ids':[report['resume_id']]}).json()
    assert result['reports'] == [] and result['errors'][0]['code'] == 'NOTICE_REQUIRED'


def test_enterprise_reason_maps_tier_without_changing_record():
    row = gpa_tier('GPA 3.5/4.0')
    original = copy.deepcopy(row)
    display = rationale_for_display(row['rationale'], PRESENTATION)
    assert not presentation_violations(display, PRESENTATION)
    assert '相符' in display and row == original
    candidate = rationale_for_display(row['rationale'], PRESENTATION, True, 'Python 后端岗')
    assert 'B4（相对 Python 后端岗）' in candidate


def test_service_d4_partial_interval_bonus_exclusion_and_missing_region(client):
    jd = '后端开发工程师\n任职要求：熟悉 Python，熟练 Redis。\n加分项：了解 Docker。'
    profile = {'direction':'后端开发', 'education':None, 'requirements':[
        {'skill':'Python','required_level':2,'quote':'熟悉 Python','hard':True},
        {'skill':'Redis','required_level':3,'quote':'熟练 Redis','hard':True},
        {'skill':'Docker','required_level':1,'quote':'了解 Docker','hard':False}]}
    job = client.post('/jobs',json={'title':'D4 对齐验收','jd':jd,'manual_profile':profile}).json()
    confirmed = client.put('/jobs/'+job['id']+'/confirm',json={'profile':profile,'expected_version':job['version']})
    assert confirmed.status_code == 200
    resume = client.post('/resumes',json={'name':'区间验收','text':'专业：软件工程，本科\n课程项目使用 Python 实现统计功能\n使用 Docker 设计容器项目架构'}).json()
    response = client.post('/assessments',json={'job_id':job['id'],'resume_ids':[resume['id']]}).json()
    assert not response['errors'] and len(response['reports']) == 1
    report = response['reports'][0]
    row = next(d for d in report['dimensions'] if d['dimension_id']=='D4')
    assert row['tier_range'] == ['B2','B4'] and '部分证据不足' in row['rationale']
    assert row in report['structure_view']['insufficient'] and row not in report['structure_view']['weaknesses']
    assert 'Docker' not in ' / '.join(row['evidence'])
    assert next(s for s in report['skill_levels'] if s['skill']=='Redis')['tier'] == 'insufficient'


def test_d4_bounds_respect_possible_skill_tiers_for_each_requirement():
    unknown = {**hard_skill('insufficient'), 'required_level':4}
    row = d4_result([hard_skill('B5'), unknown])
    assert row['tier_range'] == ['B1','B4']
    unknown['required_level'] = 1
    assert d4_result([hard_skill('B5'), unknown])['tier_range'] == ['B4','B5']


def test_fractional_skill_level_is_rejected_in_code():
    with pytest.raises(DomainError):skill_tier(2.5,3)


def test_agent_rejects_unquoted_features_and_keyword_based_level_inflation():
    text = '课程项目使用 Python 实现数据统计'
    obj = {'dimensions':[], 'skills':[{'skill':'Python','evidence_level':4,'evidence':[text],'self_reported':'精通','anchor_hits':[{'feature':'架构设计','quote':text}]}]}
    with pytest.raises(DomainError) as error:AgentGateway.validate_evaluation(obj,text)
    assert error.value.code == 'SKILL_ANCHOR_UNSUPPORTED'
    obj['skills'][0]['evidence_level'] = 2
    obj['skills'][0]['anchor_hits'][0]['feature'] = '使用场景包含任务与对象'
    AgentGateway.validate_evaluation(obj,text)
    obj['skills'][0]['anchor_hits'][0]['quote'] = '凭空引用'
    with pytest.raises(DomainError) as error:AgentGateway.validate_evaluation(obj,text)
    assert error.value.code == 'EVIDENCE_INVALID'


def test_agent_interval_requires_cross_band_basis():
    text = '参与 Python 后端项目，协助边缘任务，使用 Python 实现统计功能'
    row = project_result(text, PROFILE)
    row['cross_band_reason'] = ''
    with pytest.raises(DomainError) as error:AgentGateway.validate_evaluation({'dimensions':[row],'skills':[]},text)
    assert error.value.code == 'CROSS_BAND_REASON_REQUIRED'


def test_pack_rejects_incomplete_anchor_evidence_or_cross_reference(client):
    cfg = client.get('/config/rubric').json()
    cfg['version'] = 'invalid-anchor-proof'
    cfg['evidence_requirements']['D1']['B4']['requirement'] = '同上'
    assert client.put('/config/rubric',json=cfg).status_code == 400
    cfg['evidence_requirements']['D1']['B4']['requirement'] = '专业名称原文'
    cfg['anchors']['D1']['B4'] = '比 B3 高一档'
    assert client.put('/config/rubric',json=cfg).status_code == 400


def test_business_export_reads_shared_blacklist_and_has_bias_notices(client):
    service = client.app.state.service
    report = client.get('/assessments').json()[0]
    report['rank'] = 1
    content = service.csv_export([report])
    assert not presentation_violations(content, PRESENTATION)
    assert content.count('可能存在偏差') == 2 and content.count('系统不设合格线') == 2
    report['display_name'] = '门槛 B4'
    with pytest.raises(DomainError) as error:service.csv_export([report])
    assert error.value.code == 'PRESENTATION_BLOCKED'


def test_report_content_violation_is_blocked_before_persistence_and_audited(client):
    before = len(client.get('/assessments').json())
    report = client.get('/assessments').json()[0]
    resume = client.post('/resumes',json={'name':'B4 非法呈现验收','text':'专业：软件工程，本科\n课程项目使用 Python 实现数据统计'}).json()
    result = client.post('/assessments',json={'job_id':report['job_id'],'resume_ids':[resume['id']]}).json()
    assert not result['reports'] and result['errors'][0]['code'] == 'PRESENTATION_BLOCKED'
    assert len(client.get('/assessments').json()) == before
    assert any(row['event_type']=='报告呈现阻断' for row in client.app.state.service.db.list('audit_logs'))


def test_calendar_month_is_not_internship_duration():
    text = '后端开发实习：2025年6月至2025年12月，主导 Python API 开发'
    assert internship_result(text, PROFILE)['tier'] == 'insufficient'
    assert internship_result('后端开发实习：2025 年 6 月至 12 月，主导 Python API', PROFILE)['tier'] == 'insufficient'
    assert internship_result('后端开发实习 6 月至 8 月，主导 Python API', PROFILE)['tier'] == 'insufficient'
    assert internship_result('后端开发实习3-6个月，主导 Python API', PROFILE)['tier'] == 'insufficient'
    assert internship_result(text+'，明确时长6个月', PROFILE)['tier'] == 'B5'


def test_planned_outputs_and_core_project_name_do_not_prove_achievements_or_role():
    text = '主导交易项目，使用 Python 实现交易功能，目标日均 3000 单\n参与检索项目，使用 Python 实现检索功能'
    assert project_result(text, PROFILE)['tier'] != 'B5'
    text = '参与核心交易项目，使用 Python 实现交易功能，支撑日均 3000 单\n参与检索项目，使用 Python 实现检索功能'
    assert project_result(text, PROFILE)['tier'] != 'B5'
    assert project_result('课程项目：使用 Python，尚未实现统计功能', PROFILE)['tier'] == 'B2'


def test_malformed_alignment_metadata_is_rejected_without_server_error(client):
    for field, invalid in [('evidence_requirements', []), ('evidence_requirements', {'D1':None}), ('insufficient_anchors', None), ('general_disciplines', None), ('general_disciplines', [0]*8)]:
        cfg = copy.deepcopy(RUBRIC)
        cfg['version'] = 'invalid-metadata'
        cfg[field] = invalid
        assert client.put('/config/rubric',json=cfg).status_code == 400
