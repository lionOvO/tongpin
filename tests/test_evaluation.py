from scripts.evaluate import run


def test_evaluation_does_not_invent_unannotated_metrics(client):
    records=[{'id':'fixture','jd':'后端开发岗位要求：熟悉 Python，熟悉 MySQL，本科。','resume':'专业：软件工程\n课程项目使用 Python 开发后端，并使用 MySQL 实现存储。','human':{'skill_levels':{'Python':2}}}]
    result=run(records,client.app.state.service)
    assert result['failed_count']==0
    assert result['metrics']['skill_accuracy']=={'correct':1,'total':1,'rate':1.0}
    assert result['metrics']['screening_agreement']['rate'] is None
    assert result['baseline_advantage_pp'] is None
    assert result['mode']=='demo' and result['llm_cost_cny']==0


def test_evaluation_failures_are_not_hidden(client):
    result=run([{'id':'invalid','jd':'无效','resume':'无效','human':{}}],client.app.state.service)
    assert result['failed_count']==1
    assert result['cases'][0]['status']=='failed'
    assert result['metrics']['skill_accuracy']['rate'] is None
