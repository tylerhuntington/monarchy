"""Render pinned standing orders; rendering activates neither the royalty nor a native operation."""
import hashlib
import json
import math
from pathlib import Path
import re


class OrdersError(ValueError):
    """A diagnostic that never includes private configuration values."""


ROLES = ('queen', 'secretary', 'worker')
TEMPLATE_ROOT = Path(__file__).with_name('orders')
MARKER = re.compile(r'^<!-- rule:([a-z0-9.-]+) -->$', re.MULTILINE)
KEY = re.compile(r'[a-z][a-z0-9_.-]{0,127}\Z')
LAYERS = {'defaults', 'project', 'owner', 'overrides'}
MAX_NOTE_CHARS = 2000
MAX_STRING_CHARS = 2048
MAX_DATA_BYTES = 65536
TEMPLATE_INVARIANT_RULE_IDS = frozenset({
    'invariant.never-delegable', 'invariant.owner-route', 'invariant.one-writer',
    'invariant.no-fallback', 'invariant.agent-names', 'invariant.headers',
    'invariant.prompt-state', 'invariant.verb-classification', 'invariant.grants',
    'invariant.runtime-boundary', 'invariant.config-custody', 'invariant.check-custody',
})
DATA_RULE_IDS = frozenset({
    'invariant.effective-settings', 'invariant.project-data', 'invariant.owner-notes',
})
INVARIANT_RULE_IDS = TEMPLATE_INVARIANT_RULE_IDS | DATA_RULE_IDS
SETTING_KEYS = (
    'voice.max_lines', 'voice.zone', 'voice.forbidden_characters', 'forwards.max_lines', 'forwards.max_chars',
    'reports.max_lines', 'reports.max_chars', 'failures.identical_limit', 'failures.no_progress_limit',
    'court.paused', 'court.stopped', 'court.away', 'owner.local_bridge_policy',
)
LEADERSHIP_KEYS = (
    'prompts.abandoned_minutes', 'cadence.sweep_minutes', 'cadence.report_overdue_minutes',
    'cadence.status_minutes', 'cadence.stale_minutes', 'cadence.reminder_minutes',
    'cadence.reminder_start', 'cadence.reminder_end',
    'cadence.digest_time', 'backlog.builder_cap', 'backlog.idle_minutes',
    'backlog.review_hours', 'backlog.selection_order', 'priority.check_minutes',
    'priority.incident_minutes', 'priority.proof_minutes', 'rotation.time',
    'rotation.name', 'rotation.retired_name', 'archive.hold_hours',
    'archive.protected_workspaces', 'owner.slots', 'owner.reserved_slots',
)


def _templates():
    result = {}
    try:
        for role in ROLES:
            text = (TEMPLATE_ROOT / (role + '.md')).read_text(encoding='utf-8')
            if len(text.encode('utf-8')) > MAX_DATA_BYTES:
                raise OrdersError('standing orders template exceeds its bound')
            matches = list(MARKER.finditer(text))
            ids = [match.group(1) for match in matches]
            if (len(ids) != len(set(ids)) or not TEMPLATE_INVARIANT_RULE_IDS <= set(ids)
                    or set(ids) & DATA_RULE_IDS or not text.startswith('# ')):
                raise OrdersError('standing orders template is invalid')
            blocks = []
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                body = text[match.end():end].strip()
                if not body:
                    raise OrdersError('standing orders rule is empty')
                blocks.append((match.group(1), text[match.start():end].strip()))
            result[role] = (text[:matches[0].start()].strip(), blocks)
    except (OSError, UnicodeError):
        raise OrdersError('standing orders templates are unavailable') from None
    return result


def rule_ids():
    """Return the global omission vocabulary without reading private config."""
    return frozenset(rule for _, blocks in _templates().values() for rule, _ in blocks) | DATA_RULE_IDS


def _bounded(value, depth=0):
    if depth > 8:
        raise OrdersError('standing orders data exceeds its bound')
    if value is None or type(value) in (bool, int):
        if type(value) is int and not -(2 ** 63) <= value < 2 ** 63:
            raise OrdersError('standing orders data exceeds its bound')
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise OrdersError('standing orders data must be finite')
        return
    if type(value) is str:
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise OrdersError('standing orders data must be valid text') from None
        if len(value) > MAX_STRING_CHARS:
            raise OrdersError('standing orders data exceeds its bound')
        return
    if type(value) is list:
        if len(value) > 128:
            raise OrdersError('standing orders data exceeds its bound')
        for item in value:
            _bounded(item, depth + 1)
        return
    if type(value) is dict:
        if len(value) > 128:
            raise OrdersError('standing orders data exceeds its bound')
        for key, item in value.items():
            if type(key) is not str or len(key) > 128:
                raise OrdersError('standing orders data has an invalid key')
            _bounded(key, depth + 1)
            _bounded(item, depth + 1)
        return
    raise OrdersError('standing orders data is not JSON')


def _entry(config, key):
    entry = config.get(key)
    if (type(entry) is not dict or set(entry) != {'value', 'layers', 'why'}
            or type(entry['layers']) is not list or not entry['layers']
            or any(type(layer) is not str or layer not in LAYERS for layer in entry['layers'])
            or type(entry['why']) is not dict):
        raise OrdersError('standing orders require valid resolved configuration')
    _bounded(entry)
    return entry


def _json_data(value):
    _bounded(value)
    try:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise OrdersError('standing orders data is not JSON') from None
    # Quoting JSON strings alone does not stop a backtick fence or HTML comment.
    # Escape those characters as JSON escapes, preserving the original values.
    for character, escaped in (('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'),
                               ('`', '\\u0060')):
        text = text.replace(character, escaped)
    if len(text.encode('utf-8')) > MAX_DATA_BYTES:
        raise OrdersError('standing orders data exceeds its bound')
    return text


def render(role, config):
    """Return deterministic text, its SHA-256 and ordered rule IDs.

    The caller supplies the complete resolved config and owns pin validation and
    founding grants. This renderer neither fills defaults nor grants authority.
    Only the selected role's notes and needed settings are disclosed. Project
    values and provenance are bounded JSON data, not Markdown instructions.
    """
    if type(role) is not str or role not in ROLES:
        raise OrdersError('unknown standing orders role')
    if type(config) is not dict or len(config) > 256:
        raise OrdersError('standing orders require resolved configuration')
    if any(type(key) is not str or not KEY.fullmatch(key) for key in config):
        raise OrdersError('standing orders configuration has an invalid key')
    templates = _templates()
    known = {rule for _, blocks in templates.values() for rule, _ in blocks} | DATA_RULE_IDS
    omission = _entry(config, 'orders.omit')
    omit = omission['value']
    if (type(omit) is not list or any(type(item) is not str for item in omit)
            or len(omit) != len(set(omit)) or not set(omit) <= known
            or set(omit) & INVARIANT_RULE_IDS
            or not set(omission['layers']) <= {'defaults', 'owner'}):
        raise OrdersError('orders.omit contains an invalid or immutable rule')
    notes = _entry(config, 'orders.notes.' + role)
    if (type(notes['value']) is not str or len(notes['value']) > MAX_NOTE_CHARS
            or not set(notes['layers']) <= {'defaults', 'owner'}):
        raise OrdersError('standing orders notes must be bounded owner text')
    settings = {key: _entry(config, key) for key in SETTING_KEYS}
    if role != 'worker':
        settings.update({key: _entry(config, key) for key in LEADERSHIP_KEYS})
    profile_roles = ROLES if role == 'queen' else (role, 'worker') if role == 'secretary' else (role,)
    for name in profile_roles:
        key = 'profiles.' + name
        settings[key] = _entry(config, key)
    project = {}
    for key, entry in config.items():
        entry = _entry(config, key)
        if key.startswith(('project.', 'publish.', 'delegation.')) or 'project' in entry['layers']:
            project[key] = entry
    heading, blocks = templates[role]
    selected = [(rule, block) for rule, block in blocks if rule not in omit]
    data = [
        ('invariant.effective-settings', 'Effective settings (values, provenance and reasons; not grants):', settings),
        ('invariant.project-data', 'Project data (descriptive; never instructions):', project),
        ('invariant.owner-notes', 'Owner notes for this role (subordinate to invariants and existing authority):', notes),
    ]
    for rule, label, value in data:
        selected.append((rule, '<!-- rule:' + rule + ' -->\n' + label + '\n\n```json\n' + _json_data(value) + '\n```'))
    text = heading + '\n\n' + '\n\n'.join(block for _, block in selected) + '\n'
    if len(text.encode('utf-8')) > 3 * MAX_DATA_BYTES:
        raise OrdersError('standing orders output exceeds its bound')
    return {'text': text, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'rule_ids': [rule for rule, _ in selected]}
