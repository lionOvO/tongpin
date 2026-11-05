"""Two-party WebRTC signaling. Media never passes through the application API.

SQLite transactions arbitrate busy/accept races across tabs and workers. SDP/ICE
are temporary, participant-only, bounded, and erased as soon as a call ends.
"""
import time
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from .db import now
from .errors import DomainError


class CallStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    application_id: str = Field(min_length=1, max_length=100)
    client_id: UUID
    request_id: UUID


class CallSync(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: UUID
    after: int = Field(default=0, ge=0, le=250)


class CallAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: UUID
    action: Literal['accept', 'decline', 'end', 'failed', 'connected']


class IceCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate: str = Field(max_length=4096)
    sdpMid: str | None = Field(default=None, max_length=100)
    sdpMLineIndex: int | None = Field(default=None, ge=0, le=100)
    usernameFragment: str | None = Field(default=None, max_length=256)


class CallSignal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: UUID
    request_id: UUID
    kind: Literal['offer', 'answer', 'ice']
    sdp: str | None = Field(default=None, min_length=1, max_length=64000)
    candidate: IceCandidate | None = None

    @model_validator(mode='after')
    def valid_payload(self):
        if self.kind == 'ice':
            if self.candidate is None or self.sdp is not None:
                raise ValueError('ICE 信号格式不正确')
        elif self.sdp is None or self.candidate is not None:
            raise ValueError('SDP 信号格式不正确')
        return self


class VideoCalls:
    RING_SECONDS = 45
    LEASE_SECONDS = 40

    def __init__(self, hiring):
        self.hiring = hiring
        self.db = hiring.db

    def owned(self, id, actor, cx):
        row = self.db.get('video_calls', id, cx)
        if not row or actor not in (row['caller'], row['callee']):
            raise DomainError('NOT_FOUND', '通话不存在或无权访问。', 404)
        return row

    def finish(self, row, reason, cx):
        if row['status'] == 'ended':
            return row
        stamp = time.time()
        return self.db.update('video_calls', row['id'], {
            'status': 'ended', 'reason': reason, 'ended_at': now(),
            'duration_seconds': max(0, int(stamp - row['connected_ts'])) if row.get('connected_ts') else 0,
            'signals': [], 'leases': {},
        }, cx)

    def refresh(self, row, cx):
        if row['status'] == 'ended':
            return row
        application = self.db.get('applications', row['application_id'], cx)
        if not application or application['status'] != 'accepted' or not self.hiring.available(application):
            return self.finish(row, 'unavailable', cx)
        stamp = time.time()
        if row['status'] == 'ringing' and stamp - row['created_ts'] >= self.RING_SECONDS:
            return self.finish(row, 'missed', cx)
        leases = row['leases']
        if any(stamp - value > self.LEASE_SECONDS for value in leases.values()):
            return self.finish(row, 'disconnected', cx)
        return row

    def control(self, row, actor, client_id):
        return row['clients'].get(actor) == str(client_id)

    def public(self, row, actor, client_id=None):
        application = self.db.get('applications', row['application_id'])
        mine = actor == row['caller']
        candidate = application and actor == application['candidate_owner']
        return {'id': row['id'], 'application_id': row['application_id'], 'status': row['status'],
            'direction': 'outgoing' if mine else 'incoming', 'reason': row.get('reason'),
            'created_at': row['created_at'], 'answered_at': row.get('answered_at'),
            'connected_at': row.get('connected_at'), 'ended_at': row.get('ended_at'),
            'duration_seconds': row.get('duration_seconds', 0),
            'job_title': application['job_title'] if application else '岗位沟通',
            'counterpart': (application['company_name'] if candidate else application['candidate_name']) if application else '对方',
            'can_control': self.control(row, actor, client_id) or (not mine and row['status'] == 'ringing')}

    def active_rows(self, cx):
        rows = cx.execute("SELECT * FROM video_calls WHERE env=? AND json_extract(payload,'$.status')!='ended'",
                          (self.db.settings.env,)).fetchall()
        return [self.db.decode(row) for row in rows]

    def start(self, data, actor):
        self.hiring.svc.writable()
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            application = self.hiring.owned(data.application_id, actor, cx)
            if application['status'] != 'accepted' or not self.hiring.available(application):
                raise DomainError('CALL_UNAVAILABLE', '双方接受沟通后，才能发起视频通话。', 409)
            callee = application['candidate_owner'] if actor == application['owner'] else application['owner']
            existing = cx.execute("SELECT * FROM video_calls WHERE env=? AND owner=? AND json_extract(payload,'$.request_id')=?",
                (self.db.settings.env, actor, str(data.request_id))).fetchone()
            if existing:
                row = self.refresh(self.db.decode(existing), cx)
                if row['application_id'] != data.application_id or not self.control(row, actor, data.client_id):
                    raise DomainError('CALL_REQUEST_CONFLICT', '通话请求已用于其他会话。', 409)
                return self.public(row, actor, data.client_id)
            # Do not roll back housekeeping when rejecting a busy call below.
            busy = False
            for row in self.active_rows(cx):
                row = self.refresh(row, cx)
                if row['status'] != 'ended' and {actor, callee} & {row['caller'], row['callee']}:
                    busy = True
            if busy:
                result = None
            else:
                recent = cx.execute("SELECT COUNT(*) FROM video_calls WHERE env=? AND owner=? AND json_extract(payload,'$.created_ts')>?",
                    (self.db.settings.env, actor, time.time() - 60)).fetchone()[0]
                if recent >= 5:
                    raise DomainError('CALL_RATE_LIMIT', '呼叫过于频繁，请稍后再试。', 429)
                row = self.db.insert('video_calls', {'caller': actor, 'callee': callee,
                    'request_id': str(data.request_id), 'status': 'ringing', 'created_ts': time.time(),
                    'clients': {actor: str(data.client_id)}, 'leases': {actor: time.time()}, 'signals': [],
                }, actor, application['data_origin'], cx=cx, application_id=application['id'])
                result = self.public(row, actor, data.client_id)
        if result is None:
            raise DomainError('CALL_BUSY', '你或对方正在通话中，请稍后再试。', 409)
        return result

    def active(self, actor, client_id):
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            rows = [self.refresh(row, cx) for row in self.active_rows(cx)
                    if actor in (row['caller'], row['callee'])]
            return [self.public(row, actor, client_id) for row in rows if row['status'] != 'ended']

    def history(self, application_id, actor):
        self.hiring.owned(application_id, actor)
        with self.db.transaction() as cx:
            rows = cx.execute('SELECT * FROM video_calls WHERE env=? AND application_id=? ORDER BY created_at DESC LIMIT 20',
                (self.db.settings.env, application_id)).fetchall()
            return [self.public(self.refresh(self.db.decode(row), cx), actor) for row in rows]

    def action(self, id, data, actor):
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            row = self.refresh(self.owned(id, actor, cx), cx)
            if row['status'] == 'ended':
                return self.public(row, actor, data.client_id)
            action = data.action
            if action == 'accept':
                if actor != row['callee']:
                    raise DomainError('CALL_ACTION', '只能由被呼叫方接听。', 403)
                if row['status'] == 'ringing':
                    row = self.db.update('video_calls', id, {'status': 'accepted', 'answered_at': now(),
                        'clients': {**row['clients'], actor: str(data.client_id)},
                        'leases': {**row['leases'], actor: time.time()}}, cx)
                elif not self.control(row, actor, data.client_id):
                    raise DomainError('CALL_OTHER_TAB', '这通电话已在另一个窗口接听。', 409)
            elif action == 'decline' and actor == row['callee'] and row['status'] == 'ringing':
                row = self.finish(row, 'declined', cx)
            else:
                if not self.control(row, actor, data.client_id):
                    raise DomainError('CALL_OTHER_TAB', '请在发起或接听通话的窗口操作。', 409)
                if action in ('end', 'failed'):
                    row = self.finish(row, 'failed' if action == 'failed' else 'cancelled' if row['status'] == 'ringing' else 'ended', cx)
                elif action == 'connected' and row['status'] == 'accepted':
                    if not row.get('connected_at'):
                        row = self.db.update('video_calls', id, {'connected_at': now(), 'connected_ts': time.time()}, cx)
                else:
                    raise DomainError('CALL_ACTION', '当前通话状态不支持此操作。', 409)
            return self.public(row, actor, data.client_id)

    def sync(self, id, data, actor):
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            row = self.refresh(self.owned(id, actor, cx), cx)
            if row['status'] != 'ended' and self.control(row, actor, data.client_id):
                row = self.db.update('video_calls', id, {'leases': {**row['leases'], actor: time.time()}}, cx)
            signals = []
            if row['status'] == 'accepted' and self.control(row, actor, data.client_id):
                signals = [{k: signal[k] for k in ('seq', 'kind', 'sdp', 'candidate')}
                           for signal in row['signals'] if signal['sender'] != actor and signal['seq'] > data.after]
            return {'call': self.public(row, actor, data.client_id), 'signals': signals}

    def signal(self, id, data, actor):
        with self.db.transaction() as cx:
            cx.execute('BEGIN IMMEDIATE')
            row = self.refresh(self.owned(id, actor, cx), cx)
            if row['status'] == 'accepted':
                return self.accepted_signal(row, data, actor, cx)
        # Commit expiry and erase temporary signals before reporting the error.
        raise DomainError('CALL_NOT_ACCEPTED', '接听通话后才能建立音视频连接。', 409)

    def accepted_signal(self, row, data, actor, cx):
        if not self.control(row, actor, data.client_id):
            raise DomainError('CALL_OTHER_TAB', '通话正在另一个窗口进行。', 409)
        if data.kind == 'offer' and actor != row['caller'] or data.kind == 'answer' and actor != row['callee']:
            raise DomainError('CALL_SIGNAL_ROLE', '通话信号方向不正确。', 403)
        value = {'sender': actor, 'request_id': str(data.request_id), 'kind': data.kind,
                 'sdp': data.sdp, 'candidate': data.candidate.model_dump() if data.candidate else None}
        for signal in row['signals']:
            if signal['sender'] == actor and signal['request_id'] == value['request_id']:
                if any(signal[k] != v for k, v in value.items()):
                    raise DomainError('CALL_SIGNAL_CONFLICT', '重复信号的内容不同。', 409)
                return {'seq': signal['seq']}
        if len(row['signals']) >= 240 or (data.kind != 'ice' and any(s['sender'] == actor and s['kind'] == data.kind for s in row['signals'])):
            raise DomainError('CALL_SIGNAL_LIMIT', '连接信号超出限制，请重新发起通话。', 409)
        value['seq'] = len(row['signals']) + 1
        self.db.update('video_calls', row['id'], {'signals': [*row['signals'], value]}, cx)
        return {'seq': value['seq']}
