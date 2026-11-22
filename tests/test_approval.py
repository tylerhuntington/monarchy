"""Internal approval checks use real private records and synthetic source evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monarchy.approval import validate_internal_approval
from monarchy.preferences import Preferences, digest
from monarchy.records import CourtRecords, Conflict, RecordError
from monarchy.supervision import Court


HEAD = 'a' * 40
REPOSITORY = 'example/project'


def source(data, layer):
    raw = json.dumps(data).encode()
    return {'commit': 'b' * 40, 'path': 'owner.json' if layer == 'owner' else '.agents/monarchy.json',
            'blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': raw.decode(), 'layer': layer,
            'repository': REPOSITORY if layer == 'project' else ''}


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'royalty.db'
        self.records = CourtRecords(self.path)
        self.prefs = Preferences(self.records)
        self.court = Court(self.records)
        owner = source({'voice.zone': 'UTC'}, 'owner')
        project = source({'project.repository': REPOSITORY, 'project.required_checks': ['lint', 'unit']}, 'project')
        for box in self.prefs.founding(owner, project):
            self.records.answer_decision(box['decision_id'], {'accept': True},
                                         expected_revision=box['revision'], owner_message='founding-answer')
        self.prefs.pin(owner, project, owner_message='pin-answer', monarchy_revision='c' * 40)
        data = self.prefs.bind({'task_id': 'task', 'repository': REPOSITORY, 'owner': 'builder',
                               'metadata': {'brief': 'Implement an internal maintenance change.',
                                            'binding': {'repo': REPOSITORY, 'session_id': 'builder'}}})
        self.records.create_task(data['task_id'], data['repository'], data['owner'], metadata=data['metadata'])
        self.records.record_event('completion', 'task', 1, 'builder', 'completed',
                                  {'summary': 'Prepared for independent review.', 'source_revision': HEAD})
        self.court.tick('task')
        self.evidence = {'repository': REPOSITORY, 'candidate_id': 'pr-17', 'source_revision': HEAD,
                         'findings': [], 'checks': [
                             {'name': name, 'repository': REPOSITORY, 'source_revision': HEAD,
                              'status': 'completed', 'conclusion': 'success'} for name in ('lint', 'unit')]}
        self.outcome = self.court.verify('task', source_revision=HEAD, observed_revision=HEAD,
                                         reviewer='independent-reviewer', evidence=self.evidence)
        self.review_payload = copy.deepcopy(self.outcome['payload'])
        self.candidate = {'candidate_id': 'pr-17', 'repository': REPOSITORY, 'source_revision': HEAD,
                          'generation': 1, 'outcome_id': self.outcome['outcome_id'],
                          'outcome_digest': digest(self.outcome['payload'])}
        self.decision = self.records.open_decision('approve-internal', 'task', {
            'generation': 1, 'question': 'Approve this internal candidate?',
            'delegation': {'category': 'internal-pr-approval', 'candidate': self.candidate}})
        # Core delegation owns authoritative grant lookup, precedent, floor,
        # revocation and configuration checks inside its answer transaction.
        self.grant = {'grant_id': 'grant-internal', 'project': REPOSITORY,
                      'category': 'internal-pr-approval', 'state': 'delegated'}

    def tearDown(self):
        self.records.close()
        self.tmp.cleanup()

    def validate(self, **kwargs):
        values = {'decision': self.decision, 'candidate': self.candidate,
                  'grant': self.grant, 'current_head': HEAD}
        values.update(kwargs)
        return validate_internal_approval(self.records, **values)

    def replace_review(self, evidence, **changes):
        payload = dict(self.review_payload, evidence=copy.deepcopy(evidence), **changes)
        self.outcome = self.records.record_outcome('review.' + digest(payload), 'task', payload)
        self.candidate = dict(self.candidate, outcome_id=self.outcome['outcome_id'],
                              outcome_digest=digest(payload))
        self.decision = self.records.open_decision('approval.' + digest(self.candidate), 'task', {
            'generation': 1, 'question': 'Approve the updated internal candidate?',
            'delegation': {'category': 'internal-pr-approval', 'candidate': self.candidate}})

    def proposal(self, candidate=None, **changes):
        candidate = self.candidate if candidate is None else candidate
        payload = dict(self.decision['payload'], **changes)
        payload['delegation'] = dict(payload.get('delegation', {}), candidate=candidate)
        return self.records.open_decision('proposal.' + digest(payload), 'task', payload)

    def test_verified_current_head_returns_exact_readonly_evidence_binding(self):
        before = copy.deepcopy((self.decision, self.candidate, self.grant))
        changes = self.records._connection.total_changes
        result = self.validate()
        self.assertEqual(result, {
            'decision_id': 'approve-internal', 'decision_revision': 1, 'grant_id': 'grant-internal',
            'task_id': 'task', 'generation': 1, 'candidate_id': 'pr-17', 'repository': REPOSITORY,
            'source_revision': HEAD, 'outcome_id': self.outcome['outcome_id'],
            'outcome_digest': self.candidate['outcome_digest'], 'required_checks': ['lint', 'unit']})
        self.assertEqual(result, self.validate())
        self.assertEqual(self.records._connection.total_changes, changes)
        self.assertEqual((self.decision, self.candidate, self.grant), before)
        result['required_checks'].clear()
        self.assertEqual(self.validate()['required_checks'], ['lint', 'unit'])

    def test_required_checks_cannot_be_missing_duplicate_or_non_green(self):
        original = copy.deepcopy(self.evidence)
        cases = [[], original['checks'][:1], original['checks'] + [original['checks'][0]]]
        for field, value in [('status', 'queued'), ('status', 'in_progress'),
                             ('conclusion', 'failure'), ('conclusion', 'neutral'),
                             ('conclusion', 'skipped'), ('conclusion', True)]:
            checks = copy.deepcopy(original['checks'])
            checks[1][field] = value
            cases.append(checks)
        for checks in cases:
            with self.subTest(checks=checks):
                self.replace_review(dict(original, checks=checks))
                with self.assertRaises(RecordError): self.validate()

    def test_evidence_requires_matching_candidate_and_explicitly_resolved_findings(self):
        cases = []
        for field, value in [('repository', 'example/other'), ('candidate_id', 'pr-18'),
                             ('source_revision', 'f' * 40), ('findings', None),
                             ('findings', [{'id': 'review-1', 'status': 'open'}]),
                             ('findings', [{'id': 'review-1', 'status': 'waived'}]),
                             ('findings', [{'id': 'review-1', 'status': 'resolved'}] * 2)]:
            cases.append(dict(self.evidence, **{field: value}))
        cases.append({key: value for key, value in self.evidence.items() if key != 'findings'})
        cases.append(dict(self.evidence, unexpected='private-marker'))
        for evidence in cases:
            with self.subTest(fields=sorted(evidence)):
                self.replace_review(evidence)
                with self.assertRaises(RecordError): self.validate()
        self.replace_review(dict(self.evidence, findings=[{'id': 'review-1', 'status': 'resolved'}]))
        self.assertEqual(self.validate()['source_revision'], HEAD)

    def test_new_review_or_untriaged_report_invalidates_older_eligibility(self):
        old_candidate, old_decision = copy.deepcopy(self.candidate), copy.deepcopy(self.decision)
        self.replace_review(dict(self.evidence, findings=[{'id': 'finding-1', 'status': 'resolved'}]))
        with self.assertRaises(Conflict): self.validate(candidate=old_candidate, decision=old_decision)
        self.assertEqual(self.validate()['outcome_id'], self.outcome['outcome_id'])
        self.records.record_event('late-failure', 'task', 1, 'builder', 'failed',
                                  {'summary': 'A later failure needs triage.'})
        with self.assertRaises(Conflict): self.validate()
        self.court.tick('task')
        with self.assertRaises(Conflict): self.validate()

    def test_malformed_decision_context_and_boolean_generation_are_rejected_safely(self):
        for context in (None, [], 'private-context'):
            decision = self.records.open_decision('malformed.' + digest(context), 'task', {
                'generation': 1, 'delegation': context})
            with self.assertRaises(RecordError): self.validate(decision=decision)
        with self.assertRaises(RecordError): self.validate(decision={})
        decision = self.proposal(generation=True)
        with self.assertRaises(RecordError): self.validate(decision=decision)

    def test_current_head_is_required_fresh_and_full(self):
        with self.assertRaises(TypeError):
            validate_internal_approval(self.records, self.decision, self.candidate, self.grant)
        for head in (None, True, HEAD[:12], HEAD.upper(), 'main', 'd' * 40):
            with self.subTest(head=head):
                with self.assertRaises(RecordError): self.validate(current_head=head)

    def test_each_check_is_bound_to_repository_and_full_source(self):
        for field, value in [('repository', 'example/other'), ('source_revision', 'd' * 40),
                             ('source_revision', HEAD[:8]), ('name', 'missing-required-check')]:
            evidence = copy.deepcopy(self.evidence)
            evidence['checks'][0][field] = value
            self.replace_review(evidence)
            with self.assertRaises(RecordError): self.validate()

    def test_grant_scope_category_and_state_are_required(self):
        for field, value in [('state', 'ask'), ('state', 'ask-again-later'), ('state', 'revoked'),
                             ('project', 'example/other'), ('category', 'ci-rerun-at-approved-head'),
                             ('grant_id', '')]:
            with self.subTest(field=field, value=value):
                with self.assertRaises(RecordError): self.validate(grant=dict(self.grant, **{field: value}))
        with self.assertRaises(RecordError): self.validate(grant={})

    def test_candidate_and_outcome_cannot_be_substituted_or_partially_identified(self):
        for field, value in [('candidate_id', 'pr-18'), ('repository', 'example/other'),
                             ('source_revision', HEAD[:8]), ('generation', True),
                             ('outcome_digest', self.candidate['outcome_digest'][:12]),
                             ('outcome_id', 'missing-outcome')]:
            candidate = dict(self.candidate, **{field: value})
            decision = self.proposal(candidate)
            with self.subTest(field=field):
                with self.assertRaises(RecordError): self.validate(candidate=candidate, decision=decision)
        with self.assertRaises(RecordError): self.validate(candidate=dict(self.candidate, extra=True))

    def test_outcome_must_be_verified_and_independent(self):
        for changes in ({'kind': 'completed'}, {'reviewer': 'builder'}, {'reviewer': ''},
                        {'generation': True}, {'generation': 2}, {'source_revision': 'd' * 40}):
            self.replace_review(self.evidence, **changes)
            with self.subTest(changes=changes):
                with self.assertRaises(RecordError): self.validate()

    def test_another_tasks_verification_cannot_qualify_this_task(self):
        self.records.create_task('other-task', REPOSITORY, 'other-builder')
        row = self.records.record_outcome('other-review', 'other-task', self.outcome['payload'])
        candidate = dict(self.candidate, outcome_id=row['outcome_id'])
        with self.assertRaises(Conflict): self.validate(candidate=candidate, decision=self.proposal(candidate))

    def test_changed_decision_revision_or_assignment_invalidates_replay(self):
        self.records.revise_decision(self.decision['decision_id'], self.decision['payload'], expected_revision=1)
        with self.assertRaises(Conflict): self.validate()
        self.decision = self.records.get_decision(self.decision['decision_id'])
        self.assertEqual(self.validate()['decision_revision'], 2)
        self.records.assign_task('task', 'replacement-builder', expected_generation=1)
        with self.assertRaises(Conflict): self.validate()

    def test_an_owner_answer_cannot_be_replayed_as_a_grant_answer(self):
        self.records.answer_decision(self.decision['decision_id'], {'accept': True},
                                     expected_revision=1, owner_message='direct-owner-answer')
        self.decision = self.records.get_decision(self.decision['decision_id'])
        with self.assertRaises(Conflict): self.validate()

    def test_pause_holds_existing_internal_approval_evidence(self):
        self.prefs.override('court.paused', True, owner_message='pause-before-approval')
        with self.assertRaises(Conflict): self.validate()

    def test_configuration_change_requires_a_fresh_task_binding(self):
        owner = source({'voice.zone': 'UTC'}, 'owner')
        project = source({'project.repository': REPOSITORY,
                          'project.required_checks': ['lint', 'unit', 'security']}, 'project')
        for box in self.prefs.founding(owner, project):
            self.records.answer_decision(box['decision_id'], {'accept': True},
                                         expected_revision=box['revision'], owner_message='changed-check-policy')
        self.prefs.pin(owner, project, owner_message='pin-changed-policy', monarchy_revision='c' * 40)
        with self.assertRaises(Conflict): self.validate()

    def test_check_and_finding_collections_are_bounded(self):
        evidence = copy.deepcopy(self.evidence)
        evidence['checks'].extend(dict(evidence['checks'][0], name='extra-' + str(i)) for i in range(99))
        self.replace_review(evidence)
        with self.assertRaises(RecordError): self.validate()
        evidence = dict(self.evidence, findings=[{'id': 'finding-' + str(i), 'status': 'resolved'} for i in range(101)])
        self.replace_review(evidence)
        with self.assertRaises(RecordError): self.validate()

    def test_safe_diagnostics_do_not_echo_private_evidence(self):
        marker = 'private-marker-value'
        evidence = dict(self.evidence, **{marker: marker})
        self.replace_review(evidence)
        with self.assertRaises(RecordError) as raised: self.validate()
        self.assertNotIn(marker, str(raised.exception))

    def test_record_reopen_reproduces_binding_without_sources_or_network(self):
        expected = self.validate()
        self.records.close()
        self.records = CourtRecords(self.path)
        self.assertEqual(self.validate(), expected)

    def test_history_scan_holds_instead_of_silently_skipping_records(self):
        for index in range(98):
            self.records.record_outcome('history-' + str(index), 'task', {'generation': 0, 'kind': 'historical'})
        with patch('monarchy.approval.MAX_OUTCOMES', 100):
            with self.assertRaises(RecordError): self.validate()

    def test_unconfigured_project_checks_cannot_be_treated_as_all_green(self):
        with CourtRecords(Path(self.tmp.name) / 'no-checks.db') as records:
            prefs = Preferences(records)
            owner = source({'voice.zone': 'UTC'}, 'owner')
            project = source({'project.repository': REPOSITORY}, 'project')
            for box in prefs.founding(owner, project):
                records.answer_decision(box['decision_id'], {'accept': True},
                                        expected_revision=box['revision'], owner_message='founding-answer')
            prefs.pin(owner, project, owner_message='pin-answer', monarchy_revision='c' * 40)
            task = prefs.bind(self.records.get_task('task'))
            records.create_task('task', REPOSITORY, 'builder', metadata=task['metadata'])
            records.record_event('completion', 'task', 1, 'builder', 'completed',
                                 {'summary': 'Ready for review.', 'source_revision': HEAD})
            court = Court(records)
            court.tick('task')
            outcome = court.verify('task', source_revision=HEAD, observed_revision=HEAD,
                                   reviewer='independent-reviewer', evidence=self.evidence)
            self.assertEqual(outcome['outcome_id'], self.candidate['outcome_id'])
            decision = records.open_decision('approve-internal', 'task', self.decision['payload'])
            with self.assertRaises(Conflict):
                validate_internal_approval(records, decision, self.candidate, self.grant, current_head=HEAD)
