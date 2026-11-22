"""Process-level delegation commands preserve explicit owner approval boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from monarchy.records import CourtRecords


ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'example/project'
CATEGORY = 'plan-or-date-acceptance'


class DelegationCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.state = self.path / 'private.sqlite'

    def command(self, *args, succeeds=True):
        result = subprocess.run(
            [sys.executable, '-m', 'monarchy', '--state', str(self.state), *args],
            cwd=ROOT, capture_output=True, text=True, timeout=15)
        if succeeds:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def document(self, name, value):
        path = self.path / name
        path.write_text(json.dumps(value))
        return str(path)

    def test_help_exposes_delegation_without_opening_state(self):
        result = subprocess.run(
            [sys.executable, '-m', 'monarchy', '--state', str(self.state), '--help'],
            cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('delegation', result.stdout)
        self.assertFalse(self.state.exists())

    def test_taxonomy_and_initial_state_do_not_activate_a_grant(self):
        taxonomy = self.command('delegation', 'categories', PROJECT)
        self.assertIn('internal-pr-approval', json.dumps(taxonomy))
        self.assertIn(CATEGORY, json.dumps(taxonomy))
        state = self.command('delegation', 'state', PROJECT, CATEGORY)
        self.assertEqual(state['state'], 'ask')
        self.assertIsNone(state.get('grant_id'))

    def test_proposal_needs_owner_answer_and_replay_cannot_undo_revoke(self):
        source = self.document('proposal.json', {
            'project': PROJECT, 'category': CATEGORY,
            'state': 'ask-again-later', 'precedents': [],
        })
        decision = self.command('delegation', 'propose', source,
                                '--owner-message', 'owner-proposal')
        self.assertEqual(decision['state'], 'pending')
        decision_id = decision['decision_id']
        self.command('delegation', 'apply', decision_id, succeeds=False)
        self.assertEqual(self.command('delegation', 'state', PROJECT, CATEGORY)['state'], 'ask')
        answer = self.document('answer.json', {'accept': True})
        self.command('answer', decision_id, answer, '--revision', str(decision['revision']),
                     '--owner-message', 'owner-confirmation')
        self.command('delegation', 'apply', decision_id)
        self.assertEqual(self.command('delegation', 'state', PROJECT, CATEGORY)['state'],
                         'ask-again-later')
        self.command('delegation', 'revoke', PROJECT, CATEGORY,
                     '--owner-message', 'owner-revocation')
        self.command('delegation', 'apply', decision_id)
        self.assertEqual(self.command('delegation', 'state', PROJECT, CATEGORY)['state'], 'ask')

    def test_malformed_proposal_does_not_echo_private_input_or_grant(self):
        self.command('delegation', 'state', PROJECT, CATEGORY)
        source = self.path / 'malformed.json'
        source.write_text('{"project":"private-value-fixture","project":NaN}')
        result = self.command('delegation', 'propose', str(source),
                              '--owner-message', 'owner-proposal', succeeds=False)
        self.assertNotIn('private-value-fixture', result.stdout + result.stderr)
        state = self.command('delegation', 'state', PROJECT, CATEGORY)
        self.assertEqual(state['state'], 'ask')
        self.assertIsNone(state.get('grant_id'))

    def test_three_choice_followup_and_grant_answer_survive_process_boundaries(self):
        category = 'ci-rerun-at-approved-head'
        context = {'category': category, 'actions': ['rerun-approved-ci'],
                   'scope': {'workflow': 'required-checks'}, 'classification_complete': True}
        binding = {'session_id': '22222222-2222-4222-8222-222222222222',
                   'workspace_id': '11111111-1111-4111-8111-111111111111', 'repo': PROJECT}
        with CourtRecords(self.state) as records:
            records.create_task('task', PROJECT, binding['session_id'], metadata={'binding': binding})
            records.open_decision('precedent', 'task', {'generation': 1, 'delegation': context})
        approval = self.document('approve.json', {'accept': True})
        self.command('answer', 'precedent', approval, '--revision', '1',
                     '--owner-message', 'owner-precedent')
        box = self.command('delegation', 'followup', 'precedent',
                           '--owner-message', 'owner-followup')
        self.assertEqual(set(box['payload']['choices']), {'ask', 'delegated', 'ask-again-later'})
        self.assertEqual(self.command('delegation', 'state', PROJECT, category)['state'], 'ask')
        selected = self.document('selection.json', {'state': 'delegated'})
        self.command('answer', box['decision_id'], selected, '--revision', str(box['revision']),
                     '--owner-message', 'owner-grant-answer')
        grant = self.command('delegation', 'apply', box['decision_id'])
        with CourtRecords(self.state) as records:
            records.open_decision('matching', 'task', {'generation': 1, 'delegation': {
                **context, 'precedent': {'decision_id': 'precedent', 'revision': 1},
                'new_risk': False, 'unresolved_flags': []}})
        answered = self.command('delegation', 'answer', 'matching', approval, '--revision', '1',
                                '--grant-id', grant['grant_id'])
        self.assertEqual(answered['answered_by'], 'grant:' + grant['grant_id'])
        self.assertIsNone(answered['owner_message'])
        with CourtRecords(self.state) as records:
            self.assertEqual(records.get_decision('matching'), answered)
        relay = self.command('prepare-answer', 'matching')
        message = json.loads(relay['request']['text'])
        self.assertEqual(message['answered_by'], answered['answered_by'])
        self.assertIsNone(message['owner_message'])
        self.command('answer', 'matching', approval, '--revision', '1',
                     '--owner-message', 'would-impersonate-owner', succeeds=False)
        self.command('delegation', 'revoke', PROJECT, category, '--owner-message', 'revoke-grant')
        self.command('prepare-answer', 'matching', succeeds=False)


if __name__ == '__main__':
    unittest.main()
