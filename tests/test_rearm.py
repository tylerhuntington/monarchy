"""Bounded Secretary wake intents never complete checks or install hooks."""
import json
import io
import fcntl
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from monarchy.rearm import settings_snippet, wait, run_hook
from monarchy.records import CourtRecords, RecordError
from monarchy.controls import Controls
from monarchy.preferences import digest
from monarchy.cadence import Cadence


SECRETARY = '22222222-2222-4222-8222-222222222222'
PROJECT = 'example/project'
QUEEN = '33333333-3333-4333-8333-333333333333'
NOW = datetime(2026, 1, 1, 0, 31, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.elapsed = 0
        self.sleeps = []

    def __call__(self):
        return self.elapsed

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.elapsed += seconds


def binding(session):
    return {'session_id': session, 'workspace_id': '11111111-1111-4111-8111-111111111111',
            'repo': PROJECT}


class RearmTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.records = CourtRecords(Path(self.directory.name) / 'private.db')
        self.addCleanup(self.records.close)
        with patch('monarchy.records._now', return_value='2026-01-01T00:00:00+00:00'):
            self.records.create_task('task', PROJECT, 'builder', metadata={
                'secretary_binding': binding(SECRETARY), 'queen_binding': binding(QUEEN)})

    def test_snippet_is_explicit_and_does_not_install_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = settings_snippet(str(root / "hook '$.py"), str(root / 'private.db'), PROJECT, SECRETARY)
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual(set(result['hooks']), {'Stop', 'StopFailure'})
            for event in result['hooks'].values():
                hook = event[0]['hooks'][0]
                self.assertTrue(hook['asyncRewake'])
                self.assertGreater(hook['timeout'], 6600)
                self.assertIn('MONARCHY_REARM=1', hook['command'])
                self.assertIn(SECRETARY, hook['command'])
            json.dumps(result)

    def test_invalid_bounds_and_foreign_session_never_begin_polling(self):
        for value in (0, -1, True, float('nan'), float('inf'), 7201):
            with self.subTest(seconds=value), self.assertRaises(RecordError):
                wait(self.records, project=PROJECT, secretary_session=SECRETARY, max_seconds=value)
        for value in (0, 0.001, True, 61):
            with self.subTest(poll=value), self.assertRaises(RecordError):
                wait(self.records, project=PROJECT, secretary_session=SECRETARY, poll_seconds=value)
        self.assertEqual(wait(self.records, project=PROJECT, secretary_session=QUEEN)['reason'],
                         'identity-changed')

    def test_pause_stops_new_wake_without_erasing_records(self):
        Controls(self.records).command('pause', owner_message='owner-pause')
        before = self.records._connection.total_changes
        self.assertEqual(wait(self.records, project=PROJECT, secretary_session=SECRETARY)['reason'], 'held')
        self.assertEqual(self.records._connection.total_changes, before)

    def environment(self):
        return {'MONARCHY_REARM': '1', 'MONARCHY_STATE': str(self.records.path),
                'MONARCHY_PROJECT': PROJECT, 'MONARCHY_SECRETARY_SESSION': SECRETARY,
                'CONDUCTOR_SESSION_ID': SECRETARY}

    def test_hook_needs_explicit_opt_in_and_never_runs_in_the_queen(self):
        raw = json.dumps({'hook_event_name': 'Stop', 'stop_hook_active': False}).encode()
        for env in ({}, dict(self.environment(), MONARCHY_REARM='0'),
                    dict(self.environment(), CONDUCTOR_SESSION_ID=QUEEN)):
            self.assertEqual(run_hook(raw, env, stderr=io.StringIO()), 0)
        self.assertEqual(sorted(p.name for p in Path(self.directory.name).iterdir()), ['private.db'])

    def test_hook_failure_is_safe_and_does_not_create_a_missing_journal(self):
        err = io.StringIO()
        for raw in (b'{}', b'{"hook_event_name":"Stop","hook_event_name":"Stop"}',
                    b'{"hook_event_name":"Stop","private-marker":NaN}'):
            self.assertEqual(run_hook(raw, self.environment(), stderr=err), 0)
        missing = dict(self.environment(), MONARCHY_STATE=str(Path(self.directory.name) / 'missing.db'))
        self.assertEqual(run_hook(b'{"hook_event_name":"Stop"}', missing, stderr=err), 0)
        self.assertFalse(Path(missing['MONARCHY_STATE']).exists())
        self.assertNotIn('private-marker', err.getvalue())
        self.assertNotIn(self.directory.name, err.getvalue())

    def test_hook_active_and_subagent_events_do_not_rearm(self):
        for extra in ({'stop_hook_active': True}, {'agent_id': 'child'}):
            raw = json.dumps(dict(hook_event_name='Stop', **extra)).encode()
            self.assertEqual(run_hook(raw, self.environment(), stderr=io.StringIO()), 0)

    def test_standalone_hook_without_opt_in_is_silent(self):
        env = dict(os.environ)
        for key in list(env):
            if key.startswith('MONARCHY_'):
                del env[key]
        done = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'bin/monarchy-rearm.py')],
                              input=b'', capture_output=True, env=env, timeout=5)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b'', b''))

    def test_only_one_waiter_can_prepare_a_notice(self):
        due_at = datetime.fromisoformat(self.records.get_task('task')['created_at']) + timedelta(minutes=31)
        lock_path = str(self.records.path) + '.rearm.' + digest({'secretary': SECRETARY}) + '.lock'
        descriptor = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = wait(self.records, project=PROJECT, secretary_session=SECRETARY, now=lambda: due_at)
        finally:
            os.close(descriptor)
        self.assertEqual(result['reason'], 'already-waiting')
        due = Cadence(self.records).due(now=due_at.isoformat(), project=PROJECT)
        self.assertEqual(Cadence(self.records).unnotified(due, SECRETARY), due)

    def test_restart_retains_pending_checks_without_repeating_an_uncertain_wake(self):
        first = wait(self.records, project=PROJECT, secretary_session=SECRETARY, now=lambda: NOW)
        self.assertEqual(first['reason'], 'change')
        cadence = Cadence(self.records)
        self.assertEqual(cadence.get_notice(first['notification_id'])['state'], 'prepared')
        for identity in first['check_ids']:
            row = cadence.get(identity, now=NOW.isoformat())
            self.assertEqual(row['state'], 'pending')
            self.assertIsNone(row['receipt_id'])
        clock = Clock()
        with CourtRecords(self.records.path) as reopened:
            second = wait(reopened, project=PROJECT, secretary_session=SECRETARY,
                          max_seconds=65, poll_seconds=60, now=lambda: NOW, clock=clock, sleep=clock.sleep)
            self.assertEqual(second['reason'], 'timeout')
            self.assertEqual({row['check_id'] for row in second['checks']}, set(first['check_ids']))
        self.assertEqual(clock.sleeps, [60, 5])
        self.assertEqual(self.records.list_events(task_id='task'), [])
        self.assertEqual(self.records.list_operations(task_id='task'), [])

    def test_hook_wake_is_only_a_prepared_intent_and_fresh_stop_suppresses_it(self):
        raw = b'{"hook_event_name":"StopFailure"}'
        err = io.StringIO()
        code = run_hook(raw, self.environment(), stderr=err, now=lambda: NOW)
        self.assertEqual(code, 2)
        self.assertIn('Prepared notice', err.getvalue())
        self.assertTrue(all(row['state'] == 'pending' for row in Cadence(self.records).due(now=NOW.isoformat())))
        Controls(self.records).command('stop', owner_message='owner-stop')
        self.assertEqual(run_hook(raw, self.environment(), stderr=io.StringIO(), now=lambda: NOW), 0)

    def test_previously_notified_first_page_does_not_hide_later_checks(self):
        with patch('monarchy.records._now', return_value='2026-01-01T00:00:00+00:00'):
            for index in range(51):
                self.records.create_task('another-' + str(index), PROJECT, 'builder', metadata={
                    'secretary_binding': binding(SECRETARY), 'queen_binding': binding(QUEEN)})
        cadence = Cadence(self.records)
        first = cadence.due(now=NOW.isoformat(), project=PROJECT, limit=100)
        self.assertEqual(len(first), 100)
        ids = [row['check_id'] for row in first]
        cadence.prepare_notice(ids, 'previous-notice', secretary_session=SECRETARY, created_at=NOW.isoformat())
        clock = Clock()
        result = wait(self.records, project=PROJECT, secretary_session=SECRETARY, max_seconds=1,
                      now=lambda: NOW, clock=clock, sleep=clock.sleep)
        self.assertEqual(result['reason'], 'change')
        self.assertTrue(result['check_ids'])
        self.assertTrue(set(result['check_ids']).isdisjoint(ids))

    def test_reassignment_after_notice_preparation_holds_the_wake(self):
        prepare = Cadence.prepare_notice

        def rotate(cadence, *args, **kwargs):
            notice = prepare(cadence, *args, **kwargs)
            cadence.records.assign_task('task', 'new-builder', expected_generation=1)
            return notice

        with patch.object(Cadence, 'prepare_notice', rotate):
            result = wait(self.records, project=PROJECT, secretary_session=SECRETARY, now=lambda: NOW)
        self.assertEqual(result['reason'], 'held')
        self.assertEqual(result['check_ids'], [])
        notice = Cadence(self.records).get_notice(result['notification_id'])
        self.assertEqual(notice['state'], 'prepared')

    def test_expired_scan_cannot_prepare_a_notification(self):
        clock = Clock()
        due = Cadence.due

        def expensive(cadence, **kwargs):
            result = due(cadence, **kwargs)
            clock.elapsed += 2
            return result

        with patch.object(Cadence, 'due', expensive):
            result = wait(self.records, project=PROJECT, secretary_session=SECRETARY, now=lambda: NOW,
                          max_seconds=1, clock=clock, sleep=clock.sleep)
        self.assertEqual(result['reason'], 'timeout')
        pending = Cadence(self.records).due(now=NOW.isoformat(), project=PROJECT)
        self.assertEqual(Cadence(self.records).unnotified(pending, SECRETARY), pending)

    def test_pause_and_secretary_rotation_are_rechecked_after_each_sleep(self):
        mutations = [
            lambda: Controls(self.records).command('pause', owner_message='pause-during-wait'),
            lambda: self.records.assign_task('task', 'builder', expected_generation=1,
                metadata={'secretary_binding': binding(QUEEN), 'queen_binding': binding(SECRETARY)}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(change=index):
                clock = Clock()
                def sleep(seconds):
                    clock.sleep(seconds)
                    mutate()
                result = wait(self.records, project=PROJECT, secretary_session=SECRETARY,
                              now=lambda: NOW - timedelta(minutes=30), max_seconds=10,
                              poll_seconds=1, clock=clock, sleep=sleep)
                self.assertEqual(result['reason'], 'held' if index == 0 else 'identity-changed')
                self.assertEqual(clock.elapsed, 1)
                if index == 0:
                    box = Controls(self.records).command('resume', owner_message='resume-for-second-case')
                    self.records.answer_decision(box['decision_id'], {'accept': True},
                                                 expected_revision=1, owner_message='confirmed-resume')
                    Controls(self.records).apply(box['decision_id'])

    def test_unknown_native_state_and_repeated_polling_never_create_idle_progress(self):
        cadence = Cadence(self.records)
        original = cadence.observe('task', 'unknown-observation', generation=1,
                                   observed_at=NOW.isoformat(), native_status='unknown')
        first = wait(self.records, project=PROJECT, secretary_session=SECRETARY, now=lambda: NOW)
        self.assertEqual(first['reason'], 'change')
        clock = Clock()
        second = wait(self.records, project=PROJECT, secretary_session=SECRETARY, now=lambda: NOW,
                      max_seconds=3, poll_seconds=1, clock=clock, sleep=clock.sleep)
        self.assertEqual(second['reason'], 'timeout')
        self.assertEqual(cadence.observation('unknown-observation'), original)
        self.assertFalse(any(row['kind'].startswith('idle-') for row in cadence.due(now=NOW.isoformat())))

    def test_page_budget_reports_a_limit_without_consuming_pending_checks(self):
        with patch('monarchy.records._now', return_value='2026-01-01T00:00:00+00:00'):
            for index in range(51):
                self.records.create_task('bounded-' + str(index), PROJECT, 'builder', metadata={
                    'secretary_binding': binding(SECRETARY), 'queen_binding': binding(QUEEN)})
        cadence = Cadence(self.records)
        first = cadence.due(now=NOW.isoformat(), project=PROJECT, limit=100)
        cadence.prepare_notice([row['check_id'] for row in first], 'bounded-previous',
                                secretary_session=SECRETARY, created_at=NOW.isoformat())
        with patch('monarchy.rearm.MAX_CHECK_PAGES', 1):
            result = wait(self.records, project=PROJECT, secretary_session=SECRETARY, now=lambda: NOW)
        self.assertEqual(result['reason'], 'budget-exhausted')
        later = cadence.due(now=NOW.isoformat(), project=PROJECT, offset=100)
        self.assertTrue(later)
        self.assertEqual(cadence.unnotified(later, SECRETARY), later)

    def test_hook_reports_exhausted_budget_without_a_model_wake(self):
        with patch('monarchy.rearm.MAX_CHECK_PAGES', 0):
            err = io.StringIO()
            self.assertEqual(run_hook(b'{"hook_event_name":"Stop"}', self.environment(),
                                      stderr=err, now=lambda: NOW), 0)
        self.assertIn('stopped safely', err.getvalue())
