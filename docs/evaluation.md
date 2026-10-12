# 人工标注集评测

业务测试验证程序契约，不能证明模型准确率。原始资料要求的初筛一致率、熟练度准确率、重复一致性与 baseline 对比，应使用独立人工标注集。

`scripts/evaluate.py` 为标注集提供可执行的入口。每行 JSON 为一份简历与一个岗位，至少 20 对起步。建议两位标注者独立标注并解决分歧；不要把内置示例当作验收集。

格式如下（字段可省略，未标注指标输出 null）：

```json
{"id":"case-001","title":"后端工程师","jd":"完整岗位描述……","resume":"完整简历文字……","human":{"batch_tier":"潜力","direction":"后端开发","dimensions":{"D3":"B4"},"skill_levels":{"Python":2}},"preferences":{"enterprise":{"direction":"后端开发","autonomy":"在协作中自主推进","learning":"适度探索新技术"},"candidate":{"direction":"后端开发","autonomy":"在协作中自主推进","learning":"适度探索新技术"}}}
```

在项目目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate.py 私有标注集.jsonl
```

默认检查本地演示规则。使用 `--live` 才调用 `.env` 中的 DeepSeek，产生 API 费用；单个样本重复分析三次，成本预算仍生效。评测数据库放在 `artifacts/evaluation-runs`，与当前演示数据隔离；该目录及报告不入库。其内容仍须按真实简历材料管理。

报告包含数据集哈希、模式、量规版本、样本数、失败数、token 费用汇总及逐项计数。证据覆盖率仅统计已给结论的维度；insufficient 不被算作错误定级。重复一致性要求三次逐维完全一致，采用比“允许同侧变动”更严格的口径。

关键词 baseline 为：岗位所有技能均被提及为高匹配，部分为潜力，均无为存疑。当前初筛实现为确定性行为规则，不能把其一致率说成 LLM Agent 的一致率。方向反向恢复复用 JD 解析器，是内部实验口径，须人工审查。任一失败都会单列并以非零状态退出，禁止选择性剔除后宣称达标。

人工改档率由运行审计看板记录。无人工标注集、无真实模型调用或样本不足时，不判断 SRS 中的数值目标已经达到。
