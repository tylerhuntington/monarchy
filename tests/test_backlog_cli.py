"""Backlog commands retain explicit owner activation across process restarts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from monarchy.records import CourtRecords

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'example/project'


class BacklogCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.state = self.path / 'royalty.db'
        self.bin = self.path / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ.get('PATH', ''))
        for command in ('gh', 'conductor'):
            executable = self.bin / command
            executable.write_text('#!/bin/sh\nexit 95\n')
            executable.chmod(0o700)

    def command(self, *args, succeeds=True):
        result = subprocess.run([sys.executable, '-m', 'monarchy', '--state', str(self.state), *args],
                                cwd=ROOT, env=self.env, text=True, capture_output=True, timeout=15)
        if succeeds:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)
        return result

    def document(self, name, value):
        path = self.path / name
        path.write_text(json.dumps(value))
        return str(path)

    def proposal(self, **extra):
        return self.document('proposal.json', dict(project=PROJECT,
            references=[{'kind': 'issue', 'number': 7}], builder_cap=1, **extra))

    def github(self, response):
        (self.bin / 'response.json').write_text(json.dumps(response))
        gh = self.bin / 'gh'
        gh.write_text('#!' + sys.executable + '\n' + '''import json, sys
from pathlib import Path
assert sys.argv[1:] == ['api', 'graphql', '--input', '-']
request = json.load(sys.stdin)
assert request['variables']['owner'] == 'example'
assert request['variables']['name'] == 'project'
assert request['variables']['number'] == 7
assert request['query'].lstrip().startswith('query ')
with Path(__file__).with_name('calls').open('a') as marker:
    marker.write('read\\n')
print(Path(__file__).with_name('response.json').read_text())
''')
        gh.chmod(0o700)

    def task_data(self):
        worker = '22222222-2222-4222-8222-222222222222'
        return {'task_id': 'task', 'repository': PROJECT, 'owner': worker, 'metadata': {
            'binding': {'repo': PROJECT, 'session_id': worker,
                        'workspace_id': '11111111-1111-4111-8111-111111111111',
                        'profile': {'agent': 'codex', 'model': 'gpt-6-astra',
                                    'effort': 'ultra', 'fast_mode': True}},
            'brief': 'Inspect the scoped repository.'}}

    def test_help_exposes_backlog_without_creating_records(self):
        result = subprocess.run([sys.executable, '-m', 'monarchy', '--state', str(self.state),
                                 'backlog', '--help'], cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('state', 'propose', 'apply', 'revoke', 'read', 'select', 'bind',
                        'prepare', 'pull', 'release', 'review'):
            self.assertIn(command, result.stdout)
        self.assertFalse(self.state.exists())

    def test_defaults_and_pending_proposal_do_not_activate(self):
        state = self.command('backlog', 'state', PROJECT)
        self.assertEqual(state['state'], 'inactive')
        self.assertIsNone(state['grant_id'])
        box = self.command('backlog', 'propose', self.proposal(), '--owner-message', 'owner-proposal')
        self.assertEqual(box['state'], 'pending')
        self.command('backlog', 'apply', box['decision_id'], succeeds=False)
        self.assertEqual(self.command('backlog', 'state', PROJECT)['state'], 'inactive')
        with CourtRecords(self.state) as records:
            self.assertEqual(records.list_operations(), [])

    def test_project_grant_can_cover_future_tracked_work_without_an_item_allowlist(self):
        proposal = self.document('project-scope.json', {'project': PROJECT, 'builder_cap': 1})
        box = self.command('backlog', 'propose', proposal, '--owner-message', 'owner-project-request')
        self.assertIsNone(box['payload']['references'])
        self.assertEqual(box['state'], 'pending')
        self.assertEqual(self.command('backlog', 'state', PROJECT)['state'], 'inactive')

    def test_exact_answer_activation_and_revocation_survive_new_processes(self):
        box = self.command('backlog', 'propose', self.proposal(), '--owner-message', 'owner-proposal')
        answer = self.document('answer.json', {'accept': True})
        self.command('answer', box['decision_id'], answer, '--revision', str(box['revision']),
                     '--owner-message', 'actual-owner-answer')
        grant = self.command('backlog', 'apply', box['decision_id'])
        self.assertEqual(grant['state'], 'active')
        self.assertEqual(grant['payload']['builder_cap'], 1)
        self.assertEqual(grant['payload']['references'], [{'kind': 'issue', 'number': 7}])
        self.assertEqual(self.command('backlog', 'state', PROJECT)['grant_id'], grant['grant_id'])
        self.command('backlog', 'revoke', PROJECT, '--owner-message', 'owner-revoke')
        self.command('backlog', 'apply', box['decision_id'])
        self.assertEqual(self.command('backlog', 'state', PROJECT)['state'], 'revoked')
        with CourtRecords(self.state) as records:
            self.assertEqual(records.list_operations(), [])

    def test_malformed_and_unknown_fields_never_echo_private_values_or_activate(self):
        self.command('backlog', 'state', PROJECT)
        raw = self.path / 'bad.json'
        raw.write_text('{"project":"private-backlog-fixture","project":NaN}')
        result = self.command('backlog', 'propose', str(raw), '--owner-message', 'owner-proposal',
                              succeeds=False)
        self.assertNotIn('private-backlog-fixture', result.stdout + result.stderr)
        result = self.command('backlog', 'propose', self.proposal(unapproved='private-backlog-fixture'),
                              '--owner-message', 'owner-proposal', succeeds=False)
        self.assertNotIn('private-backlog-fixture', result.stdout + result.stderr)
        self.assertEqual(self.command('backlog', 'state', PROJECT)['state'], 'inactive')

    def test_selection_with_missing_source_and_classification_cannot_dispatch(self):
        self.command('backlog', 'state', PROJECT)
        snapshot = self.document('snapshot.json', {'repository': PROJECT, 'private': 'private-backlog-fixture'})
        classifications = self.document('classifications.json', [])
        result = self.command('backlog', 'select', snapshot, classifications, succeeds=False)
        self.assertNotIn('private-backlog-fixture', result.stdout + result.stderr)
        with CourtRecords(self.state) as records:
            self.assertEqual(records.list_operations(), [])

    def test_prepare_reads_github_again_and_rejects_source_changed_since_selection(self):
        from test_backlog_selection import native
        response = native(7, 'Issue')
        self.github(response)
        scope = self.document('scope.json', {'project': PROJECT,
            'references': [{'kind': 'issue', 'number': 7}]})
        snapshot = self.command('backlog', 'read', scope)
        snapshot_file = self.document('source.json', snapshot)
        fact = {'reference': {'kind': 'issue', 'number': 7},
            'source_digest': snapshot['items'][0]['source_digest'],
            'bucket': 'remaining-priority-smallest-first', 'priority': 0, 'size': 0,
            'wanted': True, 'dependencies': [], 'dependencies_complete': True,
            'ownership': 'clear', 'planned_branch': 'work/inspection',
            'priority_surface': None, 'evidence_ref': 'classification-evidence'}
        candidate = self.command('backlog', 'select', snapshot_file,
            self.document('facts.json', [fact]))['candidate']
        box = self.command('backlog', 'propose', self.proposal(), '--owner-message', 'owner-proposal')
        self.command('answer', box['decision_id'], self.document('accept.json', {'accept': True}),
                     '--revision', str(box['revision']), '--owner-message', 'owner-answer')
        grant = self.command('backlog', 'apply', box['decision_id'])
        data = self.command('backlog', 'bind', self.document('task.json', self.task_data()),
            '--candidate', self.document('candidate.json', candidate), '--grant-id', grant['grant_id'])
        with CourtRecords(self.state) as records:
            records.create_task(data['task_id'], data['repository'], data['owner'], metadata=data['metadata'])
        response['data']['repository']['issueOrPullRequest']['body'] = 'Changed after selection.'
        self.github(response)
        self.command('backlog', 'prepare', self.document('prepare.json', {
            'task_id': data['task_id'], 'candidate': candidate}), '--snapshot', snapshot_file, succeeds=False)
        self.assertEqual((self.bin / 'calls').read_text().splitlines(), ['read', 'read'])
        with CourtRecords(self.state) as records:
            self.assertEqual(records.list_operations(), [])

    def test_pull_without_activation_creates_no_task_or_dispatch(self):
        self.command('backlog', 'state', PROJECT)
        idle = {'task_id': 'idle', 'generation': 1,
                'first_observation_id': 'first', 'last_observation_id': 'last'}
        self.command('backlog', 'pull', self.document('task.json', self.task_data()),
            '--classifications', self.document('facts.json', []),
            '--idle-source', self.document('idle.json', idle), succeeds=False)
        with CourtRecords(self.state) as records:
            self.assertEqual(records.list_operations(), [])
            self.assertEqual(records.list_tasks(), [])

    def test_confirmed_delivery_readback_needs_no_new_source_file_or_network(self):
        from monarchy.supervision import Court
        data = self.task_data()
        data['metadata'].update(execution_mode='read-only', authority_ref='owner-inspection')
        with CourtRecords(self.state) as records:
            records.create_task(data['task_id'], data['repository'], data['owner'], metadata=data['metadata'])
            operation = Court(records).prepare_dispatch(data['task_id'])
            records.set_operation_state(operation['operation_id'], 'in_flight', expected_state='prepared')
            confirmed = records.set_operation_state(operation['operation_id'], 'confirmed',
                expected_state='in_flight', result={'native_readback': 'same-original-message'})
        result = self.command('deliver', operation['operation_id'], '--backlog-snapshot',
                              str(self.path / 'no-longer-present.json'))
        self.assertEqual(result, confirmed)

    def test_bounded_source_export_can_be_read_back_without_whitespace_overflow(self):
        from test_backlog_selection import connection, dependency, linked_pr, native
        response = native(7, 'Issue')
        item = response['data']['repository']['issueOrPullRequest']
        item['labels'] = connection([{'name': 'label-%03d-' % n + 'x' * 100} for n in range(100)])
        item['blockedBy'] = connection([dependency(n + 100, 'CLOSED', 'COMPLETED') for n in range(100)])
        item['closedByPullRequestsReferences'] = connection([
            dict(linked_pr(n + 300), state='CLOSED') for n in range(100)])
        self.github(response)
        scope = self.document('scope.json', {'project': PROJECT,
            'references': [{'kind': 'issue', 'number': 7}]})
        result = subprocess.run([sys.executable, '-m', 'monarchy', '--state', str(self.state),
            'backlog', 'read', scope], cwd=ROOT, env=self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(len(result.stdout.encode()), 65536)
        snapshot = self.path / 'roundtrip.json'
        snapshot.write_text(result.stdout)
        selected = self.command('backlog', 'select', str(snapshot), self.document('facts.json', []))
        self.assertIsNone(selected['candidate'])
        self.assertEqual(selected['held'][0]['reasons'], ['classification-missing'])


if __name__ == '__main__':
    unittest.main()
