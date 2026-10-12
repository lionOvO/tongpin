from .models import JobInput, JobConfirmation, ResumeInput, PreferenceInput, MatchInput, BriefInput, AssessmentInput, ReviewInput

ENT = "enterprise:demo"
PEOPLE = [
 {"actor":"candidate:lin","name":"林知远","subtitle":"后端开发 · 应届","text":"专业：软件工程，本科\nGPA 3.6/4.0\n技能：Python、FastAPI、MySQL、Redis、Docker\n主导校园交易平台项目，使用 Python 和 FastAPI 构建后端，支撑日均 3000 单\n独立负责知识检索项目，使用 MySQL 保存文档，接口性能优化从 800ms 至 120ms\n课程项目中使用 Redis 实现登录态缓存\n使用 Docker 完成项目容器化部署\n后端开发实习：负责 API 开发，功能已上线","prefs":["后端开发","在协作中自主推进","持续学习与探索","适度团队协作","定期沟通","迭代与规划并行","能力拓展","复杂问题解决"]},
 {"actor":"candidate:zhou","name":"周语宁","subtitle":"全栈开发 · 应届","text":"专业：计算机科学，本科\nGPA 3.7/4.0\n技能：TypeScript、React、Python、Docker\n独立开发社区活动项目，使用 React 与 TypeScript 实现活动报名，作品被 200 位用户使用\n课程项目使用 Python 实现数据统计\n使用 Docker 部署个人项目\n前端实习：负责组件开发与协作沟通","prefs":["全栈开发","在协作中自主推进","适度探索新技术","频繁跨团队协作","及时持续反馈","迭代与规划并行","能力拓展","复杂问题解决"]},
 {"actor":"candidate:chen","name":"陈予安","subtitle":"数据与算法 · 应届","text":"专业：数据科学，本科\nGPA 3.4/4.0\n技能：Python、SQL、PyTorch\n课程项目使用 Python 和 PyTorch 实现文本分类\n使用 SQL 完成公开数据统计\n参与数据分析项目，负责清洗与可视化工作","prefs":["数据与算法","高度自主探索","持续学习与探索",None,None,"稳定有序",None,"探索未知方案"]}
]
JOBS = [
 {"title":"Python 后端工程师","jd":"Python 后端工程师（校招）\n岗位职责：参与知识协作产品的后端开发，负责 API 与数据服务。\n任职要求：本科，熟练使用 Python，熟悉 FastAPI 和 MySQL。\n加分项：了解 Redis、Docker，有相关项目经历。\n团队重视协作和技术积累。","prefs":["后端开发","在协作中自主推进","持续学习与探索","适度团队协作","定期沟通","迭代与规划并行","能力拓展","复杂问题解决"],"ambience":"我们以小团队协作交付为主，定期进行代码评审与技术交流，鼓励主动表达与持续学习。"},
 {"title":"前端开发工程师","jd":"前端开发工程师（校招）\n岗位职责：负责用户工作台与协作产品的前端开发。\n任职要求：本科，熟练使用 React 和 TypeScript，熟悉 JavaScript。\n加分项：了解 Docker，有组件库或产品项目经验。","prefs":["前端开发","在协作中自主推进","适度探索新技术","频繁跨团队协作","及时持续反馈","迭代与规划并行","能力拓展","复杂问题解决"],"ambience":"设计和开发共同评审需求，采用定期迭代节奏，重视可访问性与使用体验。"},
 {"title":"数据应用工程师","jd":"数据应用工程师（校招）\n岗位职责：开发文本处理与数据分析应用。\n任职要求：本科，熟悉 Python、SQL 和 PyTorch。\n加分项：有数据分析或机器学习项目。","prefs":["数据与算法","高度自主探索","持续学习与探索","适度团队协作","定期沟通","稳定有序","专业积累","探索未知方案"],"ambience":"围绕数据应用开展探索，讨论方法的适用范围，先验证再迭代。"}
]


def seed(service):
    if service.settings.env == "prod" or service.db.list("job_profiles"):
        return
    dims = service.config.get("preferences")
    people = []
    for person in PEOPLE:
        r = service.create_resume(ResumeInput(name=person["name"],text=person["text"]),person["actor"])
        service.submit_preference(PreferenceInput(side="candidate",resume_id=r["id"],dimensions={d["id"]:v for d,v in zip(dims["dimensions"],person["prefs"])},dimension_version=dims["version"],share_with_counterparty=True),person["actor"])
        people.append(r)
        service.create_resume(ResumeInput(name=person["name"],text=person["text"]),ENT)
    previous = service.settings.llm_mode
    try:
        service.settings.llm_mode="demo"  # Seed never consumes API tokens.
        for item in JOBS:
            j=service.create_job(JobInput(title=item["title"],jd=item["jd"]),ENT)
            j=service.confirm_job(j["id"],JobConfirmation(profile=j["profile"],expected_version=j["version"]),ENT)
            service.brief(BriefInput(job_id=j["id"],answers={"source":"业务需要"}),ENT)
            service.submit_preference(PreferenceInput(side="enterprise",job_id=j["id"],dimensions={d["id"]:v for d,v in zip(dims["dimensions"],item["prefs"])},ambience_text=item["ambience"],dimension_version=dims["version"],share_with_counterparty=True),ENT)
            for r in people: service.run_match(MatchInput(job_id=j["id"],resume_id=r["id"]),ENT)
            service.batch(j["id"],ENT)
        first=service.db.list("job_profiles",owner=ENT)[-1]
        reports=service.assess(AssessmentInput(job_id=first["id"],resume_ids=[r["id"] for r in service.db.list("resumes",owner=ENT)]),ENT)["reports"]
        # Human gate stays pending; synthetic demo reports are never auto-confirmed.
    finally:
        service.settings.llm_mode=previous

