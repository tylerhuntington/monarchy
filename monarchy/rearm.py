"""Opt-in Secretary observation and wake preparation, never action execution."""
from datetime import datetime, timezone
from contextlib import contextmanager
import fcntl
import math
import os
from pathlib import Path
import shlex
import sqlite3
import stat
import sys
import time

from .conductor import _binding, _uuid
from .config import resolve
from .preferences import Preferences, digest
from .prompt_hooks import MAX_INPUT_BYTES, _path, _payload
from .records import Conflict, CourtRecords, RecordError, _REPOSITORY


FAILURE_MESSAGE = 'Monarchy Secretary observation stopped safely; inspect the private journal before re-arming.'
MAX_CHECK_PAGES = 100


def settings_snippet(script_path, state_path, project, secretary_session):
    """Return reviewable Claude settings; never install or activate a hook."""
    script_path, state_path = _path(script_path), _path(state_path)
    _uuid(secretary_session, 'secretary_session')
    if type(project) is not str or not _REPOSITORY.fullmatch(project):
        raise RecordError('re-arm requires an exact repository')
    command = ' '.join(['MONARCHY_REARM=1',
        'MONARCHY_STATE=' + shlex.quote(state_path),
        'MONARCHY_PROJECT=' + shlex.quote(project),
        'MONARCHY_SECRETARY_SESSION=' + shlex.quote(secretary_session),
        shlex.quote(sys.executable), shlex.quote(script_path)])
    return {'hooks': {event: [{'hooks': [{'type': 'command', 'command': command,
                                        'asyncRewake': True, 'timeout': 7210}]}]
                      for event in ('Stop', 'StopFailure')}}


def _scope(project, secretary_session):
    _uuid(secretary_session, 'secretary_session')
    if type(project) is not str or not _REPOSITORY.fullmatch(project):
        raise RecordError('re-arm requires an exact repository')


def _current(records, project, secretary_session):
    """Require an unambiguous current registered Secretary, never the Queen."""
    secretaries, queens = set(), set()
    for offset in range(0, 10000, 100):
        rows = records.list_tasks(limit=100, offset=offset)
        for task in rows:
            if task['repository'] != project or task['task_id'].startswith('court.'):
                continue
            meta = task['metadata']
            for field, sessions in (('secretary_binding', secretaries), ('queen_binding', queens)):
                if field in meta:
                    binding = _binding(meta[field])
                    if binding['repo'] != project:
                        return False
                    sessions.add(binding['session_id'])
        if len(rows) < 100:
            return secretaries == {secretary_session} and secretary_session not in queens
    raise RecordError('Secretary registration exceeds its read bound')


def _guard(records, project, secretary_session):
    if not _current(records, project, secretary_session):
        return 'identity-changed'
    try:
        if records.has_pins():
            Preferences(records).require_current(project)
        else:
            config = resolve(overrides=records.config_overrides(project))
            if any(config[key]['value'] for key in ('court.paused', 'court.stopped')):
                return 'held'
    except Conflict:
        return 'held'
    return None


def _now(now):
    value = now() if now else datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RecordError('wait clock must return an offset-aware timestamp')
    return value.astimezone(timezone.utc).isoformat()


def wait(records, *, project, secretary_session, max_seconds=6600, poll_seconds=30,
         now=None, clock=time.monotonic, sleep=time.sleep):
    """Observe bounded local checks and prepare one durable notification intent.

    Listing never completes a check. A prepared notice is not delivery proof;
    a crash before native exit leaves it visible for deliberate recovery instead
    of automatically waking repeatedly. This function makes no native calls.
    """
    _scope(project, secretary_session)
    for value, maximum in ((max_seconds, 7200), (poll_seconds, 60)):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
            raise RecordError('wait duration or polling interval is outside its bound')
    if poll_seconds < 1:
        raise RecordError('wait polling interval must be at least one second')
    deadline = clock() + max_seconds
    reason = _guard(records, project, secretary_session)
    if reason:
        return {'reason': reason, 'checks': [], 'check_ids': []}
    with _lock(records.path, secretary_session) as acquired:
        if not acquired:
            return {'reason': 'already-waiting', 'checks': [], 'check_ids': []}
        return _poll(records, project, secretary_session, deadline, poll_seconds, now, clock, sleep)


def _poll(records, project, secretary_session, deadline, poll_seconds, now, clock, sleep):
    rows = []
    while True:
        reason = _guard(records, project, secretary_session)
        if reason:
            return {'reason': reason, 'checks': [], 'check_ids': []}
        from .cadence import Cadence
        cadence = Cadence(records)
        checked_at = _now(now)
        ready = []
        for page in range(MAX_CHECK_PAGES):
            if clock() >= deadline:
                return {'reason': 'timeout', 'checks': rows, 'check_ids': []}
            reason = _guard(records, project, secretary_session)
            if reason:
                return {'reason': reason, 'checks': rows, 'check_ids': []}
            batch = cadence.due(now=checked_at, project=project, limit=100, offset=page * 100)
            if not page:
                rows = batch
            ready = cadence.unnotified([row for row in batch if not row['held_reasons']
                                       and row['state'] == 'pending'], secretary_session)
            if ready or len(batch) < 100:
                break
        else:
            return {'reason': 'budget-exhausted', 'checks': rows, 'check_ids': []}
        if ready:
            reason = _guard(records, project, secretary_session)
            if reason:
                return {'reason': reason, 'checks': rows, 'check_ids': []}
            check_ids = sorted(row['check_id'] for row in ready)
            notification_id = 'notice.' + digest({'checks': check_ids, 'secretary': secretary_session})
            if clock() >= deadline:
                return {'reason': 'timeout', 'checks': rows, 'check_ids': []}
            notice = cadence.prepare_notice(check_ids, notification_id,
                secretary_session=secretary_session, created_at=_now(now))
            result = _notice_result(records, cadence, notice, project, secretary_session, now)
            if clock() >= deadline:
                result.update(reason='timeout', check_ids=[])
            return result
        remaining = deadline - clock()
        if remaining <= 0:
            return {'reason': 'timeout', 'checks': rows, 'check_ids': []}
        sleep(min(poll_seconds, remaining))


def _notice_result(records, cadence, notice, project, secretary_session, now):
    reason = _guard(records, project, secretary_session)
    checked_at = _now(now)
    rows = [cadence.get(check_id, now=checked_at) for check_id in notice['check_ids']]
    ready = [row for row in rows if row['state'] == 'pending' and not row['held_reasons']]
    return {'reason': reason or ('change' if ready else 'held'), 'checks': ready if not reason else rows,
            'check_ids': sorted(row['check_id'] for row in ready) if not reason else [],
            'notification_id': notice['notification_id']}


@contextmanager
def _lock(state, secretary_session):
    path = str(state) + '.rearm.' + digest({'secretary': secretary_session}) + '.lock'
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise RecordError('re-arm lock must be a private regular file')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(descriptor)


def run_hook(raw, environ, *, stderr=None, now=None, clock=time.monotonic, sleep=time.sleep):
    """Run one explicitly enabled Secretary wait; native exit 2 requests a wake.

    No hook success callback exists. The journal records a prepared intent only,
    not a delivered wake. Timeout ends observation. Errors never create repeated
    StopFailure wake turns. No session is launched and no host setting is changed.
    """
    stderr = sys.stderr if stderr is None else stderr
    if environ.get('MONARCHY_REARM') != '1':
        return 0
    try:
        project, session = environ.get('MONARCHY_PROJECT'), environ.get('MONARCHY_SECRETARY_SESSION')
        _scope(project, session)
        if environ.get('CONDUCTOR_SESSION_ID') != session:
            return 0
        data = _payload(raw)
        if data.get('hook_event_name') not in {'Stop', 'StopFailure'}:
            raise RecordError('unsupported re-arm event')
        if data.get('stop_hook_active', False) is True or data.get('agent_id') is not None:
            return 0
        if data.get('stop_hook_active', False) is not False:
            raise RecordError('invalid re-arm event state')
        if any(data.get(key) is True for key in ('interrupted', 'is_interrupt', 'cancelled', 'aborted')):
            return 0
        state = _path(environ.get('MONARCHY_STATE'))
        if not Path(state).is_file():
            raise RecordError('re-arm requires an existing private journal')
        with CourtRecords(state) as records:
            if _guard(records, project, session):
                return 0
            result = wait(records, project=project, secretary_session=session, now=now, clock=clock, sleep=sleep)
            if result['reason'] != 'change':
                if result['reason'] in {'budget-exhausted', 'read-error'}:
                    print(FAILURE_MESSAGE, file=stderr)
                return 0
            from .cadence import Cadence
            cadence = Cadence(records)
            result = _notice_result(records, cadence, cadence.get_notice(result['notification_id']), project, session, now)
            if result['reason'] != 'change':
                return 0
            print('[wake] Secretary supervision checks are pending. Prepared notice ' +
                  result['notification_id'] + '; inspect monarchy due before acting.', file=stderr)
            return 2
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, RecursionError, KeyboardInterrupt):
        print(FAILURE_MESSAGE, file=stderr)
        return 0


def main(stdin=None, environ=None):
    env = os.environ if environ is None else environ
    if env.get('MONARCHY_REARM') != '1':
        return 0
    try:
        raw = (sys.stdin.buffer if stdin is None else stdin).read(MAX_INPUT_BYTES + 1)
        return run_hook(raw, env)
    except (OSError, KeyboardInterrupt):
        print(FAILURE_MESSAGE, file=sys.stderr)
        return 0
