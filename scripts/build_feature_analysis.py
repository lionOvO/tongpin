"""Build per-function Markdown from reviewed implementation traces; no app imports.

Run with .venv/Scripts/python.exe scripts/build_feature_analysis.py.
The feature traces below are editorial data, not a runtime call-graph inference.
"""
import ast
import html
import hashlib
import json
import re
import textwrap
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '功能业务分析'
MODULES = ['账号、认证与工作空间', '岗位与用人需求', '简历与材料管理', 'AI协作与能力报告', '双向偏好与岗位比较', '投递、邀请与消息沟通', '平台监管与质量治理']
NUMERALS = '①②③④⑤⑥⑦'
FEATURES = []


def add(module, title, role, page, frontend, backend, inputs, output, trace, notes=''):
    FEATURES.append(dict(module=module, title=title, role=role, page=page,
        frontend=frontend.split(), backend=backend.split(), inputs=inputs, output=output,
        trace=[line.split('|', 2) for line in trace.strip().splitlines()], notes=notes))


# A = HTTP request, R = HTTP response, C = service decision/error branch;
# D = business DB, H = auth DB, M = model, K = configuration, P = private files;
# W/E = background branch start/end; F/S = frontend/service action, L = browser storage.
add(1,'短信服务状态与验证码发送','未登录用户或工作人员','/login、/register、/forgot-password 及管理登录页','pages/Login.vue','auth.py:Auth.send sms.py',
    'phone、purpose（login/register/reset）；前端手机号格式、重复点击与倒计时检查。','短信配置可用性及 retry_after；验证码通过短信服务发送，不在响应中返回。','''
F|读取手机号及用途，校验 11 位号码
A|GET /auth/options|无请求体
K|读取短信配置是否齐备，不返回密钥
R|200：sms_available、missing
A|POST /auth/sms/send|phone、purpose
C|号码、来源与发送频率合法|配置缺失、发送过频或来源不合法时拒绝
H|检查发送限流，存储验证码摘要及到期信息
S|调用 SmsSender 发送用途对应验证码
R|200：message、retry_after；失败返回业务错误
F|开始倒计时并显示发送结果，不把验证码当登录成功
''','短信属于外部服务；短信失败不建立登录会话。验证码校验与会话签发在后续登录/注册功能完成。')
add(1,'手机号验证码注册','普通新用户','/register','pages/Login.vue store.ts','auth.py:Auth.register auth.py:Auth.issue passwords.py',
    'phone、code、password、role；前端确认密码与创建账号同意项。','账号、两类普通工作空间、user 会话 Cookie 和 csrf_token。','''
F|核对两次密码、手机号、验证码及注册确认
A|POST /auth/register|phone、code、password、role
C|验证码有效且手机号尚未注册|验证码过期、重复账号或密码不合规则拒绝
H|消费 register 验证码，写入 scrypt 密码哈希与工作空间
H|签发会话，保存 token 摘要与 CSRF、scope、到期时间
R|200：Set-Cookie、user、csrf_token
F|adoptSession 后刷新材料；招聘身份未认证则进入企业认证页
''')
add(1,'普通用户密码登录','已注册普通用户','/login','pages/Login.vue store.ts','auth.py:Auth.login_password auth.py:Auth.issue',
    'phone、password、role；密码长度与手机号格式。','user scope 会话、身份信息和 CSRF；刷新所选工作空间资料。','''
F|选择求职或招聘身份并提交密码
A|POST /auth/login/password|phone、password、role
H|读取账号、密码哈希、禁用状态及登录限流
C|密码正确、账号可用且目标空间允许进入|错误密码、账号暂停或招聘准入不足时拒绝
H|签发 user 范围会话并设置独立 Cookie
R|200：user、csrf_token 与 Cookie
F|清除旧缓存并 adoptSession，加载岗位和简历；按认证状态导航
''')
add(1,'普通用户验证码登录','已注册普通用户','/login','pages/Login.vue store.ts','auth.py:Auth.login auth.py:Auth.verify_code',
    'phone、code、role；使用 login 用途验证码。','普通会话与工作空间身份；不会自动注册未知手机号。','''
F|选择验证码登录，填写验证码和目标身份
A|POST /auth/login/phone|phone、code、role
H|校验 login 验证码、账号及目标工作空间
C|账号存在且验证码可消费|未知账号、验证码错误或已失效时拒绝
H|消费验证码并签发 user scope 会话
R|200：user、csrf_token、Set-Cookie
F|同步同端标签页会话，刷新材料并进入工作台
''')
add(1,'管理端独立登录','已授予管理员权限的账号','/admin/login','pages/Login.vue navigation.ts store.ts','auth.py:Auth.login auth.py:Auth.login_password',
    'phone、password 或 code；使用管理端登录 URL 与 admin scope。','管理会话 Cookie，普通用户 Cookie 保持独立。','''
F|切换 admin scope 并清空当前前端身份上下文
A|POST /auth/admin/login/password;POST /auth/admin/login/phone|按所选方式发送 phone 与 password 或 code
H|校验账号认证凭据及 account_role
C|账号确为管理员且有效|普通账号不得通过切换请求头获得管理权限
H|签发 admin 范围会话，写独立管理 Cookie
R|200：管理员 user、csrf_token
F|刷新管理身份并导航 /admin；不同 scope 的 BroadcastChannel 独立
''','两个登录接口是互斥入口，时序中表示二选一调用，不是连续调用。管理员不能代替企业或求职者参与投递。')
add(1,'密码设置与找回','普通账号或管理账号持有人','/forgot-password、/admin/forgot-password','pages/Login.vue store.ts','auth.py:Auth.reset_password passwords.py',
    'phone、reset 用途 code、password；前端要求两次密码一致。','更新密码哈希、撤销旧会话并返回当前范围的新会话。','''
F|校验新密码与确认密码后提交
A|POST /auth/password/reset;POST /auth/admin/password/reset|按当前门户二选一，phone、code、password
H|校验 reset 验证码与目标账号
C|验证码有效且符合管理或普通门户身份要求|无效验证码、账号不可用则拒绝
H|替换密码哈希，撤销旧会话，签发当前 scope 新会话
R|200：新的 user、csrf_token 和 Cookie
F|清空密码与验证码输入，同步同范围标签页并回到工作空间
''')
add(1,'会话恢复与路由准入','所有已登录身份','所有受保护路由','main.ts navigation.ts store.ts','auth.py:Auth.session auth.py:Auth.actor auth.py:Auth.admin',
    'Cookie、X-Session-Scope；路由 meta、当前 epoch。','恢复身份或重定向登录；岗位、简历、呈现配置与健康状态。','''
F|路由守卫按路径设置 scope，initialize 去重初始化请求
A|GET /auth/me;GET /auth/admin/me|按门户选择身份接口
H|按 scope 读取会话，验证到期、账号状态和角色
C|会话存在、scope 正确且账号可用|401 清空身份并导航对应登录页
R|200：user、actor、csrf_token
F|依据 admin、enterprise、candidate 路由规则检查准入
A|GET /jobs;GET /resumes;GET /config/{name};GET /health|refresh 并行读取，name=presentation
D|按 actor 与 env 读取可见岗位及有效简历
K|返回呈现配置与服务运行状态
R|200：四组初始化结果；前端 Promise.all 汇总
F|仅当 epoch 未变化时回填 store，选择有效默认岗位和简历
''','初始化四个请求为并行同批请求。流程图中聚合在一个调用节点；并非服务端单个聚合接口。')
add(1,'求职与招聘工作空间切换','普通已登录用户','侧边栏模式切换','App.vue store.ts','auth.py:Auth.switch_workspace',
    'role=candidate/enterprise；当前 Cookie、CSRF。','切换 actor 并旋转当前普通会话令牌，加载新空间资料。','''
F|确认当前无进行中操作；递增 epoch，中止请求并清空材料
A|POST /auth/workspace|role、当前 CSRF 与 user scope
H|读取账号和目标工作空间、企业认证状态
C|目标身份允许进入且不是管理员门户|未认证招聘空间或管理端切换被拒绝
H|旋转会话令牌，更新当前工作空间关联
R|200：新 user、csrf_token 与 Cookie
F|通知同范围标签页，刷新岗位简历；网络结果不明则重新读取身份
''','迟到响应通过 epoch 与 AbortController 阻断。切换失败不能恢复旧身份材料缓存。')
add(1,'退出登录','普通用户或管理员','顶部退出登录','App.vue store.ts','auth.py:Auth.logout',
    '当前门户 Cookie、scope 与 CSRF。','撤销对应范围会话并清空浏览器内存身份。','''
F|根据当前 scope 选择退出接口
A|POST /auth/logout;POST /auth/admin/logout|对应门户 Cookie 与 CSRF，无业务请求体
H|撤销对应 token，会话 Cookie 到期
R|200：退出完成；会话已失效时前端容忍 401
F|clearSession 中止请求并清空材料，广播同范围退出
''')
add(1,'企业资质提交与进度查询','申请招聘身份的普通用户','/enterprise-verification','pages/EnterpriseVerification.vue','enterprise_verification.py:EnterpriseVerification.submit enterprise_verification.py:EnterpriseVerification.mine',
    'company_name、credit_code、legal_representative、contact_name；营业执照与招聘授权文件。','pending 申请及审核状态；不会因上传成功自动取得招聘权限。','''
F|打开认证页并读取本人申请状态
A|GET /enterprise-verification|当前普通会话
H|查询当前账号最新申请与状态
R|200：status、submission
F|填写登记信息，选择两个证明文件
A|POST /enterprise-verification|multipart 表单与两份文件
C|字段、文件类型、大小和当前申请状态符合约束|重复待审、空信息或不支持文件拒绝
P|以私有路径保存审核证明，不返回服务器路径
H|写 enterprise_submissions 与审核关联信息
R|200：待人工审核申请
F|重新加载审核进度；通过后再允许切换招聘空间
''')
add(1,'企业证明材料下载','本人申请账号或管理员','认证页、企业资质审核页','pages/EnterpriseVerification.vue store.ts','enterprise_verification.py:EnterpriseVerification.evidence platform_admin.py:PlatformAdmin.record',
    '申请 id、kind=license/authorization。','带附件文件名的文件响应；管理端下载留痕。','''
F|点击营业执照或招聘授权材料下载
A|GET /enterprise-verification/{id}/files/{kind}|申请 id 与证明种类
H|核对申请归属或管理员范围
C|拥有申请访问权且证明文件存在|越权或无文件时拒绝，禁止任意路径下载
P|解析受控私有路径并读取证明文件
H|管理员下载时追加 platform_admin_events 操作记录
R|200：FileResponse 附件，不返回私有路径
F|download 创建 Blob URL 保存并回收地址
''')
add(1,'工作台进度与快捷入口','普通用户','/workspace','pages/Home.vue store.ts','service.py:TalentService.active_resumes',
    '当前角色、可见岗位简历、偏好保存记录。','按实际数据展示材料、期待等准备状态及快捷入口。','''
F|进入工作台，读取 store 中已加载的岗位简历
A|GET /preferences;GET /applications|求职者期待历史与双端投递待办分别读取
D|按 owner 与 env 查询 preference_submissions，按投递参与方读取 applications
R|200：期待历史及投递摘要；前端分别汇总
F|计算准备卡片状态与数量，选择下一步路由；不自动写偏好或生成报告
''')
add(1,'公开首页与本地布局偏好','访客及普通用户','/、全局侧边栏、AI工作区布局','pages/Home.vue components/PublicHome.vue App.vue pages/AIWorkspace.vue','',
    '入口点击、窗口尺寸、侧边栏和对话布局选择。','前端导航、收起侧边栏、专注对话或工作台布局；不改变业务数据。','''
F|展示公开首页，点击角色入口或侧边栏布局控件
L|读取或保存可选布局偏好；浏览器禁用存储时仍使用内存默认值
F|响应尺寸变化与减少动画偏好，更新展示布局
F|点击业务入口后交给 Vue Router；受保护页面另走会话恢复功能
''','本功能是纯前端交互，没有专属后端写接口。首页动画、布局或折叠不应被画成一次业务 API 请求。')

add(2,'岗位列表查询与原文查看','求职者或招聘方','/jobs','pages/Jobs.vue store.ts','service.py:TalentService.job_visible service.py:TalentService.public_job',
    '当前 actor、可选 job 查询参数与前端搜索词。','企业自有岗位或对求职者可见的公开岗位/私人参照。','''
F|进入岗位页或点击刷新、选择岗位
A|GET /jobs|会话身份
D|企业读取自有 job_profiles；求职者读取后经 job_visible 过滤
C|公开岗位企业仍通过认证且未暂停|不符合可见性条件的岗位不返回
R|200：public_job 列表
F|本地按名称或方向搜索，选中后展示画像与 source_jd
A|GET /jobs/{id}/profile|外部或按需调用的单岗位入口
S|再次检查目标岗位可见性并生成 public_job
R|200：岗位画像；不可见返回 404
F|展示原文及参照来源，私人参照不提供投递能力
''','默认页面使用 store 列表数据展示详情，单岗位 profile 接口为可用的按需入口，并非每次点击列表都会调用。')
add(2,'JD解析创建岗位','招聘方','/jobs 新建岗位','pages/Jobs.vue','service.py:TalentService.create_job agents.py:AgentGateway.jd',
    'title、jd、data_origin；可选 manual_profile。','待确认、未公开的岗位画像 version=1。','''
F|输入岗位名和 JD，选择自动解析或手工画像
A|POST /jobs|title、jd、data_origin、可选 manual_profile
C|招聘身份、可写状态及预算允许|维护、额度不足或输入无效时拒绝
M|无手工画像时通过 JD Agent 解析脱敏原文；有手工画像时跳过模型
C|每项技能 quote 均能定位 JD 原文|引用不匹配返回 EVIDENCE_INVALID
D|写 job_profiles：待确认、published=false、version=1，记录审计
R|200：新岗位与画像
F|刷新列表并进入人工核对；此时求职者尚不能看到未公开岗位
''','demo 模式走本地规则；live 走模型传输。手工创建不等于自动通过人工确认。')
add(2,'岗位画像核对与版本确认','岗位所属招聘方','/jobs 核对岗位画像','pages/Jobs.vue components/JobRequirements.vue','service.py:TalentService.confirm_job',
    'expected_version、direction、education、技能及 required_level、quote、hard。','已确认的新画像版本，历史画像保存在 history。','''
F|编辑方向、学历、逐项技能和对应原文
A|PUT /jobs/{id}/confirm|expected_version、profile
D|读取本人 job_profiles 及原文
C|版本一致且全部引用来自 JD|409 VERSION_CONFLICT 或 422 EVIDENCE_INVALID
D|事务中复查版本，追加 history，version 加一并写确认审计
R|200：已确认画像新版本
F|刷新岗位；历史报告保留旧快照，旧 Brief 不自动适配新版本
''')
add(2,'岗位公开与设为私有','岗位所属招聘方','/jobs 岗位可见性操作','pages/Jobs.vue','service.py:TalentService.owned service.py:TalentService.job_visible',
    'published=true/false。','更新公开标记及审计，影响后续求职者列表可见性。','''
F|明确点击公开岗位或设为私有
A|PUT /jobs/{id}/visibility|published
D|读取 owner 匹配的岗位
C|公开时画像已确认且岗位未被平台暂停|未确认或平台下架时拒绝公开
D|更新 job_profiles.published 并记录可见性变更
R|200：更新后的岗位
F|刷新状态；求职者下次查询时由服务端重新检查企业和岗位状态
''','可见性更新不是替代企业认证的入口。已有投递的授权可用性还由 Hiring.available 独立核对。')
add(2,'结构化用人需求澄清','招聘方','/jobs 澄清用人需求','pages/Jobs.vue','service.py:TalentService.clarify service.py:TalentService.brief',
    'job_id、answers；可选逐技能 type 与 priority 覆盖。','与当前画像版本关联的 hiring_briefs，保留需求来源、业务目的与成功标准。','''
F|打开澄清页签
A|POST /requirements/clarify;GET /requirements/brief/{job_id}|澄清问题与当前历史 Brief 并行读取
D|验证本人岗位，读取既有 hiring_briefs
S|返回固定结构化问题 QUESTIONS，不调用模型
R|200：questions 与 Brief 历史
F|填写业务期待并逐项确认可培养、加分或硬性要求
A|POST /requirements/brief|job_id、answers、requirement_overrides
C|问题和选项合法，覆盖技能唯一且属于当前画像|未知回答或技能返回校验错误
D|写入 profile_version 对应的新 Brief，不覆盖旧版本
R|200：带来源和可评标记的需求记录
F|重读并展示澄清结果；允许不清楚或跳过
''')
add(2,'需求证据覆盖检查','招聘方','/jobs 澄清用人需求','pages/Jobs.vue','service.py:TalentService.current_brief',
    'job_id。','当前版本 Brief 中不能直接从简历评估的业务期待。','''
F|岗位或 Brief 保存后读取覆盖说明
A|GET /requirements/coverage/{job_id}|目标岗位
D|读取岗位与相同 profile_version 的 hiring_briefs
S|提取 assessable=false 的要求；无当前 Brief 则返回先保存提示
R|200：uncovered、message
F|展示待双方沟通的业务期待，不把未覆盖项当候选人不合格
''')
add(2,'岗位要求诊断','招聘方','/jobs 检查岗位要求','pages/Jobs.vue','service.py:TalentService.diagnose service.py:TalentService.valid_benchmarks',
    'job_id、当前 JD 和可用同类岗位基准。','内部矛盾、不可从简历评估、超同级基准三类可确定发现。','''
F|点击检查岗位要求
A|POST /requirements/diagnose|job_id
D|读取本人岗位、当前量规与有效 role_benchmarks
S|确定性检查届别和年限冲突、不可评词、技能要求超基准
D|保存 jd_diagnoses，附原文与版本
R|200：findings、benchmark_available
F|逐条显示原文；无发现明确显示未发现可确定问题，样本不足不伪造诊断
''')

add(3,'简历材料库查询与展示','求职者或招聘方','/resumes','pages/Resumes.vue components/ResumePaper.vue resume-display.ts','service.py:TalentService.active_resumes service.py:TalentService.public_resume',
    '会话身份，前端搜索、材料选择与列表/卡片视图。','本人空间有效且授权仍可用的简历，不返回 raw_file_path 和 source_hash。','''
F|打开材料库或刷新已导入简历
A|GET /resumes|当前工作空间
D|读取 owner、env 作用域内 resumes，排除软删除与失效授权
S|public_resume 移除内部路径和源摘要
R|200：简历列表与可用正文
F|本地搜索、切换卡片/列表并在 ResumePaper 阅读正文
L|仅保存 tongpin:resume-layout 视图偏好，不在浏览器存储完整简历
''','招聘端会周期性刷新授权变化；正文阅读使用已有受控响应，不生成公共文件 URL。')
add(3,'文字简历录入','求职者或招聘方','/resumes 文字录入','pages/Resumes.vue','service.py:TalentService.create_resume security.py:redact retrieval.py',
    'name、text、data_origin。','候选人记录、脱敏正文简历、私有原文及可选索引。','''
F|填写展示名称、简历正文与来源
A|POST /resumes|name、text、data_origin
S|隔离敏感个人信息，检查可用正文长度
C|脱敏后仍有至少 10 字可用经历|不足则 NO_USABLE_TEXT，不写空简历
D|事务写 candidates 与 resumes 记录
P|保存私有原文 TXT，异常时清理残留文件
D|写导入审计；可选向量索引失败只留告警
R|200：public_resume
F|关闭导入窗口并刷新材料库，保留部分失败提示
''')
add(3,'PDF与TXT及JSON文件批量导入','求职者或招聘方','/resumes 本地导入','pages/Resumes.vue','main.py:parse_document main.py:parse_upload service.py:TalentService.create_resume',
    'multipart files、data_origin；最多 50 份、单份 10MB、批次合计 50MB。','resumes 成功列表与逐文件 errors；某文件失败不抹去其他成功项。','''
F|选择 PDF、TXT、JSON 文件，组装 FormData
A|POST /resumes/batch|files、data_origin
C|文件数量及单份和累计大小满足限制|超限文件或批次返回明确错误
S|最多两路解析线程；PDF 提取文字，TXT/JSON 按 UTF-8 读取
C|可解析且未超 20 秒，PDF 不超 50 页|扫描件 OCR_REQUIRED、忙碌或格式错误逐文件记录
S|对成功正文逐个调用 create_resume，执行脱敏
P|保存成功项私有原文
D|写 candidates、resumes 与导入审计
R|200：成功 resumes 与失败 errors
F|展示成功数量和每个文件失败原因，刷新材料库
''','当前 PDF 解析不包含 OCR。文件字节不发给模型，文件解析与后续 AI 分析是两个独立功能。')
add(3,'本人材料文本下载','材料所属用户','/resumes 下载','pages/Resumes.vue store.ts','service.py:TalentService.active_resume',
    'resume id。','可访问的整理文本 TXT，UTF-8 BOM；不是原始 PDF 回传。','''
F|点击指定简历下载
A|GET /resumes/{id}/download|简历 id
D|读取 active_resume 并核对 owner、删除和投递授权状态
C|材料仍可访问|删除、越权或授权结束返回 404 或 403
D|写简历文本下载审计
R|200：text/plain、Content-Disposition 与整理后正文
F|按安全文件名保存 Blob，释放临时 URL
''')
add(3,'简历材料删除','材料所属用户','/resumes 删除确认','pages/Resumes.vue','service.py:TalentService.delete_resume',
    'resume id；前端明确确认删除。','deleted=true、history_retained=true；材料库隐藏该材料。','''
F|弹出删除确认并显示历史保留说明
A|DELETE /resumes/{id}|目标简历 id
D|BEGIN IMMEDIATE 读取本人 resumes
C|简历属于当前空间|越权 404；重复软删除不重复破坏数据
D|设置 deleted_at 并写审计，不删除引用记录或投递快照
R|200：deleted、history_retained
F|移除失效勾选并刷新列表，选择其他有效材料
''','删除材料库项不等于撤回对企业的投递授权。撤回须到投递进展执行独立状态变更。')
add(3,'可导入投递者简历查询','认证招聘方','/resumes 导入投递者简历','components/ApplicantResumes.vue','hiring.py:Hiring.resume_candidates hiring.py:Hiring.available',
    'job_id、q、offset、limit（1～50）。','本企业可用授权投递的分页清单及已导入状态。','''
F|打开导入投递者简历窗口，选择岗位或搜索
A|GET /resumes/applicants|job_id、q、offset、limit
D|读取本企业 applications 并检查 available
S|排除终态、已撤权和不可用投递，返回允许显示的摘要
R|200：items、total
F|展示预览、下载、导入；每约 15 秒在可见时复查授权
''')
add(3,'一键导入授权投递简历','认证招聘方','/applications、/resumes','components/ApplicantResumes.vue components/ApplicationResumeActions.vue','hiring.py:Hiring.import_resume hiring.py:Hiring.shared_resume',
    'application id、expected_version。','绑定 source_application_id、application_job_id 的企业材料；重复导入复用有效材料。','''
F|选中投递者，点击导入并携带当前投递版本
A|POST /applications/{id}/resume-import|expected_version
D|读取投递、岗位及已导入 resumes
C|本企业授权可用且版本一致|撤回、暂停或 APPLICATION_CONFLICT 时拒绝
S|复制本次 resume_snapshot，不读取求职者后续私人简历版本
D|写企业 resumes 与来源、岗位约束，记录审计；重复请求复用
R|200：resume、already_imported
F|刷新材料库，可在原投递岗位整理初筛或生成报告
''','衍生材料仍受原投递授权与原岗位约束，撤权后读取、分析、下载均重新拒绝。不是无约束的永久复制。')
add(3,'授权投递简历预览与下载','认证招聘方','/applications、投递简历窗口','components/ApplicantResumes.vue components/ApplicationResumeActions.vue','hiring.py:Hiring.download_resume hiring.py:Hiring.shared_resume',
    'application id。','预览为当前授权快照；下载为对应整理 TXT。','''
F|点击核对投递简历或下载
A|GET /applications/{id}|预览时读取投递详情
D|核对当前企业归属和授权可用性，选取 resume_snapshot
R|200：有权查看的投递详情与正文
F|在受控阅读窗口核对原快照
A|GET /applications/{id}/resume-download|下载时发起独立 GET
C|下载当刻授权仍有效|已终态或暂停则拒绝下载
D|写授权下载审计并取共享正文
R|200：带附件头的整理 TXT
F|保存文件；已下载副本无法由服务端远程撤回
''')
add(3,'岗位简历初筛整理','认证招聘方','/resumes 整理本岗位初筛','pages/Resumes.vue','service.py:TalentService.batch retrieval.py deterministic.py:evidence_skills',
    'job_id；读取当前岗位允许分析的全部有效企业材料。','逐份技能命中、缺口与规则标记；所有材料仍保留。','''
F|选择已确认岗位，点击整理本岗位初筛
A|POST /batches/run|job_id
D|读取确认岗位、有效 resumes 与原投递岗位约束
C|画像已确认且材料仍在授权范围|未确认拒绝；失效材料排除
S|可选检索仅调整处理顺序，确定性提取行为证据并逐项对照
D|逐份写 batches：hits、misses、规则原因及 profile_version
R|200：本批整理结果
A|GET /batches|job_id
D|读取每份简历最新且可见的整理记录
R|200：最新初筛摘要
F|可展开依据，不删除简历、不自动淘汰
''','这是确定性规则初筛；不宣称模型筛选准确率，也不把学历未知当作已不满足要求。')

add(4,'求职AI任务创建','求职者','/ai-workspace 新建任务','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.create ai_workspace.py:AIWorkspace.materials',
    'resume_id、可选 job_id 或 jd/title、model_id；两种岗位来源互斥。','ai_sessions 新任务；粘贴 JD 是本人私有参照，不向企业公开。','''
F|选择本人简历、目标岗位或粘贴 JD
A|POST /ai/workspaces|resume_id、model_id、可选岗位来源
D|检查有效本人简历、岗位可见性及任务数量
C|材料合法且未超任务数量限制|无权材料、两种岗位来源同时提供或超限时拒绝
S|粘贴模式用规则解析脱敏 JD，建立私人岗位参照
D|写 ai_sessions：version=1、空消息及来源引用
R|200：任务详情和材料来源
F|导航 task 查询参数并展示准备状态，不自动投递
''')
add(4,'求职AI历史对话查询','求职者','/ai-workspace 对话历史','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.list ai_workspace.py:AIWorkspace.public',
    '任务 id，当前求职者 actor。','本人任务摘要、消息、分析、草稿与待处理材料提示。','''
F|打开对话历史，选择指定任务
A|GET /ai/workspaces|本人会话
D|按 owner 查询非临时材料任务摘要
R|200：任务列表
A|GET /ai/workspaces/{id}|选中任务 id
D|检查 owned 与材料权限，读取消息及待更新状态
R|200：public 任务详情
F|恢复历史消息与布局，仅回填仍选中的任务，不触发模型
''')
add(4,'求职AI任务删除','求职者','/ai-workspace 删除任务','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.delete',
    '任务 id；前端确认。','移除对话任务；简历和已确认保存的优化版本保留。','''
F|确认删除当前历史任务
A|DELETE /ai/workspaces/{id}|任务 id
D|读取 owned 任务并检查运行和临时资料状态
C|任务可编辑且不是待处理临时材料任务|处理中或须回原任务处理时拒绝
D|删除任务及需清理的暂存关联，不删除保存好的简历版本
R|200：删除结果
F|清空当前聊天，刷新历史并回到工作区入口
''')
add(4,'模型目录查询与求职任务模型切换','求职者；招聘方只读取招聘目录','双端 AI 顶部模型说明','pages/AIWorkspace.vue pages/RecruiterAI.vue','ai_workspace.py:AIWorkspace.select_model model_catalog.py',
    '求职侧 model_id、expected_version；招聘目录 default_model_id=deepseek。','可用模型的公开元数据；求职任务后续请求使用新模型。','''
F|打开模型选择或读取招聘模型说明
A|GET /ai/models;GET /recruiter/models|按当前角色选择目录接口
K|ModelCatalog 输出可用状态与 provenance，不输出密钥
R|200：models 与 default_model_id
F|求职者选择任务模型；招聘对话固定走 DeepSeek 官方
A|POST /ai/workspaces/{id}/model|仅求职任务：model_id、expected_version
C|任务版本一致、未运行且没有待解决材料|不可用模型或版本冲突拒绝
D|更新 ai_sessions.model_id、model_selection 与版本
R|200：更新任务
F|保留已有历史结果，仅后续调用采用新模型
''','目录读取两接口二选一；模型切换分支仅求职者可执行，招聘者不能调用 Candidate 专属写接口。')

def candidate_turn(title, action, output, extra):
    add(4,title,'求职者','/ai-workspace','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.turn ai_workspace.py:AIWorkspace.validate agents.py:AgentGateway.call',
        f'action={action}、message、expected_version；任务内已确认材料。',output,f'''
F|{extra}
A|POST /ai/workspaces/{{id}}/turns|action={action}、message、expected_version
D|事务检查 owned、版本、pending 材料和轮次，预留运行令牌
C|无并行任务且每十分钟未超 12 次|运行中、超限或 30 轮上限返回明确错误
S|脱敏并编号简历、岗位和已确认补充，仅取同 material_epoch 上下文
M|按任务 model_id 调用 CandidateWorkspace；结构化输出和引用校验，失败至多修复重试一次
C|引用可定位、无禁用结论且来源未失效|无效输出、超时或材料变动不写新结果
D|提交前复核登录和材料，保存本轮消息、分析或待确认草稿，清除运行标志
R|200：新任务版本与本轮结果；失败释放运行标志并保留历史
F|渲染结果和依据；超时先重读任务，保留输入供用户核对
''','模型输出不是用户事实；未明确保存的普通聊天不会自动进入后续证据来源。')

candidate_turn('求职简历与岗位分析','analyze','分析 findings、questions、来源引用与材料版本。','点击分析材料或更新分析')
candidate_turn('求职AI自由对话','chat','同材料轮次的对话回答与中性补充问题。','输入问题并发送，普通聊天不写入简历')
candidate_turn('简历表达优化草稿生成','draft','pending 草稿、逐段 before/after 与 citations；原简历尚未改变。','点击生成优化草稿')
add(4,'已有对话消息确认为本人补充','求职者','/ai-workspace 消息保存补充','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.note',
    'message_id、expected_version；仅保存本人选择的用户消息。','notes 中 self_reported 补充，新材料版本；旧分析和 pending 草稿失效。','''
F|选择自己的对话消息并明确保存为本人补充
A|POST /ai/workspaces/{id}/notes|message_id、expected_version
D|读取任务和消息，核对用户消息归属及版本
C|消息可确认且补充总量未超限|助手消息、空内容、重复冲突或过量拒绝
S|隔离敏感信息并标记本人陈述来源
D|写 notes，清空旧分析、过期旧草稿并递增版本
R|200：新任务材料状态
F|显示已保存补充，后续分析才使用该来源
''')
add(4,'直接新增本人经历补充','求职者','/ai-workspace 补充经历','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.add_note',
    'text、expected_version；明确保存的经历文本。','保存补充及对应用户消息；不会覆盖原简历文件。','''
F|打开补充窗口，填写实际任务、职责、过程与产出
A|POST /ai/workspaces/{id}/additions|text、expected_version
D|检查本人任务、可编辑状态及补充累计长度
C|脱敏后非空且累计补充不超 12000 字|无可用内容、版本冲突或超限拒绝
D|写 self_reported note 与用户消息；material_version 加一，旧结果失效
R|200：更新后的任务
F|显示补充记录；用户决定是否重新分析或生成草稿
''')
add(4,'AI工作区材料手工修改','求职者','/ai-workspace 材料卡片修改','pages/AIWorkspace.vue components/InfoHint.vue','ai_workspace.py:AIWorkspace.edit_material',
    'kind=resume/job、title、text、expected_version、request_id。','新简历/私人岗位版本与临时任务；原对话出现选择提示。','''
F|阅读修改提示后编辑材料，固定本次 request_id
A|POST /ai/workspaces/{id}/materials/edit|kind、title、text、expected_version、request_id
D|校验任务、幂等指纹和已有待处理修改
C|材料确有变化且当前版本一致|重复编号内容变更、未修改或版本冲突拒绝
S|脱敏；修改企业 JD 时复制为本人私人参照，绝不更新企业原岗位
D|新建材料与 material_staging 任务，原任务设置 pending_material_session_id
R|200：新临时材料任务
F|重读原任务并停留原对话，显示新对话或更新资料分析两种选择
''','新增或改写的经历保留本人陈述标记；保存修改本身不调用模型，也不直接跳到新对话。')
add(4,'资料修改后开启新对话','求职者','/ai-workspace 原对话资料更新提示','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.resolve_materials',
    'choice=new、pending_session_id、expected_version。','启用暂存任务；原对话及原分析保持对应旧材料。','''
F|在旧对话提示中点击在新对话中聊天
A|POST /ai/workspaces/{id}/materials/resolve|choice=new、pending_session_id、expected_version
D|核对原任务与最新暂存任务及已有处理决定
C|暂存归属、版本和会话数量合法|过期暂存、冲突或超会话数拒绝
D|清除 staging，继承已确认 notes 和模型；原任务清空 pending 并记下决定
R|200：新对话任务
F|导航新 task；开始新分析需另行调用 turns
''','同一 pending 选择重试返回原决定，不能重复创建分支；不是自动继承旧分析结论。')
add(4,'资料修改后保留对话并更新分析','求职者','/ai-workspace 原对话资料更新提示','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.resolve_materials ai_workspace.py:AIWorkspace.turn',
    'choice=update、pending_session_id、expected_version；随后 action=analyze。','原对话切换新材料，归档旧结果，material_epoch 增加并重新分析。','''
F|点击更新资料分析，保留当前对话窗口
A|POST /ai/workspaces/{id}/materials/resolve|choice=update、pending_session_id、expected_version
D|检查暂存材料，归档旧分析与草稿，更新 SQL 材料引用
C|模型可用且未超 30 轮|不允许切换的材料或版本冲突时保留提示
D|material_epoch 加一并清空 analysis、drafts，历史消息保留
R|200：原任务的新材料版本
A|POST /ai/workspaces/{id}/turns|action=analyze、返回的新 expected_version
M|只以新材料及当前材料轮次上下文重新分析
D|校验后写入新分析，保留旧轮次供历史阅读
R|200：新分析或明确失败状态
F|展示新结果；分析失败时新材料仍已切换，可重新分析
''','资料决策与模型分析是两个请求、两个提交点，不能声称任一步失败会整体回滚到旧材料。')
add(4,'优化草稿核对与保存新简历','求职者','/ai-workspace 修改草稿','pages/AIWorkspace.vue','ai_workspace.py:AIWorkspace.confirm',
    'draft_id、expected_version、可选 edits（index、after）。','原子保存新 resumes、来源及 draft.saved_resume_id；原简历保留。','''
F|逐段核对 before、after 与依据，可手工修改后明确保存
A|POST /ai/workspaces/{id}/drafts/confirm|draft_id、expected_version、edits
D|读取 pending 草稿、当前材料版本和已确认来源
C|草稿未过期且原文段落能唯一定位|过期、重复定位、非法编辑或无引用依据拒绝
S|逐段替换；新增本人内容永久保留 self_reported 来源，不伪装模型证据
D|同事务新建 resumes 并将草稿标记 saved，记录 revision_basis 与审计
R|200：session、新 resume；已保存草稿重复提交返回同一版本
F|刷新材料库，展示优化版，不覆盖原简历或已投递快照
''')
add(4,'招聘个人资料卡读取与更新','认证招聘方','/applications、/recruiter-ai','components/RecruiterProfile.vue pages/RecruiterAI.vue','recruiter_review.py:RecruiterReview.get recruiter_review.py:RecruiterReview.analyze',
    'application id、expected_version、business_context、可选 regenerate、model_id；默认 deepseek。','有出处的摘要、技术强项、业务关联与面试问题，保存到投递 payload。','''
F|读取当前投递的资料卡；点击更新时提交当前版本
A|GET /applications/{id}/recruiter-review|投递 id
D|检查本企业投递与授权，读取已有资料卡
R|200：旧卡片及生成状态
A|POST /applications/{id}/recruiter-review|expected_version、business_context、regenerate
D|校验版本、来源指纹与频率，预留运行令牌；相同输入可直接复用
M|RecruiterCard 默认 DeepSeek 官方，依据授权简历、岗位与业务背景生成结构化卡片
C|引用、模型输出、授权和材料指纹仍有效|无效或超时不覆盖旧卡；每十分钟超 12 次或并行时拒绝
D|事务复查权限与令牌，保存 recruiter_review 及审计
R|200：新卡片；失败释放标志并保留旧卡
F|渲染摘要、强项与业务建议，不输出胜任总分或自动淘汰结论
''')
add(4,'候选人核心技术经历图谱','认证招聘方','个人资料卡的技术图谱或经历结构视图','components/RecruiterProfile.vue components/RecruiterExperienceGraph.vue recruiter-review.ts','recruiter_review.py:RecruiterReview.public',
    '当前已授权资料卡 strengths、citations、business_links；选中节点。','技术节点与经历、业务关系的可视化，点击可定位原文。','''
F|在当前候选人资料卡切换到技术图谱
A|GET /applications/{id}/recruiter-review|仅在未加载或刷新时请求同一资料卡
D|检查当前投递权限并读取已有卡片，不另调模型
R|200：strengths、业务关联、引用
F|前端归组技术方向，构造节点与连线；区分具体经历与仅材料提及
F|点击节点展开任务、来源原文和业务关联，切换卡片不产生新分析
''','图谱是已有证据的视图，不是另一份评分或人格画像；同页已经加载卡片时直接复用数据，无需再次 GET。')

def recruiter_turn(title, action, goal):
    add(4,title,'认证招聘方','/recruiter-ai、候选人详情招聘 AI','pages/RecruiterAI.vue components/RecruiterChat.vue recruiter-assistant.ts',
        'recruiter_assistant.py:RecruiterAssistant.turn recruiter_review.py:RecruiterReview.sources',
        f'action={action}、message、business_context、expected_version、request_id。',goal,f'''
F|选择已授权候选人，发起 {action} 操作
A|POST /applications/{{id}}/recruiter-assistant/turns|action、message、business_context、expected_version、request_id
D|校验企业投递、独立聊天版本、请求指纹、频率和运行锁
C|同编号内容一致且授权有效|冲突、每十分钟 20 次或 100 轮上限拒绝
S|取授权材料、岗位和业务上下文，最多使用最近 10 条历史消息
M|RecruiterAssistant 固定 DeepSeek 官方；输出引用与问题经过 schema 和来源验证
C|登录身份、投递和材料指纹提交前仍一致|中途撤权、超时或无效输出不保存新消息
D|追加用户与助手消息，聊天版本加一，保存幂等请求与审计
R|200：回答、citations、questions 和新聊天版本
F|展示回答与可点击原文，结果不明先重读历史，同 request_id 防止重复提交
''','快捷操作和自由对话共用受控接口，但用途分别记录；不会向求职者自动发送面试问题或沟通邀请。')

recruiter_turn('招聘AI简历精华整理','summary','围绕当前候选人概括技术任务、个人职责与产出。')
recruiter_turn('招聘AI技术与业务关联讨论','business','结合明确提供的企业业务背景说明可进一步了解的关联，区分事实和建议。')
recruiter_turn('招聘AI面试追问生成','interview','以材料中的任务和缺口为依据组织面试追问，不直接判定候选人不适任。')
recruiter_turn('招聘AI自由对话','chat','围绕单个授权候选人的回答与出处，不做跨人排行。')
add(4,'招聘AI对话历史恢复','认证招聘方','/recruiter-ai 对话历史','pages/RecruiterAI.vue components/RecruiterChat.vue','recruiter_assistant.py:RecruiterAssistant.get recruiter_assistant.py:RecruiterAssistant.public',
    'application id。','该投递独立的 recruiter_chat、版本及生成状态。','''
F|在招聘工作区选择投递候选人，或恢复历史
A|GET /applications/{id}/recruiter-assistant|所选投递 id
D|重新核对投递授权并读取 recruiter_chat 与版本
C|授权仍有效且属于当前企业|授权结束返回拒绝，前端清除旧候选人内容
R|200：历史消息、业务上下文和运行状态
F|按消息恢复阅读；可见页面约 15 秒轮询，候选人改变用序列号隔离迟到响应
''','没有单独的招聘聊天历史表；记录存于 applications.payload。终态会清除招聘 AI 历史。')
add(4,'后台能力报告任务提交','认证招聘方','/resumes 生成能力报告；/reports 查看结果','components/ReportGenerator.vue','assessment_tasks.py:AssessmentTasks.submit assessment_tasks.py:AssessmentTasks.run service.py:TalentService.assess',
    'job_id、resume_ids（1～50）、request_id。','202 任务 id；任务与已完成报告持久化，可离开页面后查看。','''
F|勾选材料，固定 request_id 后点击生成能力报告
A|POST /assessment-tasks|job_id、resume_ids、request_id
D|事务核对已确认岗位、材料归属、原投递岗位与重复请求
C|无冲突任务且队列有容量|重号不同内容、部分重叠或容量满时拒绝
D|写 assessment_tasks.status=queued，关联简历清单与 DeepSeek 模型元数据
S|提交进程内有界线程池，最多两名 worker、八个任务槽
R|202：持久化任务详情；HTTP 不等待模型完成
W|从已提交线程池开始运行任务，写 running
M|逐份调用 assess，默认 DeepSeek 官方；复核企业及简历授权后生成证据报告
D|每份提交 ability_reports 并更新 processed、report_ids、errors
D|最终写 completed、partial 或 failed；预算或暂停时停止继续处理
E|后台结束，不通过该提交 HTTP 向浏览器推送结果
F|通过任务查询功能轮询结果，不重复创建请求
''','后台执行器仍在 FastAPI 进程内，不是 Redis/Celery 分布式队列；服务重启不会自动重放付费调用。')
add(4,'能力报告任务进度与历史恢复','认证招聘方','/resumes 报告进度组件；/reports 审阅结果','components/ReportGenerator.vue','assessment_tasks.py:AssessmentTasks.list assessment_tasks.py:AssessmentTasks.access',
    'job_id、可选任务 id。','最近任务、进度、成功报告 id 及逐份错误。','''
F|返回简历与初筛页，恢复历史或正在执行的任务
A|GET /assessment-tasks;GET /assessment-tasks/{id}|Vue 默认查询带 job_id 的列表；集成客户端可按 id 查询单条，二选一
D|核对本人岗位、owner 与关联材料授权；列表最多 20 条，运行中优先
R|200：任务列表或单条任务，含 processed、report_ids、errors、status
F|可见页面每 4 秒刷新任务列表；切换岗位用 version 与 epoch 隔离旧响应
F|显示成功报告数与逐份错误；终态可跳转 /reports 读取和审阅报告
''','当前 ReportGenerator 位于 /resumes，轮询列表而非逐个 GET 任务；单任务读取接口保留供显式客户端调用。查询失败不取消后台任务，旧成功报告可继续审阅。')
add(4,'报告任务服务重启后的中断处理','服务维护者与返回页面的招聘方','服务启动、/resumes 任务进度','components/ReportGenerator.vue','main.py:lifespan assessment_tasks.py:AssessmentTasks.recover',
    '数据库中 queued/running 任务；服务启动事件。','旧任务标记 interrupted，已生成报告保留，用户核对后可重新提交。','''
S|FastAPI lifespan 启动报告任务执行器
D|查询 assessment_tasks 中 queued 与 running 的历史任务
D|标记 interrupted、finished_at 和中断说明，不自动重放模型
F|用户返回页面查询已有任务
A|GET /assessment-tasks|job_id
D|按当前权限读取中断任务和已完成 report_ids
R|200：interrupted 与保留结果
F|提示核对成功报告后再提交未完成项，不宣称中断等于全部失败
''','重启恢复为真实后端启动入口；图中的服务先于页面请求发生，不由浏览器启动服务。')
add(4,'能力报告直接同步分析接口','招聘方集成调用；非默认生成按钮','无默认独立页面，主入口已采用后台任务','components/ReportGenerator.vue','service.py:TalentService.assess service.py:TalentService.evaluate agents.py:AgentGateway.evaluate',
    'job_id、resume_ids。','同步返回 reports 与逐份 errors；长请求可能等待模型。','''
F|集成客户端显式选择同步能力分析接口
A|POST /assessments|job_id、resume_ids
D|核对岗位已确认、分析未暂停、简历有效及岗位来源限制
M|逐份执行证据分析，模型提取后由确定性规则计算 D2、D4 和排序键
C|schema、原文引用、呈现禁词和材料权限合法|无效输出或证据不合法不签发报告
D|写 ability_reports，保留画像、量规、优先级快照
R|200：reports、errors；单份失败可与成功项同时返回
F|集成客户端展示结果；产品默认按钮仍走 202 后台任务
''','保留接口不等于前端仍调用同步路径；这里明确记录兼容入口，避免把后台任务画成同步阻塞流程。')
add(4,'能力报告与原文依据阅读','招聘方','/reports','pages/Reports.vue components/ReportView.vue','service.py:TalentService.visible_material_records service.py:TalentService.owned',
    'job_id、选中 report id。','可见报告、技能依据、面试准备及审阅历史。','''
F|选择岗位与简历，打开报告
A|GET /assessments|可选 job_id
D|读取仍有材料访问权的 ability_reports
R|200：报告列表
A|GET /assessments/{id};GET /reviews|按需读取报告详情及 report_id 审阅历史
D|检查 owner 和材料授权，读取报告快照与 review_events
R|200：报告及审阅记录
F|企业端按岗位差距呈现，原文可展开；不把内部档位当人员评级
''','同页已有列表详情时可复用，不要求额外读取单条报告。报告保存的历史快照不自动改成最新配置。')

def review_feature(title, action, change, note):
    add(4,title,'报告所属招聘方','/reports 人工审阅','pages/Reports.vue',
        'service.py:TalentService.review',f'report_id、action={action}、reason；单项修改另含 dimension_id、tier_after。',change,f'''
F|选择 {action} 并填写处理依据
A|POST /reviews|report_id、action、reason、适用的维度字段
D|事务读取本人报告并复核材料授权
C|报告状态及原文依据允许此次操作|已打回或锁定报告不能直接改动；无原文不能改成明确关系
D|写 review_events；{change}
D|改项或打回时产生未确认 calibration_memory；记录审计
S|检查本岗位最近三次审阅，连续整份打回则追加分析暂停事件
R|200：更新后的报告
F|重读报告与审阅记录，更新按钮可用状态
''',note)

review_feature('人工确认能力报告','确认','报告状态改为已确认并记 confirmed_at','确认不产生修改记忆；只有最新已确认报告参与后续比较。')
review_feature('人工修改单项岗位关系','单维改档','更新指定 dimensions、structure_view 和 sort_key','请求字段沿用内部 tier_after，企业界面用单项岗位关系措辞，不展示裸评级。')
review_feature('整份报告打回','整份打回','报告状态改为已打回','打回后须重新分析才能再次审阅，不能直接把旧报告重新确认。')
add(4,'打回报告重新分析','招聘方','/reports 已打回报告','pages/Reports.vue','service.py:TalentService.assess',
    '已打回报告 id。','新报告版本或错误；旧报告与审阅历史保留。','''
F|在已打回报告上点击重新分析
A|POST /assessments/{id}/rerun|旧报告 id
D|核对本人旧报告及其岗位、简历
C|旧报告确为已打回且岗位未暂停分析|锁定、未打回或暂停时返回冲突
M|按当前材料与配置重新评估，默认 DeepSeek 官方
D|写新的 ability_reports，不覆盖旧报告
R|200：新 reports 与 errors
F|刷新列表，选择新待确认报告进行审阅
''','该兼容重跑入口为同步调用；普通多份生成按钮使用后台任务。恢复被暂停岗位分析属于治理操作。')
add(4,'已确认报告面试追问','招聘方','/reports 面试准备','pages/Reports.vue','service.py:TalentService.followups',
    '已确认 report id。','基于 open_questions 的规则化面试追问，保存于报告 followups。','''
F|确认报告后点击生成面试追问
A|POST /assessments/{id}/followups|report id
D|检查本人报告与状态
C|报告已经人工确认|REPORT_UNCONFIRMED 时不生成
S|按每条开放问题拼装具体经历、职责、选择与结果的追问模板，不调用模型
D|更新 ability_reports.followups
R|200：带追问的报告
F|在面试准备区展示，不向候选人自动发送
''','本功能与招聘 AI 的 interview 动作不同：这里是已确认报告的确定性模板，不另行调用大模型。')

add(5,'双方期待填写与历史快照','求职者或招聘方','/preferences','pages/Preferences.vue','service.py:TalentService.submit_preference service.py:TalentService.latest_preference',
    'side、对应 resume_id 或 job_id、dimensions、dimension_version、share_with_counterparty；企业可填 ambience_text。','新的 preference_submissions 与维度配置快照，不覆盖旧期待。','''
F|选中本人简历或企业岗位并打开期待页
A|GET /config/{name};GET /preferences|name=preferences；读取同源维度与历史
K|读取必填、选项、维度版本；无判断是合法选择
D|按当前 owner 查询 preference_submissions
R|200：当前维度表与已保存快照
F|三项必填可选择无法判断，选填可留空，明确勾选共享
A|POST /preferences/submit|side、目标 id、dimensions、dimension_version、共享确认
C|目标、版本、选项、必填与共享确认有效|口径更新、无授权或错误关联时拒绝
D|保存新期待、unfilled_dims 和 dimension_snapshot，记录审计
R|200：新 submission
F|重新加载历史与已保存标记；旧对照不静默更新
''')
add(5,'偏好对照对象与企业期待查询','求职者或招聘方','/matches','pages/Matches.vue','service.py:TalentService.latest_preference',
    'job_id，当前角色与已有共享对照。','求职者可见本人简历；企业按既有匹配授权读取参与者与自己岗位期待。','''
F|选择目标岗位，准备发起双方偏好对照
A|GET /preferences/{job_id}/enterprise;GET /matches/participants|企业入口读取本岗位期待与既有对照参与者
D|核对岗位 owner，按 match_results 去重参与者，读取企业最新期待
R|200：企业期待与参与者摘要
F|企业选择已获共享来源；求职者使用本人 store 简历并明确共享
''','上述两接口均要求岗位归属，求职者不通过这些接口任意读企业内部字段；求职侧选择自己材料，真正共享校验由 matches/run 完成。')
add(5,'确定性双向偏好对照生成','求职者或岗位所属招聘方','/matches','pages/Matches.vue','service.py:TalentService.run_match deterministic.py:match_preferences',
    'job_id、resume_id、share_with_job；双方已保存且允许共享的快照。','四态逐维结果、双方原文、规则版本与快照 id；不调用 LLM。','''
F|选择岗位和本人或已授权的简历，必要时确认本次共享
A|POST /matches/run|job_id、resume_id、share_with_job
D|读取岗位和简历、双方期待及已有共享或有效投递
C|双方已填报、口径一致且本次来源被明确授权|新期待未授权、缺少填报、岗位不可见则拒绝
K|检查偏好引擎配置和结果呈现提示
S|match_preferences 确定性逐维生成相符、部分相符、存在差异或无法判断
D|相同双方 submission 和 engine_version 复用；否则写 match_results 及审计
R|200：双方原文、四态与版本依据
F|按角色呈现结果，不显示精确匹配百分比，不阻止投递或自动筛人
''','企业不能用旧对照授权读取求职者未来的新期待；使用精确已共享 submission 或本次有效投递快照。')
add(5,'偏好对照历史与过期标记','双方参与者','/matches','pages/Matches.vue','service.py:TalentService.visible_matches',
    '当前 actor；可选 match id。','只向双方展示共享历史，outdated 提醒重新确认。','''
F|进入对照记录或选中历史结果
A|GET /matches|当前参与方身份
D|筛选 enterprise_owner 或 candidate_owner 为本人的 match_results
S|比较最新双方 submission 与当前维度版本，计算 outdated
R|200：历史与过期标记
A|GET /matches/{id}|需要按需打开单份结果时调用
S|从 visible_matches 再次核对可见性
R|200：单份历史或 404
F|展开当时原文；更新期待后提示重新对照而不是改写历史
''')
add(5,'求职者单岗位对照','求职者','/fit 选择已提供岗位','pages/Reports.vue components/ReportView.vue','service.py:TalentService.fit service.py:TalentService.evaluate',
    'resume_id、job_id。','本人 fit_reports、技能依据、相对差距与岗位诊断。','''
F|选择本人简历与可见已确认岗位，点击开始岗位对照
A|POST /fit/analyze|resume_id、job_id
D|读取 active_resume 与可见岗位画像
C|岗位已确认、可见且简历属于本人|无权或失效目标返回错误
M|同源证据分析，默认 DeepSeek 官方，确定性补齐技能与维度结果
S|生成 fit_summary、差距锚点与岗位诊断，移除企业面试追问输出
D|写 fit_reports，保存岗位、量规和配置快照
R|200：个人岗位对照
F|展示具体岗位成对参照、依据与缺少描述，分析不会自动投递
''')
add(5,'粘贴JD与手工画像的个人对照','求职者','/fit 粘贴目标 JD','pages/Reports.vue','service.py:TalentService.fit agents.py:AgentGateway.jd',
    'resume_id、jd、title；解析失败可使用 manual_profile。','本人私人岗位参照及 fit_reports，不创建企业招聘发布。','''
F|粘贴完整目标 JD；可选择手工核对画像
A|POST /fit/analyze|resume_id、jd、title、可选 manual_profile
M|无手工画像时解析脱敏 JD；有画像时跳过模型解析
C|手工画像含技能且引用来自 JD，或自动解析成功|JD_PARSE_FAILED 时允许用户手工确认后再提交
D|写 candidate owner 的已确认私人 job_profiles
M|用同源量规对照本人简历，校验证据和呈现
D|写 fit_reports，记录来源及版本
R|200：个人对照结果
F|展示私人参照标记，不提供向虚拟企业自动投递的入口
''','私人岗位写入与分析并非同一大事务；分析失败可能已留下个人岗位参照，不代表企业收到材料。')
add(5,'求职岗位对照历史阅读','求职者','/fit 对照记录','pages/Reports.vue components/ReportView.vue','job_fit.py:refresh_fit_result',
    '当前本人空间；前端按 resume_id、job_id 和选中记录过滤。','历史 fit_reports 与当前展示政策下的派生摘要。','''
F|打开对照记录或刷新
A|GET /fit/reports|本人身份
D|查询本人 fit_reports
S|refresh_fit_result 更新派生展示摘要，不重新调用模型
R|200：历史结果及原版本来源
F|本地筛选简历、岗位与记录，展开技能原文及差距解释
''')
add(5,'多岗位契合度后台分析','求职者','/compare 岗位契合度与推荐顺序','components/JobFitComparison.vue','comparison_tasks.py:ComparisonTasks.submit comparison_tasks.py:ComparisonTasks.run job_fit.py:evaluate_target',
    'resume_id、job_ids（1～20）或 job_texts（2～20）、request_id。','202 持久任务与逐岗位结果；推荐顺序仅针对本人选择的岗位。','''
F|选择已有岗位或粘贴多份 JD，固定本次 request_id
A|POST /compare/tasks|resume_id、job_ids 或 job_texts、request_id
D|读取本人有效简历、目标版本及同请求任务
C|同一简历无冲突运行且槽位可用|同编号内容变化、超限或不同分析运行中拒绝
D|写 job_comparison_runs：queued、输入快照、fingerprint 与 DeepSeek 来源
S|提交两路有界线程池，持久任务先返回
R|202：任务 id、status、total
W|后台依次处理尚未完成目标，每份开始前核对账号和简历版本
M|固定 DeepSeek 官方评估目标，quote 和结构校验后形成证据结果
D|逐目标写进度、已完成结果及错误，确定性 rank_results 排序
D|完成后标记 completed、partial 或 failed；重启遗留任务标记 interrupted
E|结束 worker，不依赖浏览器持续连接
F|调用历史与进度查询，按约 4 秒间隔恢复运行进度
''','契合摘要依据技术和项目证据；缺少描述单独提示，没有可判断依据不算低契合。不是对求职者跨人排名。')
add(5,'多岗位比较历史与进度读取','求职者','/compare 分析历史','components/JobFitComparison.vue','comparison_tasks.py:ComparisonTasks.get comparison_tasks.py:ComparisonTasks.list',
    '当前本人 actor，按需 task id。','最近 50 次任务及已完成结果，不返回 worker 私有输入和指纹。','''
F|打开页面读取历史，选择记录；运行中在可见页面轮询
A|GET /compare/runs|本人身份
D|读取 job_comparison_runs 最近 50 条本人记录
S|present_comparison 输出公开结果，去除 targets、resume_snapshot、fingerprint 和 owner
R|200：任务历史与派生契合摘要
A|GET /compare/tasks/{id}|集成或按需查询单任务
D|核对 owner，读取相应任务
R|200：同一任务公开进度
F|按当前 resumeId 和 epoch 过滤迟到响应，展示成功项和逐目标错误
''','当前组件常用 GET /compare/runs 恢复整体历史，不应误写为每次必调单任务 GET。')
add(5,'多岗位比较失败项重试','求职者','/compare 重试未完成岗位','components/JobFitComparison.vue','comparison_tasks.py:ComparisonTasks.retry comparison_tasks.py:ComparisonTasks.submit',
    '原 task id、新 request_id。','新 retry_of 任务，保留已完成结果，只处理未完成目标。','''
F|选择 partial、failed 或 interrupted 历史，点击重试
A|POST /compare/tasks/{id}/retry|request_id
D|核对原任务归属、状态与原输入快照
C|简历与目标内容 fingerprint 未变化|COMPARISON_INPUT_CHANGED 要求完整重新分析，不能混合版本
D|复用成功结果，新建 queued 任务并关联 retry_of
S|提交后台，按相同 request_id 幂等返回同一重试任务
R|202：新任务及已保留结果
W|跳过已有 job_ref，只分析未完成岗位
M|DeepSeek 分析与来源校验
D|保存新结果、errors 与最终状态
E|后台结束
F|继续查询进度；网络结果不明保留同一 request_id
''')
add(5,'多岗位同步比较兼容接口','求职者集成调用','无默认独立按钮','components/JobFitComparison.vue','service.py:TalentService.compare job_fit.py:targets_for job_fit.py:rank_results',
    'resume_id、job_ids 或 job_texts。','同步返回并保存 job_comparison_runs；前端默认已改用后台任务。','''
F|集成调用者明确使用同步接口
A|POST /compare/rank|resume_id、岗位来源列表
D|检查本人有效简历和可访问目标
M|逐目标执行 DeepSeek 证据评估，单目标错误独立记录
S|对成功结果做确定性 rank_results，不把缺少证据记为低契合
D|保存 job_comparison_runs 与错误清单
R|200：completed、partial 或 failed 记录
F|展示同步响应；默认 Vue 组件使用 compare/tasks 减少超时
''')
add(5,'已确认能力报告比较','招聘方','/compare 已确认报告比较','pages/Compare.vue','service.py:TalentService.ranking',
    'job_id；前端最多勾选 4 位对照证据。','每份简历最新报告中已经确认的记录，按稳定排序键比较，同键并列。','''
F|选择企业岗位，打开已确认报告比较
A|GET /candidates/ranking|job_id
D|核对岗位归属及材料授权，按简历取最新 ability_reports
S|仅留下最新报告状态为已确认者，按 sort_key 排序，同键并列
R|200：报告与 rank、维度原文
F|呈现岗位关系，最多选四位并排阅读证据，不自动晋级或淘汰
''','该既有功能仍存在，但招聘 AI 与资料卡不产生跨候选人排名。最新报告被打回时不会回退旧已确认报告补位。')
add(5,'已确认报告比较CSV导出','招聘方','/compare 导出 CSV','pages/Compare.vue store.ts','service.py:TalentService.csv_export service.py:TalentService.ranking',
    'job_id。','当次授权可访问的已确认比较 CSV，含使用说明与安全文本。','''
F|在安全呈现检查通过后点击导出 CSV
A|GET /candidates/export|job_id
D|重新核对岗位与材料可用性，取最新已确认报告
S|复用 ranking 与呈现配置，csv_export 处理表格内容及安全转义
R|200：text/csv、UTF-8 BOM、附件名
F|download 保存文件，文件为当时快照而非实时共享链接
''')
add(5,'同类岗位参考基准生成与查看','招聘方生成、求职者查看可见岗位','治理基准操作、/compare 参照基准','pages/Governance.vue pages/Compare.vue','service.py:TalentService.build_benchmark service.py:TalentService.valid_benchmarks',
    'job_id；同企业、同方向、同来源类别的已确认岗位。','每技能至少 20 个独立岗位的区间基准；不足时明确说明。','''
F|企业维护者明确构建目标岗位基准
A|POST /benchmarks/build|job_id，普通企业范围兼容入口
D|读取本企业同方向同 data_origin 已确认岗位，按岗位去重技能样本
C|每项技能至少来自 20 个不同岗位|不足项不建基准，不拿重复技能凑样本
D|写 role_benchmarks：样本岗位 id、分布、区间、sampling_method、rubric_version
R|200：records 与样本不足说明
F|求职者对可见已确认岗位查看基准
A|GET /fit/benchmark|job_id
D|检查公开可见性，过滤当前量规和 distinct-job-v1 的有效基准
R|200：有效区间；无样本则 INSUFFICIENT_SAMPLES
F|展示来源及样本量，缺样本不显示虚构参照
''','当前治理页面的管理员构建入口是 /admin/governance/jobs/{id}/{operation}，见监管模块；不是伪装企业身份调用普通接口。')

add(6,'岗位已投递状态与防重提示','求职者','/jobs','pages/Jobs.vue components/ApplyDialog.vue','hiring.py:Hiring.list hiring.py:Hiring.apply',
    '本人 applications 摘要及所选 job id。','岗位卡片与详情直接显示已投递，提交重复时再明确提示。','''
F|进入岗位页时加载本人投递摘要
A|GET /applications|本人普通用户会话
D|按 candidate_owner 读取 applications，返回摘要
R|200：本人投递列表
F|以 job_id 与非终态投递关联标记已投递，点击时引导我的投递
F|未知或缓存过期时仍由 apply 后端重复校验，不能只依赖按钮禁用
''','已投递是与具体企业岗位关联的业务状态，不在页面加载时无故弹全局错误。重复提交错误由 APPLICATION_EXISTS 返回。')
add(6,'简历授权投递','求职者','/jobs 投递弹窗','components/ApplyDialog.vue','hiring.py:Hiring.apply',
    'job_id、resume_id、expected_job_version、request_id、consent_resume、share_preferences、introduction。','submitted 投递，保存当次简历、岗位及可选期待快照。','''
F|选择简历、核对共享正文、可选留言和期待，明确勾选授权
A|POST /applications|岗位和简历 id、画像版本、request_id、授权与留言
D|BEGIN IMMEDIATE 检查幂等编号、活跃投递、岗位和简历
C|认证企业岗位可投递、画像版本一致且授权为真|重复活跃投递、岗位变化或未授权则拒绝
S|复制本次脱敏简历和 JD；仅按勾选复制本人共享期待
D|写 applications：submitted、version=1、快照、consent、events 和审计
R|200：投递详情；同请求同内容返回既有投递
F|关闭弹窗并标记已投递；网络结果不明先查询列表核对
''','一次 AI 岗位分析不构成投递；共享简历与共享期待是不同授权项。不会把求职者后续私人修改自动推给企业。')
add(6,'投递列表检索与进展详情','投递双方','/applications','pages/Applications.vue','hiring.py:Hiring.page hiring.py:Hiring.public',
    'offset、limit、job_id、q、status；选中 application id。','本企业或本人参与的分页进展、事件、授权材料和期待。','''
F|进入应聘与邀请，筛选岗位、名称或进展
A|GET /applications/page|offset、limit、q、status、可选 job_id
D|按 env 和参与方查询 applications 并统计总数
S|public 摘要裁剪私有字段，根据当前授权返回可用信息
R|200：items、total
F|选中投递，发起详情读取
A|GET /applications/{id}|投递 id
D|再次核对 owned、状态和当前授权，读取事件、消息和快照
R|200：详情与可执行动作所需 version
F|展示时间线与双向期待，可见页约 30 秒刷新且隔离迟到响应
''')

def hiring_action(title, role, action, condition, state, explanation):
    add(6,title,role,'/applications、/messages 上下文操作','pages/Applications.vue pages/Messages.vue',
        'hiring.py:Hiring.change',f'action={action}、text、expected_version、request_id。',f'{state}；事件、业务版本及审计一并更新。',f'''
F|确认 {title}，保留当前 version 与 request_id
A|POST /applications/{{id}}/actions|action={action}、text、expected_version、request_id
D|事务读取投递；同编号同指纹直接复用，避免重复动作
C|身份与状态允许：{condition}|越权、过期版本或终态返回 403 或 409
S|脱敏处理说明，应用状态迁移规则
D|{state}，追加 events、requests，version 加一并写审计
R|200：更新投递详情
F|更新操作按钮和时间线；不确定是否成功时重读详情
''',explanation)

hiring_action('企业邀请沟通','认证招聘方','invite','企业方且 submitted，邀请文字至少两字','status=invited，保存邀请正文和时间','邀请发出不代表求职者接受，普通消息仍不能发送。')
hiring_action('求职者接受沟通邀请','求职者','accept','本人投递且 invited','status=accepted，开启普通聊天条件','必须由求职者主动接受；企业不能替代接受。')
hiring_action('求职者婉拒邀请','求职者','decline','本人投递且 invited','status=declined，清理招聘资料卡和招聘 AI 历史','进入终态后停止普通沟通并结束授权访问。')
hiring_action('企业结束未接受的应聘','认证招聘方','reject','企业方且 submitted 或 invited','status=rejected，清理招聘资料卡和招聘 AI 历史','AI 建议不会自动执行此动作；必须由企业明确操作。')
hiring_action('求职者撤回投递授权','求职者','withdraw','本人投递且 submitted、invited 或 accepted','status=withdrawn，清理招聘资料卡和招聘 AI 历史','即使企业或岗位暂停，本人仍可撤回；企业导入衍生简历后续不可访问。已下载文件无法远程追回。')
hiring_action('双方结束已建立的沟通','投递双方','close','本人或企业参与方且 accepted','status=closed，清理招聘资料卡和招聘 AI 历史','与单纯关闭聊天侧栏不同；这是不可继续发消息的投递终态。')
add(6,'投递内主动同步最新期待','投递双方','/applications 双方期待、消息详情','pages/Applications.vue pages/Messages.vue','hiring.py:Hiring.change hiring.py:Hiring.preference',
    'action=refresh_preferences、expected_version、request_id；本人最新已保存并同意共享的期待。','仅更新本方快照与事件；对方未来私人期待仍不自动泄露。','''
F|本人保存新期待后，明确点击同步最新期待
A|POST /applications/{id}/actions|action=refresh_preferences、expected_version、request_id
D|检查投递版本与状态，再读取本方目标的最新已共享偏好
C|状态为 submitted、invited 或 accepted 且存在可共享期待|无期待、终态或版本冲突拒绝
D|只替换本方 preferences 快照；求职侧补记共享同意和更新时间
D|追加同步事件、幂等记录、版本和审计
R|200：双方当前授权期待，口径可用时派生四态对照
F|展示更新结果；填偏好与同步是两个独立操作
''')
add(6,'消息中心会话分页与搜索','投递双方','/messages','pages/Messages.vue messages.ts','hiring.py:Hiring.page hiring.py:Hiring.conversations',
    'q、offset、limit；前端只看未读过滤。','参与方会话摘要、投递状态、总数和 unread_total。','''
F|打开消息中心，搜索时约 250ms 防抖，加载更多用 offset
A|GET /messages/conversations/page|q、offset、limit
D|按参与方分页读取 applications 会话及未读信息
R|200：items、total、unread_total
F|更新左侧会话列表，本地未读过滤；选择会话后 GET 投递详情
A|GET /applications/{id}|会话对应投递 id
D|核对参与身份与材料可见性，读取消息及邀请状态
R|200：当前详情
F|展示聊天和岗位期待侧栏；窄屏切换单面板
''','GET /messages/conversations 是保留的非分页入口，前端默认使用 page；不等同于 WebSocket 订阅。')
add(6,'消息中心普通消息发送','已接受邀请的投递双方','/messages','pages/Messages.vue request-id.ts','hiring.py:Hiring.change',
    'text、expected_version、request_id；每次会话最多 200 条。','追加脱敏消息、更新自己阅读游标、投递业务版本和审计。','''
F|检查已接受状态，发送文本；不确定网络重试复用同 request_id
A|POST /applications/{id}/messages|text、expected_version、request_id
D|事务校验参与身份、请求指纹与业务版本
C|status=accepted、授权可用、文字不少于两字且未超 200 条|未接受、终态、版本冲突或超限拒绝发送
S|脱敏消息正文，保留发送方 side 与时间
D|追加 messages，推进自己 message_reads，version 加一并写审计
R|200：更新后的投递与消息
F|清空已确认发送内容、保留其他会话草稿，对方通过轮询获取消息
''')
add(6,'消息阅读回执与未读提醒','投递双方','/messages、全局消息提醒','pages/Messages.vue messages.ts App.vue','hiring.py:Hiring.read hiring.py:Hiring.unread_total',
    'message_count、invitation_at；当前可见窗口与会话。','本方单调不回退的阅读游标与未读总量，不改变投递业务版本。','''
F|全局约 20 秒查询提醒，消息页可见时约 5 秒更新
A|GET /messages/unread;GET /messages/conversations|未读计数与保留非分页会话入口；默认会话页用 page
D|按当前参与身份汇总未读消息与尚未读邀请
R|200：total 或会话摘要
F|只在当前可见聊天且确有未读时标记已读
A|POST /messages/conversations/{id}/read|message_count、invitation_at
D|事务检查阅读数量未超过当前消息数；游标取 max
D|只写本方 message_reads 或 invitation_seen，不改 version、updated_at 与对方游标
R|200：更新阅读信息的详情
F|修正本地未读数；不得用较旧的已读响应覆盖更晚的聊天内容
''','邀请阅读与接受邀请不同；已读不会自动接受。轮询在隐藏页面暂停，不声称即时服务器推送。')
add(6,'会话草稿与聊天详情抽屉','投递双方','/messages','pages/Messages.vue messages.ts','',
    '本地当前会话 id、输入草稿、窗口宽度及滚动位置。','切换会话保留内存草稿，阅读原文与期待抽屉，快捷问题填入输入框。','''
F|切换会话前将当前输入保存到内存 Map，以投递 id 隔离
F|切换到目标会话时恢复该会话草稿，防止错发给另一人
F|按窗口宽度使用三栏、详情抽屉或手机会话切页
F|打开详情时管理焦点与 Escape 关闭；接近底部时才自动滚至新消息
F|引用面试追问只填入草稿，用户点击发送后才走消息发送接口
''','本功能没有独立后端写入；草稿不自动持久化到服务端、不自动发给对方。材料内容来自已授权投递详情，不另开公共简历访问。')

add(7,'企业资质待审与历史查询','平台工作人员','/admin/enterprise-reviews','pages/EnterpriseVerification.vue','enterprise_verification.py:EnterpriseVerification.list',
    'admin scope Cookie；当前环境。','企业资质申请、状态及处理依据，证明材料通过独立受控下载读取。','''
F|进入企业资质审核页
A|GET /enterprise-reviews|管理员独立会话
H|核对工作人员身份并按环境查询申请
R|200：申请列表和上次核验说明
F|区分 pending、approved、rejected、revoked，选中申请核对信息
''')

def enterprise_decision(title, decision, valid, status, effect):
    add(7,title,'平台工作人员','/admin/enterprise-reviews','pages/EnterpriseVerification.vue',
        'enterprise_verification.py:EnterpriseVerification.review platform_admin.py:PlatformAdmin.record',
        f'decision={decision}、reason（去空格至少 5 字符）。',f'企业申请状态 {status}，保留核验依据及审核人员。',f'''
F|填写处理依据，明确点击 {title}
A|POST /enterprise-reviews/{{id}}|decision={decision}、reason
H|读取目标及该账号最新申请
C|{valid}，且理由至少 5 字符|状态已变化返回 VERIFICATION_CONFLICT；理由不足 REVIEW_REASON
H|更新 enterprise_submissions 为 {status}，追加 enterprise_review_events
H|{effect}
H|记录 platform_admin_events 审核操作
R|200：更新后的申请
F|替换对应卡片并显示局部成功或错误；按钮不能无反馈
''','只处理当前账号最新且处于允许状态的申请；上传文件本身不替代人工资质判断。')

enterprise_decision('企业资质审核通过','approve','最新申请处于 pending','approved','保留账号会话，后续工作空间切换按已通过状态重新检查')
enterprise_decision('企业资质审核退回','reject','最新申请处于 pending','rejected','删除该账号企业 workspace 的旧会话，保留普通求职空间隔离')
enterprise_decision('撤销企业认证','revoke','最新申请处于 approved','revoked','删除该账号企业 workspace 的旧会话；公开岗位后续查询和招聘操作重新拒绝')
add(7,'平台监管概览','平台工作人员','/admin','pages/Admin.vue','platform_admin.py:PlatformAdmin.overview',
    '管理员会话，当前 env。','普通账号数、暂停账号、待审企业、岗位和报告数量。','''
F|打开监管概览
A|GET /admin/overview|admin scope
H|按环境统计账号与最新 pending 企业申请
D|统计 job_profiles、resumes、ability_reports、fit_reports
R|200：聚合数量
F|展示概览；不把统计数量当模型效果或录用转化率
''')
add(7,'账号监管分页查询','平台工作人员','/admin/accounts','pages/Admin.vue','platform_admin.py:PlatformAdmin.accounts',
    'offset、limit（最大 50）。','脱敏手机号、角色、暂停状态及企业资质摘要。','''
F|进入账号监管并翻页
A|GET /admin/accounts|offset、limit
H|按环境分页 accounts，关联最新企业申请
S|只输出脱敏手机号和监管必要摘要，不返回密码哈希
R|200：items、total
F|展示状态并根据账号性质允许暂停或恢复
''')

def account_moderation(title, operation, effect):
    add(7,title,'平台工作人员','/admin/accounts','pages/Admin.vue',
        'platform_admin.py:PlatformAdmin.account_action',f'operation={operation}、reason（至少 5 字符）。',effect,f'''
F|确认 {title} 并填写处理依据
A|POST /admin/accounts/{{id}}/{{operation}}|operation={operation}、reason
H|检查同环境目标账号
C|目标非管理员且处理依据完整|ADMIN_PROTECTED 或 MODERATION_REASON 时拒绝
H|{effect}，同事务追加 platform_admin_events
R|200：操作结果说明
F|刷新分页列表；恢复账号后仍需重新登录，不能复活旧会话
''')

account_moderation('暂停普通账号','suspend','设置 disabled=1 并删除该账号全部旧 sessions')
account_moderation('恢复普通账号','restore','设置 disabled=0，旧 sessions 不重新创建')
add(7,'岗位与简历监管列表','平台工作人员','/admin/jobs、/admin/resumes','pages/Admin.vue','platform_admin.py:PlatformAdmin.records',
    'kind=jobs/resumes、offset、limit。','当前环境分页资料摘要，关联脱敏归属信息。','''
F|选择岗位监管或求职资料监管并翻页
A|GET /admin/records/{kind}|kind、offset、limit
D|读取当前环境 job_profiles 或 resumes 摘要
H|通过 account_workspaces 查询归属账号并脱敏
R|200：items、total
F|只展示摘要；正文须用户明确点开独立详情请求
''')
add(7,'监管资料正文查看与留痕','平台工作人员','/admin/jobs、/admin/resumes 资料详情','pages/Admin.vue','platform_admin.py:PlatformAdmin.detail platform_admin.py:PlatformAdmin.record',
    'kind=jobs/resumes、目标 id。','岗位原文或整理简历正文的允许字段；敏感访问留痕。','''
F|在监管列表明确点击查看某份资料
A|GET /admin/records/{kind}/{id}|kind、id
D|按当前环境读取目标记录
C|目标存在且管理员权限有效|无目标 404，普通 Cookie 无法进入管理路由
H|写 platform_admin_events：查看资料及职责说明
R|200：限定字段正文，不返回私有路径
F|展示只读详情，关闭后不把正文存到浏览器持久存储
''')

def job_moderation(title, operation, status, explanation):
    add(7,title,'平台工作人员','/admin/jobs','pages/Admin.vue',
        'platform_admin.py:PlatformAdmin.job_action',f'operation={operation}、reason（至少 5 字符）。',f'moderation_status={status}，published=false。',f'''
F|点击 {title} 并填写依据
A|POST /admin/jobs/{{id}}/{{operation}}|operation={operation}、reason
D|BEGIN IMMEDIATE 读取企业所属岗位
C|目标确为企业招聘岗位且理由充分|不存在、私人参照或理由不足时拒绝
D|更新 moderation_status={status}、published=false、reason，并写业务审计
H|另写 platform_admin_events 管理操作留痕
R|200：published=false 与新监管状态
F|刷新岗位监管列表
''',explanation+' 业务库与认证操作日志分库写入，不能宣称两库原子事务。')

job_moderation('平台下架招聘岗位','hide','suspended','企业不能通过修改画像绕过平台暂停。')
job_moderation('解除岗位公开限制','restore','cleared','解除限制不自动公开，企业须再次主动发布。')
add(7,'平台工作人员操作记录查询','平台工作人员','/admin/events','pages/Admin.vue','platform_admin.py:PlatformAdmin.events',
    'offset、limit。','平台查看、下载、审核与治理操作的人员、时间和理由。','''
F|打开操作记录并翻页
A|GET /admin/events|offset、limit
H|按工作人员账号的当前环境分页 platform_admin_events
R|200：items、total
F|展示操作、资源和依据，与 Agent 调用审计分开阅读
''')
add(7,'治理目标岗位选择','平台工作人员','/admin/governance','components/GovernanceTarget.vue pages/Governance.vue','platform_admin.py:PlatformAdmin.governance_jobs',
    'q、offset、limit（最大 100）。','跨企业治理所需最小岗位摘要和 owner，不代替普通企业登录。','''
F|在治理页搜索并选择目标企业岗位
A|GET /admin/governance/jobs|q、offset、limit
D|只选 enterprise owner 岗位，分页返回最小字段
H|记录跨企业治理目标查看
R|200：items、total
F|后续质量、基准和记忆操作都携带明确目标 id
''')
add(7,'调用审计与成本元数据查看','工作人员；企业兼容接口按本人范围','/admin/governance 审计页签','pages/Governance.vue','platform_admin.py:PlatformAdmin.governance_audit',
    '管理员 offset、limit；企业范围 /audit/summary。','调用元数据、累计估算成本、告警数量，不包含提示词、密钥和原始模型响应。','''
F|按当前权限选择平台或本空间审计入口
A|GET /admin/governance/audit;GET /audit/summary|管理员分页；普通企业接口仅本人 owner
D|查询 audit_logs，聚合 cost_cny 与告警计数
S|平台响应按字段白名单裁剪 detail，不泄露 prompt、正文或凭据
H|平台访问时记跨账号审计操作
R|200：logs、total 或本人摘要、cost_cny、alerts
F|展示费用口径和失败阶段；无价格配置不虚构精确成本
''','当前产品治理路由进入管理端；普通企业 summary 接口为受 owner 限制的兼容路径，非全局管理权限。')
add(7,'审计记录导出','平台工作人员','/admin/governance 导出审计','pages/Governance.vue','',
    '已经通过治理审计接口加载的当前页白名单日志。','管理员在浏览器导出当前页元数据 JSON，无额外后端写入。','''
F|管理员点击导出当前页元数据
L|将已加载白名单 logs 序列化为 JSON Blob 并保存，不再发请求
F|提示本地文件已保存；不宣称包含未加载分页
''','日志读取的前后端交互见“调用审计与成本元数据查看”。企业旧版 Markdown 下载是另一个独立功能，不由管理员导出按钮调用。')
add(7,'岗位材料与审阅质量看板','工作人员或岗位所属招聘方','/reports 质量看板、/admin/governance','components/QualityPanel.vue','platform_admin.py:PlatformAdmin.governance_quality service.py:TalentService.quality_summary',
    'job_id。','最新非打回报告分布、证据不足比例、人工改动比例与最近有记录日期趋势。','''
F|选择目标岗位，展开材料与审阅质量
A|GET /quality/summary;GET /admin/governance/quality|招聘方本人岗位或管理端指定目标二选一
D|查询可见 ability_reports、review_events、batches
S|每简历取最新非打回记录，聚合维度、改动和最近 30 个有记录日期
H|管理端跨企业查看写操作留痕
R|200：counts、dimensions、trend、统计口径与 note
F|展示空样本和数据范围，不称为模型准确率或录用结论
''')
add(7,'校准记忆查询与人工确认或删除','工作人员或记忆所属招聘方','/admin/governance 记忆页签','pages/Governance.vue','platform_admin.py:PlatformAdmin.governance_memory platform_admin.py:PlatformAdmin.governance_memory_action',
    'job_id 或 memory id；操作 confirm/delete，工作人员须 reason。','确认后后续分析可引用的校准模式，或软删除；不覆盖历史报告快照。','''
F|按权限读取指定岗位记忆或本人记忆
A|GET /admin/governance/memory;GET /memory|管理员传 job_id；企业接口读取本人记录
D|查询 calibration_memory，管理端先验证目标企业岗位
R|200：记忆与确认、删除状态
F|人工核对来源，明确确认或删除；管理端填写理由
A|POST /admin/governance/memory/{id}/{operation};PUT /memory/{id}|管理端 operation=confirm/delete、reason；企业 action=confirm/delete
C|目标归属及处理依据合法|越权或非法动作拒绝
D|更新 confirmed=true 或 deleted_at，来源仍关联 review_events
H|管理操作写职责留痕
R|200：新记忆状态
F|刷新列表；仅后续评估使用已确认、未删除的记忆
''')
add(7,'治理构建同类岗位基准','平台工作人员','/admin/governance 岗位治理','pages/Governance.vue','platform_admin.py:PlatformAdmin.governance_job_action service.py:TalentService.build_benchmark',
    '目标岗位 id、operation=benchmark、reason。','目标企业范围内有效样本的 role_benchmarks，或不足说明。','''
F|选择明确企业岗位，填写依据后点击构建基准
A|POST /admin/governance/jobs/{id}/{operation}|operation=benchmark、reason
D|读取目标企业岗位，确定其真实 owner
H|记录平台跨企业治理操作及理由
S|在该企业 owner 范围调用 build_benchmark，按同方向来源与独立岗位取样
D|满足每技能至少 20 岗位才保存 role_benchmarks
R|200：records 或样本不足说明
F|显示结果，不把管理员工作空间当作目标企业数据来源
''')
add(7,'连续打回后恢复岗位分析','工作人员或岗位所属招聘方','治理恢复操作；企业兼容入口','pages/Governance.vue','platform_admin.py:PlatformAdmin.governance_job_action service.py:TalentService.is_paused',
    '管理员目标 id、operation=resume、reason；企业路径含 job_id。','写分析恢复审计；解除后续任务的暂停判定，不自动重跑报告。','''
F|核对标准与连续打回原因，再明确恢复
A|POST /admin/governance/jobs/{id}/{operation};POST /assessments/resume-job/{job_id}|管理员 operation=resume、reason；企业兼容入口本人岗位
D|核对目标岗位，检查写入可用状态
H|管理端记录恢复操作及依据
D|在目标企业 owner 范围追加分析恢复审计
R|200：恢复记录成功
F|重新勾选简历提交任务；不会自动复活中断或旧报告
''')
add(7,'证据分析漂移监控','工作人员或企业接口调用者','治理漂移检查','pages/Governance.vue','platform_admin.py:PlatformAdmin.governance_job_action service.py:TalentService.evaluate',
    '管理端目标岗位 id、operation=drift、reason；企业兼容路径检查本人范围。','锚定样本重评差异比例；少于十份时跳过并说明。','''
F|明确发起漂移检查，管理端指定目标岗位及依据
A|POST /admin/governance/jobs/{id}/{operation};POST /audit/drift-check|管理端 operation=drift；普通企业为本人范围
D|读取最新已确认锚定报告，按简历去重
C|至少 10 份锚定样本|不足直接返回 skipped=true，不调用模型
M|最多 20 份按当前量规重新评估，默认 DeepSeek 官方
S|按维度统计变化；管理端比较 tier 与 tier_range
D|写漂移监控审计，任一维变化比例大于 0.2 标告警
R|200：rates、skipped
F|展示监控结果；不覆盖锚定报告，不视为人员能力下降
''','管理员按指定岗位检查，企业旧接口按本人报告范围检查，两者口径并非完全相同；这是可能消耗模型费用的显式操作。')
add(7,'标准配置读取与版本保存','管理员编辑；普通角色读取允许配置','/admin/governance 配置页签、业务初始化','pages/Governance.vue store.ts','configuration.py:Configuration.get configuration.py:Configuration.save',
    'name、配置 JSON 与新 version。','校验后的新配置版本；历史报告与匹配快照保留。','''
F|选择配置名称并读取内容
A|GET /config/{name}|name 如 rubric、priorities、preferences、presentation
K|读取允许名称的配置，拒绝任意文件路径
R|200：配置 JSON
F|管理端修改 JSON 与新版本号，先做 JSON 语法检查
A|PUT /config/{name}|管理员 scope、完整配置 JSON
C|名称、结构、版本及跨配置纪律合法|同版本覆盖或字段不合法拒绝
K|Configuration.save 保存校验通过的新版本
D|记录配置变更审计
R|200：新配置
F|刷新当前工作空间配置；不静默重算旧结果
''')
add(7,'标准配置整包导出','平台工作人员','/admin/governance 标准包','pages/Governance.vue','configuration.py:Configuration.pack',
    '管理员会话，无业务正文。','包含版本清单的 standard-pack JSON。','''
F|点击导出标准包
A|GET /config/packs/export;GET /config/packs|默认 export，packs 为同处理函数兼容入口
K|读取整套标准配置并生成 pack_version
R|200：标准包 JSON
L|前端创建 Blob 保存 standard-pack.json，不导出业务简历数据库
''')
add(7,'标准配置整包校验导入','平台工作人员','/admin/governance 标准包','pages/Governance.vue','configuration.py:Configuration.import_pack',
    '用户选择标准包 JSON，解析后作为请求体发送。','通过整包与跨项约束后导入标准配置，记录版本审计。','''
F|选择本地 JSON 文件并解析，语法无效在前端提示
A|POST /config/packs/import|完整标准包对象
C|配置结构、版本关系和呈现纪律通过服务端校验|非法包拒绝，不将文件名当受信任配置路径
K|Configuration.import_pack 写入验证后的配置集合
D|写配置变更审计与 pack_version
R|200：导入后配置包
F|刷新 rubric、展示配置与当前编辑器；旧报告保留原快照
''')
add(7,'敏感属性输入隔离自检','企业权限接口调用者；治理内置检查','治理检查入口或集成调用','pages/Governance.vue','main.py:bias_check security.py:redact',
    '内置成对敏感属性样本，无用户简历输入。','sanitized_inputs_equal 与说明，仅证明该样本输入隔离。','''
F|明确触发输入隔离检查
A|POST /audit/bias-check|无请求体
S|构造相同经历但性别、年龄等不同的内置样本
S|redact 后逐对比较，不调用模型
D|写敏感属性隔离检查审计，按是否相等记录正常或告警
R|200：pairs、note
F|展示范围说明；不宣称通过完整模型公平性或偏见评测
''','该接口要求企业能力，不能用管理员页面可见性推断所有普通接口均能跨企业调用。')
add(7,'岗位画像可辨识规则冒烟自检','企业权限接口调用者','治理检查入口或集成调用','pages/Governance.vue','main.py:selfcheck deterministic.py:parse_jd',
    '三条内置后端、前端、算法规则样例。','fixture_examples 与 fixture_accuracy，仅内置规则冒烟结果。','''
F|显式触发可辨识自检
A|POST /selfcheck/identifiability|无请求体
S|对三条固定样例调用 parse_jd，比较预期方向
S|计算 fixture_accuracy，不调用模型也不加载独立人工标注集
R|200：fixture_examples、fixture_accuracy、note
F|显示冒烟范围，不能宣传为生产画像准确率已达标
''')
add(7,'演示合成数据装载与旧入口说明','平台工作人员','/admin/governance 演示数据维护','pages/Governance.vue','seed.py:seed_account main.py:demo_seed',
    '管理员明确点击装载合成示例；当前环境和 actor。','按 seed_account 生成合成业务示例；旧 people 入口仅返回空数组。','''
F|维护者明确点击重新装载合成示例
A|POST /demo/seed|管理员独立会话
C|写入未维护且企业能力检查通过|维护期间拒绝写入
D|seed_account 写当前作用域的 synthetic 示例及关联记录
R|200：status=ok
F|刷新材料与治理界面；不会伪造真实用户投递
''','旧 /demo/people 兼容查询另见独立功能文档；点击装载不调用该查询，当前登录也不依赖演示人员列表。')
add(7,'非生产合成数据备份清理','平台工作人员','/admin/governance 演示数据维护','pages/Governance.vue','service.py:TalentService.purge',
    'env=当前 dev/demo、confirmation=清理合成数据。','先备份业务 SQLite，再按引用次序清理合成业务，返回统计与备份名。','''
F|填写完整确认语句并明确点击备份清理
A|POST /maintenance/purge|env、confirmation
C|确认语句正确且显式为当前非生产环境|生产环境或错误确认语句拒绝
S|设置 maintenance 阻止并行新业务写入
P|SQLite backup 写入带时间戳的业务库备份
D|检查真实数据未引用待清理合成记录，否则拒绝并回滚
D|按依赖次序删除 synthetic 业务，失效基准；执行 foreign_key_check 并写审计
P|事务成功后清理对应私有原文文件
S|finally 退出维护状态，异常仍恢复状态
R|200：counts、backup；失败返回原因
F|刷新工作空间与治理列表，显示备份文件名
''','这是业务数据库备份清理，不等同于认证库、证明文件和运行配置的完整灾备；不在本次文档生成时实际执行。')
add(7,'服务健康与模型可用状态读取','所有初始化客户端及维护者','工作空间初始化、运行检查','store.ts','main.py:health',
    'GET 请求无业务输入。','status、env、llm_mode、配置可用性、maintenance 与认证说明。','''
F|初始化或维护检查读取健康接口
A|GET /health|不要求业务身份
K|读取当前 Settings、ModelCatalog 可用元数据及维护标志
R|200：状态摘要，不返回 API key
F|显示服务状态；配置存在不等于模型远端请求必然成功
''','此健康接口不执行真实模型调用，也不是数据库完整性或所有依赖的深度探测。')
add(7,'企业本人审计Markdown下载兼容入口','企业权限接口调用者','显式集成客户端，无当前管理端按钮','store.ts','main.py:audit_export',
    '本人企业会话；与管理端本地 JSON 导出相互独立。','可下载当前企业 owner 范围的审计 Markdown 附件。','''
F|企业客户端明确请求本人范围审计下载
A|GET /audit/export|本人企业会话
D|只查询 owner 为本人的 audit_logs
S|格式化事件、时间、结果和 detail 为 Markdown
R|200：text/markdown 附件
F|download 保存审计文件，下载失败呈现错误
''','此接口不读取其他企业日志，不是管理端导出按钮的后续请求；管理端仅导出已经加载的白名单元数据。')
add(7,'旧演示人员列表兼容查询','平台工作人员或旧集成调用方','无当前页面登录入口','store.ts','main.py:people',
    '独立管理员会话；仅为历史调用兼容。','固定空列表，不创建或切换任何模拟身份。','''
F|旧集成客户端显式查询演示人员
A|GET /demo/people|无请求体，要求管理员会话
S|返回固定空列表，不查询真实人员和登录凭据
R|200：空数组
F|按空列表结束，无后续人员冒用或角色切换
''','与演示数据装载独立；当前普通登录使用账号凭据与验证码，不提供从演示人员列表直接登录的能力。')


def route_inventory():
    result = {}
    for node in ast.walk(ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = ', '.join(ast.unparse(a.annotation) for a in node.args.args if a.annotation)
        for d in node.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name) and d.func.value.id == 'api'
                    and d.func.attr in {'get','post','put','delete','patch','head','options'}
                    and d.args and isinstance(d.args[0], ast.Constant)):
                continue
            key = d.func.attr.upper() + ' ' + d.args[0].value
            result[key] = dict(handler=node.name, line=node.lineno, params=params)
    return result


def public_route(key):
    path = key.split(' ', 1)[1]
    return path == '/health' or path == '/auth/options' or path == '/auth/sms/send' or any(
        path.endswith(suffix) for suffix in ('/login/password','/login/phone','/password/reset')) or path == '/auth/register'


def requests(feature):
    return list(dict.fromkeys(key for step in feature['trace'] if step[0]=='A' for key in step[1].split(';')))


def guard(keys):
    if all(public_route(k) for k in keys):
        return '公开认证或状态入口：检查参数、来源与该入口限流；不要求已有业务会话'
    return '按接口依赖校验 Cookie、scope、角色和账号状态；已有会话写请求还检查 CSRF'


LANES = {'F':'前端 Vue 与用户交互','L':'浏览器本地状态','A':'后端 FastAPI 接口与认证',
         'S':'后端领域服务与规则','C':'后端领域服务与规则','W':'后端领域服务与规则',
         'E':'后端领域服务与规则','D':'业务 SQLite','H':'认证 SQLite',
         'K':'配置文件','P':'私有文件或受控外部资源','M':'受控模型调用'}


def label(text):
    # Quote every label; ASCII node IDs avoid old Mermaid Unicode identifier bugs.
    # CJK does not contain spaces: ordinary textwrap leaves huge single-line diamonds.
    lines, current, width = [], '', 0
    for token in re.findall(r'[A-Za-z0-9_./{}=:+,-]+|\s+|.', text):
        if token.isspace():
            token = ' '
        chunks = textwrap.wrap(token, width=40, break_long_words=True, break_on_hyphens=False) if len(token)>40 else [token]
        for chunk in chunks:
            size = sum(2 if ord(c)>127 else 1 for c in chunk)
            if current and width+size>40:
                lines.append(current.strip()); current=''; width=0
            current += chunk; width += size
    if current: lines.append(current.strip())
    lines = lines or ['']
    return html.escape('<br/>'.join(lines), quote=True).replace('&lt;br/&gt;','<br/>')


def flowchart(feature):
    nodes, edges = {}, []
    previous = None
    spawn = response = None
    counter = 0
    def node(kind, text, decision=False):
        nonlocal counter
        counter += 1
        id = f'n{counter}'
        nodes[id] = (kind, text, decision)
        return id
    def edge(a, b, text=''):
        if a: edges.append(f'    {a} -->{("|"+text+"|") if text else ""} {b}')
    service_start = feature['trace'][0][0] == 'S'
    start = node('S' if service_start else 'F',('服务启动：' if service_start else '用户操作：')+feature['title'])
    previous = start
    for step in feature['trace']:
        kind, text = step[:2]
        extra = step[2] if len(step)>2 else ''
        if kind == 'E':
            end = node('E', text)
            edge(previous,end)
            previous = response
            continue
        if kind == 'W':
            current = node(kind,text)
            if spawn: edges.append(f'    {spawn} -. 后台调度 .-> {current}')
            else: edge(previous,current)
            previous = current
            continue
        if kind == 'C':
            current = node(kind,text,True)
            edge(previous,current)
            error = node('A','终止当前分支：'+extra+'；返回明确错误或跳过结果')
            error_ui = node('F','显示错误或跳过说明；保留已存在记录，按具体功能核对或重试')
            edge(current,error,'否');edge(error,error_ui,'HTTP 响应')
            previous = current
            continue
        if kind == 'A':
            current = node(kind,text.replace(';','；')+'：'+extra)
            edge(previous,current,'HTTP 请求')
            gate = node('A',('入口参数、来源与限流检查通过？' if all(public_route(k) for k in text.split(';')) else '会话、scope、角色、账号及适用的 CSRF 检查通过？'),True)
            edge(current,gate)
            failure = node('F','请求未通过：呈现 401 / 403 / 422 等实际错误；网络不明先核对服务器状态')
            edge(gate,failure,'未通过或请求失败')
            previous = gate
            continue
        current = node(kind,text)
        prior_kind = nodes[previous][0] if previous else ''
        edge(previous,current,'通过' if previous and nodes[previous][2] else '数据或响应' if kind in {'R','D','H','K','P','M'} else '')
        previous = current
        if kind == 'S': spawn = current
        if kind == 'R': response = current
    lines = ['flowchart TB']
    lane_names = list(dict.fromkeys(LANES.get(kind,'后端 FastAPI 接口与认证') for kind,_,_ in nodes.values()))
    for i, name in enumerate(lane_names):
        lines.append(f'    subgraph lane{i}["{name}"]')
        for id,(kind,text,decision) in nodes.items():
            if LANES.get(kind,'后端 FastAPI 接口与认证') != name: continue
            shape = ('{"','"}') if decision else ('["','"]')
            lines.append(f'        {id}{shape[0]}{label(text)}{shape[1]}')
        lines.append('    end')
    lines.extend(edges)
    lines += ['    classDef frontend fill:#eef6f4,stroke:#46766a,color:#143b32',
              '    classDef backend fill:#edf1fc,stroke:#6371ab,color:#233263',
              '    classDef storage fill:#fff6e6,stroke:#a37b36,color:#664711',
              '    classDef model fill:#f5edfb,stroke:#9367ac,color:#58326e']
    for key, kinds in [('frontend',{'F','L'}),('backend',{'A','S','C','W','E','R'}),('storage',{'D','H','K','P'}),('model',{'M'})]:
        ids = [id for id,(kind,_,_) in nodes.items() if kind in kinds]
        if ids: lines.append('    class '+','.join(ids)+' '+key)
    return '\n'.join(lines)


def sequence(feature, inventory):
    used = {step[0] for step in feature['trace']}
    actors = [('U','用户或调用者'),('F','前端 Vue 或显式集成客户端')]
    if 'A' in used: actors += [('A','FastAPI'),('G','认证与参数依赖')]
    if used-{'F','L'}: actors += [('S','领域服务与规则')]
    for kind,name in [('W','进程内后台线程池'),('D','业务 SQLite'),('H','认证 SQLite'),('K','版本配置'),('P','私有文件或外部服务'),('M','模型 Gateway 与提供方'),('L','浏览器内存或本地存储')]:
        if kind in used: actors.append((kind,name))
    lines = ['sequenceDiagram','    autonumber'] + [f'    participant {key} as {name}' for key,name in actors]
    service_start = feature['trace'][0][0] == 'S'
    lines.append('    Note over S: 服务生命周期启动本功能，独立于浏览器' if service_start else '    U->>F: '+feature['title'])
    executor = 'S'
    open_request = False
    parallel = frontend_done = False
    for index,step in enumerate(feature['trace']):
        kind,text = step[:2]
        extra = step[2] if len(step)>2 else ''
        safe = lambda s: s.replace('\n',' ').replace(';','；')
        text,extra = safe(text),safe(extra)
        if kind == 'F':
            if frontend_done: continue
            if service_start:
                lines.append('    U->>F: 用户返回页面查询现有任务'); service_start=False
            lines.append('    F->>F: '+text)
        elif kind == 'L': lines += ['    F->>L: '+text,'    L-->>F: 本地状态或下载结果']
        elif kind == 'A':
            if open_request: raise ValueError('Missing response before next request: '+feature['title'])
            keys = step[1].split(';')
            lines += ['    F->>A: '+text+'；'+extra,'    A->>G: '+guard(keys),
                      '    break 认证、参数或来源检查不通过',
                      '        G-->>A: 拒绝原因',
                      '        A-->>F: 相应 HTTP 状态与 detail.code/message',
                      '        F-->>U: 提示处理，不继续该分支',
                      '    end',
                      '    G-->>A: 校验通过，获得接口需要的上下文',
                      '    A->>S: '+ ' / '.join(dict.fromkeys(inventory[k]['handler'] for k in keys))+'；按所选入口或并行子请求分别调用']
            executor='S';open_request=True
        elif kind == 'R':
            if index+1 < len(feature['trace']) and feature['trace'][index+1][0] == 'W':
                lines.append('    par HTTP 返回与前端独立继续')
                parallel=True
            lines += ['    S-->>A: '+text,'    A-->>F: '+text]
            open_request=False
            if parallel:
                end = next(i for i in range(index+1,len(feature['trace'])) if feature['trace'][i][0]=='E')
                for tail in feature['trace'][end+1:]:
                    if tail[0]!='F': raise ValueError('Unexpected non-frontend asynchronous tail')
                    lines.append('    F->>F: '+safe(tail[1]))
                lines += ['    F-->>U: '+safe(feature['output']), '    and 后台执行与独立存储结果']
                frontend_done=True
        elif kind == 'W':
            lines += ['    Note over S,W: 后台已由线程池调度，可在 202 返回前后开始；不等待前端轮询',
                      '    W->>W: '+text]
            executor='W'
        elif kind == 'E':
            lines.append('    Note over W,D: '+text if 'D' in used else '    W->>W: '+text)
            if parallel:
                lines.append('    end'); parallel=False
            executor='S'
        elif kind == 'C':
            lines += ['    '+executor+'->>'+executor+': 校验 '+text,
                      '    break 条件不满足',
                      '        '+executor+'-->>A: '+extra if 'A' in used and executor=='S' else '        Note over '+executor+': '+extra,
                      '        A-->>F: 明确错误或 skipped，当前分支终止' if 'A' in used and executor=='S' else '        Note over '+executor+': 保存失败状态，等待客户端查询',
                      '    end']
        elif kind in {'D','H','K','P','M'}:
            lines += ['    '+executor+'->>'+kind+': '+text,'    '+kind+'-->>'+executor+': '+{'D':'查询结果或事务提交状态','H':'认证记录或提交结果','K':'已校验的配置元数据','P':'受控文件或服务执行结果','M':'结构化输出，引用须由服务端核对'}[kind]]
        elif kind == 'S':
            lines.append('    '+executor+'->>'+executor+': '+text)
            if '线程池' in text and 'W' in used: lines.append('    S->>W: pool.submit；保存任务 id，异步执行')
        else: raise ValueError(kind)
    if open_request: raise ValueError('Unclosed request: '+feature['title'])
    if not frontend_done: lines.append('    F-->>U: '+feature['output'])
    return '\n'.join(lines)


def code_link(path, symbol=None, prefix='../../'):
    file = ROOT/path
    if not file.exists(): raise ValueError('Missing source '+str(file))
    line=1
    if symbol:
        wanted=symbol.split('.')[-1]
        matches=[node for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and node.name==wanted]
        if not matches: raise ValueError('Missing symbol '+str(file)+':'+symbol)
        line=matches[0].lineno
    caption=path+((':'+symbol) if symbol else '')+f'（L{line}）'
    return f'[{caption}]({prefix}{quote(path,safe="/")}#L{line})'


def build():
    inventory=route_inventory()
    coverage={key:[] for key in inventory}
    modules={i:[] for i in range(1,len(MODULES)+1)}
    hashes={}
    for feature in FEATURES:
        module=feature['module'];index=len(modules[module])+1
        feature['id']=f'{module:02}-{index:02}'
        folder=f'{module:02}-{MODULES[module-1]}'
        filename=f'{index:02}-{feature["title"]}.md'
        feature['relative']=folder+'/'+filename
        keys=requests(feature)
        for key in keys:
            if key not in inventory: raise ValueError('Unknown API '+key+' in '+feature['title'])
            coverage[key].append(feature['relative'])
        frontend=[code_link('frontend/src/'+f) for f in feature['frontend']]
        backend=[]
        for ref in feature['backend']:
            path,_,symbol=ref.partition(':')
            backend.append(code_link('app/'+path,symbol or None))
        interface_rows=[]
        for key in keys:
            row=inventory[key]
            interface_rows.append(f'| `{key}` | `{row["handler"]}` | {code_link("app/main.py",row["handler"])} |')
        api_table=('| 后端接口 | 处理函数 | 路由源码 |\n| --- | --- | --- |\n'+'\n'.join(interface_rows)) if keys else '纯前端功能，无专属业务 HTTP 接口；受保护路由的通用身份初始化见账号模块，不为本功能虚构后端调用。'
        errors=[s[2] for s in feature['trace'] if s[0]=='C']
        error_text='\n'.join('- '+e+'。' for e in errors) or '- 无独立业务写入时，只展示已有授权数据或本地状态；查询失败保留错误说明，不伪造成功结果。'
        transport=('前端通过 `store.api`/`download` 访问同源 `/api` 前缀；表内路径为 FastAPI 注册路径。受保护请求携带会话 Cookie 与 `X-Session-Scope`，已有会话写请求携带 `X-CSRF-Token`。公开登录/注册、找回和健康入口按自身规则校验，不要求事先拥有业务会话。\n\n'
                   '图中一个调用框若列出多个路径，按“请求数据”及备注区分角色二选一、兼容入口、按需读取或同批并行子请求，并非一个合并接口；完整字段以源码模型为准。') if keys else ''
        body=f'''# {feature['id']} {feature['title']}

> 模块{NUMERALS[module-1]}：{MODULES[module-1]} · 核对日期：2026-10-18 · 当前代码分析，非生产验收结论。

[返回本模块](README.md) · [返回总目录](../README.md)

## 功能与边界

{feature['output']}

| 项目 | 说明 |
| --- | --- |
| 操作角色 | {feature['role']} |
| 页面或触发入口 | {feature['page']} |
| 输入与前置条件 | {feature['inputs']} |
| 结果与数据去向 | {feature['output']} |

{feature['notes']}

## 前后端调用契约

{api_table}

{transport}

## 完整业务流程图

图中按前端、接口认证、领域服务与实际依赖分区。实线表示调用、结果或数据传递；后台调度另用虚线。校验失败分支终止当次处理，不自动改写既有结果。

```mermaid
{flowchart(feature)}
```

## 前后端时序图

请求在 HTTP 响应后才交还前端；后台任务分支的结果由之后的查询获取。`break` 表示条件失败即退出该次交互。不同角色或兼容接口的路径并列是选用说明，不表示每次操作全部发送。

```mermaid
{sequence(feature,inventory)}
```

## 异常、授权与一致性

{error_text}

{('- HTTP 业务错误通常为 `detail.code/message`，参数错误另含字段信息；文件下载成功返回附件而非 JSON。401 清空当前范围身份，403/404 不展示越权材料。' + chr(10) + '- 网络超时只说明客户端未确认结果，不能推出服务端写入失败；只有具备 request_id 幂等契约的写接口才能按原编号安全核对/重试。普通写接口先读取实际状态。') if keys else '- 不把本地草稿、布局状态或视图切换误标为服务端已保存。'}

## 代码追踪与维护

前端入口：

{chr(10).join('- '+item for item in frontend)}

后端服务与依赖：

{chr(10).join('- '+item for item in backend) if backend else '- 本功能没有专属后端实现。'}

维护时先核对页面调用和 FastAPI 路由，再检查领域服务、授权、版本及数据结构；不得只修改图中的接口名称而保留旧业务语义。功能更改后重新执行文档生成与 Mermaid 兼容检查。总体背景参阅 [项目开发文档](../../docs/同频项目开发文档.md)。
'''
        target=OUT/folder/filename
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(body,encoding='utf-8')
        hashes[feature['relative']]=hashlib.sha256(target.read_bytes()).hexdigest()
        modules[module].append(feature)
    missing=[key for key,docs in coverage.items() if not docs]
    if missing: raise ValueError('Uncovered current backend routes:\n'+'\n'.join(missing))
    for module,features in modules.items():
        folder=OUT/f'{module:02}-{MODULES[module-1]}'
        rows='\n'.join(f'| {f["id"]} | [{f["title"]}]({quote(Path(f["relative"]).name)}) | {f["role"]} |' for f in features)
        (folder/'README.md').write_text(f'# 模块{NUMERALS[module-1]} {MODULES[module-1]}\n\n[返回总目录](../README.md)\n\n共 {len(features)} 个独立功能；每篇包含一张完整业务流程图及一张时序图。\n\n| 编号 | 独立功能文档 | 角色 |\n| --- | --- | --- |\n{rows}\n',encoding='utf-8')
    outline=[]
    for module,features in modules.items():
        folder=f'{module:02}-{MODULES[module-1]}'
        outline.append(f'## 模块{NUMERALS[module-1]} {MODULES[module-1]}\n\n共 {len(features)} 个功能。[模块目录]({quote(folder)}/README.md)\n\n'+'\n'.join(f'- [{f["id"]} {f["title"]}]({quote(f["relative"],safe="/")})' for f in features))
    total=len(FEATURES)
    (OUT/'README.md').write_text(f'''# 同频功能业务分析

核对日期：2026-10-18。依据当前 `app/`、`frontend/src/` 与 PRD/专题文档按真实业务分组。编号仅表示阅读顺序，无固定业务编码含义。

共 **{len(MODULES)} 个模块、{total} 个独立功能、{total*2} 张 Mermaid 图**。每份功能 Markdown 独立提供业务流程图和前后端时序图，覆盖入口、参数、认证、领域处理、存储、模型/文件依赖、结果回显与异常分支。

## 阅读与范围

- 按模块①～⑦顺序阅读下列目录，每个功能一个文件；模块目录与此总目录均可点击导航。
- 当前 Vue 3 前端为真实入口；旧 Streamlit 页面不作为当前事实。接口路径取自 FastAPI AST；同源部署请求另加 `/api`。
- 普通会话、管理员会话、企业 owner 与候选人 owner 分开；不因后台可查资料就放宽普通接口。
- 同步模型调用、进程内后台任务、确定性规则、纯前端视图分别标注；没有专属后端的功能明确写出，不虚构交互。
- 默认报告、招聘对话与岗位契合分析按代码使用 DeepSeek 官方；求职任务可使用所选模型。demo 本地规则不是远端真实模型调用。
- 对多个入口的合并标注代表角色二选一、兼容接口、同批并行或按需请求，详见每篇输入和备注；不是一次操作必调全部路径。
- 需求意图来自 [PRD](../docs/upstream/PRD-人才发掘Agent系统-v2.1.md) 与 [需求规格说明](../04-需求规格说明书-开发测试版.md)；后续认证、授权投递、消息及双端 AI 扩展以当前代码为准。未实现的外部人才搜索、外部平台自动触达、自动录用不画为已完成。
- [接口覆盖索引](接口覆盖索引.md)逐项映射当前 **{len(inventory)}** 个方法/路径；这是静态代码覆盖，不等于执行了全部业务测试。[校验记录](校验记录.md)记载实际图表检查结果。

{chr(10).join(outline)}

## 维护

运行 `.venv/Scripts/python.exe scripts/build_feature_analysis.py` 重新生成；再运行 `scripts/validate_feature_analysis.py` 进行链接、图数量与 Mermaid 10.6.1 / 11.17.2 兼容检查。脚本只静态读取代码与定义好的业务追踪，不导入应用、不读取 `.env` 或业务数据库，不调用真实模型、短信和清理接口。
''',encoding='utf-8')
    rows=[]
    for key,paths in sorted(coverage.items()):
        row=inventory[key]
        links='、'.join(f'[{Path(p).stem}]({quote(p,safe="/")})' for p in paths)
        rows.append(f'| `{key}` | `{row["handler"]}`（L{row["line"]}） | {links} |')
    (OUT/'接口覆盖索引.md').write_text('# 后端接口与独立功能覆盖索引\n\n[返回总目录](README.md)\n\n按当前 app/main.py AST 提取方法与路径；同一接口的不同动作可分别对应多个功能文档。重复映射不是重复后端接口。保留兼容路径与无默认页面入口的接口均在功能中明示。\n\n| 方法与后端路径 | 处理函数 | 对应独立功能 |\n| --- | --- | --- |\n'+'\n'.join(rows)+'\n',encoding='utf-8')
    manifest={'date':'2026-10-18','modules':len(MODULES),'features':total,'diagrams':total*2,
        'routes':len(inventory),'coverage':coverage,'documents':hashes,
        'module_counts':{MODULES[m-1]:len(fs) for m,fs in modules.items()}}
    artifacts=ROOT/'artifacts/feature-analysis';artifacts.mkdir(parents=True,exist_ok=True)
    (artifacts/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in {'coverage','documents'}},ensure_ascii=False))


if __name__=='__main__':
    build()
