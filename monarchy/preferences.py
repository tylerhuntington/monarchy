"""Approved immutable configuration custody. No network or native actions."""
import hashlib
import json
from pathlib import PurePosixPath
import re
import subprocess

from .config import ConfigError, KEYS, defaults_digest, load, resolve, widening
from .orders import render
from .conductor import MAX_TEXT_BYTES
from .records import Conflict, RecordError

REVISION = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
SOURCE_FIELDS = {'commit', 'path', 'blob', 'sha256', 'bytes', 'layer', 'repository'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _git(root, *args):
    try:
        result = subprocess.run(['git', '--no-replace-objects', '-C', str(root), *args], capture_output=True, timeout=10)
        if result.returncode:
            raise ConfigError('source object is unavailable')
        return result.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError('source object is unavailable') from exc


def read_source(root, commit, path, layer):
    """Read bounded regular blobs by full commit, never mutable checkout bytes."""
    if layer not in {'owner', 'project'} or not isinstance(commit, str) or not REVISION.fullmatch(commit):
        raise ConfigError('source requires a full commit')
    if (not isinstance(path, str) or len(path) > 512 or not path
            or PurePosixPath(path).is_absolute() or any(p in {'..', '.'} for p in path.split('/'))
            or any(c in path for c in '\x00\n\r\\:')):
        raise ConfigError('invalid source path')
    if _git(root, 'cat-file', '-t', commit).strip() != b'commit':
        raise ConfigError('source requires a commit object')
    if layer == 'project':
        ref = _git(root, 'symbolic-ref', 'refs/remotes/origin/HEAD').decode().strip()
        if not ref.startswith('refs/remotes/origin/') or ref == 'refs/remotes/origin/HEAD':
            raise ConfigError('project default branch is unknown')
        _git(root, 'merge-base', '--is-ancestor', commit, ref)
    tree = _git(root, 'ls-tree', commit, '--', path).decode().split()
    if len(tree) != 4 or tree[0] not in {'100644', '100755'} or tree[1] != 'blob':
        raise ConfigError('source must be a regular blob')
    blob = tree[2]
    size = int(_git(root, 'cat-file', '-s', blob))
    if not 0 < size <= 65536:
        raise ConfigError('source exceeds file bound')
    raw = _git(root, 'cat-file', 'blob', blob)
    values = load(raw, layer)
    repository = ''
    if layer == 'project':
        from .conductor import _native_repo
        try:
            repository = _native_repo(_git(root, 'remote', 'get-url', 'origin').decode().strip())
        except ValueError as exc:
            raise ConfigError('project repository identity is unavailable') from exc
        if values.get('project.repository') != repository:
            raise ConfigError('project.repository differs from source repository')
    try:
        text = raw.decode('utf-8')
    except UnicodeError as exc:
        raise ConfigError('source must be UTF-8') from exc
    return {'commit': commit, 'path': path, 'blob': blob, 'sha256': hashlib.sha256(raw).hexdigest(),
            'bytes': text, 'layer': layer, 'repository': repository}


def _source(source, layer):
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS or source['layer'] != layer:
        raise ConfigError('invalid pinned source')
    if not all(isinstance(source[k], str) for k in SOURCE_FIELDS):
        raise ConfigError('invalid pinned source')
    if not REVISION.fullmatch(source['commit']) or not REVISION.fullmatch(source['blob']):
        raise ConfigError('invalid pinned source identity')
    try:
        raw = source['bytes'].encode('utf-8')
    except UnicodeError as exc:
        raise ConfigError('pinned source must be UTF-8') from exc
    if hashlib.sha256(raw).hexdigest() != source['sha256']:
        raise ConfigError('pinned source digest mismatch')
    # Git object hashes bind the exact bytes even in an offline successor.
    header = b'blob ' + str(len(raw)).encode() + b'\0'
    algorithm = hashlib.sha1 if len(source['blob']) == 40 else hashlib.sha256
    if algorithm(header + raw).hexdigest() != source['blob']:
        raise ConfigError('pinned blob digest mismatch')
    values = load(raw, layer)
    if layer == 'project' and values.get('project.repository') != source['repository']:
        raise ConfigError('project.repository differs from pinned source')
    return values


def bounded_orders(config):
    result = {role: render(role, config) for role in ('queen', 'secretary', 'worker')}
    if any(len(row['text'].encode('utf-8')) > MAX_TEXT_BYTES - 3 for row in result.values()):
        raise ConfigError('standing orders exceed the delivery budget')
    return result


def accepted(answer):
    return type(answer) is dict and set(answer) == {'accept'} and answer['accept'] is True


class Preferences:
    """Caller must be a trusted local owner-route adapter, not a worker report.

    Owner message references record authority; they do not authenticate a human.
    Confirmations are durable answered decisions with exact proposed values.
    """
    def __init__(self, records):
        self.records = records

    def _candidate(self, owner, project):
        owner_data = _source(owner, 'owner')
        project_data = _source(project, 'project') if project is not None else {}
        config = resolve(owner=owner_data, project=project_data)
        bounded_orders(config)
        return config

    def _effective_candidate(self, owner, project):
        config = self._candidate(owner, project)
        repository = config['project.repository']['value'] or ''
        effective = resolve(owner=_source(owner, 'owner'),
                            project=_source(project, 'project') if project else {},
                            overrides=self.records.config_overrides(repository))
        bounded_orders(effective)
        return effective

    def _founding_specs(self, config):
        profiles = {role: config['profiles.' + role]['value'] for role in ('queen', 'secretary', 'worker')}
        zone = config['voice.zone']['value']
        if not zone:
            raise ConfigError('voice.zone needs a founding value')
        return [('profiles', profiles), ('timezone', zone)]

    def _decision(self, category, value):
        return 'config.' + category + '.' + digest(value)

    def _pin_review(self, owner, project, config):
        repository = config['project.repository']['value'] or ''
        try:
            prior = self.records.latest_pin(repository)
        except RecordError:
            prior = None
        current = self.records.latest_pin() if self.records.has_pins() else None
        signatures = {'owner': owner, 'project': project, 'defaults_digest': defaults_digest(),
                      'orders': {r: render(r, config)['sha256'] for r in ('queen', 'secretary', 'worker')}}
        owner_change = current is not None and current['payload']['owner'] != owner
        if not owner_change:
            if prior is None or all(prior['payload'][k] == v for k, v in signatures.items()):
                return None
        before_project = prior['payload']['project'] if prior else None
        changes = widening(_source(before_project, 'project') if before_project else {},
                           _source(project, 'project') if project else {}, layer='project')
        # Court-owner changes bind the latest global pin, even for a brand new
        # project. Recheck this under the pin transaction to fence racing updates.
        return {'prior_pin': prior['pin_id'] if prior else None,
                'prior_owner_pin': current['pin_id'] if owner_change else None,
                'candidate_digest': digest(signatures), 'project_widening': changes}

    def founding(self, owner, project=None):
        config = self._candidate(owner, project)
        self._effective_candidate(owner, project)
        try:
            self.records.get_task('court.config')
        except RecordError:
            self.records.create_task('court.config', 'monarchy/court', 'queen',
                                     metadata={'kind': 'configuration-confirmation'})
        boxes = []
        for category, value in self._founding_specs(config):
            key = self._decision(category, value)
            decision = self.records.open_decision(key, 'court.config', {
                'kind': 'founding.' + category, 'proposed': value,
                'question': 'Use these role profiles?' if category == 'profiles' else 'Use this timezone?',
                'options': ['Confirm (Recommended)', 'Choose Different Values'], 'generation': 1})
            if decision['state'] == 'answered' and accepted(decision['answer']):
                continue
            boxes.append(decision)
        review = self._pin_review(owner, project, config)
        if review is not None:
            row = self.records.open_decision(self._decision('pin', review), 'court.config', {
                'kind': 'config.pin-review', 'proposed': review, 'generation': 1,
                'question': 'Approve these exact configuration sources and changes?',
                'options': ['Confirm Changes (Recommended)', 'Keep Current Pin']})
            if row['state'] != 'answered' or not accepted(row['answer']): boxes.append(row)
        return boxes

    def _approved(self, config):
        for category, value in self._founding_specs(config):
            row = self.records.get_decision(self._decision(category, value))
            if (row['task_id'] != 'court.config' or row['payload'].get('proposed') != value
                    or row['state'] != 'answered' or not accepted(row['answer'])
                    or not row['owner_message']):
                raise Conflict('founding confirmation is required')

    def pin(self, owner, project=None, *, owner_message, monarchy_revision):
        if (not isinstance(owner_message, str) or not owner_message.strip() or len(owner_message) > 128
                or not isinstance(monarchy_revision, str) or not REVISION.fullmatch(monarchy_revision)):
            raise ConfigError('pin requires owner approval and full toolkit revision')
        config = self._candidate(owner, project)
        repository = config['project.repository']['value'] or ''
        payload = {'owner': owner, 'project': project, 'monarchy_revision': monarchy_revision,
                   'defaults_digest': defaults_digest(), 'effective_digest': digest(config),
                   'orders': {role: render(role, config)['sha256'] for role in ('queen', 'secretary', 'worker')},
                   'owner_message': owner_message}
        def approve():
            self._effective_candidate(owner, project)
            self._approved(config)
            review = self._pin_review(owner, project, config)
            if review is not None:
                row = self.records.get_decision(self._decision('pin', review))
                if (row['state'] != 'answered' or not accepted(row['answer'])
                        or row['payload'].get('proposed') != review or not row['owner_message']):
                    raise Conflict('configuration change needs an answered owner box')
        return self.records.put_pin(digest(payload), repository, payload, approve=approve)

    def show(self, project=''):
        pin = self.records.latest_pin(project)
        payload = pin['payload']
        config = self._candidate(payload['owner'], payload['project'])
        drift = []
        if payload['defaults_digest'] != defaults_digest(): drift.append('defaults')
        if payload['effective_digest'] != digest(config): drift.append('effective-config')
        if payload['orders'] != {r: render(r, config)['sha256'] for r in ('queen', 'secretary', 'worker')}:
            drift.append('standing-orders')
        if self.records.latest_pin()['payload']['owner']['sha256'] != payload['owner']['sha256']:
            drift.append('owner-profile')
        self._approved(config)
        overrides = self.records.config_overrides(project)
        config = resolve(owner=_source(payload['owner'], 'owner'),
                         project=_source(payload['project'], 'project') if payload['project'] else {},
                         overrides=overrides)
        bounded_orders(config)
        return {'pin_id': pin['pin_id'], 'config': config, 'drift': drift, 'held': bool(drift),
                'effective_digest': digest(config), 'sources': {'owner': payload['owner'], 'project': payload['project']},
                'monarchy_revision': payload['monarchy_revision'], 'orders': payload['orders']}

    def require_current(self, project=''):
        view = self.show(project)
        if view['held'] or any(view['config'][k]['value'] for k in ('court.paused', 'court.stopped')):
            raise Conflict('court configuration is held')
        return view

    def override(self, key, value, *, owner_message, project=''):
        if key not in KEYS:
            raise ConfigError('unknown override key')
        if project and KEYS[key]['home'] != 'project':
            raise ConfigError('project cannot set court override')
        load(json.dumps({key: value}), 'overrides')
        def validate():
            # An override must be usable by every affected current project, not
            # merely valid as an isolated JSON fragment. Reads see the tentative
            # insertion under the same transaction; failure rolls it back.
            projects = [r[0] for r in self.records._connection.execute(
                'SELECT DISTINCT project FROM pins LIMIT 1001').fetchall()]
            if len(projects) > 1000: raise ConfigError('court project bound exceeded')
            affected = [project] if project else list(set(projects) | {''})
            for scope in affected:
                overrides = self.records.config_overrides(scope)
                if scope in projects:
                    pin = self.records.latest_pin(scope)['payload']
                    config = resolve(owner=_source(pin['owner'], 'owner'),
                                     project=_source(pin['project'], 'project') if pin['project'] else {},
                                     overrides=overrides)
                else:
                    config = resolve(overrides=overrides)
                bounded_orders(config)
        self.records.put_override(key, value, project, owner_message, validate=validate)

    def bind(self, data):
        """Bind new task context to approved profiles and hash-pinned orders."""
        import copy
        result = copy.deepcopy(data)
        view = self.require_current(result['repository'])
        meta = result['metadata']
        role = meta.get('profile_role', 'worker')
        if role not in {'queen', 'secretary', 'worker'}:
            raise ConfigError('invalid profile role')
        profile = view['config']['profiles.' + role]['value']
        binding = meta['binding']
        if 'profile' in binding and binding['profile'] != profile:
            raise Conflict('requested profile differs from founding confirmation')
        if binding['repo'] != result['repository'] or binding['session_id'] != result['owner']:
            raise Conflict('task binding differs from assignment')
        binding['profile'] = profile
        orders = render(role, view['config'])
        brief = meta.get('brief')
        if not isinstance(brief, str) or not brief.strip():
            raise ConfigError('task brief must be nonempty text')
        if len((orders['text'] + '\n\n' + brief).encode('utf-8')) > MAX_TEXT_BYTES:
            raise ConfigError('standing orders and task brief exceed the delivery budget')
        meta.update(config_pin=view['pin_id'], profile_role=role, orders_sha256=orders['sha256'])
        # Keep exact standing orders with the brief; they are authoritative toolkit
        # text. Project facts are separately encoded as bounded data by render().
        meta['standing_orders'] = orders['text']
        return result


def admission_check(records, task):
    """Called inside operation admission's transaction; holds never stop readback."""
    restrictions = resolve(overrides=records.config_overrides(task['repository']))
    if any(restrictions[k]['value'] for k in ('court.paused', 'court.stopped')):
        raise Conflict('court configuration is held')
    if not records.has_pins():
        if task['metadata'].get('config_pin'):
            raise Conflict('task configuration pin is missing')
        return  # Existing explicit v1 courts remain readable and recoverable.
    view = Preferences(records).require_current(task['repository'])
    meta = task['metadata']
    if meta.get('config_pin') != view['pin_id']:
        raise Conflict('task requires the current approved configuration binding')
    role = meta.get('profile_role')
    if role not in {'queen', 'secretary', 'worker'}:
        raise Conflict('task profile is unconfirmed')
    if meta['binding']['profile'] != view['config']['profiles.' + role]['value']:
        raise Conflict('task profile changed after confirmation')
    if (meta.get('orders_sha256') != render(role, view['config'])['sha256']
            or hashlib.sha256(meta.get('standing_orders', '').encode()).hexdigest() != meta.get('orders_sha256')):
        raise Conflict('task standing orders changed; rebind the brief')
