"""Evaluate an independently annotated JSONL set. Never treats fixtures as a benchmark."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.settings import Settings
from app.service import TalentService
from app.models import JobInput,JobConfirmation,ResumeInput
from app.deterministic import mentions,match_preferences


def ratio(correct,total): return {'correct':correct,'total':total,'rate':correct/total if total else None}


def run(records,svc,repeats=3):
    actor='enterprise:benchmark'
    counters={name:[0,0] for name in ['screening_agreement','keyword_baseline_agreement','skill_accuracy','dimension_agreement','repeat_consistency','evidence_coverage','preference_reproducibility','profile_identifiability']}
    outputs=[];started=time.monotonic()
    def add(name,good):
        counters[name][0]+=int(good);counters[name][1]+=1
    for index,item in enumerate(records):
        human=item.get('human',{})
        entry={'id':item.get('id',str(index+1)),'status':'passed'}
        try:
            job=svc.create_job(JobInput(title=item.get('title','标注岗位'),jd=item['jd'],data_origin='real'),actor)
            job=svc.confirm_job(job['id'],JobConfirmation(profile=job['profile'],expected_version=job['version']),actor)
            resume=svc.create_resume(ResumeInput(name='匿名标注样本',text=item['resume'],data_origin='real'),actor)
            reports=[svc.evaluate(job,resume,actor) for _ in range(repeats)]
            report=reports[0]
            screen=next(r for r in svc.batch(job['id'],actor) if r['resume_id']==resume['id'])
            requirements=job['profile']['requirements']
            hits=sum(mentions(resume['text'],r['skill']) for r in requirements)
            baseline='高匹配' if requirements and hits==len(requirements) else '潜力' if hits else '存疑'
            if human.get('batch_tier'):
                add('screening_agreement',screen['tier']==human['batch_tier'])
                add('keyword_baseline_agreement',baseline==human['batch_tier'])
            if human.get('direction'):
                reverse=svc.gateway.jd('岗位要求：'+resume['text'])
                add('profile_identifiability',reverse['direction']==human['direction'])
            predicted={d['dimension_id']:d['tier'] for d in report['dimensions']}
            for id,tier in human.get('dimensions',{}).items():add('dimension_agreement',predicted.get(id)==tier)
            skill_levels={s['skill']:s['evidence_level'] for s in report['skill_levels']}
            for skill,level in human.get('skill_levels',{}).items():add('skill_accuracy',skill_levels.get(skill,0)==level)
            for d in report['dimensions']:
                if d['tier']!='insufficient':add('evidence_coverage',bool(d['evidence']) and all(q in resume['text'] for q in d['evidence']))
                tiers=[next((v['tier'] for v in r['dimensions'] if v['dimension_id']==d['dimension_id']),None) for r in reports]
                add('repeat_consistency',len(set(tiers))==1)
            if item.get('preferences'):
                cfg=svc.config.get('preferences');prefs=item['preferences']
                a={'dimension_version':cfg['version'],'dimensions':prefs['enterprise']}
                b={'dimension_version':cfg['version'],'dimensions':prefs['candidate']}
                runs=[match_preferences(a,b,cfg) for _ in range(repeats)]
                add('preference_reproducibility',all(r==runs[0] for r in runs[1:]))
                entry['preference_overall']=runs[0]['overall_tier']
            entry.update({'screening':screen['tier'],'keyword_baseline':baseline,'dimensions':predicted,'skill_levels':skill_levels})
        except Exception as exc:
            entry={'id':entry['id'],'status':'failed','error_code':getattr(exc,'code',type(exc).__name__)}
        outputs.append(entry)
        print(f'{index+1}/{len(records)} {entry["status"]}',flush=True)
    metrics={name:ratio(*value) for name,value in counters.items()}
    a,b=metrics['screening_agreement']['rate'],metrics['keyword_baseline_agreement']['rate']
    calls=[a for a in svc.db.list('audit_logs') if a['event_type']=='Agent 调用']
    return {'mode':svc.settings.llm_mode,'model':svc.settings.model if svc.settings.llm_mode=='deepseek' else 'local-demo-rules-1.0','rubric_version':svc.config.get('rubric')['version'],'sample_count':len(records),'failed_count':sum(r['status']=='failed' for r in outputs),'metrics':metrics,'baseline_advantage_pp':100*(a-b) if a is not None and b is not None else None,'llm_cost_cny':sum(r['detail'].get('cost_cny',0) for r in calls),'seconds':round(time.monotonic()-started,2),'cases':outputs,'note':'失败样本单列；任何失败均禁止宣称整体验收达标。未标注的指标为 null。初筛当前为确定性规则。可辨识率用同一 JD 提取器反向识别简历方向，须结合人工检查。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts'/'evaluation.json')
    parser.add_argument('--live',action='store_true',help='Use the configured DeepSeek model; incurs API costs.')
    args=parser.parse_args()
    content=args.dataset.read_bytes()
    records=[json.loads(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
    if not records:parser.error('标注集为空')
    if any(not all(k in r for k in ['jd','resume','human']) for r in records):parser.error('每行须包含 jd、resume、human')
    stamp=str(time.time_ns());folder=ROOT/'artifacts'/'evaluation-runs'/stamp
    folder.mkdir(parents=True)
    settings=Settings(data_dir=folder,env='dev',auto_seed=False)
    settings.llm_mode='deepseek' if args.live else 'demo';settings.vector=False
    if args.live and not settings.api_key:parser.error('未配置 DEEPSEEK_API_KEY')
    result=run(records,TalentService(settings))
    result['dataset_sha256']=hashlib.sha256(content).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(args.output.resolve()))
    if result['failed_count']:raise SystemExit(1)


if __name__=='__main__':main()
