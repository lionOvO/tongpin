"""Isolated phase-three UI provider; synthetic data and no external model calls."""
import json
import time
from uuid import uuid4
import uvicorn
from serve_recruiter_preview import app


def tool_step(messages, tools, **kwargs):
    context = json.loads(messages[1]['content'])
    query = context.get('message', '')
    turns = [m for m in messages if m['role'] == 'tool']
    def call(name, args):
        return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': str(uuid4()), 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]}
    time.sleep(.45)
    if not turns: return call('read_application', {})
    materials = json.loads(turns[0]['content'])['texts'][0]
    quote = next(line for line in materials.splitlines() if line.startswith('项目：'))
    if len(turns) == 1: return call('read_job_requirements', {})
    if len(turns) == 2: return call('read_business_context', {})
    if len(turns) == 3: return call('find_application_evidence', {'query': quote[3:11]})
    if len(turns) == 4: return call('prepare_interview_outline', {'resume_quotes': [quote]})
    if '测试失败' in query: raise RuntimeError('synthetic provider failure')
    text = '简历写明：' + quote + '\n\n可围绕实际负责的任务、实现过程和验证方法进一步了解。企业背景仅表示业务需要，可以与本人讨论是否参与。'
    output = {'reply': text, 'kind': 'answer', 'citations': [{'source': 'resume', 'quote': quote}],
        'questions': ['请介绍这段经历中实际负责的工作，以及如何核对实现结果。']}
    encoded = json.dumps(output, ensure_ascii=False)
    for index in range(0, len(encoded), 7):
        if kwargs.get('on_delta'): kwargs['on_delta'](encoded[index:index+7])
        time.sleep(.035)
    return {'role': 'assistant', 'content': encoded}


app.state.service.gateway.tool_step = tool_step
if __name__ == '__main__': uvicorn.run(app, host='127.0.0.1', port=8028)
