"""Exercise real approval validation through grant answer and send admission."""
import copy
from pathlib import Path
import tempfile
import unittest

from monarchy.delegation import Delegation
from monarchy.preferences import Preferences, digest
from monarchy.records import CourtRecords, Conflict, RecordError
from monarchy.supervision import Court
from test_approval import source


HEAD = 'a' * 40
PROJECT = 'example/project'
CATEGORY = 'internal-pr-approval'
WORKER = '22222222-2222-4222-8222-222222222222'


class Transport:
    def __init__(self):
        self.writes = 0
        self.uncertain = False
        self.before = lambda: None

    def send_message(self, operation, persist):
        if operation['state'] == 'prepared':
            self.before()
            persist({**operation, 'state': 'in_flight', 'result': None})
            self.writes += 1
        state = 'unknown' if self.uncertain else 'confirmed'
        return persist({**operation, 'state': state, 'result': {'receipt': 'same-native-identity'}})


class DelegationApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.records = CourtRecords(Path(self.temp.name) / 'royalty.db')
        self.prefs = Preferences(self.records)
        owner = source({'voice.zone': 'UTC'}, 'owner')
        project = source({'project.repository': PROJECT, 'project.required_checks': ['unit']}, 'project')
        for box in self.prefs.founding(owner, project):
            self.records.answer_decision(box['decision_id'], {'accept': True},
                expected_revision=box['revision'], owner_message='actual-founding-answer')
        self.prefs.pin(owner, project, owner_message='pin-answer', monarchy_revision='b' * 40)
        task = self.prefs.bind({'task_id': 'task', 'repository': PROJECT, 'owner': WORKER,
            'metadata': {'binding': {'repo': PROJECT, 'session_id': WORKER,
                                     'workspace_id': '11111111-1111-4111-8111-111111111111'},
                         'execution_mode': 'read-only',
                         'brief': 'Review an internal change.'}})
        self.records.create_task('task', PROJECT, WORKER, metadata=task['metadata'])
        self.transport = Transport()
        self.court = Court(self.records, self.transport)
        self.delegation = Delegation(self.records)
        self.records.record_event('completed', 'task', 1, WORKER, 'completed',
            {'summary': 'Ready for review.', 'source_revision': HEAD})
        self.court.tick('task')
        self.evidence = {'repository': PROJECT, 'candidate_id': 'pr-17', 'source_revision': HEAD,
            'findings': [], 'checks': [{'name': 'unit', 'repository': PROJECT,
                'source_revision': HEAD, 'status': 'completed', 'conclusion': 'success'}]}
        outcome = self.court.verify('task', source_revision=HEAD, observed_revision=HEAD,
                                    reviewer='independent-reviewer', evidence=self.evidence)
        candidate = {'candidate_id': 'pr-17', 'repository': PROJECT, 'source_revision': HEAD,
                     'generation': 1, 'outcome_id': outcome['outcome_id'],
                     'outcome_digest': digest(outcome['payload'])}
        context = {'category': CATEGORY, 'actions': ['approve-internal-pr'],
                   'scope': {'kind': 'internal-maintenance'}, 'classification_complete': True}
        self.records.open_decision('precedent', 'task',
            {'generation': 1, 'question': 'Approve matching internal work?', 'delegation': context})
        self.records.answer_decision('precedent', {'accept': True}, expected_revision=1,
                                     owner_message='actual-owner-precedent')
        box = self.delegation.propose(PROJECT, CATEGORY, 'delegated', owner_message='grant-request',
                                     precedents=[{'decision_id': 'precedent', 'revision': 1}])
        self.records.answer_decision(box['decision_id'], {'accept': True}, expected_revision=1,
                                     owner_message='actual-grant-answer')
        self.grant = self.delegation.apply(box['decision_id'])
        self.records.open_decision('target', 'task', {'generation': 1, 'question': 'Approve this current candidate?',
            'delegation': {**context, 'precedent': {'decision_id': 'precedent', 'revision': 1},
                           'new_risk': False, 'unresolved_flags': [], 'candidate': candidate}})

    def tearDown(self):
        self.records.close()
        self.temp.cleanup()

    def answer(self, **kwargs):
        return self.delegation.answer('target', {'accept': True}, expected_revision=1,
                                       grant_id=self.grant['grant_id'], **kwargs)

    def test_actual_validator_requires_fresh_head_at_answer_prepare_and_admission(self):
        for head in (None, 'c' * 40):
            with self.subTest(stage='answer', head=head), self.assertRaises(RecordError):
                self.answer(current_head=head)
            self.assertEqual(self.records.get_decision('target')['state'], 'pending')
        self.answer(current_head=HEAD)
        for head in (None, 'c' * 40):
            with self.subTest(stage='prepare', head=head), self.assertRaises(RecordError):
                self.court.prepare_answer('target', current_head=head)
        operation = self.court.prepare_answer('target', current_head=HEAD)
        self.assertNotIn('current_head', operation['request'])
        for head in (None, 'c' * 40):
            with self.subTest(stage='admission', head=head), self.assertRaises(RecordError):
                self.court.deliver(operation['operation_id'], current_head=head)
            self.assertEqual(self.records.get_operation(operation['operation_id'])['state'], 'prepared')
            self.assertEqual(self.transport.writes, 0)
        self.assertEqual(self.court.deliver(operation['operation_id'], current_head=HEAD)['state'], 'confirmed')
        self.assertEqual(self.transport.writes, 1)

    def test_uncertain_internal_answer_reconciles_after_head_drift_and_revoke(self):
        self.answer(current_head=HEAD)
        operation = self.court.prepare_answer('target', current_head=HEAD)
        self.transport.uncertain = True
        self.assertEqual(self.court.deliver(operation['operation_id'], current_head=HEAD)['state'], 'unknown')
        self.delegation.revoke(PROJECT, CATEGORY, owner_message='revoke-during-uncertainty')
        self.transport.uncertain = False
        self.assertEqual(self.court.deliver(operation['operation_id'], current_head='c' * 40)['state'], 'confirmed')
        self.court.deliver(operation['operation_id'])
        self.assertEqual(self.transport.writes, 1)

    def test_revocation_between_preflight_and_send_admission_prevents_native_write(self):
        self.answer(current_head=HEAD)
        operation = self.court.prepare_answer('target', current_head=HEAD)
        self.transport.before = lambda: self.delegation.revoke(PROJECT, CATEGORY,
                                                              owner_message='racing-revoke')
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'], current_head=HEAD)
        self.assertEqual(self.transport.writes, 0)
        self.assertEqual(self.records.get_operation(operation['operation_id'])['state'], 'prepared')

    def test_new_source_evidence_after_preparation_is_rechecked_at_admission(self):
        self.answer(current_head=HEAD)
        operation = self.court.prepare_answer('target', current_head=HEAD)
        self.records.record_event('late-failure', 'task', 1, WORKER, 'failed',
                                  {'summary': 'A new issue needs review.'})
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'], current_head=HEAD)
        self.assertEqual(self.transport.writes, 0)

    def test_configuration_change_after_preparation_requires_fresh_grant(self):
        self.answer(current_head=HEAD)
        operation = self.court.prepare_answer('target', current_head=HEAD)
        self.prefs.override('voice.forbidden_characters', ['!'], owner_message='new-policy')
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'], current_head=HEAD)
        self.assertEqual(self.transport.writes, 0)

    def test_general_category_cannot_answer_a_stale_task_using_a_new_grant(self):
        pin = self.records.latest_pin(PROJECT)['payload']
        self.prefs.pin(pin['owner'], pin['project'], owner_message='new-current-pin',
                       monarchy_revision=pin['monarchy_revision'])
        context = {'category': 'ci-rerun-at-approved-head', 'actions': ['rerun-approved-ci'],
                   'scope': {'workflow': 'unit'}, 'classification_complete': True}
        self.records.open_decision('ci-precedent', 'task',
            {'generation': 1, 'question': 'Rerun this approved check?', 'delegation': context})
        self.records.answer_decision('ci-precedent', {'accept': True}, expected_revision=1,
                                     owner_message='actual-ci-precedent')
        box = self.delegation.propose(PROJECT, context['category'], 'delegated', owner_message='new-ci-grant',
                                     precedents=[{'decision_id': 'ci-precedent', 'revision': 1}])
        self.records.answer_decision(box['decision_id'], {'accept': True}, expected_revision=1,
                                     owner_message='actual-new-grant-answer')
        grant = self.delegation.apply(box['decision_id'])
        context.update(precedent={'decision_id': 'ci-precedent', 'revision': 1},
                       new_risk=False, unresolved_flags=[])
        self.records.open_decision('ci-target', 'task',
            {'generation': 1, 'question': 'Rerun matching checks?', 'delegation': context})
        with self.assertRaises(Conflict):
            self.delegation.answer('ci-target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])
        self.assertEqual(self.records.get_decision('ci-target')['state'], 'pending')

    def test_founding_cannot_consume_a_grant_origin_confirmation(self):
        decision = next(row for row in self.records.list_decisions()
                        if row['payload'].get('kind') == 'founding.profiles')
        self.records._connection.execute('UPDATE decisions SET answered_by=?,owner_message=NULL WHERE decision_id=?',
            ('grant:' + self.grant['grant_id'], decision['decision_id']))
        with self.assertRaises(Conflict): self.prefs.require_current(PROJECT)
