"""Public names change without changing task identity or an existing intent."""
from pathlib import Path
import tempfile
import unittest

from monarchy.conductor import prepare_session
from monarchy.records import CourtRecords, RecordError
from monarchy.supervision import Court, identity

WORKER = '22222222-2222-4222-8222-222222222222'
WORKSPACE = '11111111-1111-4111-8111-111111111111'
PROFILE = {'agent': 'codex', 'model': 'selected-model', 'effort': 'high', 'fast_mode': True}


class AgentNameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.records = CourtRecords(Path(self.temp.name) / 'court.db')
        self.court = Court(self.records)

    def tearDown(self):
        self.records.close()
        self.temp.cleanup()

    def task(self, task_id, name=None):
        meta = {'authority_ref': 'owner-request', 'brief': 'Read the requested source.',
                'binding': {'session_id': WORKER, 'workspace_id': WORKSPACE,
                            'repo': 'example/project', 'profile': PROFILE}}
        if name is not None:
            meta['agent_name'] = name
        return self.records.create_task(task_id, 'example/project', WORKER, metadata=meta)

    def test_new_sessions_get_numeric_double_zero_names(self):
        for task_id, descriptor, expected in [('tests', None, '00-tests'),
                                               ('opaque-id', 'Fix build', '00-fix-build'),
                                               ('docs', '00-docs', '00-docs')]:
            with self.subTest(task=task_id):
                self.task(task_id, descriptor)
                operation = self.court.prepare_dispatch(task_id, new_session=True)
                self.assertEqual(operation['request']['name'], expected)
                self.assertEqual(operation['task_id'], task_id)
                self.assertEqual(operation['request']['binding']['session_id'], WORKER)
                self.assertEqual(self.court.prepare_dispatch(task_id, new_session=True), operation)

    def test_empty_or_nontext_descriptors_do_not_prepare_launches(self):
        for task_id, descriptor in [('blank', '  '), ('punctuation', '---'), ('not-text', 7)]:
            with self.subTest(task=task_id):
                self.task(task_id, descriptor)
                with self.assertRaises(RecordError):
                    self.court.prepare_dispatch(task_id, new_session=True)
                self.assertEqual(self.records.list_operations(task_id=task_id), [])

    def test_existing_legacy_intent_is_reused_without_renaming_or_resending(self):
        task = self.task('legacy')
        key = 'legacy:1'
        old = prepare_session('legacy', WORKSPACE, 'example/project', PROFILE,
                              'Worker · legacy', task['metadata']['brief'], session_id=WORKER,
                              operation_id=identity('dispatch-operation', key),
                              message_id=identity('dispatch-message', key))
        old['request']['generation'] = 1
        stored = self.records.prepare_operation(old['operation_id'], 'legacy', old['kind'], old['request'])
        self.assertEqual(self.court.prepare_dispatch('legacy', new_session=True), stored)
        self.records.set_operation_state(old['operation_id'], 'in_flight', expected_state='prepared')
        uncertain = self.records.set_operation_state(old['operation_id'], 'unknown',
                                                     expected_state='in_flight', result={'reason': 'timeout'})
        self.assertEqual(self.court.prepare_dispatch('legacy', new_session=True), uncertain)
        self.assertEqual(len(self.records.list_operations(task_id='legacy')), 1)
