"""Prompt observations fail closed without retaining question or answer content."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from monarchy.prompt_hooks import HookError, MAX_INPUT_BYTES, lint_box, main, run_hook, settings_snippet


ROOT = Path(__file__).resolve().parents[1]
ENV = {'CONDUCTOR_SESSION_ID': 'session-fixture', 'MONARCHY_STATE': '/tmp/court-fixture.sqlite'}
QUESTION = {'question': 'Which path should proceed?', 'header': 'Path', 'multiSelect': False,
            'options': [{'label': 'Continue (Recommended)', 'description': 'Continue the task.'},
                        {'label': 'Hold', 'description': 'Keep the task held.'}]}
CANCELLED = ('User cancelled the question. Please continue without this information or ask in a different way.\n'
             'Error code: CONDUCTOR_ASK_USER_QUESTION_USER_CANCELLED\n'
             'Retryable: no\n'
             'Suggested action: Continue without this information or ask in a normal message if it is still necessary.')


def payload(event='PreToolUse'):
    data = {'hook_event_name': event, 'tool_name': 'AskUserQuestion',
            'tool_use_id': 'toolu_fixture', 'session_id': 'native-session-fixture',
            'tool_input': {'questions': [copy.deepcopy(QUESTION)]}}
    if event == 'PostToolUse':
        data['tool_response'] = {'questions': [copy.deepcopy(QUESTION)],
                                 'answers': {QUESTION['question']: 'Continue (Recommended)'}}
    return data


class Recorder:
    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [0])

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        value = self.results.pop(0) if self.results else 0
        if isinstance(value, BaseException):
            raise value
        return SimpleNamespace(returncode=value)


class PromptHookTests(unittest.TestCase):
    def run_adapter(self, data, env=None, recorder=None):
        recorder = recorder or Recorder()
        raw = json.dumps(data).encode() if not isinstance(data, bytes) else data
        error, output = io.StringIO(), io.StringIO()
        with redirect_stderr(error), redirect_stdout(output):
            code = run_hook(raw, ENV if env is None else env, runner=recorder)
        self.assertEqual(output.getvalue(), '')
        return code, recorder, error.getvalue()

    def test_pre_opens_exact_conductor_session_and_tool_identity(self):
        code, runner, error = self.run_adapter(payload())
        self.assertEqual((code, error), (0, ''))
        args, kwargs = runner.calls[0]
        self.assertEqual(args, [sys.executable, '-m', 'monarchy', '--state', ENV['MONARCHY_STATE'],
                                'prompt', 'open', '--session', 'session-fixture',
                                '--prompt-id', 'toolu_fixture'])
        self.assertIs(kwargs['shell'], False)
        self.assertEqual(kwargs['cwd'], ROOT)
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
        self.assertGreater(kwargs['timeout'], 0)
        self.assertLess(kwargs['timeout'], 5)

    def test_success_closes_matching_tool_id_without_retaining_answers(self):
        data = payload('PostToolUse')
        data['tool_response']['answers'][QUESTION['question']] = 'private-answer-fixture'
        code, runner, _ = self.run_adapter(data)
        self.assertEqual(code, 0)
        self.assertEqual(runner.calls[0][0][6], 'close')
        self.assertNotIn('private-answer-fixture', repr(runner.calls))

    def test_failure_and_interrupt_observations_are_unknown(self):
        for event in ('PostToolUseFailure', 'PostToolUse'):
            for key in ('error', 'is_interrupt'):
                data = payload(event)
                data[key] = 'private-error-fixture' if key == 'error' else True
                code, runner, error = self.run_adapter(data)
                self.assertEqual(code, 0)
                self.assertEqual(runner.calls[0][0][6], 'unknown')
                self.assertNotIn('private-error-fixture', repr(runner.calls) + error)

    def test_ambiguous_cancelled_and_automatic_post_results_never_close(self):
        answered = payload('PostToolUse')['tool_response']
        responses = [None, 'interrupted', {}, {'answers': {}},
                     dict(answered, afkTimeoutMs=60000),
                     dict(answered, response='Use another approach'),
                     dict(answered, answers={'Other question': 'Hold'}),
                     dict(answered, answers={QUESTION['question']: ''}),
                     dict(answered, answers={QUESTION['question']: ['Hold']}),
                     dict(answered, cancelled=True), dict(answered, interrupted=True),
                     dict(answered, error='failed')]
        for response in responses:
            with self.subTest(response=response):
                data = payload('PostToolUse')
                data['tool_response'] = response
                code, runner, _ = self.run_adapter(data)
                self.assertEqual(code, 0)
                self.assertEqual(runner.calls[0][0][6], 'unknown')

    def test_changed_question_result_and_missing_input_are_unknown(self):
        for change in ('question', 'input'):
            data = payload('PostToolUse')
            if change == 'question':
                data['tool_response']['questions'][0]['question'] = 'Different question?'
            else:
                del data['tool_input']
            code, runner, _ = self.run_adapter(data)
            self.assertEqual(code, 0)
            self.assertEqual(runner.calls[0][0][6], 'unknown')

    def test_pre_write_failure_blocks_and_never_echoes_child_errors(self):
        for failure in (1, OSError('private-path-fixture'),
                        subprocess.TimeoutExpired(['private-command-fixture'], 3)):
            code, runner, error = self.run_adapter(payload(), recorder=Recorder([failure]))
            self.assertEqual(code, 2)
            self.assertEqual(len(runner.calls), 1)
            self.assertNotIn('private-', error)
            self.assertTrue(error.strip())

    def test_failed_close_attempts_unknown_and_returns_safe_error(self):
        code, runner, error = self.run_adapter(payload('PostToolUse'), recorder=Recorder([1, 0]))
        self.assertEqual(code, 2)
        self.assertEqual([args[6] for args, _ in runner.calls], ['close', 'unknown'])
        self.assertTrue(error.strip())

    def test_invalid_payloads_are_bounded_and_block_without_writes(self):
        for raw in (b'', b'[]', b'{"hook_event_name":NaN}', b'{"x":1,"x":2}',
                    b'{"tool_name":"Read","unused":1e999}',
                    b'\xff', b'x' * (MAX_INPUT_BYTES + 1), b'[' * 2000):
            code, runner, error = self.run_adapter(raw)
            self.assertEqual(code, 2)
            self.assertFalse(runner.calls)
            self.assertNotIn('Traceback', error)

    def test_unrelated_tools_are_ignored_without_reading_identity(self):
        data = payload()
        data['tool_name'] = 'Read'
        code, runner, error = self.run_adapter(data, env={})
        self.assertEqual((code, error), (0, ''))
        self.assertFalse(runner.calls)

    def test_exact_conductor_alias_records_the_same_prompt_lifecycle(self):
        for event, expected in [('PreToolUse', 'open'), ('PostToolUse', 'close'),
                                ('PostToolUseFailure', 'unknown')]:
            with self.subTest(event=event):
                data = payload(event)
                data['tool_name'] = 'mcp__conductor__AskUserQuestion'
                if event == 'PostToolUse':
                    data['tool_response'] = [{'type': 'text',
                        'text': 'User responses:\n1. Continue (Recommended)'}]
                code, runner, error = self.run_adapter(data)
                self.assertEqual((code, error), (0, ''))
                self.assertEqual(len(runner.calls), 1)
                self.assertEqual(runner.calls[0][0][6], expected)
                self.assertEqual(runner.calls[0][0][-1], 'toolu_fixture')

    def test_conductor_alias_does_not_guess_json_or_the_builtin_answer_format(self):
        data = payload('PostToolUse')
        data['tool_name'] = 'mcp__conductor__AskUserQuestion'
        for response in (data['tool_response'],
                         {'content': [{'type': 'text', 'text': json.dumps(data['tool_response'])}]}):
            with self.subTest(response=response):
                data['tool_response'] = response
                code, runner, _ = self.run_adapter(data)
                self.assertEqual(code, 0)
                self.assertEqual(len(runner.calls), 1)
                self.assertEqual(runner.calls[0][0][6], 'unknown')

    def test_native_conductor_single_freeform_and_multiselect_answers_close(self):
        for questions, text in [
            ([QUESTION], 'User responses:\n1. Continue (Recommended)'),
            ([QUESTION], 'User responses:\n1. Another bounded path'),
            ([dict(QUESTION, multiSelect=True)], 'User responses:\n1.\n   - Continue\n   - Other path'),
            ([QUESTION, dict(QUESTION, question='Which follow-up?', multiSelect=True)],
             'User responses:\n1. Hold\n2.\n   - Follow-up A\n   - Follow-up B')]:
            data = payload('PostToolUse')
            data['tool_name'] = 'mcp__conductor__AskUserQuestion'
            data['tool_input'] = {'questions': copy.deepcopy(questions)}
            blocks = [{'type': 'text', 'text': text}]
            for response in (blocks, {'content': blocks}, {'content': blocks, 'isError': False}):
                data['tool_response'] = response
                code, runner, _ = self.run_adapter(data)
                self.assertEqual(code, 0)
                self.assertEqual(runner.calls[0][0][6], 'close')
                self.assertNotIn(text, repr(runner.calls))

    def test_native_conductor_cancellation_error_and_ambiguous_results_hold(self):
        success = {'content': [{'type': 'text', 'text': 'User responses:\n1. Continue'}]}
        responses = [
            {'content': [{'type': 'text', 'text': 'User cancelled the question. Please continue without this information or ask in a different way.'}]},
            dict(success, isError=True), dict(success, isError='false'),
            dict(success, cancelled=True), dict(success, is_interrupt=True),
            dict(success, afkTimeoutMs=1000), dict(success, error='failed'),
            {'content': [{'type': 'text', 'text': 'Error asking the user a question: delivery failed'}], 'isError': True},
            {'content': success['content'] * 2}, {'content': []},
            {'content': [{'type': 'image', 'text': 'User responses:\n1. Continue'}]},
            {'content': success['content'], 'unknown': True},
            'User responses:\n1. Continue', {'result': success},
            [{'type': 'text', 'text': 'User responses:\n1. Continue', 'unknown': True}],
        ]
        for text in ('User responses:\n1. ', 'User responses:\n1.', 'User responses:\n2. Continue',
                     'User responses:\n1. Continue\n2. Extra', 'User responses:\n1. Continue\nExtra',
                     'User responses:\n1. Continue\n', 'User responses:\n1.\n   - ',
                     'User responses:\n1.\n  - Wrong indent', 'User responses:\n1.\n   - Continue',
                     'User responses:\n1. Continue\x00', 'User responses:\r\n1. Continue'):
            responses.append({'content': [{'type': 'text', 'text': text}]})
        responses.extend(response['content'] for response in list(responses)
                         if type(response) is dict and set(response) == {'content'})
        for response in responses:
            with self.subTest(response=response):
                data = payload('PostToolUse')
                data['tool_name'] = 'mcp__conductor__AskUserQuestion'
                data['tool_response'] = response
                code, runner, _ = self.run_adapter(data)
                self.assertEqual(code, 0)
                self.assertEqual(runner.calls[0][0][6], 'unknown')

    def test_native_conductor_success_with_top_level_failure_stays_unknown(self):
        for flag, value in [('error', 'failed'), ('cancelled', True), ('is_interrupt', True),
                            ('afkTimeoutMs', 1000), ('isError', True)]:
            data = payload('PostToolUse')
            data['tool_name'] = 'mcp__conductor__AskUserQuestion'
            data['tool_response'] = [{'type': 'text', 'text': 'User responses:\n1. Continue'}]
            data[flag] = value
            code, runner, _ = self.run_adapter(data)
            self.assertEqual(code, 0)
            self.assertEqual(runner.calls[0][0][6], 'unknown')

    def test_exact_native_cancellation_records_cancel_without_private_content(self):
        data = payload('PostToolUse')
        data['tool_name'] = 'mcp__conductor__AskUserQuestion'
        blocks = [{'type': 'text', 'text': CANCELLED}]
        for response in (blocks, {'content': blocks}, {'content': blocks, 'isError': False}):
            with self.subTest(response=response):
                data['tool_response'] = response
                code, runner, error = self.run_adapter(data)
                self.assertEqual((code, error), (0, ''))
                self.assertEqual([args[6] for args, _ in runner.calls], ['cancel'])
                self.assertNotIn(CANCELLED, repr(runner.calls))
                self.assertNotIn(QUESTION['question'], repr(runner.calls))

    def test_cancellation_requires_exact_native_formatter_and_unambiguous_envelope(self):
        blocks = [{'type': 'text', 'text': CANCELLED}]
        responses = [
            [{'type': 'text', 'text': text}] for text in
            (CANCELLED.split('\n')[0], CANCELLED + '\n', 'prefix' + CANCELLED,
             CANCELLED.replace('Retryable: no', 'Retryable: yes'),
             CANCELLED.replace('\n', '\r\n'), CANCELLED + '\nUser responses:\n1. Hold')]
        responses += [blocks * 2, {'content': blocks, 'isError': True},
                      {'content': blocks, 'isError': 'false'}, {'content': blocks, 'error': 'failed'},
                      {'content': blocks, 'cancelled': True}, {'content': blocks, 'unknown': True},
                      [{'type': 'text', 'text': CANCELLED, 'isError': True}]]
        for response in responses:
            with self.subTest(response=response):
                data = payload('PostToolUse')
                data.update(tool_name='mcp__conductor__AskUserQuestion', tool_response=response)
                code, runner, _ = self.run_adapter(data)
                self.assertEqual(code, 0)
                self.assertEqual(runner.calls[0][0][6], 'unknown')
        for update in ({'tool_name': 'AskUserQuestion'}, {'hook_event_name': 'PostToolUseFailure'},
                       {'tool_input': {}}, {'error': 'failed'}, {'isError': True},
                       {'is_interrupt': True}, {'cancelled': True}, {'afkTimeoutMs': 1000}):
            with self.subTest(update=update):
                data = payload('PostToolUse')
                data.update(tool_name='mcp__conductor__AskUserQuestion', tool_response=blocks)
                data.update(update)
                code, runner, _ = self.run_adapter(data)
                self.assertEqual(code, 0)
                self.assertEqual(runner.calls[0][0][6], 'unknown')

    def test_uncertain_cancellation_write_attempts_generic_unknown(self):
        data = payload('PostToolUse')
        data.update(tool_name='mcp__conductor__AskUserQuestion',
                    tool_response=[{'type': 'text', 'text': CANCELLED}])
        code, runner, error = self.run_adapter(data, recorder=Recorder([1, 0]))
        self.assertEqual(code, 2)
        self.assertEqual([args[6] for args, _ in runner.calls], ['cancel', 'unknown'])
        self.assertTrue(error.strip())

    def test_builtin_tool_does_not_accept_conductor_numbered_text(self):
        data = payload('PostToolUse')
        data['tool_response'] = {'content': [{'type': 'text', 'text': 'User responses:\n1. Continue'}]}
        code, runner, _ = self.run_adapter(data)
        self.assertEqual(code, 0)
        self.assertEqual(runner.calls[0][0][6], 'unknown')

    def test_alias_lookalikes_never_match_or_write_prompt_observations(self):
        names = ['AskUserQuestion', 'mcp__conductor__AskUserQuestion']
        lookalikes = ['askuserquestion', 'mcp__other__AskUserQuestion',
                     'mcp__Conductor__AskUserQuestion', 'mcp__conductor__askuserquestion']
        for name in names:
            lookalikes.extend([name + 'Extra', 'Prefix' + name, name + '\n', name + '\r'])
        snippet = settings_snippet('/tmp/hook.py', '/tmp/state.sqlite')
        for entries in snippet['hooks'].values():
            matcher = entries[0]['matcher']
            for name in names:
                self.assertIsNotNone(re.search(matcher, name), name)
            for name in lookalikes:
                self.assertIsNone(re.search(matcher, name), name)
        for name in lookalikes:
            data = payload()
            data['tool_name'] = name
            code, runner, error = self.run_adapter(data, env={})
            self.assertEqual((code, error), (0, ''))
            self.assertFalse(runner.calls)

    def test_unknown_events_and_subagent_calls_cannot_change_queen_state(self):
        for update in ({'hook_event_name': 'Stop'}, {'agent_id': 'child-fixture'}):
            data = payload()
            data.update(update)
            code, runner, _ = self.run_adapter(data)
            self.assertEqual(code, 2)
            self.assertFalse(runner.calls)

    def test_required_identity_and_absolute_state_path_fail_closed(self):
        for key in ENV:
            for value in (None, '', 'private-fixture\n', 'x' * 4097):
                env = dict(ENV)
                if value is None:
                    env.pop(key)
                else:
                    env[key] = value
                code, runner, error = self.run_adapter(payload(), env=env)
                self.assertEqual(code, 2)
                self.assertFalse(runner.calls)
                self.assertNotIn('private-fixture', error)
        for value in ('', '../tool', 'x' * 129, 'tool\x00'):
            data = payload()
            data['tool_use_id'] = value
            self.assertEqual(self.run_adapter(data)[0], 2)
        env = dict(ENV, MONARCHY_STATE='relative.sqlite')
        self.assertEqual(self.run_adapter(payload(), env=env)[0], 2)

    def test_main_reads_at_most_input_limit_plus_one(self):
        class Input:
            def read(self, count):
                self.count = count
                return b'x' * count
        stream = Input()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(stdin=stream, environ=ENV), 2)
        self.assertEqual(stream.count, MAX_INPUT_BYTES + 1)

    def test_adapter_only_reads_two_environment_settings(self):
        class Environment:
            def get(self, key):
                if key not in ENV:
                    raise AssertionError('unexpected environment read')
                return ENV[key]
        self.assertEqual(self.run_adapter(payload(), env=Environment())[0], 0)

    def test_entrypoint_imports_from_an_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / 'bin/monarchy-prompt-hook.py')],
                                    cwd=directory, input=b'not-json', capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b'')
        self.assertNotIn(b'Traceback', result.stderr)

    def test_snippet_quotes_paths_and_never_installs_settings(self):
        script = "/tmp/tool's folder/$(touch marker)`code`/hook.py"
        state = "/tmp/court's folder/$(touch marker)`data`.sqlite"
        snippet = settings_snippet(script, state)
        self.assertEqual(set(snippet), {'hooks'})
        self.assertEqual(set(snippet['hooks']), {'PreToolUse', 'PostToolUse', 'PostToolUseFailure'})
        for event, entries in snippet['hooks'].items():
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]['matcher'],
                             r'^(?:AskUserQuestion|mcp__conductor__AskUserQuestion)(?![\s\S])')
            hook = entries[0]['hooks'][0]
            self.assertEqual(hook['type'], 'command')
            self.assertEqual(shlex.split(hook['command']),
                             ['MONARCHY_STATE=' + state, sys.executable, script])
            self.assertEqual(hook['onFailure'], 'block')
            self.assertNotIn('async', hook)
            self.assertEqual(hook['timeout'], 10)

    def test_snippet_rejects_relative_or_control_character_paths_safely(self):
        for path in ('relative', '/tmp/private\npath', '/tmp/private\x00path', ''):
            with self.assertRaises(HookError) as caught:
                settings_snippet(path, '/tmp/state')
            self.assertNotIn('private', str(caught.exception))

    def test_generated_command_preserves_literal_shell_metacharacters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "hook '$(touch marker)`touch marker`.py"
            state = str(root / "state '$(touch marker)`touch marker`.sqlite")
            script.write_text('import json, os\nprint(json.dumps(os.environ["MONARCHY_STATE"]))\n')
            command = settings_snippet(script, state)['hooks']['PreToolUse'][0]['hooks'][0]['command']
            result = subprocess.run(['/bin/sh', '-c', command], cwd=root,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout), state)
            self.assertFalse((root / 'marker').exists())

    def test_box_lint_accepts_two_through_four_options(self):
        for count in range(2, 5):
            options = copy.deepcopy(QUESTION['options'])
            options += [{'label': 'Choice ' + str(i), 'description': 'Another path.'}
                        for i in range(count - 2)]
            self.assertIsNone(lint_box(QUESTION['question'], options))

    def test_box_lint_rejects_structure_duplicates_recommendation_and_bounds(self):
        valid = QUESTION['options']
        invalid = [('', valid), (['One?', 'Two?'], valid), ('One? Two?', valid),
                   ('x' * 2001, valid), ('One?', valid[:1]), ('One?', valid * 3),
                   ('One?', list(reversed(valid))), ('One?', [valid[0], valid[0]]),
                   ('One?', [valid[0], {'label': 'Continue', 'description': 'Duplicate.'}]),
                   ('One?', [valid[0], {'label': 'Other (Recommended)', 'description': 'Other.'}]),
                   ('One?', [valid[0], {'label': 'Hold', 'description': 'x' * 2001}])]
        for question, options in invalid:
            with self.subTest(question=question, options=options), self.assertRaises(HookError):
                lint_box(question, options)


if __name__ == '__main__':
    unittest.main()
