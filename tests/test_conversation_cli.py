"""Exercise the hook-to-CLI boundary in separate processes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from monarchy.records import CourtRecords
from monarchy.conversation import Conversation, prompt_policy
from monarchy.prompt_hooks import CONDUCTOR_CANCELLED, run_hook

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

    def test_native_cancel_reopen_and_answer_survive_real_hook_cli_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'royalty.db'
            with CourtRecords(state) as records:
                records.create_task('task', 'example/project', 'worker', metadata={
                    'queen_binding': {'session_id': SESSION}})
            env = {'CONDUCTOR_SESSION_ID': SESSION, 'MONARCHY_STATE': str(state)}
            data = {'tool_name': 'mcp__conductor__AskUserQuestion', 'tool_use_id': 'first',
                    'tool_input': {'questions': [{'question': 'Private synthetic question?',
                                                  'options': ['Hold', 'Continue']}]}}
            for event, prompt_id, response, expected in [
                ('PreToolUse', 'first', None, ('open', None)),
                ('PostToolUse', 'first', CONDUCTOR_CANCELLED, ('unknown', 'native-cancelled')),
                ('PreToolUse', 'second', None, ('open', 'answer-required')),
                ('PostToolUse', 'second', 'User responses:\n1. Private synthetic answer', ('closed', None))]:
                data.update(hook_event_name=event, tool_use_id=prompt_id,
                            tool_response=[{'type': 'text', 'text': response}])
                self.assertEqual(run_hook(json.dumps(data).encode(), env), 0)
                with CourtRecords(state) as records:
                    observation = Conversation(records).status(SESSION)
                    self.assertEqual((observation['state'], observation['reason']), expected)
                    self.assertEqual(prompt_policy(observation),
                                     'available' if expected[0] == 'closed' else 'hold')
                    self.assertEqual(records._connection.execute('SELECT count(*) FROM decisions').fetchone()[0], 0)
            raw = state.read_bytes()
            self.assertNotIn(b'Private synthetic question', raw)
            self.assertNotIn(b'Private synthetic answer', raw)

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
