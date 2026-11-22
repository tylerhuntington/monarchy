"""Opt-in Claude prompt observations, with no answer or authority persistence."""
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


MAX_INPUT_BYTES = 65536
ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
EVENTS = ('PreToolUse', 'PostToolUse', 'PostToolUseFailure')
QUESTION_TOOLS = ('AskUserQuestion', 'mcp__conductor__AskUserQuestion')
# Match the real end of the name, including when malformed input ends in a newline.
QUESTION_MATCHER = r'^(?:' + '|'.join(re.escape(name) for name in QUESTION_TOOLS) + r')(?![\s\S])'
FAILURE_MESSAGE = 'Monarchy could not safely record the prompt observation; keep forwarding held.'


class HookError(ValueError):
    """A safe diagnostic that never contains input values or private paths."""


def _text(value, maximum):
    if (type(value) is not str or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise HookError('prompt text is missing, invalid or exceeds its bound')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise HookError('prompt text must be valid Unicode') from None
    return value


def _path(value):
    try:
        value = os.fspath(value)
    except TypeError:
        raise HookError('prompt paths must be absolute text paths') from None
    _text(value, 4096)
    if not Path(value).is_absolute():
        raise HookError('prompt paths must be absolute text paths')
    return value


def lint_box(question, options):
    """Check optional box style, without interpreting an answer as permission.

    This structural check cannot establish that prose asks only one semantic
    question. It accepts one question string and rejects multiple question marks.
    """
    _text(question, 2000)
    if question.count('?') > 1:
        raise HookError('a decision box must ask one question')
    if type(options) is not list or not 2 <= len(options) <= 4:
        raise HookError('a decision box must contain two through four options')
    seen = set()
    marker = ' (Recommended)'
    for index, option in enumerate(options):
        if type(option) is not dict or not {'label', 'description'} <= set(option):
            raise HookError('each decision option requires a label and description')
        label = _text(option['label'], 120).strip()
        _text(option['description'], 2000)
        if index == 0:
            if not label.endswith(marker):
                raise HookError('the first decision option must end with (Recommended)')
            label = label[:-len(marker)].strip()
            if not label or '(recommended)' in label.casefold():
                raise HookError('the first decision option has an invalid recommendation')
        elif '(recommended)' in label.casefold():
            raise HookError('only the first decision option can be recommended')
        key = label.casefold()
        if key in seen:
            raise HookError('decision option labels must be distinct')
        seen.add(key)


def settings_snippet(script_path, state_path):
    """Return settings data for review; never read or write host settings.

    Generate on the intended host so the Python interpreter path is applicable.
    The shell receives only quoted paths; session identity stays in the native
    environment and is validated by the adapter at execution time.
    """
    script_path, state_path = _path(script_path), _path(state_path)
    command = 'MONARCHY_STATE={} {} {}'.format(
        shlex.quote(state_path), shlex.quote(sys.executable), shlex.quote(script_path))
    return {'hooks': {event: [{'matcher': QUESTION_MATCHER, 'hooks': [{
        'type': 'command', 'command': command, 'timeout': 10, 'onFailure': 'block',
    }]}] for event in EVENTS}}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HookError('hook JSON contains duplicate keys')
        result[key] = value
    return result


def _nonfinite(_value):
    raise HookError('hook JSON contains a nonfinite value')


def _float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise HookError('hook JSON contains a nonfinite value')
    return parsed


def _payload(raw):
    if type(raw) is not bytes or not raw or len(raw) > MAX_INPUT_BYTES:
        raise HookError('hook input is missing or exceeds its bound')
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                      parse_constant=_nonfinite, parse_float=_float)
    if type(data) is not dict:
        raise HookError('hook input must be an object')
    return data


def _questions(value):
    if type(value) is not list or not 1 <= len(value) <= 4:
        return None
    questions = []
    for entry in value:
        if type(entry) is not dict:
            return None
        question = entry.get('question')
        if type(question) is not str or not question.strip() or len(question) > 2000:
            return None
        questions.append(question)
    return questions if len(set(questions)) == len(questions) else None


def _builtin_answered(data):
    # Managed PostToolUse can receive failed tool output. Do not treat the
    # event name alone, a freeform dismissal or an automatic timeout as a close.
    response, tool_input = data.get('tool_response'), data.get('tool_input')
    if type(response) is not dict or type(tool_input) is not dict:
        return False
    for item in (data, response):
        if 'error' in item or item.get('afkTimeoutMs') is not None:
            return False
        for flag in ('is_interrupt', 'interrupted', 'cancelled', 'canceled', 'aborted'):
            if flag in item and item[flag] is not False:
                return False
    if response.get('response') not in (None, ''):
        return False
    questions = _questions(tool_input.get('questions'))
    if questions is None or _questions(response.get('questions')) != questions:
        return False
    answers = response.get('answers')
    return (type(answers) is dict and set(answers) == set(questions)
            and all(type(answer) is str and bool(answer.strip())
                    for answer in answers.values()))


def _single_answer(value):
    return (bool(value.strip()) and len(value.splitlines()) == 1
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _conductor_answered(data):
    """Recognize the installed Conductor formatter, not arbitrary MCP prose.

    Claude passes the native tool's content array to PostToolUse. The exact
    one-content MCP envelope is also recognized. Neither is an owner grant.
    Multiline freeform text is ambiguous in this positional format and holds.
    """
    response, tool_input = data.get('tool_response'), data.get('tool_input')
    if type(tool_input) is not dict or _questions(tool_input.get('questions')) is None:
        return False
    for item in (data, response):
        if type(item) is not dict:
            continue
        if 'error' in item or item.get('afkTimeoutMs') is not None:
            return False
        for flag in ('isError', 'is_interrupt', 'interrupted', 'cancelled', 'canceled', 'aborted'):
            if flag in item and item[flag] is not False:
                return False
    if type(response) is dict:
        if not set(response) <= {'content', 'isError'}:
            return False
        response = response.get('content')
    if (type(response) is not list or len(response) != 1 or type(response[0]) is not dict
            or set(response[0]) != {'type', 'text'} or response[0]['type'] != 'text'
            or type(response[0]['text']) is not str):
        return False
    lines = response[0]['text'].split('\n')
    if not lines or lines[0] != 'User responses:':
        return False
    cursor = 1
    for number, question in enumerate(tool_input['questions'], 1):
        if cursor >= len(lines):
            return False
        prefix = str(number) + '. '
        if lines[cursor].startswith(prefix):
            if not _single_answer(lines[cursor][len(prefix):]):
                return False
            cursor += 1
        elif lines[cursor] == str(number) + '.' and question.get('multiSelect') is True:
            cursor += 1
            start = cursor
            while cursor < len(lines) and lines[cursor].startswith('   - '):
                if not _single_answer(lines[cursor][5:]):
                    return False
                cursor += 1
            if cursor == start:
                return False
        else:
            return False
    return cursor == len(lines)


def _answered(data):
    if data.get('tool_name') == 'mcp__conductor__AskUserQuestion':
        return _conductor_answered(data)
    return _builtin_answered(data)


def _record(action, session, prompt_id, state, runner):
    args = [sys.executable, '-m', 'monarchy', '--state', state, 'prompt', action,
            '--session', session, '--prompt-id', prompt_id]
    try:
        result = runner(args, cwd=ROOT, shell=False, stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=3, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt):
        return False


def run_hook(raw, environ, runner=subprocess.run):
    """Translate bounded hook bytes into a durable CLI observation.

    The CLI owns current-holder validation, prompt-ID matching, timestamps and
    the transaction that excludes an in-flight forward. These observations do
    not answer decisions, grant authority or authenticate an owner's response.
    """
    try:
        data = _payload(raw)
        tool = data.get('tool_name')
        if type(tool) is not str or not tool:
            raise HookError('hook tool identity is missing')
        if tool not in QUESTION_TOOLS:
            return 0
        event = data.get('hook_event_name')
        if event not in EVENTS or data.get('agent_id') is not None:
            raise HookError('unsupported prompt event or subagent context')
        session = environ.get('CONDUCTOR_SESSION_ID')
        prompt_id = data.get('tool_use_id')
        if any(type(value) is not str or not IDENTIFIER.fullmatch(value)
               for value in (session, prompt_id)):
            raise HookError('prompt identity is missing or invalid')
        state = _path(environ.get('MONARCHY_STATE'))
        action = ('open' if event == 'PreToolUse' else
                  'close' if event == 'PostToolUse' and _answered(data) else 'unknown')
        if not _record(action, session, prompt_id, state, runner):
            # A close may have committed before its process timed out. Attempt
            # a conservative same-ID unknown observation; never retry a close.
            if action == 'close':
                _record('unknown', session, prompt_id, state, runner)
            raise HookError('prompt observation could not be recorded')
        return 0
    except (ValueError, TypeError, UnicodeError, RecursionError, OSError, KeyboardInterrupt):
        print(FAILURE_MESSAGE, file=sys.stderr)
        return 2


def main(stdin=None, environ=None):
    """Read only bounded stdin and the two documented environment settings."""
    try:
        raw = (sys.stdin.buffer if stdin is None else stdin).read(MAX_INPUT_BYTES + 1)
    except (OSError, KeyboardInterrupt):
        print(FAILURE_MESSAGE, file=sys.stderr)
        return 2
    return run_hook(raw, os.environ if environ is None else environ)
