"""Durable owner controls. No native actions, file promotion, or new grants."""
import copy
import hashlib
import json
import uuid

from .config import KEYS, load
from .preferences import Preferences, accepted, digest
from .records import Conflict, RecordError, _identifier, _now, _payload


RESTRICTIONS = {'pause': 'court.paused', 'stop': 'court.stopped', 'away': 'court.away'}
WIDENING = frozenset({'resume', 'model', 'handoff'})
MAX_HISTORY = 10000
EMPTY_CHECKPOINT = {'sequence': 0, 'sha256': hashlib.sha256(b'').hexdigest()}


def _request(verb, payload):
    if type(verb) is not str or verb not in set(RESTRICTIONS) | WIDENING | {'bearings', 'decisions'}:
        raise RecordError('unknown owner control')
    request = json.loads(_payload({} if payload is None else payload))
    if verb == 'model':
        if set(request) != {'role', 'profile'} or request['role'] not in ('queen', 'secretary', 'worker'):
            raise RecordError('model requires a role and complete profile')
        load(json.dumps({'profiles.' + request['role']: request['profile']}), 'owner')
    elif verb == 'handoff':
        if set(request) != {'role', 'session_id'} or request['role'] not in ('queen', 'secretary'):
            raise RecordError('handoff requires a leadership role and session')
        try:
            if type(request['session_id']) is not str or str(uuid.UUID(request['session_id'])) != request['session_id']:
                raise ValueError()
        except (ValueError, AttributeError) as exc:
            raise RecordError('handoff requires a canonical session identifier') from exc
    elif request:
        raise RecordError('this owner control accepts no payload')
    return request


def _effects(verb, request):
    if verb in RESTRICTIONS:
        return {'set': {RESTRICTIONS[verb]: True}}
    if verb == 'resume':
        return {'clear': list(RESTRICTIONS.values())}
    return {verb: copy.deepcopy(request)}


def _promotion(verb, request):
    if verb != 'model':
        return None
    return {'state': 'offered', 'destination': 'owner.json',
            'setting': 'profiles.' + request['role'], 'value': copy.deepcopy(request['profile'])}


def _command_id(owner_message):
    return 'control.' + digest({'owner_message': _identifier(owner_message, 'owner_message')})


def _rows(records):
    rows = records._connection.execute('SELECT * FROM overrides ORDER BY sequence LIMIT ?',
                                       (MAX_HISTORY + 1,)).fetchall()
    if len(rows) > MAX_HISTORY:
        raise RecordError('override history exceeds its read bound')
    return [dict(row) for row in rows]


def _pins(records):
    rows = records._connection.execute('SELECT sequence,pin_id,project,payload FROM pins ORDER BY sequence LIMIT ?',
                                       (MAX_HISTORY + 1,)).fetchall()
    if len(rows) > MAX_HISTORY:
        raise RecordError('pin history exceeds its read bound')
    # Pin bytes are already custody-checked by Preferences. Hash the records too,
    # so changing the source while a model proposal waits requires a fresh box.
    return digest([dict(row) for row in rows])


def _proposal(verb, request, owner_message, checkpoint, pins):
    questions = {'resume': 'Resume the royalty by clearing pause, stop, and away?',
                 'model': 'Use this exact role profile?',
                 'handoff': 'Record this exact leadership handoff target?'}
    return {'kind': 'control.' + verb, 'verb': verb, 'request': request,
            'command_id': _command_id(owner_message), 'request_owner_message': owner_message,
            'checkpoint': checkpoint, 'pins': pins, 'generation': 1,
            'question': questions[verb], 'options': ['Confirm (Recommended)', 'Keep Current State']}


def _checked_proposal(row):
    payload = row['payload']
    try:
        verb = payload['verb']
        if verb not in WIDENING:
            raise ValueError()
        request = _request(verb, payload['request'])
        checkpoint = payload['checkpoint']
        if (type(checkpoint) is not dict or set(checkpoint) != {'sequence', 'sha256'}
                or type(checkpoint['sequence']) is not int or checkpoint['sequence'] < 0
                or type(checkpoint['sha256']) is not str or len(checkpoint['sha256']) != 64
                or type(payload['pins']) is not str or len(payload['pins']) != 64):
            raise ValueError()
        expected = _proposal(verb, request, payload['request_owner_message'], checkpoint, payload['pins'])
        if (_payload(payload) != _payload(expected) or row['task_id'] != 'court.control'
                or row['decision_id'] != 'control.' + digest(expected) or row['revision'] != 1):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise Conflict('owner control proposal is changed or invalid') from exc
    return payload


def _approved(row):
    proposal = _checked_proposal(row)
    if (row['state'] != 'answered' or not accepted(row['answer']) or not row['owner_message']
            or row.get('answered_by', 'owner') != 'owner'):
        raise Conflict('owner control needs its exact answered owner box')
    return proposal


def _checked_receipt(records, row, receipt, checkpoint):
    try:
        if type(receipt) is not dict or set(receipt) != {
                'command_id', 'verb', 'request', 'request_owner_message', 'decision',
                'proposal', 'effects', 'promotion', 'checkpoint'}:
            raise ValueError()
        verb = receipt['verb']
        request = _request(verb, receipt['request'])
        if verb not in set(RESTRICTIONS) | WIDENING or row['project'] != '':
            raise ValueError()
        if (receipt['command_id'] != _command_id(receipt['request_owner_message'])
                or digest(receipt['effects']) != digest(_effects(verb, request))
                or digest(receipt['promotion']) != digest(_promotion(verb, request))
                or digest(receipt['checkpoint']) != digest(checkpoint)):
            raise ValueError()
        if verb in RESTRICTIONS:
            if (receipt['decision'] is not None or receipt['proposal'] is not None
                    or row['owner_message'] != receipt['request_owner_message']):
                raise ValueError()
        else:
            ref = receipt['decision']
            if type(ref) is not dict or set(ref) != {'decision_id', 'revision', 'owner_message'}:
                raise ValueError()
            decision = records.get_decision(ref['decision_id'])
            proposal = _approved(decision)
            if (digest(ref) != digest({k: decision[k] for k in ref}) or row['owner_message'] != ref['owner_message']
                    or digest(proposal) != digest(receipt['proposal']) or proposal['checkpoint'] != checkpoint
                    or proposal['command_id'] != receipt['command_id']
                    or proposal['verb'] != verb or proposal['request'] != request
                    or proposal['request_owner_message'] != receipt['request_owner_message']):
                raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise Conflict('stored owner control receipt is invalid or stale') from exc
    return receipt


def fold_overrides(records, project=''):
    """Validate the full history and fold restrictive config and approved models.

    A clear is a receipt effect, never a false value accepted by config.load.
    Prefix hashes bind each approval to the history it observed. Existing receipt
    replay does not append another clear or disturb later restrictive commands.
    """
    config, models, receipts = {}, {}, {}
    checkpoint = dict(EMPTY_CHECKPOINT)
    chain = hashlib.sha256()
    for row in _rows(records):
        try:
            if type(row['value']) is not str or len(row['value'].encode()) > 65536:
                raise ValueError()
            value = json.loads(row['value'])
            if _payload(value) != row['value']:
                raise ValueError()
            _identifier(row['owner_message'], 'owner_message')
            key = row['setting']
            if key == 'control.command':
                if set(value) != {'control'}:
                    raise ValueError()
                receipt = _checked_receipt(records, row, value['control'], checkpoint)
                if receipt['command_id'] in receipts:
                    raise ValueError()
                receipts[receipt['command_id']] = {'state': 'applied', 'sequence': row['sequence'],
                                                   'receipt': receipt}
                effect = receipt['effects']
                config.update(effect.get('set', {}))
                for setting in effect.get('clear', []):
                    config.pop(setting, None)
                if 'model' in effect:
                    model = effect['model']
                    models[model['role']] = {'profile': model['profile'], 'decision': receipt['decision']}
            else:
                if set(value) != {'value'} or key not in KEYS:
                    raise ValueError()
                load(json.dumps({key: value['value']}), 'overrides')
                if row['project'] and KEYS[key]['home'] != 'project':
                    raise ValueError()
                if row['project'] in ('', project):
                    item = value['value']
                    if key in config and KEYS[key]['merge'] == 'min':
                        item = min(config[key], item)
                    elif key in config and KEYS[key]['merge'] == 'union':
                        item = sorted(set(config[key]) | set(item))
                    config[key] = item
        except (KeyError, TypeError, ValueError, RecursionError) as exc:
            raise RecordError('stored override history is invalid or stale') from exc
        chain.update(_payload(row).encode())
        checkpoint = {'sequence': row['sequence'], 'sha256': chain.hexdigest()}
    return {'config': config, 'models': models, 'receipts': receipts, 'checkpoint': checkpoint}


class Controls:
    """Trusted owner-route adapter; owner references record, not authenticate, authority."""
    def __init__(self, records):
        self.records = records

    def _existing(self, command_id, verb, request):
        state = fold_overrides(self.records)
        existing = state['receipts'].get(command_id)
        if existing:
            row = existing['receipt']
            if (row['verb'], row['request']) != (verb, request):
                raise Conflict('owner message already has a different control')
            return existing, state
        rows = self.records._connection.execute(
            'SELECT * FROM decisions WHERE task_id=? AND revision=1 LIMIT ?',
            ('court.control', MAX_HISTORY + 1)).fetchall()
        if len(rows) > MAX_HISTORY:
            raise RecordError('control decision history exceeds its read bound')
        for row in rows:
            first = self.records._decode(row)
            proposal = _checked_proposal(first)
            if proposal['command_id'] == command_id:
                if (proposal['verb'], proposal['request']) != (verb, request):
                    raise Conflict('owner message already has a different control')
                return self.records.get_decision(first['decision_id']), state
        return None, state

    def _model_ready(self):
        if not self.records.has_pins():
            raise Conflict('model change requires confirmed configuration')
        projects = self.records._connection.execute('SELECT DISTINCT project FROM pins LIMIT 1001').fetchall()
        if len(projects) > 1000:
            raise RecordError('royalty project bound exceeded')
        for row in projects:
            if Preferences(self.records).show(row[0])['held']:
                raise Conflict('model change requires current configuration')

    def _append(self, verb, request, owner_message, state, decision=None):
        proposal = _approved(decision) if decision else None
        receipt = {'command_id': _command_id(owner_message), 'verb': verb, 'request': request,
                   'request_owner_message': owner_message, 'effects': _effects(verb, request),
                   'promotion': _promotion(verb, request), 'checkpoint': state['checkpoint'],
                   'proposal': proposal, 'decision': None if decision is None else
                       {k: decision[k] for k in ('decision_id', 'revision', 'owner_message')}}
        authority = decision['owner_message'] if decision else owner_message
        self.records._connection.execute(
            'INSERT INTO overrides(project,setting,value,owner_message,created_at) VALUES(?,?,?,?,?)',
            ('', 'control.command', _payload({'control': receipt}), authority, _now()))
        Preferences(self.records).validate_current_overrides()
        return fold_overrides(self.records)['receipts'][receipt['command_id']]

    def command(self, verb, payload=None, *, owner_message=None):
        request = _request(verb, payload)
        if verb in {'bearings', 'decisions'}:
            pending = self.records.list_decisions(state='pending')
            if verb == 'decisions':
                return {'verb': verb, 'decisions': pending,
                        'has_more': bool(self.records.list_decisions(state='pending', limit=1, offset=len(pending)))}
            overrides = self.records.config_overrides()
            tasks = self.records.list_tasks()
            line_limit = KEYS['voice.max_lines']['default']
            held = False
            if self.records.has_pins():
                latest = self.records.latest_pin()
                view = Preferences(self.records).show(latest['project'])
                line_limit = view['config']['voice.max_lines']['value']
                held = view['held']
            mode = ('stopped' if overrides.get('court.stopped') else 'paused' if overrides.get('court.paused')
                    else 'no pause or stop recorded')
            if held:
                mode += '; configuration held'
            lines = ['Royalty controls: ' + mode + '.',
                    'Owner away: ' + ('yes.' if overrides.get('court.away') else 'no.'),
                    'Pending decisions: ' + str(len(pending)) + (' or more.' if len(pending) == 100 else '.'),
                    'Recorded tasks: ' + str(len(tasks)) + (' or more.' if len(tasks) == 100 else '.'),
                    'Controls record intent; native work remains separately governed.']
            return {'verb': verb, 'lines': lines[:line_limit]}
        command_id = _command_id(owner_message)
        with self.records._transaction():
            existing, state = self._existing(command_id, verb, request)
            if existing is not None:
                return existing
            if verb in RESTRICTIONS:
                return self._append(verb, request, owner_message, state)
            if verb == 'model':
                self._model_ready()
            proposal = _proposal(verb, request, owner_message, state['checkpoint'], _pins(self.records))
            decision_id = 'control.' + digest(proposal)
            now = _now()
            self.records._connection.execute(
                'INSERT OR IGNORE INTO tasks(task_id,repository,owner,generation,metadata,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?)', ('court.control', 'monarchy/court', 'queen', 1,
                                        _payload({'kind': 'owner-controls'}), now, now))
            task = self.records.get_task('court.control')
            if (task['repository'], task['owner'], task['generation'], task['metadata']) != (
                    'monarchy/court', 'queen', 1, {'kind': 'owner-controls'}):
                raise Conflict('owner control task identity changed')
            self.records._connection.execute(
                'INSERT INTO decisions(decision_id,revision,task_id,payload,state,created_at) VALUES(?,?,?,?,?,?)',
                (decision_id, 1, 'court.control', _payload(proposal), 'pending', now))
            return self.records.get_decision(decision_id)

    def apply(self, decision_id):
        _identifier(decision_id, 'decision_id')
        with self.records._transaction():
            decision = self.records.get_decision(decision_id)
            proposal = _approved(decision)
            existing, state = self._existing(proposal['command_id'], proposal['verb'], proposal['request'])
            if existing is not None and existing.get('state') == 'applied':
                return existing
            if proposal['checkpoint'] != state['checkpoint'] or proposal['pins'] != _pins(self.records):
                raise Conflict('owner control approval is stale; request a fresh box')
            if proposal['verb'] == 'model':
                self._model_ready()
            return self._append(proposal['verb'], proposal['request'], proposal['request_owner_message'], state, decision)
