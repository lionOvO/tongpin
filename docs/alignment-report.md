| 上游条目 | 锚点原文／原文说明 | 证据要求 | 状态 | 文件与函数 | 边界与冲突说明 |
| --- | --- | --- | --- | --- | --- |
| §A.1 D1 B5 | 直接对口专业 + （辅修/双学位/行业证书 满足其一） | 专业名称 + 辅修或证书原文；独立证据要求：专业名称 + 辅修或证书原文 | 已实现 | app/deterministic.py:213（major_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.1 D1 B4 | 直接对口专业 | 专业名称原文；独立证据要求：专业名称原文 | 已实现 | app/deterministic.py:213（major_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.1 D1 B3 | 相邻相关专业（映射表标注"相邻"） | 专业名称原文；独立证据要求：专业名称原文 | 已实现 | app/deterministic.py:213（major_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.1 D1 B2 | 弱相关专业（映射表标注"弱相关"），或专业未填写但课程/技能线显示可迁移 | 专业或课程清单原文；独立证据要求：专业或课程清单原文 | 已实现 | app/deterministic.py:213（major_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.1 D1 B1 | 无关专业且无迁移证据 | —；独立证据要求：— | 已实现 | app/deterministic.py:213（major_result）；config/rubric.json | 证据要求原文为 —；仍需明确专业引用。映射未覆盖者不足，不自动当无关。 |
| §A.1 D1 insufficient | 整体无证据 → insufficient（EV-004，不入档、不按最低档计）。 | 无可定位的简历原文；按通用纪律第 2 条处理 | 已实现 | app/deterministic.py:213（major_result）；config/rubric.json | 来源：通用定级纪律第 2 条；上游没有独立不足档表时使用通用纪律，不伪造专属原文。 |
| §A.2 D2 B5 | 百分位 ≥ 90（或排名前 10%），或国家级奖学金 | 成绩/排名原文；独立证据要求：成绩/排名原文 | 已实现 | app/deterministic.py:84（gpa_tier）；config/rubric.json | 国奖适用本节前置限制：须有成绩依据，最多上调一档，不单独成档。 |
| §A.2 D2 B4 | 百分位 75-89（前 25%） | 同上；独立证据要求：成绩/排名原文 | 已实现 | app/deterministic.py:84（gpa_tier）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.2 D2 B3 | 百分位 60-74（前 50%） | 同上；独立证据要求：成绩/排名原文 | 已实现 | app/deterministic.py:84（gpa_tier）；config/rubric.json | 数值阈值与括号排名范围有冲突，执行明确数值阈值。 |
| §A.2 D2 B2 | 百分位 40-59（前 75%） | 同上；独立证据要求：成绩/排名原文 | 已实现 | app/deterministic.py:84（gpa_tier）；config/rubric.json | 数值阈值与括号排名范围有冲突，执行明确数值阈值。 |
| §A.2 D2 B1 | 百分位 < 40（后 25%） | 同上；独立证据要求：成绩/排名原文 | 已实现 | app/deterministic.py:84（gpa_tier）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.2 D2 insufficient | 成绩与排名均无 → insufficient（不得按最低档计）。 | 成绩与排名均无，奖学金不独立成档 | 已实现 | app/deterministic.py:84（gpa_tier）；config/rubric.json | 来源：§A.2 特殊处理；上游没有独立不足档表时使用通用纪律，不伪造专属原文。 |
| §A.3 D3 B5 | ≥2 个对口项目 + 至少 1 个担任主导/核心角色 + 至少 1 项量化成果 | 每个判断点独立引用；独立证据要求：每个判断点独立引用 | 已实现 | app/deterministic.py:252（project_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.3 D3 B4 | 1-2 个对口项目 + 核心/参与角色 + 成果可描述（无论文数字） | 同上；独立证据要求：每个判断点独立引用 | 已实现 | app/deterministic.py:252（project_result）；config/rubric.json | “无论文数字”是上游原文，照录；按明确角色与可描述成果处理。 |
| §A.3 D3 B3 | 项目方向部分相关（相邻领域），或方向对口但角色边缘 | 同上；独立证据要求：每个判断点独立引用 | 已实现 | app/deterministic.py:252（project_result）；config/rubric.json | 角色边缘原文可判；未给定相邻领域映射时保守不足，不猜测相邻关系。 |
| §A.3 D3 B2 | 仅课程设计/练手项目相关，无实质成果 | 同上；独立证据要求：每个判断点独立引用 | 已实现 | app/deterministic.py:252（project_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.3 D3 B1 | 无相关项目（整体信息完整前提下的"无"） | 判定说明；独立证据要求：判定说明 | 已实现 | app/deterministic.py:252（project_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.3 D3 insufficient | 整体无证据 → insufficient（EV-004，不入档、不按最低档计）。 | 无可定位的简历原文；按通用纪律第 2 条处理 | 已实现 | app/deterministic.py:252（project_result）；config/rubric.json | 来源：通用定级纪律第 2 条；上游没有独立不足档表时使用通用纪律，不伪造专属原文。 |
| §A.4 D4 B5 | L ≥ R+1；显著超出要求（可作团队补强项） | 每个等级须附 ≥1 条原文引用，无引用不得定级。；独立证据要求：每项硬性要求的 JD 原文与技能证据原文；按技能档位的下中位数汇总 | 已实现 | app/deterministic.py:186（d4_result）；config/rubric.json | 上游为 L-R 映射原文，维度按硬性技能下中位数产生；没有另造维度五档表。 |
| §A.4 D4 B4 | L = R；正好达标 | 每个等级须附 ≥1 条原文引用，无引用不得定级。；独立证据要求：每项硬性要求的 JD 原文与技能证据原文；按技能档位的下中位数汇总 | 已实现 | app/deterministic.py:186（d4_result）；config/rubric.json | 上游为 L-R 映射原文，维度按硬性技能下中位数产生；没有另造维度五档表。 |
| §A.4 D4 B3 | L = R−1；略欠，通常可短期上手弥补 | 每个等级须附 ≥1 条原文引用，无引用不得定级。；独立证据要求：每项硬性要求的 JD 原文与技能证据原文；按技能档位的下中位数汇总 | 已实现 | app/deterministic.py:186（d4_result）；config/rubric.json | 上游为 L-R 映射原文，维度按硬性技能下中位数产生；没有另造维度五档表。 |
| §A.4 D4 B2 | L = R−2；明显不足 | 每个等级须附 ≥1 条原文引用，无引用不得定级。；独立证据要求：每项硬性要求的 JD 原文与技能证据原文；按技能档位的下中位数汇总 | 已实现 | app/deterministic.py:186（d4_result）；config/rubric.json | 上游为 L-R 映射原文，维度按硬性技能下中位数产生；没有另造维度五档表。 |
| §A.4 D4 B1 | L ≤ R−3；不具备 | 每个等级须附 ≥1 条原文引用，无引用不得定级。；独立证据要求：每项硬性要求的 JD 原文与技能证据原文；按技能档位的下中位数汇总 | 已实现 | app/deterministic.py:186（d4_result）；config/rubric.json | 上游为 L-R 映射原文，维度按硬性技能下中位数产生；没有另造维度五档表。 |
| §A.4 D4 insufficient | L = L0；证据不足，不入档 | 未提及或仅见于自我评价套话 | 已实现 | app/deterministic.py:186（d4_result）；config/rubric.json | 来源：§A.4 L0 与第二步映射；上游没有独立不足档表时使用通用纪律，不伪造专属原文。 |
| §A.5 D5 B5 | 相关领域实习 ≥6 个月 + 承担核心职责 | 实习描述 + 时长；独立证据要求：实习描述 + 时长 | 已实现 | app/deterministic.py:284（internship_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.5 D5 B4 | 相关领域实习 3-6 个月 | 同上；独立证据要求：实习描述 + 时长 | 已实现 | app/deterministic.py:284（internship_result）；config/rubric.json | 超过六个月且未描述核心/边缘职责时，无完整适用锚点则保守不足。 |
| §A.5 D5 B3 | 相关实习 <3 个月，或时长够但职责边缘 | 同上；独立证据要求：实习描述 + 时长 | 已实现 | app/deterministic.py:284（internship_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.5 D5 B2 | 有实习但与岗位领域无关 | 同上；独立证据要求：实习描述 + 时长 | 已实现 | app/deterministic.py:284（internship_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.5 D5 B1 | 无任何实习经历（整体信息完整前提下的"无"，按事实落入 B1，非证据不足） | 判定说明；独立证据要求：判定说明 | 已实现 | app/deterministic.py:284（internship_result）；config/rubric.json | 逐档原文保留，理由记录锚点特征与引用。 |
| §A.5 D5 insufficient | 整体无证据 → insufficient（EV-004，不入档、不按最低档计）。 | 无可定位的简历原文；按通用纪律第 2 条处理 | 已实现 | app/deterministic.py:284（internship_result）；config/rubric.json | 来源：通用定级纪律第 2 条；上游没有独立不足档表时使用通用纪律，不伪造专属原文。 |
| §A.4 L4 精通 | 深度证据之一：架构设计 / 性能优化并量化 / 开源贡献 / 技术分享或教学 / 专利论文 | 正等级至少一条原文；每个特征与原文一一对应 | 已实现 | app/deterministic.py:143（evidence_skills）；app/agents.py:93（validate_evaluation） | 仅自评或未提及为 L0，未知技能不推断相邻技能。 |
| §A.4 L3 熟练 | 可验证产出：功能上线、指标改善、作品链接、被他人使用 | 正等级至少一条原文；每个特征与原文一一对应 | 已实现 | app/deterministic.py:143（evidence_skills）；app/agents.py:93（validate_evaluation） | 仅自评或未提及为 L0，未知技能不推断相邻技能。 |
| §A.4 L2 熟悉 | 有使用场景描述（课程/项目/实习中使用过，含任务与对象） | 正等级至少一条原文；每个特征与原文一一对应 | 已实现 | app/deterministic.py:143（evidence_skills）；app/agents.py:93（validate_evaluation） | 仅自评或未提及为 L0，未知技能不推断相邻技能。 |
| §A.4 L1 了解 | 仅出现技能名，无任何使用场景 | 正等级至少一条原文；每个特征与原文一一对应 | 已实现 | app/deterministic.py:143（evidence_skills）；app/agents.py:93（validate_evaluation） | 仅自评或未提及为 L0，未知技能不推断相邻技能。 |
| §A.4 L0 无证据 | 未提及或仅见于自我评价套话（→ insufficient，不入档） | 正等级至少一条原文；每个特征与原文一一对应 | 已实现 | app/deterministic.py:143（evidence_skills）；app/agents.py:93（validate_evaluation） | 仅自评或未提及为 L0，未知技能不推断相邻技能。 |
| §A.4 第二步 L ≥ R+1 | 显著超出要求（可作团队补强项） | 岗位要求原文与候选证据原文 | 已实现 | app/deterministic.py:13（skill_tier） | L0 不入档；无分数、无档内微调。 |
| §A.4 第二步 L = R | 正好达标 | 岗位要求原文与候选证据原文 | 已实现 | app/deterministic.py:13（skill_tier） | L0 不入档；无分数、无档内微调。 |
| §A.4 第二步 L = R−1 | 略欠，通常可短期上手弥补 | 岗位要求原文与候选证据原文 | 已实现 | app/deterministic.py:13（skill_tier） | L0 不入档；无分数、无档内微调。 |
| §A.4 第二步 L = R−2 | 明显不足 | 岗位要求原文与候选证据原文 | 已实现 | app/deterministic.py:13（skill_tier） | L0 不入档；无分数、无档内微调。 |
| §A.4 第二步 L ≤ R−3 | 不具备 | 岗位要求原文与候选证据原文 | 已实现 | app/deterministic.py:13（skill_tier） | L0 不入档；无分数、无档内微调。 |
| §A.4 第二步 L = L0 | 证据不足，不入档 | 岗位要求原文与候选证据原文 | 已实现 | app/deterministic.py:13（skill_tier） | L0 不入档；无分数、无档内微调。 |

| 通用纪律（逐条原文） | 状态 | 可执行断言名称 |
| --- | --- | --- |
| 1. **只定档、不取分**：Agent 必须输出命中的档位标识（如 `B4`）；**不设档内取分、不设 ±微调**。若证据同时部分满足相邻两档的锚点特征 → 输出**档位区间**（如 `B3–B4`），并写明跨档依据。 | 已实现 | tests/test_alignment.py::test_discipline_1_ordinal_only_schema_rejects_fractional_and_micro_tiers；test_fractional_skill_level_is_rejected_in_code；test_agent_interval_requires_cross_band_basis |
| 2. **无证据不定档**：任一锚点特征若无简历原文支撑，不得计入该档；整体无证据 → `insufficient`（EV-004，**不入档、不按最低档计**）。 | 已实现 | tests/test_alignment.py::test_discipline_2_no_quote_means_insufficient_not_lowest |
| 3. **等级不得拔高**：原文写"了解/熟悉/精通"必须按原文等级判定，Agent 不得推断为更高等级（MT-002 负向验收）。 | 已实现 | tests/test_alignment.py::test_discipline_3_no_level_inflation_and_jd_default_one；test_agent_rejects_unquoted_features_and_keyword_based_level_inflation |
| 4. **敏感属性禁用**：性别、年龄、民族、婚育、政治面貌、院校层次（985/211/双一流）不得作为任何档位判据（AU-001）。 | 已实现 | tests/test_alignment.py::test_discipline_4_all_sensitive_attributes_excluded_from_rating |
| 5. **理由三要素**：每条维度理由 = 命中档位 + 锚点特征命中情况 + 证据引用；输出区间时另附跨档依据。 | 已实现 | tests/test_alignment.py::test_discipline_5_every_reason_contains_tier_features_and_source_quotes |
| 6. **区分"没有"与"未写"**：简历明确未提及某类经历且整体信息完整 → 按"无该类经历"落 **B1**；简历信息严重不完整（如仅半页）→ 按证据不足处理（`insufficient`）。此判定须在理由中说明。 | 已实现 | tests/test_alignment.py::test_discipline_6_explicit_absence_vs_unmentioned_or_incomplete |
| 7. **表述纪律（v0.9.5 新增）**：系统是**证据整理者，不是能力认定者**——维度理由、摘要句与清单条目一律用"简历显示 / 简历描述 / 简历自评"陈述证据，**禁用"具备 / 掌握 / 精通 / 确实 / 证实"等断言词**；档位表示"简历证据所支持的水平"，不得表述为对个人能力的认定。**"验证/追问"类提示仅允许出现在报告的面试准备区与页脚**，不得进入首屏结构视图、档位表、排序页与人才端（详见 PRD §6.3 结论表述纪律）。 | 已实现 | tests/test_alignment.py::test_discipline_7_evidence_voice_and_candidate_interview_boundary |
| 8. **锚点可双向引用（v0.9.6 新增）**：每个档位的锚点描述**必须可被独立引用**——企业侧用于定档（EV-001），求职者侧用于量规差距说明（TM-003）。因此锚点描述须**自足**（不依赖上下文即可读懂"这一档要求什么"），且**不得内嵌分数、不得引用其他档位的表述**。 | 已实现 | tests/test_alignment.py::test_discipline_8_independent_anchors_original_and_self_contained_requirements；test_pack_rejects_incomplete_anchor_evidence_or_cross_reference |

| PRD 红线（逐条原文） | 现状与必要裁定 | 证据位置（文件:行号） |
| --- | --- | --- |
| 1. 不做强制撮合、不做自动决策：允许基于双方主动填报字段输出匹配建议；建议非强制，判断权归用户；不做自动淘汰、不做自动排序晋级 | 已满足：偏好共享须双方主动同意；审核后的比较不触发自动晋级、淘汰或过滤。 | app/service.py:140（run_match）；app/service.py:234（review）；app/service.py:271（ranking） |
| 2. 不生成企业介绍、企业文化叙述、雇主品牌内容：企业自行填写的氛围描述可录入并展示，但系统不代写、不润色、不评判其好坏 | 已满足：氛围仅原样保存企业自填文本，独立标为企业自行填写，无生成/润色接口。 | app/service.py:112（submit_preference）；web/pages.py:90（preferences_page）；web/pages.py:8（matches_page） |
| 3. 不从公开渠道抓取公司信息生成企业画像 | 已满足：岗位仅来源于输入/合成种子，无公开公司抓取或企业画像生成调用。 | app/service.py:63（create_job）；app/agents.py:61（jd） |
| 4. 不代写 JD、不提供"改写后的岗位描述" | 已满足：仅画像解析与定位原文诊断，没有改写 JD 输出。 | app/agents.py:61（jd）；app/service.py:329（diagnose） |
| 5. 不抓取招聘平台岗位数据；亦不通过第三方"聚合 API"间接获取（例外：24365 等面向公众的公开浏览接口匿名可取，不属此列） | 已满足：岗位集合仅用户输入和合成示例，无招聘平台或第三方聚合数据抓取。 | app/service.py:63（create_job）；app/service.py:359（compare） |
| 6. 不承诺面试通过率、录用概率；不做薪资预测；匹配结果不得使用百分比与精确分数，只出档位（高/中/低/无法判断） | 已满足：偏好结果仅四态与依据，无录用/通过概率或薪资预测；业务页禁数字百分比。 | app/deterministic.py:43（match_preferences）；app/deterministic.py:312（presentation_violations） |
| 7. 不推荐课程、书籍、学习路径、技术路线 | 已满足：差距说明读取同一量规原文，不生成课程/资源/学习顺序。 | app/service.py:343（fit）；web/components.py:67（report_view） |
| 8. 不做个体级录用数据展示与候选人排名（含"击败 X%"式对比） | 已按用户裁定实现：人才端不披露他人录用画像、竞争排名；保留 EV-005 的企业已确认报告比较。原文冲突已在 implementation-decisions.md 明确，未静默删除原功能。 | app/service.py:271（ranking）；app/service.py:379（build_benchmark）；app/service.py:343（fit） |
| 9. 披露纪律对两侧一致：聚合优先、k-匿名 ≥20（服务层强制）、不回传竞争信息、敏感属性零出现；示例企业与合成岗位必须 `data_origin=synthetic` 显式标注 | 已满足结构化披露：基准服务强制每项样本 ≥20，企业/人才 owner 隔离，偏好无敏感维度，定级输入脱敏，合成示例标记来源；未开放个体录用数据。 | app/service.py:379（build_benchmark）；app/service.py:43（owned）；app/security.py:4（redact）；web/components.py:62（mode_caption） |
| 10. 表述纪律适用于标准侧与求职者侧：只陈述事实 + 定位原文，不评价企业、不做 JD 好坏总评、不做能力断言 | 已满足：诊断定位原文并只陈述可确定问题；定级理由以简历描述表述，引用保留前缀，不作企业好坏总评。 | app/service.py:329（diagnose）；app/deterministic.py:72（dimension_result）；web/components.py:67（report_view） |
| 11. 求职者端不生成任何可直接使用的文案 | 已满足：人才端输出仅事实、对照和量规原文，无可直接粘贴的简历或 JD 文案。 | app/service.py:343（fit）；app/service.py:359（compare） |
| 12. 匹配结论必须可展开到双方原文：无依据不得出档位；允许并鼓励输出"无法判断" | 已满足：同一记录保存两侧真实填报引用；缺填报为无法判断，未填报状态不伪装原文。 | app/deterministic.py:43（match_preferences）；web/pages.py:8（matches_page） |
| 13. 两侧填报字段口径必须同源：偏好维度表为唯一版本化配置（走 EV-007 版本纪律），两侧不得各用一套维度 | 已满足：唯一偏好维度版本；两侧版本不同或与当前配置不符拒绝匹配；历史快照保留。 | app/deterministic.py:43（match_preferences）；app/service.py:112（submit_preference）；app/service.py:162（visible_matches） |
| 14. 档位不得被用作筛选门槛（v2.3 新增）：①企业端不出现"档位/评级"字样，一律以"与岗位要求的差距"表述；②系统不设任何阈值语义（禁"合格线/达标线/分数线/淘汰线"）；③AI 偏差提示须在企业端首屏与页脚默认可见；④两端底层判定同源、措辞区分（企业端=差距，求职者端=档位） | 已按用户裁定实现：企业业务结果/名单导出禁 B1–B5、档位、评级、匹配度及阈值；固定否定句例外；首屏与页脚各含双提示且可见；记录同源仅渲染分措辞。内部配置编辑器与标准包为用户确认的维护例外。生成/导出遇违规写审计并阻断，旧报告渲染遇违规显示兜底。 | app/deterministic.py:312（presentation_violations）；app/deterministic.py:320（rationale_for_display）；app/service.py:170（evaluate）；app/service.py:419（csv_export）；web/components.py:26（notice）；web/components.py:67（report_view）；web/pages.py:8（matches_page）；web/pages.py:270（ranking_page）；web/pages.py:420（config_page） |
