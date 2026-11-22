"""Persistent service tests; no live workers are launched."""
from pathlib import Path
import tempfile
import unittest

from monarchy.records import CourtRecords, Conflict, StaleGeneration
from monarchy.supervision import Court

WORKER = '22222222-2222-4222-8222-222222222222'
WORKSPACE = '11111111-1111-4111-8111-111111111111'
REVISION = 'a' * 40
BINDING = {'session_id': WORKER, 'workspace_id': WORKSPACE, 'repo': 'example/project',
           'profile': {'agent': 'codex', 'model': 'chosen-model', 'effort': 'high', 'fast_mode': False}}


class CourtTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'court.db'
        self.records = CourtRecords(self.path)
        self.court = Court(self.records)
        self.records.create_task('task', 'example/project', WORKER, metadata={
            'execution_mode': 'read-only',
            'binding': BINDING, 'brief': 'Read-only investigation.', 'source_revision': REVISION})

    def tearDown(self):
        self.records.close()
        self.temp.cleanup()

    def event(self, event_id, kind, payload):
        return self.records.record_event(event_id, 'task', 1, WORKER, kind, payload)

    def test_routine_progress_is_quiet_but_ambiguity_is_actionable(self):
        self.event('progress', 'progress', {'summary': 'Reading source', 'routine': True})
        self.event('uncertain', 'progress', {'summary': 'Unsure whether we may proceed'})
        result = self.court.tick('task')
        self.assertEqual(result['consumed'], 2)
        self.assertEqual(len(self.records.list_outcomes(recipient='secretary')), 1)
        self.assertEqual(self.court.tick('task')['consumed'], 0)

    def test_decision_survives_done_restart_and_presentation(self):
        self.event('question', 'decision', {'question': 'May scope expand?', 'recommendation': 'Keep scope'})
        self.event('done', 'completed', {'summary': 'Worker finished', 'source_revision': REVISION})
        self.court.tick('task')
        presentation = self.court.inbox()
        self.assertTrue(presentation['outcomes'])
        self.records.close()
        self.records = CourtRecords(self.path)
        self.court = Court(self.records)
        self.assertEqual(self.court.inbox()['presentation_id'], presentation['presentation_id'])
        self.assertEqual(len(self.records.list_decisions(task_id='task', state='pending')), 1)
        self.assertEqual(self.court.status('task')['next_action'], 'owner_decision')
        self.assertFalse(self.court.status('task')['complete'])

    def test_tick_crash_after_outcome_does_not_duplicate_or_lose_event(self):
        self.event('blocked', 'blocked', {'summary': 'Test failed'})
        original = self.records.ack_events
        self.records.ack_events = lambda *a, **k: (_ for _ in ()).throw(OSError('crash'))
        with self.assertRaises(OSError): self.court.tick('task')
        self.records.ack_events = original
        self.court.tick('task')
        self.assertEqual(len(self.records.list_outcomes(task_id='task')), 1)
        self.assertEqual(self.records.list_events(task_id='task', processed=False), [])

    def test_unknown_prompt_state_does_not_push_to_queen(self):
        self.event('blocked', 'blocked', {'summary': 'Needs diagnosis'})
        self.court.tick('task')
        self.assertEqual(self.court.notification_policy('unknown'), 'hold')
        self.assertEqual(self.court.notification_policy('open'), 'hold')
        self.assertEqual(self.court.notification_policy('closed'), 'available')
        self.assertTrue(self.court.inbox(actor='secretary')['outcomes'])

    def test_verification_requires_current_source_and_independent_evidence(self):
        self.event('done', 'completed', {'summary': 'Ready', 'source_revision': REVISION})
        self.court.tick('task')
        for source, observer in [('b'*40, 'reviewer'), (REVISION, WORKER)]:
            with self.assertRaises(Conflict):
                self.court.verify('task', source_revision=source, observed_revision=REVISION,
                                  reviewer=observer, evidence={'checks': ['test passed']})
        result = self.court.verify('task', source_revision=REVISION, observed_revision=REVISION,
                                   reviewer='reviewer', evidence={'checks': ['test passed']})
        self.assertEqual(result['payload']['kind'], 'verified')
        self.assertTrue(self.court.status('task')['complete'])

    def test_pending_decision_prevents_verification(self):
        self.event('question', 'decision', {'question': 'Can we expand scope?'})
        self.event('done', 'completed', {'summary': 'Ready', 'source_revision': REVISION})
        self.court.tick('task')
        with self.assertRaises(Conflict):
            self.court.verify('task', source_revision=REVISION, observed_revision=REVISION,
                              reviewer='reviewer', evidence={'checks': ['test passed']})

    def test_reassignment_makes_old_completion_unusable(self):
        self.event('done', 'completed', {'summary': 'Ready', 'source_revision': REVISION})
        self.court.tick('task')
        self.records.assign_task('task', 'replacement', expected_generation=1)
        with self.assertRaises(Conflict):
            self.court.verify('task', source_revision=REVISION, observed_revision=REVISION,
                              reviewer='reviewer', evidence={'checks': ['test passed']})

    def test_answer_reuses_identity_and_cannot_reach_replacement_worker(self):
        self.event('question', 'decision', {'question': 'Proceed?'})
        self.court.tick('task')
        decision = self.records.list_decisions(task_id='task')[0]
        self.court.answer(decision['decision_id'], {'text': 'Within the original scope'},
                          expected_revision=decision['revision'], owner_message='trusted-owner-message')
        one = self.court.prepare_answer(decision['decision_id'])
        two = self.court.prepare_answer(decision['decision_id'])
        self.assertEqual(one['operation_id'], two['operation_id'])
        self.assertEqual(one['request']['message_id'], two['request']['message_id'])
        self.records.assign_task('task', 'replacement', expected_generation=1)
        with self.assertRaises(StaleGeneration):
            self.court.prepare_answer(decision['decision_id'])
        class UnusedTransport:
            def send_message(self, *args): raise AssertionError('must not send')
        self.court.transport = UnusedTransport()
        with self.assertRaises(StaleGeneration): self.court.deliver(one['operation_id'])

    def test_uncertain_delivery_persists_and_restart_only_reconciles(self):
        self.event('question', 'decision', {'question': 'Proceed?'})
        self.court.tick('task')
        decision = self.records.list_decisions(task_id='task')[0]
        self.court.answer(decision['decision_id'], {'text': 'Yes'},
                          expected_revision=decision['revision'], owner_message='owner-reference')
        operation = self.court.prepare_answer(decision['decision_id'])
        class UncertainTransport:
            def send_message(self, op, persist):
                if op['state'] == 'prepared':
                    persist({**op, 'state': 'in_flight', 'result': None})
                value = {**op, 'state': 'unknown', 'result': {'reason': 'timeout'}}
                persist(value)
                return value
        self.court.transport = UncertainTransport()
        self.court.deliver(operation['operation_id'])
        self.assertEqual(self.court.status('task')['next_action'], 'reconcile_delivery')
        self.records.close()
        self.records = CourtRecords(self.path)
        self.court = Court(self.records, UncertainTransport())
        self.assertEqual(self.court.deliver(operation['operation_id'])['state'], 'unknown')

    def test_native_report_is_bound_to_assignment_and_ingested_once(self):
        meta = self.records.get_task('task')['metadata']
        meta.update(court_id='court', secretary_binding={**BINDING, 'session_id': 'secretary'})
        self.records.assign_task('task', WORKER, expected_generation=1, metadata=meta)
        class ReportTransport:
            def accept_report(self, event_id, court_id, recipient, members):
                assert members[WORKER]['attempt_id'] == '2'
                return {'envelope': {'report_id': 'native-report', 'report': {
                    'status': 'decision', 'summary': 'Need input', 'evidence': [],
                    'next_action': 'Ask the owner', 'question': 'Which scope?'}}}
        self.court.transport = ReportTransport()
        self.court.ingest('task', 'native-event')
        self.court.ingest('task', 'native-event')
        self.court.tick('task')
        self.assertEqual(len(self.records.list_events(task_id='task')), 1)
        self.assertEqual(len(self.court.inbox()['outcomes']), 1)

    def test_answer_without_prepared_delivery_still_blocks_completion(self):
        self.event('question', 'decision', {'question': 'Which choice?'})
        self.event('done', 'completed', {'summary': 'Ready', 'source_revision': REVISION})
        self.court.tick('task')
        decision = self.records.list_decisions(task_id='task')[0]
        self.court.answer(decision['decision_id'], {'text': 'Choose the first'},
                          expected_revision=1, owner_message='trusted-message')
        self.assertEqual(self.court.status('task')['next_action'], 'deliver_answer')
        with self.assertRaises(Conflict):
            self.court.verify('task', source_revision=REVISION, observed_revision=REVISION,
                              reviewer='reviewer', evidence={'checks': ['pass']})

    def test_superseded_decision_answer_cannot_be_delivered(self):
        self.event('question', 'decision', {'question': 'Which choice?'})
        self.court.tick('task')
        decision = self.records.list_decisions(task_id='task')[0]
        self.court.answer(decision['decision_id'], {'text': 'First'},
                          expected_revision=1, owner_message='trusted-message')
        operation = self.court.prepare_answer(decision['decision_id'])
        self.records.revise_decision(decision['decision_id'], {
            'generation': 1, 'question': 'A changed question', 'source_event': 'question'}, expected_revision=1)
        class MustNotSend:
            def send_message(self, *args): raise AssertionError('stale decision must not send')
        self.court.transport = MustNotSend()
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'])

    def test_reassignment_between_disposition_and_ack_does_not_poison_replay(self):
        self.event('blocked', 'blocked', {'summary': 'Investigate failure'})
        original = self.records.ack_events
        def reassign_before_ack(*args, **kwargs):
            self.records.assign_task('task', 'replacement', expected_generation=1)
            return original(*args, **kwargs)
        self.records.ack_events = reassign_before_ack
        with self.assertRaises(StaleGeneration): self.court.tick('task')
        self.records.ack_events = original
        self.assertEqual(self.court.tick('task')['consumed'], 1)
        self.assertEqual(len(self.records.list_outcomes(task_id='task')), 1)
        self.assertEqual(self.records.list_events(task_id='task', processed=False), [])

    def test_decision_creation_replay_preserves_later_revision(self):
        for crash_at in ('outcome', 'ack'):
            with self.subTest(crash_at=crash_at), tempfile.TemporaryDirectory() as directory:
                with CourtRecords(Path(directory) / 'court.db') as records:
                    court = Court(records)
                    records.create_task('task', 'example/project', WORKER)
                    records.record_event('question', 'task', 1, WORKER, 'decision', {'question': 'Original?'})
                    method = 'record_outcome' if crash_at == 'outcome' else 'ack_events'
                    original = getattr(records, method)
                    setattr(records, method, lambda *a, **k: (_ for _ in ()).throw(OSError('crash')))
                    with self.assertRaises(OSError): court.tick('task')
                    setattr(records, method, original)
                    decision = records.list_decisions(task_id='task')[0]
                    changed = {**decision['payload'], 'question': 'Changed?'}
                    records.revise_decision(decision['decision_id'], changed, expected_revision=1)
                    self.assertEqual(court.tick('task')['consumed'], 1)
                    self.assertEqual(records.get_decision(decision['decision_id'])['revision'], 2)
                    self.assertEqual(records.get_decision(decision['decision_id'])['payload'], changed)
                    self.assertEqual(len(records.list_outcomes(task_id='task')), 1)
