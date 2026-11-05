import json
import re
from pathlib import Path
from .errors import DomainError

SKILLS = ["Python", "Java", "Go", "JavaScript", "TypeScript", "React", "Vue", "FastAPI", "Spring", "MySQL", "PostgreSQL", "Redis", "Docker", "Kafka", "Kubernetes", "Linux", "PyTorch", "SQL", "Git"]


def mentions(text, skill):
    return bool(re.search(r"(?<![A-Za-z])" + re.escape(skill) + r"(?![A-Za-z])", text, re.I))


def skill_tier(level, required):
    if type(level) is not int or type(required) is not int or not 0 <= level <= 4 or not 1 <= required <= 4:
        raise DomainError('SKILL_LEVEL_INVALID', '技能等级与要求必须为有效的整数行为等级', 422)
    if level == 0:
        return "insufficient"
    return "B" + str(max(1, min(5, 4 + level - required)))


def median_tier(tiers):
    values = sorted(int(t[1]) for t in tiers if t != "insufficient")
    return "B" + str(values[(len(values)-1)//2]) if values else "insufficient"


def sort_key(dimensions, priorities):
    enabled = priorities["enabled"]
    by_id = {d["dimension_id"]: d for d in dimensions}
    order = sorted(enabled, key=lambda d: (priorities["priorities"][d], d))
    def lower(d):
        row = by_id.get(d, {})
        if row.get("tier") == "insufficient" or not row.get("evidence"):
            return 0  # Internal absence sentinel, never shown as B1.
        interval = row.get("tier_range") or [row["tier"]]
        return min(int(v[1]) for v in interval)
    return {"qualified_dims":sum(lower(d)>=4 for d in enabled), "ordered_tiers":[lower(d) for d in order], "evidenced_dims":sum(lower(d)>0 for d in enabled)}


def key_tuple(key):
    return (key["qualified_dims"], *key["ordered_tiers"], key["evidenced_dims"])


def match_preferences(ent, cand, config):
    if ent["dimension_version"] != cand["dimension_version"]:
        raise DomainError("DIMENSION_VERSION_MISMATCH", "维度口径版本不一致，请双方重新填写")
    if ent["dimension_version"] != config["version"]:
        raise DomainError("DIMENSION_VERSION_EXPIRED", "当前偏好维度已更新，请双方重新填写")
    rows = []
    for dim in config["dimensions"]:
        id = dim["id"]
        a, b = ent["dimensions"].get(id), cand["dimensions"].get(id)
        distance, reason = None, ""
        if not a or not b:
            tier, reason = "无法判断", "一方未填报或选择不愿透露"
        elif a == b:
            tier, distance = "高", 0
        elif id == "direction":
            tier = "中" if any({a,b} == set(pair) for pair in config.get("related_directions", [])) else "低"
        else:
            distance = abs(dim["options"].index(a) - dim["options"].index(b))
            tier = "中" if distance == 1 else "低"
        rows.append({"dimension_id":id, "name":dim["name"], "required":dim["required"], "tier":tier, "distance":distance, "ent_quote":a or "未填报", "cand_quote":b or "未填报", "unmatched_reason":reason})
    required = [r["tier"] for r in rows if r["required"]]
    overall = "无法判断" if "无法判断" in required else "低" if "低" in required else "中" if "中" in required else "高"
    return {"dimension_results":rows,"overall_tier":overall,"engine_version":"preference-engine-1.0","dimension_version":config["version"],"basis_statement":"整体以三项必填偏好判定；缺任一项依据则无法判断，其次依次检查明显差异、相邻差异和相符。选填项单独呈现。"}


def rating_config():
    return json.loads((Path(__file__).resolve().parents[1] / 'config/rubric.json').read_text(encoding='utf-8'))


def dimension_result(dimension, tier, evidence, features, interval=None, cross_band_reason=''):
    evidence = list(dict.fromkeys(evidence))
    if not evidence:
        tier, interval = 'insufficient', []
    reason = f'简历描述支持 {tier}；锚点特征：' + '；'.join(features)
    reason += '；简历写明：' + (' / '.join('「' + q + '」' for q in evidence) if evidence else '无可定位原文')
    if interval:
        reason += '；跨档依据：' + cross_band_reason
    return {'dimension_id': dimension, 'tier': tier, 'tier_range': interval or [], 'evidence': evidence,
            'rationale': reason, 'anchor_hits': features, 'cross_band_reason': cross_band_reason}


def gpa_tier(text, rubric=None):
    rubric = rubric or rating_config()
    rank = re.search(r"排名\s*[:：]?\s*(\d+)\s*[/／]\s*(\d+)", text)
    top = re.search(r'排名\s*前\s*(\d+(?:\.\d+)?)\s*[%％]', text)
    percentile = re.search(r'百分位\s*[:：]?\s*(\d+(?:\.\d+)?)', text)
    note = ""
    if rank and int(rank[2]) > 0 and 0 < int(rank[1]) <= int(rank[2]):
        value, quote = 100*(1-int(rank[1])/int(rank[2])), rank[0]
        note = "按明确提供的年级排名换算"
    elif top and 0 <= float(top[1]) <= 100:
        value, quote, note = 100-float(top[1]), top[0], '按排名优先规则换算'
    elif percentile and 0 <= float(percentile[1]) <= 100:
        value, quote, note = float(percentile[1]), percentile[0], '采用原文明确给出的百分位'
    else:
        gpa = re.search(r"GPA\s*[:：]?\s*(\d+(?:\.\d+)?)(?:\s*[/／]\s*(\d+(?:\.\d+)?))?", text, re.I)
        if not gpa:
            return None
        denominator = float(gpa[2]) if gpa[2] else 5.0
        if denominator <= 0 or not 0 <= float(gpa[1]) <= denominator:
            return None
        value, quote = float(gpa[1])/denominator*100, gpa[0]
        note = '按满分比例换算，非统计百分位' + ('；满分未明确，按 5.0 保守换算，换算待确认' if not gpa[2] else '')
    thresholds = rubric['d2_percentile_thresholds']
    tier = next(t for t in ('B5', 'B4', 'B3', 'B2', 'B1') if value >= thresholds[t])
    award = next((s for s in re.split(r'[\n。；;]', text) if re.search(r'(?:获得|获评|荣获|获).*(?:奖学金|荣誉)|国家(?:级)?奖学金', s) and not re.search(r'未获|没有|申请|争取', s)), None)
    features = [note, '成绩数值命中量规的数值区间']
    quotes = [quote]
    if award:
        tier = 'B' + str(min(5, int(tier[1]) + 1))
        features.append('奖学金/荣誉仅在已有成绩依据上最多上调一档')
        quotes.append(award.strip())
    return {**dimension_result('D2', tier, quotes, features), 'normalized_value': round(value, 2)}


def parse_jd(text):
    if not re.search(r"岗位|职责|要求|任职|工程师|开发|实习|招聘", text):
        raise DomainError("NOT_A_JD", "未识别到岗位职责或任职要求，请补充完整 JD 或手工录入画像")
    clauses = [s.strip() for s in re.split(r"[\n。；;]", text) if s.strip()]
    requirements = []
    for skill in SKILLS:
        quotes = [s for s in clauses if mentions(s, skill)]
        # A title or tech-stack mention must not hide a later explicit requirement.
        def requirement_context(s):
            prefix = s[:re.search(re.escape(skill), s, re.I).start()]
            return (bool(re.search(r'任职|要求|必备', s)) and not bool(re.search(r'加分|优先|额外', s)), bool(re.search(r'精通|熟练|熟悉|了解', prefix)), usage_scene(s, skill))
        quote = max(quotes, key=requirement_context) if quotes else None
        if quote:
            # Bind the closest proficiency word to this skill, not every word in a JD clause.
            prefix = quote[:re.search(re.escape(skill), quote, re.I).start()]
            declared = re.findall(r'精通|熟练|熟悉|了解', prefix)
            level = {'精通':4, '熟练':3, '熟悉':2, '了解':1}[declared[-1]] if declared else (2 if usage_scene(quote, skill) else 1)
            requirements.append({"skill":skill,"required_level":level,"quote":quote,"hard":not bool(re.search(r"加分|优先|额外",quote))})
    direction = ("全栈开发" if re.search(r"全栈", text) else "数据与算法" if re.search(r"算法|机器学习|数据(?:分析|应用|科学|工程)", text) else "测试与质量" if re.search(r"测试工程师|质量工程师|软件测试", text) else "基础设施" if re.search(r"基础设施|运维工程师|\bSRE\b", text, re.I) else "前端开发" if re.search(r"前端", text) and not re.search(r"后端", text) else "后端开发")
    edu = next((e for e in ["博士","硕士","本科","大专"] if e in text),None)
    return {"requirements":requirements,"direction":direction,"education":edu}


def usage_scene(quote, skill):
    """A named tool plus an actual action and object; verbs alone are insufficient."""
    if not mentions(quote, skill):
        return False
    return bool(re.search(r'(?:实现|开发|构建|部署|设计|优化|编写|完成|负责|处理|训练|分析)\s*[^，,、/\s。；]{2,}', quote) and re.search(r'项目|课程|实习|平台|系统|接口|服务|功能|缓存|组件|数据|文档|任务|模型|应用|架构|作品|工具|容器', quote))


def evidence_skills(text, skills=None):
    clauses = [s.strip() for s in re.split(r"[\n。；;]", text) if s.strip()]
    result = []
    for skill in (SKILLS if skills is None else skills):
        quotes = [s for s in clauses if mentions(s,skill)]
        if not quotes:
            continue
        candidates = []
        for quote in quotes:
            if re.search(r'计划|希望|学习目标|尚未|未使用|未实现|没有使用', quote):
                continue
            advanced = bool(re.search(r'(?:主讲|讲授|开展|完成).*(?:技术分享|教学)|(?:发表|录用).*论文|(?:获授权|授权).*专利|开源.*(?:合并|被接受)', quote))
            scene = usage_scene(quote, skill) or advanced
            if not scene:
                if re.search(r'自评|自我评价|精通|熟练|熟悉|了解|掌握|擅长', quote):
                    continue
                candidates.append((1, '仅出现技能名，无任何使用场景', quote))
                continue
            candidates.append((2, '使用场景包含任务与对象', quote))
            # Require an accomplished output tied to the scene, not the words “上线/用户/ms”.
            if re.search(r'(?:功能|服务|系统|平台|应用|项目|组件).*(?:已上线|上线运行|上线并|上线，)|(?:已|完成|成功).*(?:上线|发布)', quote):
                candidates.append((3, '可验证产出：功能上线', quote))
            if re.search(r'(?:被|供).*\d*\s*(?:位|名|个)?.*(?:用户|同学|团队|他人).*(?:使用|采用)|支撑日均\s*\d+\s*(?:单|次|用户)', quote):
                candidates.append((3, '可验证产出：被他人使用', quote))
            if re.search(r'(?:降低|提升|改善|减少|提高|缩短).*(?:\d+\s*(?:%|％|ms|毫秒|秒)|从\s*\d+.*(?:至|到)\s*\d+)', quote):
                candidates.append((3, '可验证产出：指标改善', quote))
            if re.search(r'https?://[^\s]+', quote) and re.search(r'作品|项目|仓库|演示', quote):
                candidates.append((3, '可验证产出：作品链接', quote))
            if re.search(r'(?:设计|重构|完成|负责|主导).*架构|架构设计.*(?:实现|落地|完成)', quote):
                candidates.append((4, '深度证据：架构设计', quote))
            if re.search(r'性能|延迟|吞吐|响应|接口', quote) and re.search(r'优化|降低|提升|缩短', quote) and re.search(r'从\s*\d+.*(?:至|到)\s*\d+|(?:降低|提升|缩短).*\d+\s*(?:%|％|ms|毫秒)', quote):
                candidates.append((4, '深度证据：性能优化并量化', quote))
            if re.search(r'开源.*(?:合并|被接受|贡献.*(?:PR|提交))|(?:PR|提交).*合并', quote):
                candidates.append((4, '深度证据：开源贡献', quote))
            if re.search(r'(?:开展|完成|主讲|组织|讲授).*(?:技术分享|教学|培训|课程)|(?:发表|获授权|授权).*专利|(?:发表|录用).*论文', quote):
                candidates.append((4, '深度证据：技术分享或教学 / 专利论文', quote))
        level = max((item[0] for item in candidates), default=0)
        hits = [{'feature': feature, 'quote': quote} for value, feature, quote in candidates if value == level]
        self_report = next((word for word in ('精通', '熟练', '熟悉', '了解') if any(word in s for s in quotes)), '')
        result.append({'skill':skill, 'evidence_level':level, 'evidence':list(dict.fromkeys(h['quote'] for h in hits)), 'self_reported':self_report, 'anchor_hits':hits})
    return result


def d4_result(skills):
    hard = [s for s in skills if s['hard']]
    tiers = [s['tier'] for s in hard]
    known = [int(t[1]) for t in tiers if t != 'insufficient']
    missing = len(tiers) - len(known)
    quotes = [q for s in hard for q in s['evidence']]
    if not known:
        return dimension_result('D4', 'insufficient', [], ['硬性要求技能均无证据，或未提供硬性技能要求'])
    if not missing:
        return dimension_result('D4', median_tier(tiers), quotes, ['只使用硬性要求技能；偶数项取靠低者的序数中位数'])
    index = (len(tiers) - 1) // 2
    # Unknowns remain unknown. Endpoints are possible medians, never assigned skill levels.
    possible = [[int(skill_tier(level, s['required_level'])[1]) for level in range(1, 5)] for s in hard if s['tier']=='insufficient']
    low = sorted(known + [min(values) for values in possible])[index]
    high = sorted(known + [max(values) for values in possible])[index]
    interval = ['B' + str(low), 'B' + str(high)]
    basis = f'部分证据不足：{missing} 项硬性技能未参与事实定级；依据各自岗位要求与可能的 L1–L4 推导下中位数端点；已知技能保持原结论，未知不记作低能力'
    if low == high:
        basis += '；可能范围端点相同，不能伪造更宽区间'
    return dimension_result('D4', interval[0], quotes, ['硬性技能下中位数；加分项不参与', '部分证据不足'], interval, basis)


def complete_basic_text(text):
    # User-confirmed on 2026-10-11; absence alone never establishes completeness.
    return bool(re.search(r'专业|学历|本科|硕士|博士|大专', text) and re.search(r'技能|使用|开发|实现', text))


def major_result(text, profile, mapping):
    direction = profile['direction']
    domains = mapping.get('domains', [])
    candidates = [d for d in domains if d['domain'] == direction]
    if not candidates:
        tokens = [('后端|前端|全栈|移动|软件开发', '互联网软件开发'), ('人工智能|算法', '人工智能/算法工程'),
                  ('数据工程|数据分析', '数据工程/数据分析'), ('测试|质量', '测试/质量保障'),
                  ('运维|基础设施|SRE', '运维/基础设施/SRE'), ('信息安全|网络安全', '信息安全'),
                  ('金融科技', '金融科技'), ('ERP|CRM|信息化', '企业软件/信息化')]
        candidates = [d for pattern, name in tokens if re.search(pattern, direction, re.I) for d in domains if d['domain'].startswith(name)]
    if len(candidates) != 1:
        return dimension_result('D1', 'insufficient', [], ['岗位主领域未能唯一对应专业映射表'])
    domain = candidates[0]
    clauses = [s.strip() for s in re.split(r'[\n。；;]', text) if s.strip()]
    lines = [s for s in clauses if re.search(r'专业|学历|本科|硕士|博士', s)]
    aliases = mapping.get('alias', {})
    for line in lines:
        normalized = line
        for alias in sorted(aliases, key=len, reverse=True):
            if aliases[alias] not in normalized:
                normalized = normalized.replace(alias, aliases[alias])
        for category, tier in [('direct', 'B4'), ('adjacent', 'B3'), ('weak', 'B2')]:
            if any(name in normalized for name in domain[category]):
                quotes = [line]
                features = [f'专业名称命中专业-领域映射表的 {category} 类别；参照领域：{domain["domain"]}']
                extra = next((s for s in clauses if re.search(r'辅修|双学位|行业证书', s) and not re.search(r'无|未|计划', s)), None)
                if tier == 'B4' and extra:
                    tier = 'B5'; quotes.append(extra); features.append('辅修/双学位/行业证书满足其一')
                return dimension_result('D1', tier, quotes, features)
    transferable = [s for s in clauses if any(usage_scene(s, r['skill']) for r in profile['requirements'])]
    if not lines and transferable:
        return dimension_result('D1', 'B2', transferable[:2], ['专业未填写，但课程/技能使用场景显示可迁移'])
    # Only an explicitly identified major covered elsewhere in the reviewed map can be contrasted.
    known_names = {name for d in domains for key in ('direct', 'adjacent', 'weak') for name in d[key]}
    if lines and not transferable and any(name in line for name in known_names for line in lines):
        return dimension_result('D1', 'B1', lines[:1], ['专业在当前领域的三类映射中均未命中，且未见迁移证据'])
    # Missing or unmapped majors remain insufficient, never inferred as unrelated.
    return dimension_result('D1', 'insufficient', [], ['专业信息缺失或未在已评审映射表覆盖'])


def project_result(text, profile):
    clauses = [s.strip() for s in re.split(r'[\n。；;]', text) if s.strip()]
    records = [s for s in clauses if re.search(r'项目|作品', s) and not re.search(r'无.*项目|没有.*项目|未.*项目|计划.*项目', s)]
    related = [s for s in records if any(mentions(s, r['skill']) for r in profile['requirements']) or profile['direction'] in s]
    absent = next((s for s in clauses if re.search(r'无相关项目|无任何项目|没有相关项目|项目经历\s*[:：]\s*无', s)), None)
    if not related:
        if absent and complete_basic_text(text) and not records:
            return dimension_result('D3', 'B1', [absent], ['明确说明无相关项目，教育与技能等基本描述存在；非仅未提及'])
        # Not mentioning a project is not an explicit statement of having none.
        return dimension_result('D3', 'insufficient', [], ['未能定位与岗位相关的项目描述'])
    accomplished = [s for s in related if not re.search(r'未实现|未完成|未上线|没有上线|计划|目标|预计|希望', s)]
    core = [s for s in accomplished if re.search(r'主导|担任.*核心|核心(?:成员|角色|职责)|负责.*核心', s)]
    outcomes = [s for s in accomplished if re.search(r'(?:实现|完成|构建|开发).{2,}(?:功能|平台|系统|服务|接口|工具|应用|缓存|统计)|上线|被.*使用|https?://', s)]
    quantified = [s for s in accomplished if re.search(r'(?:支撑|处理|达到|降低|提升|优化|改善|实现|完成).*\d+\s*(?:单|次|用户|位|ms|毫秒|%|％|star)|(?:已|完成).*上线|被.*使用', s, re.I)]
    def project_identity(line):
        match = re.search(r'(?:主导|独立负责|独立开发|参与|负责|开发)?([\w\u4e00-\u9fff]{2,25}项目)', line)
        if match:
            return re.sub(r'^(?:主导|独立负责|独立开发|参与|负责|开发)', '', match[1])
        return line  # No named grouping is available; never merge different explicit descriptions.
    if len({project_identity(line) for line in related}) >= 2 and core and quantified:
        return dimension_result('D3', 'B5', related, ['至少两个对口项目（每条独立项目描述）', '至少一个主导/核心角色', '至少一项量化或可验证产出'])
    edge = [s for s in related if re.search(r'边缘|协助|旁听', s)]
    if edge and outcomes:
        return dimension_result('D3', 'B3', related, ['方向对口但角色边缘；成果可描述'], ['B3', 'B4'], '方向与成果描述支持相符，角色边缘支持略欠；两类特征分别有原文')
    if outcomes and any(re.search(r'核心|主导|参与|负责|独立', s) for s in related):
        return dimension_result('D3', 'B4', related, ['对口项目有核心/参与角色，成果可描述'])
    if all(re.search(r'课程|练手|课程设计', s) for s in related) and not outcomes:
        return dimension_result('D3', 'B2', related, ['仅课程设计/练手项目相关，未描述实质成果'])
    if edge:
        return dimension_result('D3', 'B3', edge, ['方向对口但角色边缘'])
    return dimension_result('D3', 'insufficient', [], ['项目描述缺少角色或成果等必要锚点特征'])


def internship_result(text, profile):
    clauses = [s.strip() for s in re.split(r'[\n。；;]', text) if s.strip()]
    absent = next((s for s in clauses if re.search(r'无(?:任何)?实习(?:经历)?|没有实习经历|实习经历\s*[:：]\s*无', s)), None)
    records = [s for s in clauses if '实习' in s and s != absent]
    if absent and not records and complete_basic_text(text):
        return dimension_result('D5', 'B1', [absent], ['明确无实习经历，教育与技能等基本描述存在；按事实处理'])
    related = [s for s in records if profile['direction'].replace('开发', '') in s or any(mentions(s, r['skill']) for r in profile['requirements'])]
    outcomes = []
    for line in related:
        month = next((match for match in re.finditer(r'(?<![\d年])(\d+(?:\.\d+)?)\s*(?:个)?月', line)
                      if ('个' in match[0] or re.search(r'(?:时长|持续|累计|共|实习)\s*$', line[:match.start()]))
                      and not re.search(r'[-—–~至到/]\s*$', line[:match.start()])
                      and not re.match(r'\s*[-—–~至到/]\s*\d+', line[match.end():])), None)
        if not month:
            continue
        duration = float(month[1])
        core, edge = bool(re.search(r'主导|核心(?:职责|成员|角色)|承担.*核心|负责.*核心', line)), bool(re.search(r'边缘|协助', line))
        tier = 'B5' if duration >= 6 and core else 'B3' if duration < 3 or edge else 'B4' if duration <= 6 else None
        if tier:
            outcomes.append(dimension_result('D5', tier, [line], ['相关领域实习', f'原文时长 {duration:g} 个月', '核心职责' if core else '职责边缘' if edge else '实习描述与时长']))
    if outcomes:
        return max(outcomes, key=lambda d: int(d['tier'][1]))
    unrelated = [s for s in records if re.search(r'与.*(?:岗位|方向|领域).*(?:无关|不相关)|不相关.*实习', s)]
    if unrelated:
        return dimension_result('D5', 'B2', unrelated, ['原文明示实习与岗位领域无关'])
    # Never fill missing internship duration or responsibilities by inference.
    return dimension_result('D5', 'insufficient', [], ['实习经历的相关性、时长或职责描述不足'])


def presentation_violations(text, config, enterprise=True):
    value = str(text)
    # Permit only this exact mandatory negative phrase, never a user supplied allow-list.
    value = value.replace('系统不设合格线', '')
    terms = config['banned_terms'] + (config['enterprise_banned_terms'] if enterprise else [])
    return [term for term in terms if term in value] + (['数字百分比'] if enterprise and re.search(r'\d\s*[%％]', value) else [])


def rationale_for_display(value, config, candidate=False, job=''):
    if not candidate:
        value = re.sub(r'\bB[1-5]\b', lambda m: config['tier_labels'][m[0]], value)
    else:
        value = re.sub(r'\bB[1-5]\b', lambda m: m[0] + f'（相对 {job}）', value)
    # Per-item confirmation language belongs in interview preparation, not in the evidence table.
    return value.replace('，换算待确认', '').replace('；换算待确认', '')
