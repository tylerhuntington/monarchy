"""Public names change without changing task identity or an existing intent."""
from pathlib import Path
import tempfile
import unittest

from monarchy.conductor import prepare_session
from monarchy.records import CourtRecords, RecordError, Conflict
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
                'execution_mode': 'read-only',
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

    def test_legacy_launch_holds_new_admission_and_retains_original_recovery_intent(self):
        task = self.task('legacy')
        key = 'legacy:1'
        old = prepare_session('legacy', WORKSPACE, 'example/project', PROFILE,
                              'Worker · legacy', task['metadata']['brief'], session_id=WORKER,
                              operation_id=identity('dispatch-operation', key),
                              message_id=identity('dispatch-message', key))
        old['request']['generation'] = 1
        stored = self.records.prepare_operation(old['operation_id'], 'legacy', old['kind'], old['request'])
        with self.assertRaises(Conflict):
            self.court.prepare_dispatch('legacy', new_session=True)
        # A pre-custody installation already admitted this exact legacy launch.
        # Seeding that historical state is not permission for a new admission.
        self.records._connection.execute("UPDATE operations SET state='unknown' WHERE operation_id=?",
                                         (old['operation_id'],))
        uncertain = self.records.get_operation(old['operation_id'])
        class ReconcileOnly:
            def create_session(inner, operation, persist):
                self.assertEqual(operation, uncertain)
                self.assertEqual(operation['request']['name'], 'Worker · legacy')
                return operation
        self.court.transport = ReconcileOnly()
        self.assertEqual(self.court.deliver(old['operation_id']), uncertain)
        self.assertEqual(len(self.records.list_operations(task_id='legacy')), 1)
