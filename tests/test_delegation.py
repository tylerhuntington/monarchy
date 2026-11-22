"""Grant authority is exact, revocable and separate from owner answers."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from monarchy.delegation import Delegation, TAXONOMY, STATES, PERMITTED_ACTIONS
from monarchy.config import NEVER_DELEGABLE
from monarchy.records import CourtRecords, Conflict, RecordError
from monarchy.supervision import Court


PROJECT = 'example/project'
CATEGORY = 'ci-rerun-at-approved-head'
WORKER = '22222222-2222-4222-8222-222222222222'
BINDING = {'session_id': WORKER, 'workspace_id': '11111111-1111-4111-8111-111111111111',
           'repo': PROJECT, 'profile': {'agent': 'codex', 'model': 'chosen-model',
                                      'effort': 'high', 'fast_mode': False}}


class DelegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'royalty.db'
        self.records = CourtRecords(self.path)
        self.delegation = Delegation(self.records)
        self.records.create_task('task', PROJECT, WORKER, metadata={'binding': BINDING})

    def tearDown(self):
        self.records.close()
        self.temp.cleanup()

    def context(self):
        return {'category': CATEGORY, 'actions': ['rerun-approved-ci'],
                'scope': {'workflow': 'required-checks'}, 'classification_complete': True}

    def precedent(self, name='precedent', context=None):
        self.records.open_decision(name, 'task', {'generation': 1, 'question': 'Rerun this approved check?',
            'delegation': self.context() if context is None else context})
        return self.records.answer_decision(name, {'accept': True}, expected_revision=1,
                                             owner_message='owner-' + name)

    def grant(self, name='grant-request'):
        self.precedent()
        box = self.delegation.propose(PROJECT, CATEGORY, 'delegated', owner_message=name,
                                     precedents=[{'decision_id': 'precedent', 'revision': 1}])
        self.records.answer_decision(box['decision_id'], {'accept': True}, expected_revision=1,
                                     owner_message='owner-' + name)
        return self.delegation.apply(box['decision_id'])

    def target(self, name='target', **changes):
        context = self.context()
        context.update(precedent={'decision_id': 'precedent', 'revision': 1},
                       new_risk=False, unresolved_flags=[])
        context.update(changes)
        return self.records.open_decision(name, 'task',
            {'generation': 1, 'question': 'Rerun this matching check?', 'delegation': context})

    def test_default_ask_and_taxonomy_never_create_authority(self):
        self.assertEqual(self.delegation.state(PROJECT, CATEGORY)['state'], 'ask')
        self.assertIsNone(self.delegation.state(PROJECT, CATEGORY)['grant_id'])
        self.assertEqual(set(STATES), {'ask', 'delegated', 'ask-again-later'})
        self.assertEqual(len(TAXONOMY), 15)
        self.assertEqual(set(PERMITTED_ACTIONS), set(TAXONOMY))
        self.assertTrue(set(NEVER_DELEGABLE).isdisjoint(TAXONOMY))
        self.target()
        with self.assertRaises(Conflict):
            self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id='missing')
        self.assertEqual(self.records.get_decision('target')['state'], 'pending')

    def test_apply_needs_exact_current_owner_answer_and_replays_without_new_grant(self):
        self.precedent()
        box = self.delegation.propose(PROJECT, CATEGORY, 'delegated', owner_message='request',
                                     precedents=[{'decision_id': 'precedent', 'revision': 1}])
        with self.assertRaises(Conflict): self.delegation.apply(box['decision_id'])
        self.records.answer_decision(box['decision_id'], {'accept': True}, expected_revision=1,
                                     owner_message='actual-owner-answer')
        grant = self.delegation.apply(box['decision_id'])
        self.assertEqual(grant['state'], 'delegated')
        self.assertEqual(self.delegation.apply(box['decision_id']), grant)
        self.assertEqual(self.delegation.propose(PROJECT, CATEGORY, 'delegated', owner_message='request',
            precedents=[{'decision_id': 'precedent', 'revision': 1}]), self.records.get_decision(box['decision_id']))
        with self.assertRaises(Conflict):
            self.delegation.propose(PROJECT, CATEGORY, 'ask', owner_message='request')

    def test_numeric_or_extra_accept_fields_never_apply(self):
        for index, answer in enumerate([{'accept': 1}, {'accept': True, 'extra': True}, {'accept': False}]):
            box = self.delegation.propose(PROJECT, CATEGORY, 'ask-again-later', owner_message='request-' + str(index))
            self.records.answer_decision(box['decision_id'], answer, expected_revision=1,
                                         owner_message='answer-' + str(index))
            with self.assertRaises(Conflict): self.delegation.apply(box['decision_id'])
        self.assertEqual(self.delegation.state(PROJECT, CATEGORY)['state'], 'ask')

    def test_delegated_answer_preserves_grant_and_has_no_owner_message(self):
        grant = self.grant()
        self.target()
        row = self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])
        self.assertEqual(row['answered_by'], 'grant:' + grant['grant_id'])
        self.assertIsNone(row['owner_message'])
        self.assertEqual(self.delegation.answer('target', {'accept': True}, expected_revision=1,
                                              grant_id=grant['grant_id']), row)
        with self.assertRaises(Conflict):
            self.records.answer_decision('target', {'accept': True}, expected_revision=1,
                                         owner_message='pretend-owner')
        with CourtRecords(self.path) as reopened:
            self.assertEqual(reopened.get_decision('target'), row)

    def test_action_answer_precedent_risk_and_scope_must_match(self):
        grant = self.grant()
        invalid = [({'new_risk': True}, {'accept': True}),
                   ({'new_risk': 0}, {'accept': True}),
                   ({'unresolved_flags': ['unresolved']}, {'accept': True}),
                   ({'classification_complete': False}, {'accept': True}),
                   ({'scope': {'workflow': 'another-check'}}, {'accept': True}),
                   ({'actions': ['unknown-action']}, {'accept': True}),
                   ({'actions': ['rerun-approved-ci', 'production-approval-or-rollout']}, {'accept': True}),
                   ({'precedent': {'decision_id': 'other', 'revision': 1}}, {'accept': True}),
                   ({}, {'accept': True, 'expanded_scope': True})]
        for index, (changes, answer) in enumerate(invalid):
            name = 'target-' + str(index)
            self.target(name, **changes)
            with self.subTest(changes=changes, answer=answer), self.assertRaises((Conflict, RecordError)):
                self.delegation.answer(name, answer, expected_revision=1, grant_id=grant['grant_id'])
            self.assertEqual(self.records.get_decision(name)['state'], 'pending')

    def test_floor_cannot_be_proposed_or_hidden_in_broader_actions(self):
        for category in NEVER_DELEGABLE:
            with self.subTest(category=category), self.assertRaises((Conflict, RecordError)):
                self.delegation.propose(PROJECT, category, 'delegated', owner_message='forbidden-' + category)
        context = self.context()
        context.update(category='backlog-cleanup-with-notifications',
                       actions=['clean-backlog-without-contact', 'contacting-or-naming-people'])
        self.precedent(context=context)
        with self.assertRaises((Conflict, RecordError)):
            self.delegation.propose(PROJECT, context['category'], 'delegated', owner_message='broader',
                                     precedents=[{'decision_id': 'precedent', 'revision': 1}])

    def test_revocation_blocks_new_answers_and_cannot_be_undone_by_apply_replay(self):
        grant = self.grant()
        self.target()
        revoked = self.delegation.revoke(PROJECT, CATEGORY, owner_message='one-line-revoke')
        self.assertEqual((revoked['state'], revoked['grant_id']), ('ask', None))
        self.assertEqual(self.delegation.revoke(PROJECT, CATEGORY, owner_message='one-line-revoke'), revoked)
        box = next(row for row in self.records.list_decisions() if row['payload'].get('kind') == 'delegation.proposal')
        self.delegation.apply(box['decision_id'])
        self.assertEqual(self.delegation.state(PROJECT, CATEGORY), revoked)
        with self.assertRaises(Conflict):
            self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])

    def test_intervening_revocation_invalidates_an_unapplied_proposal(self):
        self.precedent()
        box = self.delegation.propose(PROJECT, CATEGORY, 'delegated', owner_message='request',
                                     precedents=[{'decision_id': 'precedent', 'revision': 1}])
        self.records.answer_decision(box['decision_id'], {'accept': True}, expected_revision=1,
                                     owner_message='grant-answer')
        self.delegation.revoke(PROJECT, CATEGORY, owner_message='revoke-before-apply')
        with self.assertRaises(Conflict): self.delegation.apply(box['decision_id'])

    def test_owner_only_boxes_cannot_use_a_grant_even_with_matching_classification(self):
        grant = self.grant()
        for index, kind in enumerate(('founding.profiles', 'founding.timezone', 'config.pin-review',
                                      'control.resume', 'control.model', 'delegation.proposal')):
            target = self.target('protected-' + str(index))
            payload = {**target['payload'], 'kind': kind}
            self.records.revise_decision(target['decision_id'], payload, expected_revision=1)
            with self.subTest(kind=kind), self.assertRaises(Conflict):
                self.delegation.answer(target['decision_id'], {'accept': True},
                                       expected_revision=2, grant_id=grant['grant_id'])

    def test_grant_is_project_scoped_and_cannot_become_a_precedent(self):
        grant = self.grant()
        self.target()
        self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])
        with self.assertRaises(Conflict):
            self.delegation.propose(PROJECT, CATEGORY, 'delegated', owner_message='chain-grant',
                                     precedents=[{'decision_id': 'target', 'revision': 1}])
        with self.assertRaises(Conflict):
            self.delegation.propose('example/other', CATEGORY, 'delegated', owner_message='other-project',
                                     precedents=[{'decision_id': 'precedent', 'revision': 1}])

    def test_prepared_relay_contains_actual_authority_and_is_blocked_after_revoke(self):
        grant = self.grant()
        self.target()
        self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])
        operation = Court(self.records).prepare_answer('target')
        message = json.loads(operation['request']['text'])
        self.assertEqual(message['answered_by'], 'grant:' + grant['grant_id'])
        self.assertIsNone(message['owner_message'])
        self.delegation.revoke(PROJECT, CATEGORY, owner_message='revoke-before-relay')
        with self.assertRaises(Conflict):
            self.records.set_operation_state(operation['operation_id'], 'in_flight', expected_state='prepared')
        self.assertEqual(self.records.get_operation(operation['operation_id'])['state'], 'prepared')

    def test_uncertain_relay_reconciles_after_revoke(self):
        grant = self.grant()
        self.target()
        self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])
        operation = Court(self.records).prepare_answer('target')
        self.records.set_operation_state(operation['operation_id'], 'in_flight', expected_state='prepared')
        self.records.set_operation_state(operation['operation_id'], 'unknown', expected_state='in_flight')
        self.delegation.revoke(PROJECT, CATEGORY, owner_message='revoke-after-uncertain')
        reconciled = self.records.set_operation_state(operation['operation_id'], 'confirmed',
            expected_state='unknown', result={'native_readback': 'same-operation'})
        self.assertEqual(reconciled['state'], 'confirmed')

    def test_followup_requires_an_owner_precedent_and_keeps_the_selected_state(self):
        self.precedent()
        box = self.delegation.followup('precedent', owner_message='followup-request')
        self.assertEqual(set(box['payload']['choices']), set(STATES))
        self.assertEqual(len(box['payload']['options']), 3)
        self.records.answer_decision(box['decision_id'], {'state': 'ask-again-later'}, expected_revision=1,
                                     owner_message='followup-answer')
        row = self.delegation.apply(box['decision_id'])
        self.assertEqual((row['state'], row['grant_id']), ('ask-again-later', None))

    def test_followup_cannot_accept_confirmation_or_unlisted_state(self):
        self.precedent()
        for index, answer in enumerate([{'accept': True}, {'state': 'unlisted'},
                                        {'state': 'delegated', 'extra': True}]):
            box = self.delegation.followup('precedent', owner_message='followup-' + str(index))
            self.records.answer_decision(box['decision_id'], answer, expected_revision=1,
                                         owner_message='followup-answer-' + str(index))
            with self.assertRaises(Conflict): self.delegation.apply(box['decision_id'])
        self.assertEqual(self.delegation.state(PROJECT, CATEGORY)['state'], 'ask')

    def test_custom_category_cannot_skip_internal_approval_evidence_gate(self):
        from monarchy.delegation import _policy
        policy = _policy(self.records, PROJECT)
        policy['categories'].add('custom-review')
        context = self.context()
        context.update(category='custom-review', actions=['approve-internal-pr'])
        self.precedent(context=context)
        with patch('monarchy.delegation._policy', return_value=policy), self.assertRaises(Conflict):
            self.delegation.propose(PROJECT, 'custom-review', 'delegated', owner_message='custom-grant',
                                     precedents=[{'decision_id': 'precedent', 'revision': 1}])

    def test_custom_category_lists_only_actions_it_can_actually_use(self):
        from monarchy.delegation import _policy
        policy = _policy(self.records, PROJECT)
        policy['categories'].add('custom-review')
        with patch('monarchy.delegation._policy', return_value=policy):
            listing = self.delegation.categories(PROJECT)['permitted_actions']
        self.assertNotIn('approve-internal-pr', listing['custom-review'])
        self.assertEqual(listing['internal-pr-approval'], ['approve-internal-pr'])

    def test_custom_category_cannot_alias_a_project_forbidden_category(self):
        from monarchy.delegation import _policy
        policy = _policy(self.records, PROJECT)
        policy['categories'].add('custom-plan')
        policy['never'].add('plan-or-date-acceptance')
        context = self.context()
        context.update(category='custom-plan', actions=['accept-internal-plan'])
        self.precedent(context=context)
        with patch('monarchy.delegation._policy', return_value=policy):
            with self.assertRaises(Conflict):
                self.delegation.propose(PROJECT, 'custom-plan', 'delegated', owner_message='alias-grant',
                                         precedents=[{'decision_id': 'precedent', 'revision': 1}])
            self.assertNotIn('accept-internal-plan',
                             self.delegation.categories(PROJECT)['permitted_actions']['custom-plan'])

    def test_boolean_or_float_generation_cannot_be_answered_under_a_grant(self):
        grant = self.grant()
        for index, generation in enumerate((True, 1.0)):
            target = self.target('malformed-generation-' + str(index))
            self.records.revise_decision(target['decision_id'],
                {**target['payload'], 'generation': generation}, expected_revision=1)
            with self.subTest(generation=generation), self.assertRaises(RecordError):
                self.delegation.answer(target['decision_id'], {'accept': True},
                    expected_revision=2, grant_id=grant['grant_id'])
            self.assertEqual(self.records.get_decision(target['decision_id'])['state'], 'pending')

    def test_grant_proposal_answered_under_a_grant_never_applies(self):
        box = self.delegation.propose(PROJECT, CATEGORY, 'ask-again-later', owner_message='bad-authority')
        self.records.answer_decision(box['decision_id'], {'accept': True}, expected_revision=1,
                                     owner_message='actual-owner')
        self.records._connection.execute("UPDATE decisions SET answered_by='grant:pretend',owner_message=NULL "
                                        'WHERE decision_id=?', (box['decision_id'],))
        with self.assertRaises(Conflict): self.delegation.apply(box['decision_id'])

    def test_changed_config_or_precedent_holds_an_existing_grant(self):
        grant = self.grant()
        self.target()
        from monarchy.preferences import Preferences
        Preferences(self.records).override('voice.forbidden_characters', ['!'], owner_message='changed-config')
        with self.assertRaises(Conflict):
            self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])
        # Revocation stays possible even when configuration no longer matches.
        self.assertEqual(self.delegation.revoke(PROJECT, CATEGORY, owner_message='revoke-stale')['state'], 'ask')

    def test_revised_precedent_cannot_reuse_an_earlier_grant(self):
        grant = self.grant()
        self.target()
        original = self.records.get_decision('precedent')
        self.records.revise_decision('precedent', {**original['payload'], 'question': 'Changed scope?'},
                                     expected_revision=1)
        with self.assertRaises(Conflict):
            self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])

    def test_existing_owner_relay_survives_added_provenance_without_new_identity(self):
        self.precedent()
        court = Court(self.records)
        operation = court.prepare_answer('precedent')
        request = operation['request']
        message = json.loads(request['text'])
        self.assertEqual(message.pop('answered_by'), 'owner')
        request['text'] = json.dumps(message, sort_keys=True)
        self.records._connection.execute('UPDATE operations SET request=? WHERE operation_id=?',
            (json.dumps(request, sort_keys=True, separators=(',', ':')), operation['operation_id']))
        self.assertEqual(court.prepare_answer('precedent')['request'], request)

    def test_answer_and_revocation_are_serialized(self):
        grant = self.grant()
        self.target()
        barrier, errors = threading.Barrier(2), []
        def revoke():
            try:
                with CourtRecords(self.path) as other:
                    barrier.wait()
                    Delegation(other).revoke(PROJECT, CATEGORY, owner_message='racing-revoke')
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=revoke)
        thread.start()
        barrier.wait()
        try:
            self.delegation.answer('target', {'accept': True}, expected_revision=1, grant_id=grant['grant_id'])
        except Conflict:
            pass
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.delegation.state(PROJECT, CATEGORY)['state'], 'ask')
        if self.records.get_decision('target')['state'] == 'answered':
            with self.assertRaises(Conflict): Court(self.records).prepare_answer('target')

    def test_v4_owner_provenance_migrates_without_relabeling_pending_decisions(self):
        original = self.precedent()
        revised = self.precedent('revised')
        self.records.revise_decision('revised', {**revised['payload'], 'question': 'A fresh owner decision?'},
                                     expected_revision=1)
        self.target()
        self.records.close()
        with sqlite3.connect(self.path) as old:
            old.execute('ALTER TABLE decisions RENAME TO decisions_v5')
            old.execute("""CREATE TABLE decisions (
                decision_id TEXT NOT NULL, revision INTEGER NOT NULL,
                task_id TEXT NOT NULL REFERENCES tasks(task_id), payload TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','answered','superseded')),
                answer TEXT, owner_message TEXT, created_at TEXT NOT NULL, answered_at TEXT,
                PRIMARY KEY(decision_id,revision))""")
            old.execute('INSERT INTO decisions SELECT decision_id,revision,task_id,payload,state,answer,owner_message,created_at,answered_at FROM decisions_v5')
            old.execute('DROP TABLE decisions_v5')
            old.execute('DROP TABLE delegation_events')
            for identity, owner_ref, state in [('missing-owner', None, 'answered'),
                                                ('malformed-owner', 'not an identifier', 'answered'),
                                                ('empty-owner', '', 'answered'),
                                                ('invalid-pending', 'owner-ref', 'pending')]:
                old.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?)',
                            (identity, 1, 'task', '{}', state, '{"accept":true}', owner_ref,
                             '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'))
            old.execute('PRAGMA user_version=4')
        self.records = CourtRecords(self.path)
        self.assertEqual(self.records.get_decision('precedent')['answered_by'], 'owner')
        self.assertEqual(self.records.get_decision('precedent')['answer'], original['answer'])
        self.assertIsNone(self.records.get_decision('target')['answered_by'])
        self.assertEqual(self.records.get_decision('revised', 1)['answered_by'], 'owner')
        self.assertIsNone(self.records.get_decision('revised', 2)['answered_by'])
        for identity in ('missing-owner', 'malformed-owner', 'empty-owner', 'invalid-pending'):
            raw = self.records._connection.execute('SELECT answered_by FROM decisions WHERE decision_id=?',
                                                    (identity,)).fetchone()
            self.assertIsNone(raw[0])
            with self.assertRaises(RecordError): self.records.get_decision(identity)
        self.assertEqual(self.records._connection.execute('PRAGMA user_version').fetchone()[0], 6)


if __name__ == '__main__':
    unittest.main()
