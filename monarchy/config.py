"""Strict preference data, not authority grants or external side effects.

Defaults recommend behavior. The royalty confirm profiles/timezone and
record authority. A validated file is not permission to dispatch or delegate.
"""
import copy
import hashlib
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MAX_BYTES = 65536
MAX_NODES = 4096
MAX_DEPTH = 8
LAYERS = ('project', 'owner', 'overrides')
NEVER_DELEGABLE = (
    'production-approval-or-rollout', 'terraform-apply', 'iam', 'secrets',
    'spending', 'contacting-or-naming-people', 'legal',
)
INVARIANTS = {
    'never-delegable': NEVER_DELEGABLE,
    'trusted-owner-route': True,
    'one-writer': True,
    'no-model-substitution': True,
    'no-metered-fallback': True,
    'agent-prefix': '00-',
    'secretary-header': '[secretary]',
    'unknown-prompt-holds': True,
    'verb-classification': {
        'restrictive': ('bearings', 'decisions', 'away', 'pause', 'stop'),
        'confirmation-required': ('resume', 'model', 'handoff'),
    },
}


class ConfigError(ValueError):
    """Safe error: only schema-owned setting names may appear in diagnostics."""


def _spec(default, kind, *, home='owner', merge='replace', layers=None, **bounds):
    return dict(default=default, kind=kind, home=home, merge=merge,
                layers=layers if layers is not None else (home,), **bounds)


def _limit(default, minimum, maximum, *, layers=('owner',), home='owner'):
    return _spec(default, 'integer', minimum=minimum, maximum=maximum,
                 home=home, layers=layers, merge='min')


def _minutes(default):
    return _spec(default, 'integer', minimum=1, maximum=1440)


def _project(default, kind='strings', **bounds):
    return _spec(default, kind, home='project', **bounds)


# Each replace key has exactly one writable home. Project-scoped safety limits
# may have several restrictive contributors without an override precedence order.
# Private owner facts have no populated public default.
KEYS = {
    'voice.max_lines': _limit(5, 1, 20),
    'voice.zone': _spec(None, 'zone', nullable=True),
    'voice.forbidden_characters': _spec(['\u2014'], 'characters', merge='union',
                                      layers=('owner', 'overrides')),
    'forwards.max_lines': _limit(3, 1, 20),
    'forwards.max_chars': _limit(900, 1, 10000),
    'reports.max_lines': _limit(5, 1, 20),
    'reports.max_chars': _limit(1200, 1, 10000),
    'failures.identical_limit': _limit(2, 1, 10),
    'prompts.abandoned_minutes': _minutes(60),
    'profiles.queen': _spec({'agent': 'claude', 'model': 'opus-5-5-1m',
                             'effort': 'xhigh', 'fast_mode': False}, 'profile'),
    'profiles.secretary': _spec({'agent': 'claude', 'model': 'opus-5-5-1m',
                                 'effort': 'xhigh', 'fast_mode': False}, 'profile'),
    'profiles.worker': _spec({'agent': 'codex', 'model': 'gpt-6-astra',
                              'effort': 'ultra', 'fast_mode': True}, 'profile'),
    'orders.omit': _spec([], 'strings'),
    'orders.notes.queen': _spec('', 'text', maximum=2000, multiline=True),
    'orders.notes.secretary': _spec('', 'text', maximum=2000, multiline=True),
    'orders.notes.worker': _spec('', 'text', maximum=2000, multiline=True),
    'cadence.sweep_minutes': _minutes(30),
    'cadence.report_overdue_minutes': _minutes(20),
    'cadence.status_minutes': _minutes(30),
    'cadence.stale_minutes': _minutes(60),
    'cadence.reminder_minutes': _minutes(120),
    'cadence.digest_time': _spec('06:57', 'clock'),
    'backlog.builder_cap': _limit(8, 1, 8, home='project',
                                  layers=('project', 'owner', 'overrides')),
    'backlog.idle_minutes': _project(20, 'integer', minimum=1, maximum=1440),
    'backlog.review_hours': _project(48, 'integer', minimum=1, maximum=168),
    'backlog.selection_order': _project([
        'open-prs', 'wanted-parked-prs', 'priority-epics', 'user-reported-bugs',
        'other-bugs', 'remaining-priority-smallest-first'], 'selection'),
    'priority.check_minutes': _project(15, 'integer', minimum=1, maximum=1440),
    'priority.incident_minutes': _project(30, 'integer', minimum=1, maximum=1440),
    'priority.proof_minutes': _project(60, 'integer', minimum=1, maximum=1440),
    'rotation.time': _spec('04:00', 'clock'),
    'rotation.name': _spec('Queen · YYYY-MM-DD', 'text', maximum=128),
    'rotation.retired_name': _spec('retired (old Queen <date>)', 'text', maximum=128),
    'archive.hold_hours': _spec(24, 'integer', minimum=24, maximum=8760),
    'archive.protected_workspaces': _spec([], 'strings', merge='union',
                                        layers=('owner', 'overrides')),
    'owner.slots': _spec(None, 'integer', nullable=True, minimum=1, maximum=64),
    'owner.reserved_slots': _spec(None, 'integer', nullable=True, minimum=0, maximum=64),
    'owner.account_facts': _spec([], 'strings'),
    'owner.local_bridge_policy': _spec('read-only', 'choice', choices=('disabled', 'read-only')),
    'project.repository': _project(None, 'repository', nullable=True),
    'project.required_checks': _project([], merge='union'),
    'project.merge_labels': _project([]),
    'project.priority_surfaces': _project([]),
    'project.priority_feed': _project('', 'text', maximum=2048),
    'project.priority_milestones': _project([]),
    'project.evidence_capture_command': _project('', 'text', maximum=2048),
    'project.ledger_location': _project('', 'text', maximum=2048),
    'project.production_approval_template': _project('', 'text', maximum=2048),
    'publish.brand_terms': _project([], merge='union'),
    'delegation.never': _project(list(NEVER_DELEGABLE), merge='union'),
    'delegation.categories': _project([], merge='union'),
    'court.paused': _spec(False, 'restriction', home='overrides'),
    'court.stopped': _spec(False, 'restriction', home='overrides'),
    'court.away': _spec(False, 'restriction', home='overrides'),
}


def _fail(key=None, reason='invalid configuration'):
    # An arbitrary input key is just as private as an arbitrary input value.
    label = key if type(key) is str and key in KEYS else 'configuration'
    raise ConfigError(label + ': ' + reason) from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail(reason='duplicate JSON member')
        result[key] = value
    return result


def _integer_token(raw):
    if len(raw.lstrip('-')) > 19:
        _fail(reason='integer exceeds supported bounds')
    return int(raw)


def _constant(_):
    _fail(reason='nonfinite JSON value')


def _bounded_tree(value):
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            _fail(reason='document exceeds structural bounds')
        kind = type(item)
        if item is None or kind is bool:
            return
        if kind is int:
            if not -(2**63) <= item < 2**63:
                _fail(reason='integer exceeds supported bounds')
            return
        if kind is float:
            if not math.isfinite(item):
                _fail(reason='nonfinite JSON value')
            return
        if kind is str:
            try:
                encoded = item.encode('utf-8')
            except UnicodeError:
                _fail(reason='invalid text encoding')
            if len(encoded) > MAX_BYTES:
                _fail(reason='text exceeds supported bounds')
            return
        if kind is list:
            for child in item:
                visit(child, depth + 1)
            return
        if kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _fail(reason='setting names must be text')
                visit(key, depth + 1)
                visit(child, depth + 1)
            return
        _fail(reason='document contains a non-JSON value')

    visit(value, 0)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail(reason='invalid JSON document')
    if len(encoded) > MAX_BYTES:
        _fail(reason='document exceeds 64 KiB')


def _text(value, maximum, *, multiline=False, nonempty=False):
    return (type(value) is str and len(value) <= maximum and
            (not nonempty or bool(value.strip())) and
            all(ord(c) >= 32 and ord(c) != 127 or multiline and c in '\n\t' for c in value))


def _validate_value(key, value):
    spec = KEYS[key]
    if value is None and spec.get('nullable'):
        return None
    kind = spec['kind']
    valid = False
    if kind == 'integer':
        valid = type(value) is int and spec['minimum'] <= value <= spec['maximum']
    elif kind == 'restriction':
        valid = value is True  # Releasing a restriction belongs to the approved verb path.
    elif kind == 'text':
        valid = _text(value, spec['maximum'], multiline=spec.get('multiline', False))
    elif kind == 'choice':
        valid = type(value) is str and value in spec['choices']
    elif kind == 'clock':
        valid = type(value) is str and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value) is not None
    elif kind == 'repository':
        valid = (type(value) is str and len(value) <= 201 and
                 re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,99}/[A-Za-z0-9_.-]{1,100}', value) is not None
                 and value.split('/')[1] not in ('.', '..'))
    elif kind == 'zone':
        if _text(value, 128, nonempty=True):
            try:
                ZoneInfo(value)
                valid = True
            except (ZoneInfoNotFoundError, ValueError):
                pass
    elif kind in ('strings', 'characters', 'selection'):
        maximum = 1 if kind == 'characters' else 256
        valid = (type(value) is list and len(value) <= 64 and
                 all(_text(item, maximum, nonempty=True) for item in value))
        if valid and kind == 'selection':
            valid = len(value) == len(set(value)) and set(value) == set(spec['default'])
        if valid:
            return list(dict.fromkeys(value))
    elif kind == 'profile':
        valid = (type(value) is dict and set(value) == {'agent', 'model', 'effort', 'fast_mode'}
                 and type(value['fast_mode']) is bool
                 and all(_text(value[field], 128, nonempty=True) and not value[field].startswith('-')
                         for field in ('agent', 'model', 'effort')))
    if not valid:
        _fail(key, 'invalid value or bounds')
    return copy.deepcopy(value)


def _validate(value, layer):
    if type(layer) is not str or layer not in LAYERS:
        _fail(reason='unsupported layer')
    if type(value) is not dict:
        _fail(reason='expected an object of dotted settings')
    _bounded_tree(value)
    result = {}
    for key, item in value.items():
        if key == '_why':
            continue
        if key not in KEYS:
            _fail(reason='unknown setting')
        if layer not in KEYS[key]['layers']:
            _fail(key, 'setting is not allowed in this layer')
        result[key] = _validate_value(key, item)
        if key == 'orders.omit' and result[key]:
            if any(rule.startswith('invariant.') for rule in result[key]):
                _fail(key, 'invariant rules cannot be omitted')
            # Imported only for explicit omissions. Orders has no config import,
            # and missing/corrupt definitions hold instead of accepting a typo.
            try:
                from .orders import INVARIANT_RULE_IDS, rule_ids
                available = rule_ids()
            except (ImportError, ValueError):
                _fail(key, 'standing order definitions are unavailable')
            if any(rule in INVARIANT_RULE_IDS or rule not in available for rule in result[key]):
                _fail(key, 'unknown or invariant omission')
    why = value.get('_why', {})
    if type(why) is not dict:
        _fail(reason='_why must map configured settings to explanations')
    for key, item in why.items():
        if key not in result or not _text(item, 2000, multiline=True, nonempty=True):
            _fail(key, 'invalid _why explanation')
    if '_why' in value:
        result['_why'] = copy.deepcopy(why)
    return result


def load(raw, layer):
    """Parse one UTF-8 JSON document; filenames and file I/O belong to callers."""
    if type(raw) not in (bytes, str):
        _fail(reason='expected UTF-8 JSON text')
    try:
        encoded = raw if type(raw) is bytes else raw.encode('utf-8')
        if len(encoded) > MAX_BYTES:
            _fail(reason='document exceeds 64 KiB')
        text = encoded.decode('utf-8')
        data = json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=_constant, parse_int=_integer_token)
        return _validate(data, layer)
    except ConfigError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        _fail(reason='invalid JSON document')


def resolve(project=None, owner=None, overrides=None):
    """Resolve one project's preferences without competing replace homes.

    layers lists the effective home for replace, or every contributor for min
    and union. why preserves each supplied explanation with its layer identity.
    Nothing in this result authenticates the caller or activates a grant.
    """
    inputs = {'project': project, 'owner': owner, 'overrides': overrides}
    checked = {layer: _validate({} if value is None else value, layer)
               for layer, value in inputs.items()}
    result = {}
    for key, spec in KEYS.items():
        entry = {'value': copy.deepcopy(spec['default']), 'layers': ['defaults'], 'why': {}}
        for layer in LAYERS:
            source = checked[layer]
            if key not in source:
                continue
            value = source[key]
            if spec['merge'] == 'replace':
                entry['value'] = copy.deepcopy(value)
                entry['layers'] = [layer]
            elif spec['merge'] == 'min':
                entry['value'] = min(entry['value'], value)
                entry['layers'].append(layer)
            elif spec['merge'] == 'union':
                entry['value'] = list(dict.fromkeys(entry['value'] + value))
                entry['layers'].append(layer)
            else:
                _fail(key, 'unsupported schema merge rule')
            if key in source.get('_why', {}):
                entry['why'][layer] = source['_why'][key]
        result[key] = entry
    slots, reserved = result['owner.slots']['value'], result['owner.reserved_slots']['value']
    if slots is not None and reserved is not None and reserved > slots:
        _fail('owner.reserved_slots', 'reserved slots exceed total slots')
    return result


def defaults_digest():
    """Pin both default values and validation policy, including invariant floors."""
    data = json.dumps({'keys': KEYS, 'invariants': INVARIANTS}, sort_keys=True,
                      separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def widening(before, after, layer='project'):
    """Known setting names whose change needs an owner review before pinning.

    Removing a restriction or increasing a cap widens policy. A changed replace
    fact is conservatively reviewed, even if the caller believes it harmless.
    This comparison produces no answer or grant and does not read current pins.
    """
    previous, candidate = _validate(before, layer), _validate(after, layer)
    changes = []
    for key, spec in KEYS.items():
        if layer not in spec['layers']:
            continue
        old = previous.get(key, spec['default'])
        new = candidate.get(key, spec['default'])
        if old == new:
            continue
        if spec['merge'] == 'min':
            changed = min(spec['default'], new) > min(spec['default'], old)
        elif spec['merge'] == 'union':
            floor = set(spec['default'])
            changed = not (floor | set(old)) <= (floor | set(new))
        elif spec['kind'] == 'restriction':
            changed = old is True and new is False
        else:
            changed = True
        if changed:
            changes.append(key)
    return sorted(changes)
