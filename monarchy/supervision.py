"""One explicit Secretary pass over durable royalty records. No background loop."""
import hashlib
import json
import re
import uuid

from .records import Conflict, RecordError, StaleGeneration
from .conductor import prepare_message, prepare_session


REVISION = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')


def identity(kind, value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'monarchy:' + kind + ':' + value))


def agent_name(descriptor):
    """Make a readable display name; task and native session identities stay intact."""
    if not isinstance(descriptor, str):
        raise RecordError('00 Agent name must be a nonempty text descriptor')
    value = descriptor.strip().lower()
    if value.startswith('00-'):
        value = value[3:]
    value = re.sub(r'[\W_]+', '-', value).strip('-')
    if not value:
        raise RecordError('00 Agent name needs a purpose descriptor')
    return '00-' + value


def _revision(value):
    if not isinstance(value, str) or not REVISION.fullmatch(value):
        raise RecordError('a full source revision is required')
    return value


class Court:
    def __init__(self, records, transport=None):
        self.records = records
        self.transport = transport

    def tick(self, task_id, *, actor='secretary', limit=100):
        """Persist each disposition before consuming its exact claimed event."""
        claim = self.records.claim_events(actor, task_id, limit=limit)
        if claim is None:
            return {'task_id': task_id, 'consumed': 0}
        consumed = 0
        for event in claim['events']:
            if event['processed_at'] is not None:
                continue
            payload = event['payload']
            kind = event['kind']
            routine = (kind == 'progress' and payload.get('routine') is True
                       and set(payload) <= {'summary', 'routine', 'evidence', 'next_action', 'status'})
            if not routine:
                outcome = {'kind': kind,
                           'generation': event['generation'], 'source_event': event['event_id'],
                           'report': payload}
                if kind == 'decision':
                    # Old obligations survive reassignment and need explicit disposition.
                    decision_id = identity('decision', event['event_id'])
                    question = payload.get('question')
                    if not isinstance(question, str) or not question.strip():
                        outcome['kind'] = 'malformed_report'
                    else:
                        self.records.open_decision(decision_id, task_id, {
                            'generation': event['generation'], 'question': question,
                            'recommendation': payload.get('recommendation'),
                            'source_event': event['event_id']})
                        outcome['decision_id'] = decision_id
                recipient = 'queen' if 'decision_id' in outcome else 'secretary'
                self.records.record_outcome(identity('triage', event['event_id']), task_id, outcome,
                                            recipient=recipient)
            self.records.ack_events(claim['claim_id'], actor, [event['event_id']])
            consumed += 1
        return {'task_id': task_id, 'consumed': consumed}

    def ingest(self, task_id, native_event_id):
        """Receive a report using native identity, never shared checkout files."""
        if self.transport is None:
            raise RecordError('a native transport is required')
        task = self.records.get_task(task_id)
        meta = task['metadata']
        binding = meta['binding']
        member = {**binding, 'court_id': meta['court_id'], 'task_id': task_id,
                  'attempt_id': str(task['generation']), 'role': 'worker'}
        result = self.transport.accept_report(native_event_id, meta['court_id'],
                                               meta['secretary_binding'], {task['owner']: member})
        envelope = result['envelope']
        report = envelope['report']
        kind = 'completed' if report['status'] == 'complete' else report['status']
        return self.records.record_event(envelope['report_id'], task_id, task['generation'],
                                         task['owner'], kind, report)

    def inbox(self, *, actor='queen', limit=100):
        # Presentation is not processing. Reopening shows the same pending batch.
        return self.records.present_outcomes(actor, limit=limit)

    @staticmethod
    def notification_policy(prompt_state):
        if prompt_state not in {'open', 'closed', 'unknown'}:
            raise RecordError('prompt state must be open, closed, or unknown')
        return 'available' if prompt_state == 'closed' else 'hold'

    def _outcomes(self, task_id):
        rows = []
        offset = 0
        while True:
            page = self.records.list_outcomes(task_id=task_id, limit=100, offset=offset)
            rows.extend(page)
            if len(page) < 100:
                return rows
            offset += len(page)
            if offset >= 10000:
                raise RecordError('task history exceeds this pass budget; compact with reviewed migration')

    def _all(self, method, **filters):
        rows = []
        for offset in range(0, 10000, 100):
            page = method(limit=100, offset=offset, **filters)
            rows.extend(page)
            if len(page) < 100:
                return rows
        raise RecordError('task history exceeds this pass budget')

    def status(self, task_id):
        task = self.records.get_task(task_id)
        decisions = self._all(self.records.list_decisions, task_id=task_id)
        by_id = {d['decision_id']: d for d in decisions}
        operations = self._all(self.records.list_operations, task_id=task_id)
        active = []
        for operation in operations:
            request = operation['request']
            if operation['state'] in {'prepared', 'failed'}:
                if request.get('generation') != task['generation']:
                    continue
                decision = by_id.get(request.get('decision_id'))
                if decision and request.get('decision_revision') != decision['revision']:
                    continue
            active.append(operation)
        states = {o['state'] for o in active}
        confirmed = {o['operation_id'] for o in operations if o['state'] == 'confirmed'}
        undelivered = [d for d in decisions if d['state'] == 'answered' and
                       identity('answer-operation', d['decision_id'] + ':' + str(d['revision'])) not in confirmed]
        complete = False
        if any(d['state'] == 'pending' for d in decisions):
            next_action, owner = 'owner_decision', 'queen'
        elif states & {'in_flight', 'unknown'}:
            next_action, owner = 'reconcile_delivery', 'secretary'
        elif 'prepared' in states:
            next_action, owner = 'deliver_prepared_operation', 'secretary'
        elif 'failed' in states:
            next_action, owner = 'resolve_failed_delivery', 'secretary'
        elif undelivered:
            stale = any(d['payload'].get('generation') != task['generation'] for d in undelivered)
            next_action = 'reconcile_prior_answer' if stale else 'deliver_answer'
            owner = 'secretary'
        elif self.records.list_events(task_id=task_id, processed=False, limit=1):
            next_action, owner = 'triage_events', 'secretary'
        else:
            outcomes = [o for o in self._outcomes(task_id)
                        if o['payload'].get('generation') == task['generation']]
            latest = outcomes[-1]['payload'] if outcomes else {}
            if latest.get('kind') == 'verified':
                next_action, owner, complete = 'report_result', 'queen', True
            elif latest.get('kind') == 'completed':
                next_action, owner = 'verify_result', 'secretary'
            elif latest.get('kind') in {'blocked', 'failed', 'malformed_report'}:
                next_action, owner = 'resolve_blocker', 'secretary'
            else:
                next_action, owner = 'continue_assignment', task['owner']
        return {'task_id': task_id, 'generation': task['generation'], 'complete': complete,
                'next_action': next_action, 'owner': owner}

    def answer(self, decision_id, answer, *, expected_revision, owner_message):
        """The caller must obtain authority from the host's trusted owner channel.

        This journal records that authority reference; it cannot authenticate a
        person from an arbitrary native CLI userMessage or from a worker report.
        """
        return self.records.answer_decision(decision_id, answer,
                                            expected_revision=expected_revision,
                                            owner_message=owner_message)

    def prepare_dispatch(self, task_id, *, new_session=False):
        task = self.records.get_task(task_id)
        meta = task['metadata']
        binding = meta['binding']
        from .preferences import admission_check
        admission_check(self.records, task)
        if binding['session_id'] != task['owner'] or binding['repo'] != task['repository']:
            raise Conflict('00 Agent binding differs from the current assignment')
        if not meta.get('authority_ref'):
            raise RecordError('dispatch requires the original user authority reference')
        brief = meta['standing_orders'] + '\n\n' + meta['brief'] if meta.get('standing_orders') else meta['brief']
        key = task_id + ':' + str(task['generation'])
        ids = {'operation_id': identity('dispatch-operation', key),
               'message_id': identity('dispatch-message', key)}
        if new_session:
            operation = prepare_session(task_id, binding['workspace_id'], binding['repo'],
                                        binding['profile'], agent_name(meta.get('agent_name', task_id)), brief,
                                        session_id=binding['session_id'], **ids)
        else:
            operation = prepare_message(task_id, binding, brief, **ids)
        operation['request']['generation'] = task['generation']
        if new_session:
            # A stored launch is immutable. A branding change must not replace
            # its original intent or prevent reconciliation of an uncertain send.
            try:
                previous = self.records.get_operation(operation['operation_id'])
            except RecordError:
                previous = None
            if previous is not None and previous['kind'] == operation['kind']:
                comparable = {**previous['request'], 'name': operation['request']['name']}
                if comparable == operation['request']:
                    operation['request'] = previous['request']
        return self.records.prepare_operation(operation['operation_id'], task_id,
                                               operation['kind'], operation['request'])

    def prepare_answer(self, decision_id):
        decision = self.records.get_decision(decision_id)
        task = self.records.get_task(decision['task_id'])
        if decision['state'] != 'answered':
            raise Conflict('decision has no recorded owner answer')
        if decision['payload']['generation'] != task['generation']:
            raise StaleGeneration('answer belongs to an earlier 00 Agent assignment')
        binding = task['metadata']['binding']
        if binding['session_id'] != task['owner'] or binding['repo'] != task['repository']:
            raise Conflict('00 Agent binding differs from the current assignment')
        key = decision_id + ':' + str(decision['revision'])
        text = json.dumps({'kind': 'monarchy.answer', 'task_id': task['task_id'],
                           'generation': task['generation'], 'decision_id': decision_id,
                           'revision': decision['revision'], 'answer': decision['answer'],
                           'owner_message': decision['owner_message']}, sort_keys=True)
        operation = prepare_message(task['task_id'], binding, text,
                                    operation_id=identity('answer-operation', key),
                                    message_id=identity('answer-message', key))
        operation['request'].update(generation=task['generation'], decision_id=decision_id,
                                    decision_revision=decision['revision'])
        return self.records.prepare_operation(operation['operation_id'], operation['task_id'],
                                               operation['kind'], operation['request'])

    def deliver(self, operation_id):
        if self.transport is None:
            raise RecordError('a native transport is required')
        operation = self.records.get_operation(operation_id)
        task = self.records.get_task(operation['task_id'])
        request = operation['request']
        if (request.get('generation') != task['generation']
                or request['binding']['session_id'] != task['owner']):
            raise StaleGeneration('delivery belongs to an earlier 00 Agent assignment')
        if 'decision_id' in request:
            decision = self.records.get_decision(request['decision_id'])
            if decision['revision'] != request['decision_revision'] or decision['state'] != 'answered':
                raise Conflict('delivery belongs to a superseded or unanswered decision')
        expected_state = operation['state']
        def persist(value):
            nonlocal expected_state
            saved = self.records.set_operation_state(operation_id, value['state'],
                                                     expected_state=expected_state, result=value['result'])
            expected_state = value['state']
            return saved
        if operation['kind'] == 'create_session':
            return self.transport.create_session(operation, persist)
        return self.transport.send_message(operation, persist)

    def verify(self, task_id, *, source_revision, observed_revision, reviewer, evidence):
        """Record an independently obtained review tied to the current source.

        The caller supplies actual repository readback and review evidence; this
        function does not invent a review or treat a worker's claim as proof.
        """
        _revision(source_revision)
        _revision(observed_revision)
        task = self.records.get_task(task_id)
        if source_revision != observed_revision or reviewer == task['owner']:
            raise Conflict('review must be independent and match the current source')
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise RecordError('reviewer identity is required')
        if not isinstance(evidence, dict) or not evidence.get('checks'):
            raise RecordError('verification requires check evidence')
        if self.status(task_id)['next_action'] != 'verify_result':
            raise Conflict('task has unfinished obligations or no current completion report')
        latest = [o for o in self._outcomes(task_id)
                  if o['payload'].get('generation') == task['generation']][-1]['payload']
        if latest['report'].get('source_revision') != source_revision:
            raise Conflict('completion report and review refer to different source revisions')
        payload = {'kind': 'verified', 'generation': task['generation'],
                   'source_revision': source_revision, 'reviewer': reviewer, 'evidence': evidence}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return self.records.record_outcome(identity('verification', task_id + ':' + digest), task_id, payload)
