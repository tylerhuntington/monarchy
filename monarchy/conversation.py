"""Prompt observations and bounded, journaled Secretary forwards."""
from datetime import datetime, timezone
import unicodedata

from .config import resolve
from .conductor import _binding, _uuid, prepare_message
from .records import Conflict, RecordError, _identifier, _now
from .supervision import identity


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp requires text')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timestamp requires an offset')
    return parsed


def prompt_policy(observation, abandoned_minutes=60, *, now=None):
    """Only a known-open prompt may age out; absence and ambiguity always hold."""
    if not observation or observation.get('state') not in {'open', 'closed'}:
        return 'hold'
    try:
        current = now or datetime.now(timezone.utc)
        age = (current - _timestamp(observation['observed_at'])).total_seconds()
        if age < 0:
            return 'hold'
        if observation['state'] == 'closed':
            return 'available'
        if type(abandoned_minutes) is not int or abandoned_minutes < 1:
            return 'hold'
        return 'available' if age >= abandoned_minutes * 60 else 'hold'
    except (ValueError, TypeError, KeyError, OverflowError):
        return 'hold'


def effective_config(records, project):
    if records.has_pins():
        from .preferences import Preferences
        return Preferences(records).show(project)['config']
    return resolve(overrides=records.config_overrides(project))


def lint_text(text, config, section):
    """Reject oversized prose without truncating obligations or source evidence."""
    if section not in {'reports', 'forwards'}:
        raise RecordError('unknown message policy')
    if not isinstance(text, str) or not text.strip():
        raise RecordError('message requires nonempty text')
    if (len(text) > config[section + '.max_chars']['value']
            or len(text.splitlines()) > config[section + '.max_lines']['value']):
        raise RecordError('message exceeds configured limits')
    if any(c in text for c in config['voice.forbidden_characters']['value']):
        raise RecordError('message contains a forbidden character')
    if any(unicodedata.category(c).startswith('C') and c != '\n' for c in text):
        raise RecordError('message contains a control character')


def validate_forward(records, operation):
    """Bind the immutable operation to the recorded source and leadership route."""
    request = operation['request']
    task = records.get_task(operation['task_id'])
    meta = task['metadata']
    if operation['kind'] != 'send_message' or request.get('route') != 'queen-forward':
        raise Conflict('forward requires the Secretary route')
    if request.get('generation') != task['generation']:
        raise Conflict('forward belongs to an earlier assignment')
    queen = _binding(meta.get('queen_binding'))
    secretary = _binding(meta.get('secretary_binding'))
    if (request.get('binding') != queen
            or request.get('sender_session_id') != secretary['session_id']
            or queen['session_id'] == secretary['session_id']):
        raise Conflict('forward differs from the registered leadership route')
    source = records.get_outcome(request.get('source_outcome'))
    if (source['task_id'] != task['task_id']
            or source['payload'].get('generation') != task['generation']):
        raise Conflict('forward source differs from the current assignment')
    text = request.get('text')
    if not isinstance(text, str) or not text.startswith('[secretary] ') or not text[12:].strip():
        raise RecordError('forward requires the Secretary header and summary')
    config = effective_config(records, task['repository'])
    lint_text(text, config, 'forwards')
    if records.has_pins():
        for role, binding in [('queen', queen), ('secretary', secretary)]:
            if binding['profile'] != config['profiles.' + role]['value']:
                raise Conflict('leadership profile differs from its approved configuration')
    return queen, config


def forward_admission_check(records, operation):
    """Run inside the same write transaction used by prompt-open observations."""
    request = operation['request']
    if request.get('route') != 'queen-forward':
        return
    queen, config = validate_forward(records, operation)
    status = Conversation(records).status(queen['session_id'])
    if prompt_policy(status, config['prompts.abandoned_minutes']['value']) != 'available':
        raise Conflict('Queen prompt state holds this forward')


class Conversation:
    def __init__(self, records):
        self.records = records

    def status(self, session):
        _uuid(session, 'session_id')
        row = self.records._connection.execute(
            'SELECT * FROM prompt_observations WHERE session_id=? ORDER BY sequence DESC LIMIT 1',
            (session,)).fetchone()
        return dict(row) if row else {'session_id': session, 'state': 'unknown', 'prompt_id': None,
                                     'observed_at': None}

    def observe(self, session, prompt_id, action):
        _uuid(session, 'session_id')
        _identifier(prompt_id, 'prompt_id')
        if action not in {'open', 'close', 'unknown'}:
            raise RecordError('prompt action must be open, close, or unknown')
        state = 'closed' if action == 'close' else action
        with self.records._transaction():
            registered = False
            for offset in range(0, 10000, 100):
                tasks = self.records.list_tasks(offset=offset)
                if any(t['metadata'].get('queen_binding', {}).get('session_id') == session
                       for t in tasks):
                    registered = True
                    break
                if len(tasks) < 100:
                    break
            if not registered:
                raise Conflict('prompt session is not a registered Queen')
            current = self.status(session)
            connection = self.records._connection
            # A retry must not restart the abandonment clock or resurrect an old box.
            previous = connection.execute(
                'SELECT 1 FROM prompt_observations WHERE session_id=? AND prompt_id=? AND state=? LIMIT 1',
                (session, prompt_id, state)).fetchone()
            if previous:
                return current
            if action == 'open':
                for offset in range(0, 10000, 100):
                    operations = self.records.list_operations(states=['in_flight', 'unknown'],
                                                               offset=offset)
                    for operation in operations:
                        request = operation['request']
                        if (request.get('route') == 'queen-forward'
                                and request.get('binding', {}).get('session_id') == session):
                            raise Conflict('reconcile the forward before opening another prompt')
                    if len(operations) < 100:
                        break
                else:
                    raise RecordError('unresolved operation budget exceeded')
            elif current['prompt_id'] != prompt_id:
                # Stale callbacks cannot clear a newer prompt. With no open event,
                # there is no evidence of a closed prompt at all.
                known = connection.execute(
                    'SELECT 1 FROM prompt_observations WHERE session_id=? AND prompt_id=? LIMIT 1',
                    (session, prompt_id)).fetchone()
                if known:
                    return current
                state = 'unknown'
            elif action == 'close' and current['state'] != 'open':
                return current
            connection.execute(
                'INSERT INTO prompt_observations(session_id,prompt_id,state,observed_at) VALUES(?,?,?,?)',
                (session, prompt_id, state, _now()))
            return self.status(session)

    def prepare_forward(self, outcome_id, text):
        source = self.records.get_outcome(outcome_id)
        task = self.records.get_task(source['task_id'])
        meta = task['metadata']
        if not isinstance(text, str) or text.startswith('[secretary]'):
            raise RecordError('supply a summary without a message header')
        operation = prepare_message(task['task_id'], meta['queen_binding'], '[secretary] ' + text,
            operation_id=identity('forward-operation', outcome_id),
            message_id=identity('forward-message', outcome_id),
            sender_session_id=meta['secretary_binding']['session_id'])
        operation['request'].update(route='queen-forward', source_outcome=outcome_id,
                                    generation=task['generation'])
        validate_forward(self.records, operation)
        return self.records.prepare_operation(operation['operation_id'], task['task_id'],
                                               operation['kind'], operation['request'])
