"""Bounded, project-scoped authority from actual owner-answered proposals.

These APIs require trusted local classification and owner-route callers. They
neither authenticate humans nor infer action semantics from prose or reports.
"""
import copy
import json
import re

from .config import NEVER_DELEGABLE, resolve
from .preferences import Preferences, accepted, admission_check, digest
from .records import Conflict, RecordError, _REPOSITORY, _generation, _identifier, _now, _payload, owner_answered


PERMITTED_ACTIONS = {
    'adr-record-of-owner-decision': ('write-internal-documentation',),
    'ci-rerun-at-approved-head': ('rerun-approved-ci',),
    'resubmission-fixing-send-back-points': ('resubmit-internal-change',),
    'staging-only-one-time-recovery-retry': ('retry-staging-recovery',),
    'ui-signoff-small-copy-or-layout-fix': ('approve-small-ui-change',),
    'plan-or-date-acceptance': ('accept-internal-plan',),
    'rebase-only-reapproval-identical-patch': ('reapprove-identical-patch',),
    'evidence-storage-move-verified': ('move-evidence-storage',),
    'ui-signoff-new-feature': ('approve-ui-feature',),
    'research-closure': ('close-research',),
    'additive-database-change': ('add-database-change',),
    'delivery-or-watcher-control-change': ('change-nonproduction-controls',),
    'backlog-cleanup-with-notifications': ('clean-backlog-without-contact',),
    'new-standing-rule-or-policy': ('change-nonauthority-policy',),
    'internal-pr-approval': ('approve-internal-pr',),
}
TAXONOMY = tuple(PERMITTED_ACTIONS)
STATES = ('ask', 'delegated', 'ask-again-later')
SAFE_ACTIONS = frozenset(action for actions in PERMITTED_ACTIONS.values() for action in actions)
MAX_HISTORY = 10000
MAX_PRECEDENTS = 20
_CATEGORY = re.compile(r'[a-z][a-z0-9-]{0,95}\Z')
_OWNER_KINDS = ('founding.', 'config.', 'control.', 'delegation.')


def _project(value):
    if type(value) is not str or not _REPOSITORY.fullmatch(value):
        raise RecordError('delegation requires an exact repository')
    return value


def _category(value):
    if type(value) is not str or not _CATEGORY.fullmatch(value):
        raise RecordError('delegation category is invalid')
    return value


def _policy(records, project, *, current=False):
    _project(project)
    if records.has_pins():
        view = (Preferences(records).require_current(project) if current
                else Preferences(records).show(project))
        config, pin_id = view['config'], view['pin_id']
    else:
        config, pin_id = resolve(overrides=records.config_overrides(project)), None
        if current and any(config[key]['value'] for key in ('court.paused', 'court.stopped')):
            raise Conflict('royalty configuration is held')
    never = set(NEVER_DELEGABLE) | set(config['delegation.never']['value'])
    categories = set(TAXONOMY) | set(config['delegation.categories']['value'])
    return {'never': never, 'categories': categories,
            'digest': digest({'config': config, 'pin_id': pin_id})}


def _eligible(category, policy):
    _category(category)
    if category not in policy['categories'] or category in policy['never']:
        raise Conflict('category is reserved or not registered; ask the owner')


def _forbidden_actions(policy):
    # A project restriction on a canonical category also restricts its actions;
    # a custom label cannot alias those actions back into the permitted set.
    return set(policy['never']) | {action for category in policy['never']
                                   for action in PERMITTED_ACTIONS.get(category, ())}


def _context(decision, project, policy):
    """Validate explicit action facts, not the meaning of the decision's prose."""
    payload = decision['payload']
    kind = payload.get('kind', '')
    if (decision['task_id'].startswith('court.') or type(kind) is not str
            or kind.startswith(_OWNER_KINDS)):
        raise Conflict('this decision requires the owner route')
    context = payload.get('delegation')
    if (type(context) is not dict or not {'category', 'actions', 'scope', 'classification_complete'} <= set(context)
            or not set(context) <= {'category', 'actions', 'scope', 'classification_complete',
                                    'precedent', 'new_risk', 'unresolved_flags', 'candidate'}
            or context['classification_complete'] is not True):
        raise Conflict('decision needs complete trusted classification; ask the owner')
    _eligible(context['category'], policy)
    actions = context['actions']
    allowed = set(PERMITTED_ACTIONS.get(context['category'], SAFE_ACTIONS))
    if (type(actions) is not list or not 1 <= len(actions) <= 20
            or any(type(action) is not str for action in actions)
            or len(set(actions)) != len(actions) or not set(actions) <= allowed
            or set(actions) & _forbidden_actions(policy)):
        raise Conflict('decision actions are reserved or unsupported; ask the owner')
    if 'approve-internal-pr' in actions and context['category'] != 'internal-pr-approval':
        raise Conflict('internal approval requires its canonical category and evidence gate')
    if type(context['scope']) is not dict or not context['scope']:
        raise Conflict('decision requires a concrete precedent scope')
    if len(_payload(context['scope']).encode()) > 4096:
        raise RecordError('delegation scope exceeds its bound')
    return context


def _reference(value):
    if (type(value) is not dict or set(value) != {'decision_id', 'revision'}
            or type(value['revision']) is not int or value['revision'] < 1):
        raise RecordError('precedent requires an exact decision and revision')
    _identifier(value['decision_id'], 'decision_id')
    return copy.deepcopy(value)


def _freeze(records, reference, project, category, policy, *, current=True):
    reference = _reference(reference)
    decision = records.get_decision(reference['decision_id'], reference['revision'])
    task = records.get_task(decision['task_id'])
    if (task['repository'] != project or decision.get('answered_by') != 'owner'
            or not decision.get('owner_message') or decision.get('answer') is None
            or decision['state'] not in {'answered', 'superseded'}):
        raise Conflict('precedent must be an actual owner answer in this project')
    if current and (records.get_decision(reference['decision_id'])['revision'] != reference['revision']
                    or not owner_answered(decision)):
        raise Conflict('precedent is no longer the current owner answer')
    context = _context(decision, project, policy)
    if context['category'] != category:
        raise Conflict('precedent belongs to another category')
    if not decision['answer'] or (category == 'internal-pr-approval' and not accepted(decision['answer'])):
        raise Conflict('precedent has no permitted answer for this category')
    return {**reference, 'payload_sha256': digest(decision['payload']),
            'answer_sha256': digest(decision['answer']), 'owner_message': decision['owner_message'],
            'actions': context['actions'], 'scope': context['scope'], 'answer': decision['answer']}


def _proposal_id(owner_message):
    return 'delegation.' + digest({'owner_message': _identifier(owner_message, 'owner_message')})


def _refs(precedents):
    if type(precedents) is not list or len(precedents) > MAX_PRECEDENTS:
        raise RecordError('delegation precedent list exceeds its bound')
    checked = [_reference(value) for value in precedents]
    if len({(value['decision_id'], value['revision']) for value in checked}) != len(checked):
        raise RecordError('delegation precedents must be distinct')
    return sorted(checked, key=lambda value: (value['decision_id'], value['revision']))


def _proposal(project, category, state, owner_message, precedents, checkpoint, config_digest):
    result = {'kind': 'delegation.proposal', 'generation': 1, 'project': project,
            'category': category, 'state': state, 'request_owner_message': owner_message,
            'precedents': precedents, 'checkpoint': checkpoint, 'config_digest': config_digest,
            'question': 'Use this exact delegation state and permitted precedents?',
            'options': ['Confirm This State (Recommended)', 'Keep Current State']}
    if state is None:
        result.update(kind='delegation.followup', question='How should these matching decisions be handled?',
                      choices=['delegated', 'ask', 'ask-again-later'],
                      options=['Delegate This Category (Recommended)', 'Ask Every Time', 'Ask Again Later'])
    return result


def _checked_proposal(decision):
    try:
        proposal = decision['payload']
        _project(proposal['project'])
        _category(proposal['category'])
        if proposal['state'] not in (*STATES, None) or proposal['category'] in NEVER_DELEGABLE:
            raise ValueError()
        expected = _proposal(proposal['project'], proposal['category'], proposal['state'],
                             proposal['request_owner_message'], proposal['precedents'],
                             proposal['checkpoint'], proposal['config_digest'])
        if (decision['task_id'] != 'court.delegation' or decision['revision'] != 1
                or decision['decision_id'] != _proposal_id(proposal['request_owner_message'])
                or _payload(proposal) != _payload(expected)):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise Conflict('delegation proposal is invalid or changed') from exc
    return proposal


def _selected(decision, proposal):
    answer = decision['answer']
    if decision['answered_by'] != 'owner' or not decision['owner_message']:
        raise Conflict('delegation needs its actual owner answer')
    if proposal['state'] is None:
        if type(answer) is not dict or set(answer) != {'state'} or answer['state'] not in STATES:
            raise Conflict('delegation follow-up needs one exact listed state')
        return answer['state']
    if not accepted(answer):
        raise Conflict('delegation needs its exact answered owner box')
    return proposal['state']


class Delegation:
    def __init__(self, records):
        self.records = records

    def categories(self, project):
        policy = _policy(self.records, project)
        return {'project': project, 'categories': sorted(policy['categories']),
                'never': sorted(policy['never']), 'states': list(STATES),
                'permitted_actions': {category: sorted(set(PERMITTED_ACTIONS.get(
                    category, SAFE_ACTIONS - {'approve-internal-pr'})) - _forbidden_actions(policy))
                                      for category in sorted(policy['categories'] - policy['never'])}}

    def _history(self, project, category):
        _project(project)
        _category(category)
        rows = self.records._connection.execute(
            'SELECT * FROM delegation_events WHERE project=? AND category=? ORDER BY sequence LIMIT ?',
            (project, category, MAX_HISTORY + 1)).fetchall()
        if len(rows) > MAX_HISTORY:
            raise RecordError('delegation history exceeds its bound')
        checkpoint = digest([])
        current = {'project': project, 'category': category, 'state': 'ask', 'grant_id': None,
                   'sequence': 0, 'checkpoint': checkpoint}
        for raw in rows:
            row = dict(raw)
            try:
                payload = json.loads(row['payload'])
                if _payload(payload) != row['payload'] or payload['checkpoint'] != checkpoint:
                    raise ValueError()
                if payload['kind'] == 'apply':
                    if set(payload) != {'kind', 'decision_id', 'proposal', 'owner_message', 'checkpoint'}:
                        raise ValueError()
                    decision = self.records.get_decision(payload['decision_id'], 1)
                    proposal = _checked_proposal(decision)
                    if (decision['answered_by'] != 'owner'
                            or decision['owner_message'] != payload['owner_message']
                            or _payload(proposal) != _payload(payload['proposal'])
                            or proposal['project'] != project or proposal['category'] != category
                            or _selected(decision, proposal) != row['state'] or proposal['checkpoint'] != checkpoint
                            or row['event_id'] != 'apply.' + decision['decision_id']):
                        raise ValueError()
                    grant_id = 'grant.' + digest(proposal) if row['state'] == 'delegated' else None
                    details = {'precedents': proposal['precedents'], 'config_digest': proposal['config_digest']}
                elif payload['kind'] == 'revoke':
                    if (set(payload) != {'kind', 'owner_message', 'checkpoint'} or row['state'] != 'ask'
                            or row['event_id'] != 'revoke.' + digest({'owner_message': payload['owner_message']})):
                        raise ValueError()
                    _identifier(payload['owner_message'], 'owner_message')
                    grant_id, details = None, {}
                else:
                    raise ValueError()
            except (KeyError, TypeError, ValueError) as exc:
                raise Conflict('stored delegation history is invalid') from exc
            checkpoint = digest({'previous': checkpoint, 'row': row})
            current = {'project': project, 'category': category, 'state': row['state'],
                       'grant_id': grant_id, 'sequence': row['sequence'],
                       'checkpoint': checkpoint, **details}
        return current

    def state(self, project, category):
        return self._history(project, category)

    def propose(self, project, category, state, *, owner_message, precedents=None):
        if type(state) is not str or state not in STATES:
            raise RecordError('delegation state is invalid')
        return self._propose(project, category, state, owner_message=owner_message, precedents=precedents)

    def _propose(self, project, category, state, *, owner_message, precedents):
        _project(project)
        _category(category)
        references = _refs([] if precedents is None else precedents)
        if state in ('delegated', None) and not references:
            raise Conflict('delegation requires permitted owner precedents')
        decision_id = _proposal_id(owner_message)
        with self.records._transaction():
            policy = _policy(self.records, project, current=True)
            _eligible(category, policy)
            frozen = [_freeze(self.records, ref, project, category, policy) for ref in references]
            existing = self.records._connection.execute(
                'SELECT 1 FROM decisions WHERE decision_id=? LIMIT 1', (decision_id,)).fetchone()
            if existing:
                decision = self.records.get_decision(decision_id)
                proposal = _checked_proposal(decision)
                if ((project, category, state, frozen) !=
                        (proposal['project'], proposal['category'], proposal['state'], proposal['precedents'])):
                    raise Conflict('delegation request identity has different content')
                return decision
            checkpoint = self._history(project, category)['checkpoint']
            proposal = _proposal(project, category, state, owner_message, frozen, checkpoint, policy['digest'])
            now = _now()
            self.records._connection.execute(
                'INSERT OR IGNORE INTO tasks(task_id,repository,owner,generation,metadata,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?)', ('court.delegation', 'monarchy/court', 'queen', 1,
                    _payload({'kind': 'delegation-policy'}), now, now))
            task = self.records.get_task('court.delegation')
            if (task['repository'], task['owner'], task['generation'], task['metadata']) != (
                    'monarchy/court', 'queen', 1, {'kind': 'delegation-policy'}):
                raise Conflict('delegation task identity changed')
            self.records._connection.execute(
                'INSERT INTO decisions(decision_id,revision,task_id,payload,state,created_at) VALUES(?,?,?,?,?,?)',
                (decision_id, 1, 'court.delegation', _payload(proposal), 'pending', now))
            return self.records.get_decision(decision_id)

    def apply(self, decision_id):
        with self.records._transaction():
            decision = self.records.get_decision(decision_id)
            proposal = _checked_proposal(decision)
            if not owner_answered(decision):
                raise Conflict('delegation needs its exact answered owner box')
            selected = _selected(decision, proposal)
            project, category = proposal['project'], proposal['category']
            current = self._history(project, category)
            event_id = 'apply.' + decision_id
            if self.records._connection.execute(
                    'SELECT 1 FROM delegation_events WHERE event_id=?', (event_id,)).fetchone():
                return current  # Replaying a past grant never reverses a later revoke.
            policy = _policy(self.records, project, current=True)
            _eligible(category, policy)
            if proposal['checkpoint'] != current['checkpoint'] or proposal['config_digest'] != policy['digest']:
                raise Conflict('delegation approval is stale; ask the owner again')
            for frozen in proposal['precedents']:
                ref = {key: frozen[key] for key in ('decision_id', 'revision')}
                if _freeze(self.records, ref, project, category, policy) != frozen:
                    raise Conflict('permitted precedent changed')
            payload = {'kind': 'apply', 'decision_id': decision_id, 'proposal': proposal,
                       'owner_message': decision['owner_message'], 'checkpoint': current['checkpoint']}
            self._append(event_id, project, category, selected, payload)
            return self._history(project, category)

    def _append(self, event_id, project, category, state, payload):
        self.records._connection.execute(
            'INSERT INTO delegation_events(event_id,project,category,state,payload,created_at) VALUES(?,?,?,?,?,?)',
            (event_id, project, category, state, _payload(payload), _now()))

    def revoke(self, project, category, *, owner_message):
        _project(project)
        _category(category)
        _identifier(owner_message, 'owner_message')
        event_id = 'revoke.' + digest({'owner_message': owner_message})
        with self.records._transaction():
            current = self._history(project, category)
            existing = self.records._connection.execute(
                'SELECT project,category FROM delegation_events WHERE event_id=?', (event_id,)).fetchone()
            if existing:
                if tuple(existing) != (project, category):
                    raise Conflict('revocation identity belongs to another scope')
                return current
            self._append(event_id, project, category, 'ask',
                         {'kind': 'revoke', 'owner_message': owner_message, 'checkpoint': current['checkpoint']})
            return self._history(project, category)

    def followup(self, owner_decision_id, *, owner_message):
        decision = self.records.get_decision(owner_decision_id)
        if not owner_answered(decision):
            raise Conflict('delegation follow-up needs an actual owner answer')
        project = self.records.get_task(decision['task_id'])['repository']
        context = _context(decision, project, _policy(self.records, project, current=True))
        return self._propose(project, context['category'], None, owner_message=owner_message,
                             precedents=[{'decision_id': owner_decision_id, 'revision': decision['revision']}])

    def _authorize(self, decision, answer, grant_id, *, current_head=None):
        _identifier(grant_id, 'grant_id')
        task = self.records.get_task(decision['task_id'])
        admission_check(self.records, task)
        project = task['repository']
        policy = _policy(self.records, project, current=True)
        context = _context(decision, project, policy)
        generation = _generation(decision['payload'].get('generation'))
        if (generation != task['generation']
                or context.get('new_risk') is not False or context.get('unresolved_flags') != []):
            raise Conflict('decision is stale or has risk or unresolved flags; ask the owner')
        reference = _reference(context.get('precedent'))
        grant = self._history(project, context['category'])
        if (grant['state'] != 'delegated' or grant['grant_id'] != grant_id
                or grant['config_digest'] != policy['digest']):
            raise Conflict('delegation is absent, revoked, or stale; ask the owner')
        permitted = next((value for value in grant['precedents']
                          if all(value[key] == reference[key] for key in reference)), None)
        if permitted is None:
            raise Conflict('decision has no permitted precedent')
        frozen = _freeze(self.records, reference, project, context['category'], policy)
        if (frozen != permitted or context['actions'] != frozen['actions']
                or _payload(context['scope']) != _payload(frozen['scope'])
                or _payload(answer) != _payload(frozen['answer'])):
            raise Conflict('decision action, scope, or answer differs from its permitted precedent')
        if context['category'] == 'internal-pr-approval':
            if not accepted(answer):
                raise Conflict('internal approval requires its exact affirmative answer')
            from .approval import validate_internal_approval
            validate_internal_approval(self.records, decision, context.get('candidate'), grant,
                                       current_head=current_head)
        elif 'candidate' in context:
            raise Conflict('candidate approval requires the internal approval category')
        return grant

    def answer(self, decision_id, answer, *, expected_revision, grant_id, current_head=None):
        with self.records._transaction():
            decision = self.records.get_decision(decision_id)
            if decision['revision'] != expected_revision:
                raise Conflict('decision changed before delegated answer')
            self._authorize(decision, answer, grant_id, current_head=current_head)
            return self.records._answer_decision(decision_id, answer, expected_revision=expected_revision,
                owner_message=None, answered_by='grant:' + grant_id)


def answer_admission_check(records, operation, *, current_head=None):
    """Recheck authority inside the transaction admitting a prepared delivery."""
    request = operation['request']
    decision = records.get_decision(request['decision_id'])
    if decision['answered_by'] == 'owner':
        if not owner_answered(decision):
            raise Conflict('decision has no current owner answer')
        return
    authority = decision.get('answered_by')
    if type(authority) is not str or not authority.startswith('grant:'):
        raise Conflict('decision answer lacks authority provenance')
    if (decision['state'] != 'answered' or decision['revision'] != request['decision_revision']
            or decision['task_id'] != operation['task_id'] or operation['kind'] != 'send_message'):
        raise Conflict('delegated delivery does not match the current decision')
    try:
        message = json.loads(request['text'])
        expected = {'kind': 'monarchy.answer', 'task_id': decision['task_id'],
                    'generation': decision['payload']['generation'], 'decision_id': decision['decision_id'],
                    'revision': decision['revision'], 'answer': decision['answer'],
                    'answered_by': authority, 'owner_message': None}
        if _payload(message) != _payload(expected):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise Conflict('delegated relay must preserve its actual authority') from exc
    Delegation(records)._authorize(decision, decision['answer'], authority[6:], current_head=current_head)
