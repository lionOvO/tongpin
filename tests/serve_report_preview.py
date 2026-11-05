"""Isolated browser QA: synthetic resumes, delayed local evaluation, no model calls."""
import time
import uvicorn
from serve_recruiter_preview import app

app.state.service.settings.llm_mode = 'demo'
evaluate = app.state.service.evaluate


def slow_evaluate(*args):
    time.sleep(12)
    return evaluate(*args)


app.state.service.evaluate = slow_evaluate

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8019)
