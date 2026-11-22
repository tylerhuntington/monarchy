"""Source-bound evidence validation for delegated internal PR approval.

The delegation layer must resolve the current grant, enforce its scope,
precedent, invariant floor and configuration binding, then call this validator
inside the same answer/admission transaction. The returned evidence binding is
not an authority grant, a merge instruction or an external action.

This module does not fetch GitHub or authenticate callers. A trusted adapter must
read the actual current head anew before every answer and admission; repeating
the stored candidate head is not a fresh observation. Review/check evidence is
also supplied through the trusted local record API, not verified remotely here.
"""
from .preferences import Preferences, REVISION, admission_check, digest
from .records import Conflict, RecordError, _identifier, _payload


CANDIDATE_FIELDS = frozenset({'candidate_id', 'repository', 'source_revision',
                              'generation', 'outcome_id', 'outcome_digest'})
CHECK_FIELDS = frozenset({'name', 'repository', 'source_revision', 'status', 'conclusion'})
EVIDENCE_FIELDS = frozenset({'repository', 'candidate_id', 'source_revision', 'findings', 'checks'})
MAX_OUTCOMES = 10000


def _revision(value):
    if type(value) is not str or not REVISION.fullmatch(value):
        raise RecordError('internal approval requires a full source revision')


def _latest_verification(records, task, outcome_id):
    if records.list_events(task_id=task['task_id'], processed=False, limit=1):
        raise Conflict('internal approval holds until new reports are triaged')
    latest = None
    for offset in range(0, MAX_OUTCOMES, 100):
        rows = records.list_outcomes(task_id=task['task_id'], limit=100, offset=offset)
        for row in rows:
            if row['payload'].get('generation') == task['generation']:
                latest = row
        if len(rows) < 100:
            break
    else:
        raise RecordError('internal approval outcome history exceeds its read bound')
    if latest is None or latest['outcome_id'] != outcome_id:
        raise Conflict('internal approval requires the latest verification of this assignment')


def _evidence(evidence, candidate):
    if type(evidence) is not dict or set(evidence) != EVIDENCE_FIELDS:
        raise RecordError('internal approval requires complete typed review evidence')
    if any(evidence[key] != candidate[key] for key in ('repository', 'candidate_id', 'source_revision')):
        raise Conflict('internal approval evidence belongs to a different candidate or source')
    findings = evidence['findings']
    if type(findings) is not list or len(findings) > 100:
        raise RecordError('internal approval findings must be a bounded explicit list')
    seen = set()
    for finding in findings:
        if type(finding) is not dict or set(finding) != {'id', 'status'}:
            raise RecordError('internal approval finding evidence is malformed')
        identity = _identifier(finding['id'], 'finding_id')
        if identity in seen or finding['status'] != 'resolved':
            raise Conflict('internal approval requires distinct resolved findings')
        seen.add(identity)


def _checks(evidence, required, candidate):
    checks = evidence.get('checks') if type(evidence) is dict else None
    if not required or type(checks) is not list or not 1 <= len(checks) <= 100:
        raise Conflict('internal approval requires configured checks and complete check evidence')
    seen = set()
    for check in checks:
        if type(check) is not dict or set(check) != CHECK_FIELDS:
            raise RecordError('internal approval check evidence is malformed')
        name = check['name']
        if (type(name) is not str or not name.strip() or len(name) > 256
                or any(ord(char) < 32 or ord(char) == 127 for char in name) or name in seen):
            raise RecordError('internal approval check names must be bounded and distinct')
        if (check['repository'] != candidate['repository']
                or check['source_revision'] != candidate['source_revision']
                or check['status'] != 'completed' or check['conclusion'] != 'success'):
            raise Conflict('internal approval checks must be green at the exact source')
        seen.add(name)
    if not set(required) <= seen:
        raise Conflict('internal approval is missing required check results')


def validate_internal_approval(records, decision, candidate, grant, *, current_head):
    """Return a deterministic evidence binding; create or answer no record."""
    for value in (decision, candidate, grant):
        _payload(value)
    _revision(current_head)
    if set(candidate) != CANDIDATE_FIELDS:
        raise RecordError('internal approval requires a complete candidate')
    _identifier(candidate['candidate_id'], 'candidate_id')
    _identifier(candidate['outcome_id'], 'outcome_id')
    _revision(candidate['source_revision'])
    current = records.get_decision(_identifier(decision.get('decision_id'), 'decision_id'))
    if digest(current) != digest(decision):
        raise Conflict('internal approval decision changed')
    task = records.get_task(decision['task_id'])
    context = decision['payload'].get('delegation', {})
    if (type(context) is not dict or context.get('category') != 'internal-pr-approval'
            or digest(context.get('candidate')) != digest(candidate)
            or candidate['repository'] != task['repository']
            or type(candidate['generation']) is not int or candidate['generation'] != task['generation']
            or type(decision['payload'].get('generation')) is not int
            or decision['payload']['generation'] != task['generation']
            or candidate['source_revision'] != current_head):
        raise Conflict('internal approval candidate no longer matches its decision and source')
    _identifier(grant.get('grant_id'), 'grant_id')
    if (grant.get('state') != 'delegated' or grant.get('category') != 'internal-pr-approval'
            or grant.get('project') != task['repository']):
        raise Conflict('internal approval requires an applicable delegated grant')
    if decision['state'] not in {'pending', 'answered'}:
        raise Conflict('internal approval decision is no longer active')
    if decision['state'] == 'answered' and (
            decision.get('answered_by') != 'grant:' + grant['grant_id']
            or type(decision['answer']) is not dict or set(decision['answer']) != {'accept'}
            or decision['answer']['accept'] is not True):
        raise Conflict('internal approval answer has different authority or disposition')
    view = Preferences(records).require_current(task['repository'])
    admission_check(records, task)
    outcome = records.get_outcome(candidate['outcome_id'])
    payload = outcome['payload']
    if (outcome['task_id'] != task['task_id'] or payload.get('kind') != 'verified'
            or type(payload.get('generation')) is not int or payload['generation'] != task['generation']
            or payload.get('source_revision') != current_head
            or digest(payload) != candidate['outcome_digest']
            or payload.get('reviewer') == task['owner']):
        raise Conflict('internal approval requires matching independent verification')
    _identifier(payload.get('reviewer'), 'reviewer')
    _latest_verification(records, task, outcome['outcome_id'])
    required = view['config']['project.required_checks']['value']
    _evidence(payload.get('evidence'), candidate)
    _checks(payload.get('evidence'), required, candidate)
    return {'decision_id': decision['decision_id'], 'decision_revision': decision['revision'],
            'grant_id': grant['grant_id'], 'task_id': task['task_id'], 'generation': task['generation'],
            'candidate_id': candidate['candidate_id'], 'repository': task['repository'],
            'source_revision': current_head, 'outcome_id': outcome['outcome_id'],
            'outcome_digest': candidate['outcome_digest'], 'required_checks': list(required)}
