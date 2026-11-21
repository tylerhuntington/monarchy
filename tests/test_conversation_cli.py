"""Exercise the hook-to-CLI boundary in separate processes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from monarchy.records import CourtRecords

SESSION = '33333333-3333-4333-8333-333333333333'


class ConversationCLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'monarchy', *map(str, args)],
                              capture_output=True, text=True)

    def test_prompt_observation_survives_independent_cli_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'royalty.db'
            with CourtRecords(state) as records:
                records.create_task('task', 'example/project', 'worker', metadata={
                    'queen_binding': {'session_id': SESSION}})
            for action, expected in [('open', 'open'), ('close', 'closed'), ('unknown', 'unknown')]:
                result = self.run_cli('--state', state, 'prompt', action,
                                      '--session', SESSION, '--prompt-id', 'tool-1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['state'], expected)
            result = self.run_cli('--state', state, 'prompt', 'status', '--session', SESSION)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['state'], 'unknown')

    def test_settings_and_box_lint_are_stateless(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'absent.db'
            result = self.run_cli('prompt-settings', '--script', '/tmp/observer.py', '--state-path', state)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(set(json.loads(result.stdout)['hooks']),
                             {'PreToolUse', 'PostToolUse', 'PostToolUseFailure'})
            self.assertFalse(state.exists())

            box = Path(directory) / 'box.json'
            box.write_text(json.dumps({'question': 'Continue the test?', 'options': [
                {'label': 'Continue (Recommended)', 'description': 'Run the bounded next step.'},
                {'label': 'Stop', 'description': 'Leave the test held.'}]}))
            result = self.run_cli('box-lint', box)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'valid': True})
            self.assertFalse(state.exists())

    def test_control_resume_requires_explicit_current_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'royalty.db'
            result = self.run_cli('--state', state, 'control', 'pause', '--owner-message', 'owner-pause')
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_cli('--state', state, 'control', 'resume', '--owner-message', 'owner-resume')
            self.assertEqual(result.returncode, 0, result.stderr)
            decision = json.loads(result.stdout)
            result = self.run_cli('--state', state, 'control', 'apply', decision['decision_id'])
            self.assertNotEqual(result.returncode, 0)
            answer = Path(directory) / 'answer.json'
            answer.write_text('{"accept":true}')
            result = self.run_cli('--state', state, 'answer', decision['decision_id'], answer,
                '--revision', 1, '--owner-message', 'owner-confirmation')
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_cli('--state', state, 'control', 'apply', decision['decision_id'])
            self.assertEqual(result.returncode, 0, result.stderr)
            with CourtRecords(state) as records:
                self.assertFalse(records.config_overrides().get('court.paused'))

    def test_cli_document_rejects_duplicate_and_nonfinite_members(self):
        from monarchy.__main__ import document
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'answer.json'
            for value in ('{"accept":false,"accept":true}', '{"accept":1e999}'):
                file.write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError): document(file)
