"""Owner controls retain exact approval and cannot replay away a later pause."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from monarchy.config import load, resolve
from monarchy.conductor import MAX_TEXT_BYTES
from monarchy.orders import render
from monarchy.controls import Controls
from monarchy.preferences import Preferences, admission_check
from monarchy.records import CourtRecords, Conflict, RecordError


def source(data, layer):
    raw = json.dumps(data).encode()
    return {'commit': 'a' * 40, 'path': 'owner.json' if layer == 'owner' else '.agents/monarchy.json',
            'blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': raw.decode(), 'layer': layer,
            'repository': 'example/project' if layer == 'project' else ''}


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'court.db'
        self.records = CourtRecords(self.path)
        self.controls = Controls(self.records)
        self.prefs = Preferences(self.records)
        self.profile = {'agent': 'codex', 'model': 'candidate-model', 'effort': 'high', 'fast_mode': False}

    def tearDown(self):
        self.records.close()
        self.tmp.cleanup()

    def pin(self):
        owner = source({'voice.zone': 'UTC'}, 'owner')
        project = source({'project.repository': 'example/project'}, 'project')
        for box in self.prefs.founding(owner, project):
            self.answer(box)
        return self.prefs.pin(owner, project, owner_message='pin-answer', monarchy_revision='a' * 40)

    def answer(self, box, answer=None):
        return self.records.answer_decision(box['decision_id'], {'accept': True} if answer is None else answer,
                                            expected_revision=box['revision'], owner_message='owner-answer')

    def command(self, verb, payload=None, message=None):
        return self.controls.command(verb, payload, owner_message=message or 'request-' + verb)

    def test_readonly_commands_do_not_create_records(self):
        before = self.records._connection.total_changes
        self.assertLessEqual(len(self.controls.command('bearings')['lines']), 5)
        self.assertEqual(self.controls.command('decisions')['decisions'], [])
        self.assertEqual(self.records._connection.total_changes, before)

    def test_restrictive_commands_persist_and_replay_exactly(self):
        for verb, key in [('pause', 'court.paused'), ('stop', 'court.stopped'), ('away', 'court.away')]:
            first = self.command(verb)
            self.assertEqual(self.command(verb), first)
            self.assertTrue(self.records.config_overrides()[key])
        with self.assertRaises(Conflict):
            self.command('stop', message='request-pause')
        self.assertEqual(self.records._connection.execute('SELECT count(*) FROM overrides').fetchone()[0], 3)
        self.records.close()
        self.records = CourtRecords(self.path)
        self.assertEqual(set(self.records.config_overrides()), {'court.paused', 'court.stopped', 'court.away'})

    def test_resume_requires_exact_answer_and_replay_preserves_later_pause(self):
        self.command('pause')
        self.command('stop')
        self.command('away')
        box = self.command('resume')
        self.assertEqual(box['state'], 'pending')
        with self.assertRaises(Conflict): self.controls.apply(box['decision_id'])
        self.answer(box)
        receipt = self.controls.apply(box['decision_id'])
        self.assertEqual(self.records.config_overrides(), {})
        self.assertEqual(receipt['receipt']['effects']['clear'], ['court.paused', 'court.stopped', 'court.away'])
        self.command('pause', message='later-pause')
        self.assertEqual(self.controls.apply(box['decision_id']), receipt)
        self.assertTrue(self.records.config_overrides()['court.paused'])

    def test_later_pause_makes_unapplied_resume_stale(self):
        self.command('pause')
        box = self.command('resume')
        self.answer(box)
        self.command('stop')
        with self.assertRaises(Conflict): self.controls.apply(box['decision_id'])
        self.assertEqual(self.records.config_overrides(), {'court.paused': True, 'court.stopped': True})

    def test_refusal_or_loose_boolean_never_applies(self):
        for number, answer in enumerate([{'accept': False}, {'accept': 1}, {'accept': True, 'grant': True}]):
            box = self.command('resume', message='resume-' + str(number))
            self.answer(box, answer)
            with self.assertRaises(Conflict): self.controls.apply(box['decision_id'])
        self.assertEqual(self.records.config_overrides(), {})

    def test_model_is_separate_approved_overlay_and_pin_is_immutable(self):
        original = self.pin()
        payload = {'role': 'worker', 'profile': copy.deepcopy(self.profile)}
        box = self.command('model', payload)
        payload['profile']['model'] = 'changed-after-request'
        self.assertNotEqual(self.prefs.show('example/project')['config']['profiles.worker']['value'], self.profile)
        self.answer(box)
        result = self.controls.apply(box['decision_id'])
        view = self.prefs.show('example/project')
        self.assertEqual(view['config']['profiles.worker']['value'], self.profile)
        self.assertEqual(view['config']['profiles.worker']['layers'], ['overrides'])
        self.assertEqual(self.records.get_pin(original['pin_id']), original)
        self.assertNotIn('profiles.worker', self.records.config_overrides())
        self.assertEqual(result['receipt']['promotion']['destination'], 'owner.json')
        self.assertEqual(result['receipt']['promotion']['state'], 'offered')
        self.assertFalse((Path(self.tmp.name) / 'owner.json').exists())

    def test_model_rebinds_task_and_holds_old_profile(self):
        self.pin()
        task = {'task_id': 'test-task', 'repository': 'example/project', 'owner': 'worker-session',
                'metadata': {'brief': 'Implement the assigned change.',
                             'binding': {'repo': 'example/project', 'session_id': 'worker-session'}}}
        old = self.prefs.bind(task)
        admission_check(self.records, old)
        box = self.command('model', {'role': 'worker', 'profile': self.profile})
        self.answer(box)
        self.controls.apply(box['decision_id'])
        with self.assertRaises(Conflict): admission_check(self.records, old)
        new = self.prefs.bind(task)
        self.assertEqual(new['metadata']['binding']['profile'], self.profile)
        admission_check(self.records, new)

    def test_handoff_is_approved_intent_only(self):
        payload = {'role': 'queen', 'session_id': '11111111-1111-4111-8111-111111111111'}
        box = self.command('handoff', payload)
        self.answer(box)
        result = self.controls.apply(box['decision_id'])
        self.assertEqual(result['receipt']['effects'], {'handoff': payload})
        self.assertEqual(self.records.list_operations(), [])
        self.assertEqual(self.records.config_overrides(), {})

    def test_atomic_validation_rolls_back_every_effect(self):
        self.pin()
        box = self.command('model', {'role': 'worker', 'profile': self.profile})
        self.answer(box)
        def fail_after_insert():
            self.assertEqual(self.records._connection.execute('SELECT count(*) FROM overrides').fetchone()[0], 1)
            raise ValueError('bounded failure')
        with patch('monarchy.preferences.Preferences.validate_current_overrides', side_effect=fail_after_insert):
            with self.assertRaises(ValueError): self.controls.apply(box['decision_id'])
        self.assertEqual(self.records._connection.execute('SELECT count(*) FROM overrides').fetchone()[0], 0)
        self.assertEqual(self.records.model_overrides(), {})
        self.controls.apply(box['decision_id'])

    def test_bearings_does_not_claim_admission_readiness_during_config_drift(self):
        self.pin()
        with patch('monarchy.preferences.defaults_digest', return_value='f' * 64):
            self.assertTrue(self.prefs.show('example/project')['held'])
            lines = self.controls.command('bearings')['lines']
            self.assertNotIn('ready', ' '.join(lines))
            self.assertIn('no pause or stop recorded', lines[0])

    def test_receipt_tampering_and_superseded_approval_fail_closed(self):
        self.command('pause')
        box = self.command('resume')
        self.answer(box)
        result = self.controls.apply(box['decision_id'])
        self.records.revise_decision(box['decision_id'], box['payload'], expected_revision=1)
        with self.assertRaises(RecordError): self.records.config_overrides()
        with self.assertRaises(RecordError): self.controls.apply(box['decision_id'])
        self.assertIsNotNone(result)

    def test_invalid_payloads_cannot_write_or_grant(self):
        cases = [('pause', {'grant': 'spending'}), ('model', {'role': 'worker', 'profile': {'model': 'x'}}),
                 ('model', {'role': 'worker', 'profile': self.profile}),
                 ('handoff', {'role': 'worker', 'session_id': 'not-a-session'}), ('deploy', {})]
        for verb, payload in cases:
            with self.assertRaises(ValueError): self.command(verb, payload)
        with self.assertRaises(ValueError): self.controls.command('pause')
        for value in [{'court.paused': False}, {'profiles.worker': self.profile}, {'grant': True}]:
            with self.assertRaises(ValueError): load(json.dumps(value), 'overrides')
        self.assertEqual(self.records._connection.execute('SELECT count(*) FROM overrides').fetchone()[0], 0)

    def test_model_receipt_survives_restart_without_private_source_files(self):
        self.pin()
        box = self.command('model', {'role': 'secretary', 'profile': self.profile})
        self.answer(box)
        first = self.controls.apply(box['decision_id'])
        self.records.close()
        self.records = CourtRecords(self.path)
        self.controls = Controls(self.records)
        self.assertEqual(self.controls.apply(box['decision_id']), first)
        self.assertEqual(Preferences(self.records).show('example/project')['config']['profiles.secretary']['value'], self.profile)

    def test_different_pin_requires_a_fresh_model_proposal(self):
        self.pin()
        box = self.command('model', {'role': 'worker', 'profile': self.profile})
        self.answer(box)
        owner = source({'voice.zone': 'UTC', 'owner.slots': 7}, 'owner')
        project = source({'project.repository': 'example/project'}, 'project')
        for review in self.prefs.founding(owner, project):
            self.answer(review)
        self.prefs.pin(owner, project, owner_message='new-pin-answer', monarchy_revision='a' * 40)
        with self.assertRaises(Conflict): self.controls.apply(box['decision_id'])
        self.assertEqual(self.records.model_overrides(), {})

    def test_restrictive_override_and_other_project_state_survive_resume(self):
        self.prefs.override('backlog.builder_cap', 3, owner_message='project-cap', project='example/project')
        self.prefs.override('backlog.builder_cap', 2, owner_message='other-cap', project='example/other')
        self.prefs.override('court.paused', True, owner_message='legacy-pause')
        box = self.command('resume')
        self.answer(box)
        self.controls.apply(box['decision_id'])
        self.assertEqual(self.records.config_overrides('example/project'), {'backlog.builder_cap': 3})
        self.assertEqual(self.records.config_overrides('example/other'), {'backlog.builder_cap': 2})

    def test_pending_command_is_frozen_and_conflicting_request_ref_is_rejected(self):
        payload = {'role': 'queen', 'session_id': '11111111-1111-4111-8111-111111111111'}
        box = self.command('handoff', payload)
        self.assertEqual(self.command('handoff', payload), box)
        with self.assertRaises(Conflict): self.command('resume', message='request-handoff')
        changed = dict(payload, role='secretary')
        with self.assertRaises(Conflict): self.command('handoff', changed)
        payload['role'] = 'secretary'
        self.assertEqual(self.records.get_decision(box['decision_id'])['payload']['request']['role'], 'queen')

    def test_receipt_corruption_is_rejected_even_for_numeric_boolean(self):
        result = self.command('pause')
        original = self.records._connection.execute('SELECT value FROM overrides').fetchone()[0]
        for corrupt in [dict(result['receipt'], effects={'set': {'court.paused': 1}}),
                        dict(result['receipt'], effects={'clear': ['court.paused']}),
                        dict(result['receipt'], request_owner_message='different-message')]:
            raw = json.dumps({'control': corrupt}, sort_keys=True, separators=(',', ':'))
            self.records._connection.execute('UPDATE overrides SET value=?', (raw,))
            with self.assertRaises(RecordError): self.records.config_overrides()
            self.records._connection.execute('UPDATE overrides SET value=?', (original,))

    def test_altering_prefix_history_or_proposal_cannot_preserve_approval(self):
        self.prefs.override('court.paused', True, owner_message='original-pause')
        box = self.command('resume')
        self.answer(box)
        self.controls.apply(box['decision_id'])
        self.records._connection.execute('UPDATE overrides SET owner_message=? WHERE sequence=1', ('altered-ref',))
        with self.assertRaises(RecordError): self.records.config_overrides()

    def test_changed_frozen_proposal_and_noncontrol_decision_are_rejected(self):
        box = self.command('resume')
        self.answer(box)
        changed = copy.deepcopy(box['payload'])
        changed['generation'] = True
        self.records._connection.execute('UPDATE decisions SET payload=? WHERE decision_id=?',
                                         (json.dumps(changed), box['decision_id']))
        with self.assertRaises(Conflict): self.controls.apply(box['decision_id'])
        self.records.create_task('unrelated', 'example/project', 'worker')
        other = self.records.open_decision('other-box', 'unrelated', {'question': 'Proceed?'})
        self.answer(other)
        with self.assertRaises(Conflict): self.controls.apply(other['decision_id'])

    def test_competing_apply_writers_commit_one_receipt(self):
        self.command('pause')
        box = self.command('resume')
        self.answer(box)
        barrier = threading.Barrier(2)
        def apply():
            with CourtRecords(self.path) as records:
                barrier.wait(timeout=5)
                return Controls(records).apply(box['decision_id'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(apply) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.records._connection.execute('SELECT count(*) FROM overrides').fetchone()[0], 2)
        self.assertEqual(self.records.config_overrides(), {})

    def test_competing_pause_and_resume_always_preserve_the_new_pause(self):
        box = self.command('resume')
        self.answer(box)
        barrier = threading.Barrier(2)
        def write(verb):
            with CourtRecords(self.path) as records:
                control = Controls(records)
                barrier.wait(timeout=5)
                try:
                    return control.apply(box['decision_id']) if verb == 'resume' else control.command('pause', owner_message='racing-pause')
                except Conflict:
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, verb) for verb in ('resume', 'pause')]
            for future in futures: future.result(timeout=10)
        self.assertTrue(self.records.config_overrides()['court.paused'])

    def test_full_render_budget_is_enforced_atomically_for_model_overlay(self):
        owner = {'voice.zone': 'UTC'}
        base = {'project.repository': 'example/project',
                'project.required_checks': ['c' + str(i).zfill(2) + 'x' * 253 for i in range(64)],
                'project.merge_labels': ['m' + str(i).zfill(2) + 'x' * 253 for i in range(64)]}
        def candidate(size):
            values = ['p' + str(i).zfill(2) + 'x' * min(253, size - i * 253)
                      for i in range((size + 252) // 253)]
            project = dict(base, **{'project.priority_surfaces': values})
            config = resolve(owner=owner, project=project)
            sizes = {role: len(render(role, config)['text'].encode()) for role in ('queen', 'secretary', 'worker')}
            return project, sizes
        low, high = 0, 12000
        while low < high:
            middle = (low + high + 1) // 2
            if max(candidate(middle)[1].values()) <= MAX_TEXT_BYTES - 103:
                low = middle
            else:
                high = middle - 1
        project, sizes = candidate(low)
        role = max(sizes, key=sizes.get)
        owner_source, project_source = source(owner, 'owner'), source(project, 'project')
        for box in self.prefs.founding(owner_source, project_source): self.answer(box)
        self.prefs.pin(owner_source, project_source, owner_message='bounded-pin', monarchy_revision='a' * 40)
        profile = {'agent': 'a' * 128, 'model': 'm' * 128, 'effort': 'e' * 128, 'fast_mode': False}
        box = self.command('model', {'role': role, 'profile': profile})
        self.answer(box)
        with self.assertRaises(ValueError): self.controls.apply(box['decision_id'])
        self.assertEqual(self.records.model_overrides(), {})
        self.assertEqual(self.records._connection.execute('SELECT count(*) FROM overrides').fetchone()[0], 0)

    def test_bounded_history_and_sanitized_diagnostics(self):
        self.command('pause')
        self.command('away')
        with patch('monarchy.controls.MAX_HISTORY', 1):
            with self.assertRaises(RecordError): self.records.config_overrides()
        secret = 'private-marker-value'
        with self.assertRaises(ValueError) as raised:
            self.command('handoff', {'role': 'queen', 'session_id': secret})
        self.assertNotIn(secret, str(raised.exception))
