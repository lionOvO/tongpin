/** Public synthetic examples, adapted from the three supplied fictional resumes.
 * No contacts, private uploads, account IDs, scoring or live business operations.
 */
export interface StoryEvidence { label: string; skill: string; project: string; requirement: string; quote: string; relation: string; question: string }
export interface StoryPerson {
  id: string; name: string; initials: string; role: string; shortRole: string; work: string;
  company: string; job: string; editEvidence: number; before: string; after: string; suggestion: string;
  expectation: string; teamExpectation: string; opening: string;
  evidence: StoryEvidence[];
}
export const storyPeople: StoryPerson[] = [
  {
    id: 'data', name: '吴思琪', initials: '吴', role: '数据分析', shortRole: '数据分析', work: '业务数据整理、指标分析与报表输出',
    company: '紫杉数据', job: '业务数据分析师', editEvidence: 1,
    before: '搭建销售指标看板，监控收入与转化趋势。',
    after: '围绕收入与转化趋势搭建销售指标看板，用于日常业务监控。',
    suggestion: '先说明看板关注的业务问题，再交代做了什么。保留“收入与转化”这两个明确指标；具体效果可以在补充事实后再写。',
    expectation: '参与业务讨论，持续积累分析方法', teamExpectation: '一起定义指标，让分析走进日常决策',
    opening: '可以聊聊你在销售看板中怎样定义收入和转化指标吗？',
    evidence: [
      { label: '数据处理', skill: 'SQL · Python', project: '业务数据分析', requirement: '提取与整理业务数据', quote: '使用 SQL 提取数据，结合 Excel 与 Python 进行分析', relation: '可参与业务数据提取与分析；数据口径和质量处理方式可进一步了解。', question: '遇到不同来源的数据口径不一致时，你怎样核对？' },
      { label: '指标可视化', skill: '销售看板', project: '销售数据分析看板', requirement: '搭建经营指标看板', quote: '搭建销售指标看板，监控收入与转化趋势', relation: '销售看板经历与经营指标展示有关，可继续了解指标定义及使用场景。', question: '收入与转化指标如何定义？看板主要由谁使用？' },
      { label: '用户洞察', skill: '用户分层', project: '用户画像分析', requirement: '为运营提供分析支持', quote: '完成用户分层与行为分析，支持运营策略优化', relation: '可参与用户分析与运营讨论；分层方法和具体建议值得在面试中展开。', question: '用户分层用了哪些信息？如何把分析转成运营建议？' },
    ],
  },
  {
    id: 'testing', name: '赵启航', initials: '赵', role: '测试开发工程师', shortRole: '测试开发', work: '自动化测试脚本、接口测试与测试报告分析',
    company: '紫杉软件', job: '测试开发工程师', editEvidence: 1,
    before: '搭建接口自动化测试框架，支持多环境配置。',
    after: '搭建支持多环境配置的接口自动化测试框架，用于接口测试。',
    suggestion: '把框架的用途和明确支持的功能放在一起。原文已写明多环境配置，可以保留；覆盖规模与效率变化需要补充事实后再写。',
    expectation: '参与测试工具建设，和开发一起定位问题', teamExpectation: '维护自动化测试，关注多环境下的交付质量',
    opening: '想了解一下，你的测试框架如何管理不同环境的配置？',
    evidence: [
      { label: '测试工具', skill: 'Python · Pytest', project: '自动化测试工具', requirement: '开发与维护自动化脚本', quote: '设计并维护自动化测试脚本，提升回归测试效率', relation: '可参与自动化脚本维护与回归测试；脚本边界及效率衡量方式可进一步了解。', question: '你如何组织测试用例，避免脚本之间相互依赖？' },
      { label: '接口自动化', skill: '接口 · 多环境', project: '自动化测试平台', requirement: '维护多环境接口测试', quote: '搭建接口自动化测试框架，支持多环境配置', relation: '接口测试与多环境配置经历，可与团队测试基础设施建设建立关联。', question: '环境变量、测试数据和凭证分别怎样管理？' },
      { label: '质量分析', skill: '兼容性 · 缺陷分析', project: '移动端兼容性测试', requirement: '分析兼容问题与缺陷', quote: '完成多机型兼容性测试，输出缺陷分析报告', relation: '可参与兼容性测试与缺陷整理；机型选择和问题复现方式值得继续讨论。', question: '怎样选择测试机型？复现困难的问题如何记录？' },
    ],
  },
  {
    id: 'product', name: '周雨桐', initials: '周', role: '产品经理助理', shortRole: '产品协作', work: '需求整理、原型评审、需求文档与项目协作',
    company: '紫杉协作', job: '产品经理助理', editEvidence: 2,
    before: '建立反馈分类标签，辅助产品决策。',
    after: '为用户反馈建立分类标签，将反馈整理为产品决策的参考。',
    suggestion: '把“建立标签”和“用于产品决策”的关系说清楚。保留已有职责，不把协助工作写成独立主导；具体决策案例可后续补充。',
    expectation: '接触真实用户需求，跟进产品从讨论到交付', teamExpectation: '和设计、开发、测试协作，让反馈形成可讨论的需求',
    opening: '你在用户反馈平台里，怎样确定反馈分类标签？',
    evidence: [
      { label: '需求表达', skill: '原型 · 需求文档', project: '产品需求协作', requirement: '整理需求与参与原型评审', quote: '协助完成产品需求整理、原型图评审与需求文档编写', relation: '可参与需求整理与评审协作；需求范围及验收描述可通过具体文档进一步了解。', question: '需求有歧义时，你怎样和相关同事澄清？' },
      { label: '流程协作', skill: '任务流转', project: '内部协作工具优化', requirement: '理解并优化协作流程', quote: '优化任务流转流程，提升团队协作效率', relation: '任务流转经历可与内部协作产品有关联；原流程问题和调整内容可继续讨论。', question: '原先的任务流转卡在哪里？你参与了哪些调整？' },
      { label: '反馈整理', skill: '用户反馈 · 分类标签', project: '用户反馈分析平台', requirement: '整理用户反馈与决策参考', quote: '建立反馈分类标签，辅助产品决策', relation: '可参与反馈分类与需求讨论；标签的制定依据和使用方式值得展开。', question: '重复或互相矛盾的反馈怎样整理？标签如何迭代？' },
    ],
  },
]
export const editSteps = ['选择原文', 'AI 建议', '前后对照', '确认采纳', '预览更新']
export const journeySteps = ['主动投递', '企业邀请', '求职者接受', '开始沟通']
