"""Durable forwarding boundary tests without native writes."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from monarchy.conversation import Conversation, prompt_policy, lint_text
from monarchy.config import resolve
from monarchy.records import CourtRecords, Conflict, RecordError
from monarchy.supervision import Court

QUEEN = '33333333-3333-4333-8333-333333333333'
SECRETARY = '44444444-4444-4444-8444-444444444444'
WORKER = '22222222-2222-4222-8222-222222222222'
WORKSPACE = '11111111-1111-4111-8111-111111111111'
PROFILE = {'agent': 'codex', 'model': 'chosen-model', 'effort': 'high', 'fast_mode': False}
NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def binding(session):
    return {'session_id': session, 'workspace_id': WORKSPACE, 'repo': 'example/project',
            'profile': PROFILE}


class Transport:
    def __init__(self):
        self.writes = 0
        self.before = lambda: None
        self.uncertain = False

    def send_message(self, operation, persist):
        if operation['state'] == 'prepared':
            self.before()
            persist({**operation, 'state': 'in_flight', 'result': None})
            self.writes += 1
        state = 'unknown' if self.uncertain else 'confirmed'
        return persist({**operation, 'state': state, 'result': {'receipt': 'native-readback'}})


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'royalty.db'
        self.records = CourtRecords(self.path)
        self.transport = Transport()
        self.court = Court(self.records, self.transport)
        self.conversation = Conversation(self.records)
        self.records.create_task('task', 'example/project', WORKER, metadata={
            'binding': binding(WORKER), 'queen_binding': binding(QUEEN),
            'secretary_binding': binding(SECRETARY), 'brief': 'Investigate source.'})
        self.records.record_event('blocked', 'task', 1, WORKER, 'blocked',
                                  {'summary': 'A scoped answer is needed.'})
        self.court.tick('task')
        self.outcome = self.records.list_outcomes(task_id='task')[0]['outcome_id']

    def tearDown(self):
        self.records.close()
        self.temp.cleanup()

    def prepare(self, text='One scoped answer is needed.'):
        return self.conversation.prepare_forward(self.outcome, text)

    def closed(self):
        self.conversation.observe(QUEEN, 'box', 'open')
        self.conversation.observe(QUEEN, 'box', 'close')

    def test_unknown_holds_before_any_native_write_and_queue_survives_restart(self):
        operation = self.prepare()
        self.assertEqual(operation['request']['text'], '[secretary] One scoped answer is needed.')
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'])
        self.assertEqual(self.transport.writes, 0)
        self.assertEqual(self.records.get_operation(operation['operation_id'])['state'], 'prepared')
        with CourtRecords(self.path) as other:
            self.assertEqual(Conversation(other).prepare_forward(self.outcome,
                'One scoped answer is needed.')['operation_id'], operation['operation_id'])
        with self.assertRaises(Conflict): self.prepare('Different summary.')

    def test_real_state_cycle_releases_exact_operation_once(self):
        operation = self.prepare()
        self.conversation.observe(QUEEN, 'box', 'open')
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'])
        self.conversation.observe(QUEEN, 'box', 'close')
        self.assertEqual(self.court.deliver(operation['operation_id'])['state'], 'confirmed')
        self.court.deliver(operation['operation_id'])
        self.assertEqual(self.transport.writes, 1)

    def test_expiry_only_applies_to_known_open_and_valid_past_timestamp(self):
        for state, delta, expected in [('open', 59, 'hold'), ('open', 60, 'available'),
                                       ('unknown', 600, 'hold'), ('closed', 0, 'available'),
                                       ('closed', -1, 'hold'), ('open', -100, 'hold')]:
            observation = {'state': state, 'observed_at': (NOW-timedelta(minutes=delta)).isoformat()}
            self.assertEqual(prompt_policy(observation, 60, now=NOW), expected)
        for value in ('bad', '2026-01-01T10:00:00'):
            self.assertEqual(prompt_policy({'state': 'open', 'observed_at': value}, 60, now=NOW), 'hold')
        self.assertEqual(prompt_policy(None, 60, now=NOW), 'hold')

    def test_stale_close_cannot_release_newer_box_and_duplicate_open_does_not_reset_age(self):
        first = self.conversation.observe(QUEEN, 'first', 'open')
        self.assertEqual(self.conversation.observe(QUEEN, 'first', 'open'), first)
        self.conversation.observe(QUEEN, 'first', 'close')
        self.conversation.observe(QUEEN, 'second', 'open')
        self.conversation.observe(QUEEN, 'first', 'close')
        self.assertEqual(self.conversation.status(QUEEN)['prompt_id'], 'second')
        self.assertEqual(self.conversation.status(QUEEN)['state'], 'open')

    def test_overlapping_open_cannot_hide_the_first_box(self):
        self.conversation.observe(QUEEN, 'first', 'open')
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'second', 'open')
        self.conversation.observe(QUEEN, 'second', 'close')
        with self.assertRaises(Conflict): self.court.deliver(self.prepare()['operation_id'])
        self.assertEqual(self.transport.writes, 0)

    def test_replayed_pre_hook_cannot_resurrect_a_completed_prompt(self):
        self.closed()
        operation = self.prepare()
        self.records.set_operation_state(operation['operation_id'], 'in_flight', expected_state='prepared')
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'box', 'open')
        self.court.deliver(operation['operation_id'])
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'box', 'open')

    def test_failed_close_becomes_unknown_and_duplicate_close_cannot_clear_it(self):
        self.closed()
        self.conversation.observe(QUEEN, 'box', 'unknown')
        self.conversation.observe(QUEEN, 'box', 'close')
        self.assertEqual(self.conversation.status(QUEEN)['state'], 'unknown')
        with self.assertRaises(Conflict): self.court.deliver(self.prepare()['operation_id'])

    def test_close_without_matching_open_never_establishes_closed(self):
        self.conversation.observe(QUEEN, 'missing', 'close')
        self.assertEqual(self.conversation.status(QUEEN)['state'], 'unknown')

    def test_unregistered_session_cannot_publish_prompt_observations(self):
        with self.assertRaises(Conflict): self.conversation.observe(WORKER, 'box', 'open')

    def test_uncorrelated_completion_holds_a_previously_closed_session(self):
        self.closed()
        self.conversation.observe(QUEEN, 'unseen', 'unknown')
        self.assertEqual(self.conversation.status(QUEEN)['state'], 'unknown')

    def test_uncorrelated_callback_cannot_inherit_known_open_expiry(self):
        self.conversation.observe(QUEEN, 'first', 'open')
        old = (datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat()
        self.records._connection.execute('UPDATE prompt_observations SET observed_at=?', (old,))
        self.conversation.observe(QUEEN, 'unseen', 'unknown')
        self.assertEqual(self.conversation.status(QUEEN)['state'], 'unknown')
        with self.assertRaises(Conflict): self.court.deliver(self.prepare()['operation_id'])
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'next', 'open')
        self.assertEqual(self.transport.writes, 0)

    def test_cancelled_question_reopens_but_forwards_wait_for_matching_answer(self):
        operation = self.prepare()
        self.conversation.observe(QUEEN, 'first', 'open')
        cancelled = self.conversation.observe(QUEEN, 'first', 'cancel')
        self.assertEqual((cancelled['state'], cancelled['reason']), ('unknown', 'native-cancelled'))
        self.assertEqual(self.conversation.observe(QUEEN, 'first', 'cancel'), cancelled)
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'])
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'first', 'open')
        self.assertEqual(self.conversation.observe(QUEEN, 'first', 'close'), cancelled)
        with CourtRecords(self.path) as reopened:
            next_box = Conversation(reopened).observe(QUEEN, 'second', 'open')
        self.assertEqual((next_box['state'], next_box['reason']), ('open', 'answer-required'))
        self.assertEqual(self.conversation.observe(QUEEN, 'second', 'open'), next_box)
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        self.records._connection.execute('UPDATE prompt_observations SET observed_at=?', (old,))
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'])
        for action in ('cancel', 'close', 'unknown'):
            self.conversation.observe(QUEEN, 'first', action)
            self.assertEqual(self.conversation.status(QUEEN)['prompt_id'], 'second')
            self.assertEqual(self.conversation.status(QUEEN)['reason'], 'answer-required')
        closed = self.conversation.observe(QUEEN, 'second', 'close')
        self.assertEqual((closed['state'], closed['reason']), ('closed', None))
        self.assertEqual(self.court.deliver(operation['operation_id'])['state'], 'confirmed')
        self.court.deliver(operation['operation_id'])
        self.assertEqual(self.transport.writes, 1)

    def test_successive_cancellations_keep_reopened_questions_held_past_expiry(self):
        self.conversation.observe(QUEEN, 'first', 'open')
        for previous, fresh in [('first', 'second'), ('second', 'third')]:
            self.conversation.observe(QUEEN, previous, 'cancel')
            observation = self.conversation.observe(QUEEN, fresh, 'open')
            self.assertEqual(observation['reason'], 'answer-required')
            self.assertEqual(prompt_policy(observation, now=datetime.now(timezone.utc)
                                           + timedelta(days=10)), 'hold')

    def test_cancellation_cannot_repair_generic_unknown_or_failed_reopen(self):
        self.conversation.observe(QUEEN, 'first', 'open')
        self.conversation.observe(QUEEN, 'first', 'unknown')
        observation = self.conversation.observe(QUEEN, 'first', 'cancel')
        self.assertEqual((observation['state'], observation['reason']), ('unknown', None))
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'second', 'open')
        self.conversation.observe(QUEEN, 'first', 'close')
        with self.assertRaises(Conflict): self.court.deliver(self.prepare()['operation_id'])

    def test_unknown_after_native_cancellation_removes_reopen_permission(self):
        self.conversation.observe(QUEEN, 'first', 'open')
        self.conversation.observe(QUEEN, 'first', 'cancel')
        observation = self.conversation.observe(QUEEN, 'first', 'unknown')
        self.assertEqual((observation['state'], observation['reason']), ('unknown', None))
        self.assertEqual(self.conversation.observe(QUEEN, 'first', 'cancel'), observation)
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'second', 'open')

    def test_unknown_on_reopened_question_cannot_be_repaired_by_cancel_or_close(self):
        self.conversation.observe(QUEEN, 'first', 'open')
        self.conversation.observe(QUEEN, 'first', 'cancel')
        self.conversation.observe(QUEEN, 'second', 'open')
        observation = self.conversation.observe(QUEEN, 'second', 'unknown')
        self.assertIsNone(observation['reason'])
        for action in ('cancel', 'close'):
            self.assertEqual(self.conversation.observe(QUEEN, 'second', action), observation)
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'third', 'open')

    def test_uncorrelated_or_contradictory_cancellation_never_allows_reopen(self):
        self.closed()
        for prompt_id in ('box', 'unseen'):
            observation = self.conversation.observe(QUEEN, prompt_id, 'cancel')
            self.assertEqual((observation['state'], observation['reason']), ('unknown', None))
            with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'next', 'open')
        with self.assertRaises(Conflict): self.court.deliver(self.prepare()['operation_id'])

    def test_reopen_refuses_any_historically_seen_id_including_unmatched_callback(self):
        # A legacy journal may retain a callback without its matching open.
        self.records._connection.execute(
            'INSERT INTO prompt_observations(session_id,prompt_id,state,observed_at) VALUES(?,?,?,?)',
            (QUEEN, 'old-callback', 'unknown', NOW.isoformat()))
        self.records._connection.execute(
            'INSERT INTO prompt_observations(session_id,prompt_id,state,observed_at) VALUES(?,?,?,?)',
            (QUEEN, 'first', 'open', NOW.isoformat()))
        self.conversation.observe(QUEEN, 'first', 'cancel')
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'old-callback', 'open')
        self.conversation.observe(QUEEN, 'fresh', 'open')

    def test_cancelled_reopen_keeps_inflight_and_unknown_forward_fence(self):
        self.closed()
        operation = self.prepare()
        self.records.set_operation_state(operation['operation_id'], 'in_flight', expected_state='prepared')
        # A real open may predate recovery of an uncertain native send.
        self.records._connection.execute(
            'INSERT INTO prompt_observations(session_id,prompt_id,state,observed_at) VALUES(?,?,?,?)',
            (QUEEN, 'first', 'open', NOW.isoformat()))
        self.conversation.observe(QUEEN, 'first', 'cancel')
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'second', 'open')
        self.records.set_operation_state(operation['operation_id'], 'unknown', expected_state='in_flight')
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'second', 'open')
        self.court.deliver(operation['operation_id'])
        self.conversation.observe(QUEEN, 'second', 'open')
        self.assertEqual(self.transport.writes, 0)

    def test_any_reason_holds_even_with_expired_or_closed_observation(self):
        for state in ('open', 'closed', 'unknown'):
            for reason in ('answer-required', 'native-cancelled', 'unrecognized'):
                with self.subTest(state=state, reason=reason):
                    self.assertEqual(prompt_policy({'state': state, 'reason': reason,
                        'observed_at': NOW.isoformat()}, now=NOW+timedelta(days=10)), 'hold')

    def test_v3_migration_preserves_unknown_without_inferring_cancellation(self):
        self.conversation.observe(QUEEN, 'legacy', 'unknown')
        operation = self.prepare()
        self.records.close()
        with sqlite3.connect(self.path) as legacy:
            legacy.execute('ALTER TABLE prompt_observations RENAME TO prompt_v4')
            legacy.execute("""CREATE TABLE prompt_observations (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                prompt_id TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('open','closed','unknown')),
                observed_at TEXT NOT NULL)""")
            legacy.execute('INSERT INTO prompt_observations SELECT sequence,session_id,prompt_id,state,observed_at FROM prompt_v4')
            legacy.execute('DROP TABLE prompt_v4')
            legacy.execute('PRAGMA user_version=3')
        self.records = CourtRecords(self.path)
        self.conversation = Conversation(self.records)
        self.assertEqual(self.records._connection.execute('PRAGMA user_version').fetchone()[0], 4)
        observation = self.conversation.status(QUEEN)
        self.assertEqual((observation['state'], observation['reason']), ('unknown', None))
        self.assertEqual(self.records.get_operation(operation['operation_id']), operation)
        self.assertEqual(self.conversation.observe(QUEEN, 'legacy', 'cancel'), observation)
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'fresh', 'open')
        with CourtRecords(self.path) as again:
            self.assertEqual(Conversation(again).status(QUEEN), observation)

    def test_v4_missing_reason_column_is_rejected_without_partial_repair(self):
        self.records.close()
        with sqlite3.connect(self.path) as broken:
            broken.execute('DROP TABLE prompt_observations')
            broken.execute("""CREATE TABLE prompt_observations (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                prompt_id TEXT NOT NULL, state TEXT NOT NULL, observed_at TEXT NOT NULL)""")
            broken.execute('PRAGMA user_version=4')
        with self.assertRaises(RecordError): CourtRecords(self.path)
        with sqlite3.connect(self.path) as after:
            self.assertNotIn('reason', {row[1] for row in after.execute('PRAGMA table_info(prompt_observations)')})
            self.assertEqual(after.execute('PRAGMA user_version').fetchone()[0], 4)

    def test_v4_missing_prompt_history_table_is_not_silently_recreated(self):
        self.records.close()
        with sqlite3.connect(self.path) as broken:
            broken.execute('DROP TABLE prompt_observations')
            broken.execute('PRAGMA user_version=4')
        with self.assertRaises(RecordError): CourtRecords(self.path)
        with sqlite3.connect(self.path) as after:
            self.assertIsNone(after.execute(
                "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='prompt_observations'").fetchone())

    def test_schema_refuses_invalid_cancellation_reason_state_pairs(self):
        for state, reason in [('closed', 'native-cancelled'), ('open', 'native-cancelled'),
                              ('unknown', 'answer-required'), ('closed', 'answer-required'),
                              ('open', 'unrecognized')]:
            with self.subTest(state=state, reason=reason), self.assertRaises(sqlite3.IntegrityError):
                self.records._connection.execute(
                    'INSERT INTO prompt_observations(session_id,prompt_id,state,observed_at,reason) VALUES(?,?,?,?,?)',
                    (QUEEN, 'invalid', state, NOW.isoformat(), reason))

    def test_prompt_open_between_prepare_and_admission_holds_delivery(self):
        self.closed()
        operation = self.prepare()
        self.transport.before = lambda: self.conversation.observe(QUEEN, 'racing-box', 'open')
        with self.assertRaises(Conflict): self.court.deliver(operation['operation_id'])
        self.assertEqual(self.transport.writes, 0)

    def test_inflight_or_unknown_delivery_blocks_new_prompt_until_reconciled(self):
        self.closed()
        operation = self.prepare()
        self.records.set_operation_state(operation['operation_id'], 'in_flight', expected_state='prepared')
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'racing-box', 'open')
        self.records.set_operation_state(operation['operation_id'], 'unknown', expected_state='in_flight')
        with self.assertRaises(Conflict): self.conversation.observe(QUEEN, 'racing-box', 'open')
        self.court.deliver(operation['operation_id'])
        self.conversation.observe(QUEEN, 'racing-box', 'open')
        self.assertEqual(self.transport.writes, 0)

    def test_uncertain_delivery_can_be_reconciled_during_unknown_prompt_and_pause(self):
        self.closed()
        self.transport.uncertain = True
        operation = self.prepare()
        self.court.deliver(operation['operation_id'])
        self.conversation.observe(QUEEN, 'box', 'unknown')
        from monarchy.preferences import Preferences
        Preferences(self.records).override('court.paused', True, owner_message='pause-reference')
        self.transport.uncertain = False
        self.assertEqual(self.court.deliver(operation['operation_id'])['state'], 'confirmed')
        self.assertEqual(self.transport.writes, 1)

    def test_forward_route_must_match_registered_queen_and_secretary(self):
        self.closed()
        operation = self.prepare()
        forged = dict(operation['request'])
        forged['sender_session_id'] = WORKER
        self.records.prepare_operation('55555555-5555-4555-8555-555555555555',
            'task', 'send_message', forged)
        with self.assertRaises(Conflict):
            self.records.set_operation_state('55555555-5555-4555-8555-555555555555',
                'in_flight', expected_state='prepared')

    def test_forward_caps_header_and_forbidden_character_lint(self):
        for text in ('', 'a\nb\nc\nd', 'x'*889, 'bad\u2014punctuation', '[secretary] forged', 'bad\x00text'):
            with self.subTest(text=text[:20]), self.assertRaises(RecordError): self.prepare(text)
        operation = self.prepare('x'*888)
        self.assertEqual(len(operation['request']['text']), 900)
        from monarchy.preferences import Preferences
        Preferences(self.records).override('voice.forbidden_characters', ['x'], owner_message='tighten-prose')
        self.closed()
        with self.assertRaises(RecordError): self.court.deliver(operation['operation_id'])

    def test_report_summary_caps_allow_full_evidence_separately(self):
        config = resolve()
        lint_text('line\n'*4+'last', config, 'reports')
        for text in ('line\n'*5+'last', 'x'*1201):
            with self.assertRaises(RecordError): lint_text(text, config, 'reports')


if __name__ == '__main__':
    unittest.main()
