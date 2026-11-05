"""Bounded SSE bridge. Disconnecting the viewer never replays a business write."""
import json
import re
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from .errors import DomainError


class ReplyPreview:
    """Expose only the reply string, never JSON fields, tool args or reasoning."""
    def __init__(self, emit, max_chars=3000):
        self.raw = ''; self.text = ''; self.emit = emit; self.max_chars = max_chars

    def feed(self, delta):
        self.raw += delta
        match = re.match(r'^\s*\{\s*"reply"\s*:\s*"', self.raw)
        if not match: return
        value = self.raw[match.end():]; end = 0; escaped = False
        for i, char in enumerate(value):
            if not escaped and char == '"': break
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            end = i + 1
        value = value[:end]
        # Incomplete escapes (including unicode) are retained until the next chunk.
        while value:
            try:
                text = json.loads('"' + value + '"')[:self.max_chars]
                # Avoid exposing a split UTF-16 surrogate from a provider escape.
                if any(0xD800 <= ord(c) <= 0xDFFF for c in text): return
                if text != self.text:
                    self.text = text; self.emit(text)
                return
            except (ValueError, TypeError):
                value = value[:-1]


class WorkspaceStreams:
    def __init__(self):
        self.pool = None
        self.slots = threading.BoundedSemaphore(4)

    def start(self):
        if self.pool is None:
            self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='workspace-agent')

    def open(self, work, authorize):
        if self.pool is None: raise DomainError('AI_BUSY', '协作服务尚未就绪，请稍后重试。', 503)
        if not self.slots.acquire(blocking=False):
            raise DomainError('AI_BUSY', '协作任务较多，请稍后重试。', 429)
        events = queue.Queue(maxsize=64); detached = threading.Event()

        def emit(kind, value):
            if detached.is_set(): return
            try: events.put_nowait((kind, value))
            except queue.Full:
                # The DB contains current state; a slow/disconnected viewer can refresh.
                detached.set()

        def worker():
            try: emit('done', work(emit))
            except Exception as error:
                emit('error', {'code': error.code if isinstance(error, DomainError) else 'AI_FAILED',
                    'message': error.message if isinstance(error, DomainError) else '本次处理未完成，请重试。'})
            finally: self.slots.release()

        try: self.pool.submit(copy_context().run, worker)
        except RuntimeError:
            self.slots.release()
            raise DomainError('AI_BUSY', '服务正在重启，请稍后重试。', 503) from None

        def stream():
            try:
                yield ': connected\n\n'
                while not detached.is_set():
                    authorize()  # Recheck the viewer even while waiting on provider/tool work.
                    try: kind, value = events.get(timeout=1)
                    except queue.Empty:
                        yield ': keepalive\n\n'; continue
                    yield 'event: ' + kind + '\ndata: ' + json.dumps(value, ensure_ascii=False) + '\n\n'
                    if kind in {'done', 'error'}: return
            except DomainError:
                yield 'event: error\ndata: {"code":"AUTH_REQUIRED","message":"登录状态已变化，请重新登录。"}\n\n'
            finally: detached.set()
        return stream()

    def close(self):
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
