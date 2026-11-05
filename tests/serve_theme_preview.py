"""Whole-site palette QA, isolated synthetic data; never calls external providers."""
import uvicorn
from fastapi.testclient import TestClient
from serve_recruiter_preview import app
from auth_helpers import sign_in

def denied(*args, **kwargs):
    raise AssertionError('Theme preview must never contact a model.')

with TestClient(app) as candidate:
    sign_in(candidate, '13800000980')
    resume = candidate.get('/resumes').json()[0]
    application = candidate.get('/applications').json()[0]
    result = candidate.post('/ai/workspaces', json={'resume_id': resume['id'], 'job_id': application['job_id']})
    assert result.status_code == 200, result.text

app.state.service.gateway.call = denied
app.state.service.gateway.tool_step = denied
if __name__ == '__main__': uvicorn.run(app, host='127.0.0.1', port=8029)
