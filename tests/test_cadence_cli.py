"""Explicit cadence commands keep state durable and hooks opt-in."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from monarchy.preferences import Preferences
from monarchy.records import CourtRecords
from test_approval import source


ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'example/project'
SECRETARY = '33333333-3333-4333-8333-333333333333'
WORKER = '22222222-2222-4222-8222-222222222222'


class CadenceCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.state = self.path / 'royalty.db'

    def command(self, *args, succeeds=True):
        result = subprocess.run([sys.executable, '-m', 'monarchy', '--state', str(self.state), *args],
                                cwd=ROOT, text=True, capture_output=True, timeout=15)
        if succeeds:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def document(self, name, value):
        path = self.path / name
        path.write_text(json.dumps(value))
        return str(path)

    def task(self):
        with CourtRecords(self.state) as records:
            prefs = Preferences(records)
            owner = source({'voice.zone': 'UTC'}, 'owner')
            project = source({'project.repository': PROJECT}, 'project')
            for box in prefs.founding(owner, project):
                records.answer_decision(box['decision_id'], {'accept': True},
                    expected_revision=box['revision'], owner_message='founding-answer')
            prefs.pin(owner, project, owner_message='pin-answer', monarchy_revision='a' * 40)
            data = prefs.bind({'task_id': 'task', 'repository': PROJECT, 'owner': WORKER,
                'metadata': {'brief': 'Observe this bounded task.', 'authority_ref': 'owner-assignment',
                             'binding': {'repo': PROJECT, 'session_id': WORKER,
                                         'workspace_id': '11111111-1111-4111-8111-111111111111'},
                             'secretary_binding': {'repo': PROJECT, 'session_id': SECRETARY,
                                         'workspace_id': '11111111-1111-4111-8111-111111111111'}}})
            records.create_task('task', PROJECT, WORKER, metadata=data['metadata'])

    def test_help_exposes_bounded_commands_without_creating_state(self):
        result = subprocess.run([sys.executable, '-m', 'monarchy', '--state', str(self.state), '--help'],
                                cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('cadence', 'due', 'wait', 'rearm-settings'):
            self.assertIn(command, result.stdout)
        self.assertFalse(self.state.exists())

    def test_rearm_settings_are_printed_without_installing_or_opening_records(self):
        result = self.command('rearm-settings', '--script', str(ROOT / 'bin/monarchy-rearm.py'),
            '--state-path', str(self.state), '--project', PROJECT, '--secretary-session', SECRETARY)
        self.assertEqual(set(result['hooks']), {'Stop', 'StopFailure'})
        for entries in result['hooks'].values():
            self.assertTrue(entries[0]['hooks'][0]['asyncRewake'])
            self.assertIn('MONARCHY_REARM=1', entries[0]['hooks'][0]['command'])
        self.assertFalse(self.state.exists())

    def test_observation_retry_is_stable_across_processes_and_changed_content_conflicts(self):
        self.task()
        observed = {'task_id': 'task', 'observation_id': 'observed-working', 'generation': 1,
                    'observed_at': datetime.now(timezone.utc).isoformat(), 'native_status': 'working'}
        file = self.document('observe.json', observed)
        first = self.command('cadence', 'observe', file)
        self.assertEqual(self.command('cadence', 'observe', file), first)
        changed = self.document('changed.json', dict(observed, native_status='idle'))
        self.command('cadence', 'observe', changed, succeeds=False)
        self.assertEqual(self.command('cadence', 'observe', file), first)
        with CourtRecords(self.state) as records:
            self.assertEqual(records.list_operations(), [])

    def test_malformed_observation_does_not_echo_private_input(self):
        self.task()
        file = self.path / 'malformed.json'
        file.write_text('{"task_id":"private-cadence-fixture","task_id":NaN}')
        result = self.command('cadence', 'observe', str(file), succeeds=False)
        self.assertNotIn('private-cadence-fixture', result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_wait_rejects_an_unbounded_budget_without_native_operations(self):
        self.task()
        result = self.command('wait', '--project', PROJECT, '--secretary-session', SECRETARY,
                              '--max-seconds', '7201', succeeds=False)
        self.assertNotIn('Traceback', result.stderr)
        with CourtRecords(self.state) as records:
            self.assertEqual(records.list_operations(), [])

    def test_due_repeats_keep_pending_check_ids_without_completing_or_sending(self):
        self.task()
        observed_at = datetime.now(timezone.utc)
        source = self.document('observe.json', {
            'task_id': 'task', 'observation_id': 'due-baseline', 'generation': 1,
            'observed_at': observed_at.isoformat(), 'native_status': 'working'})
        self.command('cadence', 'observe', source)
        now = (observed_at + timedelta(minutes=31)).isoformat()
        first = self.command('due', '--project', PROJECT, '--now', now)
        self.assertGreaterEqual(len(first), 2)
        page = self.command('due', '--project', PROJECT, '--now', now, '--limit', '1', '--offset', '1')
        self.assertEqual([check['check_id'] for check in page], [first[1]['check_id']])
        second = self.command('due', '--project', PROJECT, '--now', now)
        self.assertEqual([check['check_id'] for check in first], [check['check_id'] for check in second])
        for check in second:
            self.assertEqual(check['state'], 'pending')
            stored = self.command('cadence', 'get', check['check_id'])
            self.assertEqual(stored['state'], 'pending')
            self.assertIsNone(stored['receipt_id'])
        with CourtRecords(self.state) as records:
            self.assertEqual(records.list_operations(), [])

    def test_report_expectation_requires_an_exact_retained_completion_receipt(self):
        self.task()
        with CourtRecords(self.state) as records:
            source = records.record_event('expectation-source', 'task', 1, WORKER, 'progress',
                                           {'summary': 'A further report is expected.'})
        request = self.document('expect.json', {
            'task_id': 'task', 'expectation_id': 'expected-report', 'generation': 1,
            'since': source['created_at'], 'source_ref': {'kind': 'event', 'id': source['event_id']}})
        check = self.command('cadence', 'expect', request)
        self.assertEqual(check['state'], 'pending')
        receipt = self.document('receipt.json', {'event_id': 'received-report'})
        self.command('cadence', 'complete', check['check_id'], receipt,
                     '--receipt-id', 'report-receipt', succeeds=False)
        self.assertEqual(self.command('cadence', 'get', check['check_id'])['state'], 'pending')
        with CourtRecords(self.state) as records:
            records.record_event('received-report', 'task', 1, WORKER, 'progress',
                                  {'summary': 'The requested report arrived.'})
        completed_at = datetime.now(timezone.utc).isoformat()
        result = self.command('cadence', 'complete', check['check_id'], receipt,
                              '--receipt-id', 'report-receipt', '--completed-at', completed_at)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(self.command('cadence', 'complete', check['check_id'], receipt,
            '--receipt-id', 'report-receipt', '--completed-at', completed_at), result)


if __name__ == '__main__':
    unittest.main()
