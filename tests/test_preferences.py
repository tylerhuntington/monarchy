"""Configuration custody survives restart and prevents source/default drift."""
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from monarchy.records import CourtRecords, Conflict
from monarchy.preferences import Preferences, read_source


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'sources'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('remote', 'add', 'origin', 'https://github.com/example/project.git')
        self.git('config', 'user.email', 'test' + '@' + 'example.invalid')
        (self.repo / 'owner.json').write_text('{"voice.zone":"America/Los_Angeles"}\n')
        (self.repo / 'project.json').write_text('{"project.repository":"example/project","project.required_checks":["unit"]}\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Synthetic sources')
        self.sha = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/main', self.sha)
        self.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        self.db = self.root / 'court.db'
        self.records = CourtRecords(self.db)
        self.prefs = Preferences(self.records)
        self.owner = read_source(self.repo, self.sha, 'owner.json', 'owner')
        self.project = read_source(self.repo, self.sha, 'project.json', 'project')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    def tearDown(self):
        self.records.close()
        self.tmp.cleanup()

    def approve(self):
        boxes = self.prefs.founding(self.owner, self.project)
        for box in boxes:
            self.records.answer_decision(box['decision_id'], {'accept': True},
                                         expected_revision=box['revision'], owner_message='trusted-owner-answer')

    def pin(self):
        self.approve()
        return self.prefs.pin(self.owner, self.project, owner_message='trusted-pin-answer', monarchy_revision='a' * 40)

    def test_founding_answers_are_required_and_reused(self):
        with self.assertRaises(ValueError):
            self.prefs.pin(self.owner, self.project, owner_message='not-a-founding-answer', monarchy_revision='a' * 40)
        first = self.prefs.founding(self.owner, self.project)
        self.assertEqual(len(first), 2)
        self.approve()
        pin = self.prefs.pin(self.owner, self.project, owner_message='trusted-pin-answer', monarchy_revision='a' * 40)
        self.assertEqual(self.prefs.founding(self.owner, self.project), [])
        self.assertEqual(pin['payload']['owner']['sha256'], self.owner['sha256'])

    def test_pin_exact_bytes_offline_and_restart(self):
        pin = self.pin()
        (self.repo / 'owner.json').write_text('invalid new working bytes')
        self.records.close()
        self.records = CourtRecords(self.db)
        self.prefs = Preferences(self.records)
        view = self.prefs.show('example/project')
        self.assertFalse(view['held'])
        self.assertEqual(view['pin_id'], pin['pin_id'])
        self.assertEqual(view['config']['voice.zone']['value'], 'America/Los_Angeles')
        self.assertEqual(view['sources']['owner']['bytes'], '{"voice.zone":"America/Los_Angeles"}\n')

    def test_read_source_rejects_branch_partial_sha_and_unmerged_project(self):
        for rev in ('main', self.sha[:8]):
            with self.assertRaises(ValueError): read_source(self.repo, rev, 'owner.json', 'owner')
        self.git('checkout', '-b', 'candidate')
        (self.repo / 'project.json').write_text('{"project.repository":"example/other"}')
        self.git('commit', '-am', 'Unmerged project')
        with self.assertRaises(ValueError):
            read_source(self.repo, self.git('rev-parse', 'HEAD'), 'project.json', 'project')

    def test_missing_confirmation_and_false_answer_never_grant(self):
        boxes = self.prefs.founding(self.owner, self.project)
        for box in boxes:
            self.records.answer_decision(box['decision_id'], {'accept': False},
                                         expected_revision=box['revision'], owner_message='owner-no')
        with self.assertRaises(ValueError):
            self.prefs.pin(self.owner, self.project, owner_message='later-reference-only', monarchy_revision='a' * 40)

    def test_changed_defaults_hold_until_repin(self):
        from unittest.mock import patch
        self.pin()
        with patch('monarchy.preferences.defaults_digest', return_value='f' * 64):
            self.assertTrue(self.prefs.show('example/project')['held'])
            with self.assertRaises(ValueError): self.prefs.require_current('example/project')

    def test_pause_is_court_bound_and_persists(self):
        self.pin()
        self.prefs.override('court.paused', True, owner_message='owner-pause')
        self.records.close()
        self.records = CourtRecords(self.db)
        self.prefs = Preferences(self.records)
        self.assertTrue(self.prefs.show('example/project')['config']['court.paused']['value'])
        with self.assertRaises(ValueError): self.prefs.override('court.paused', False, owner_message='unconfirmed-resume')
        with self.assertRaises(ValueError): self.prefs.require_current('example/project')

    def test_project_override_cannot_control_another_project_or_court(self):
        self.pin()
        with self.assertRaises(ValueError):
            self.prefs.override('court.paused', True, owner_message='project-input', project='example/project')

    def test_v1_migration_preserves_records_and_unknown_operations(self):
        task=self.records.create_task('t','example/project','worker',metadata={})
        self.records.prepare_operation('op','t','send_message',{'generation':1})
        # Preserve a genuine pre-custody unknown operation without admitting it
        # through the newer worker-mode gate to manufacture historical state.
        self.records._connection.execute("UPDATE operations SET state='unknown' WHERE operation_id='op'")
        self.records.close()
        con=sqlite3.connect(self.db)
        con.execute('DROP TABLE pins'); con.execute('DROP TABLE overrides')
        con.execute('PRAGMA user_version=1'); con.close()
        self.records=CourtRecords(self.db)
        self.assertEqual(self.records.get_task('t'),task)
        self.assertEqual(self.records.get_operation('op')['state'],'unknown')
        self.assertEqual(self.records._connection.execute('PRAGMA user_version').fetchone()[0],7)

    def test_new_project_cannot_restore_older_court_owner_without_box(self):
        self.pin()
        (self.repo / 'owner.json').write_text('{"voice.zone":"America/Los_Angeles","owner.slots":8}')
        self.git('commit','-am','New owner profile')
        newer=read_source(self.repo,self.git('rev-parse','HEAD'),'owner.json','owner')
        for box in self.prefs.founding(newer,self.project):
            self.records.answer_decision(box['decision_id'],{'accept':True},expected_revision=box['revision'],owner_message='new-owner-answer')
        self.prefs.pin(newer,self.project,owner_message='new-owner-pin',monarchy_revision='a'*40)
        (self.repo / 'project.json').write_text('{"project.repository":"example/other"}')
        self.git('commit','-am','Another project')
        self.git('update-ref','refs/remotes/origin/main',self.git('rev-parse','HEAD'))
        self.git('remote','set-url','origin','https://github.com/example/other.git')
        other=read_source(self.repo,self.git('rev-parse','HEAD'),'project.json','project')
        self.assertTrue(self.prefs.founding(self.owner,other))
        with self.assertRaises(ValueError):
            self.prefs.pin(self.owner,other,owner_message='unconfirmed-rollback',monarchy_revision='a'*40)
        self.assertFalse(self.prefs.show('example/project')['held'])

    def test_numeric_acceptance_cannot_authorize_pin(self):
        for box in self.prefs.founding(self.owner,self.project):
            self.records.answer_decision(box['decision_id'],{'accept':1},expected_revision=box['revision'],owner_message='numeric-answer')
        with self.assertRaises(ValueError):
            self.prefs.pin(self.owner,self.project,owner_message='pin',monarchy_revision='a'*40)

    def test_restrictive_override_history_never_loses_restrictions(self):
        self.pin()
        self.prefs.override('backlog.builder_cap',2,owner_message='court-limit')
        self.prefs.override('backlog.builder_cap',5,owner_message='project-limit',project='example/project')
        self.prefs.override('archive.protected_workspaces',['scratch-a'],owner_message='protect-a')
        self.prefs.override('archive.protected_workspaces',['scratch-b'],owner_message='protect-b')
        config=self.prefs.show('example/project')['config']
        self.assertEqual(config['backlog.builder_cap']['value'],2)
        self.assertEqual(config['archive.protected_workspaces']['value'],['scratch-a','scratch-b'])

    def test_project_source_repository_must_match_its_remote(self):
        self.git('remote','set-url','origin','https://github.com/example/wrong.git')
        with self.assertRaises(ValueError): read_source(self.repo,self.sha,'project.json','project')

    def configured_task(self):
        self.pin()
        data=self.prefs.bind({'task_id':'work','repository':'example/project',
                             'owner':'22222222-2222-4222-8222-222222222222',
                             'metadata':{'authority_ref':'owner-task','brief':'Original task',
                                         'execution_mode':'writer',
                                         'writer_branch':{'repository':'example/project','ref':'work/configured'},
                                         'binding':{'session_id':'22222222-2222-4222-8222-222222222222',
                                                    'workspace_id':'11111111-1111-4111-8111-111111111111',
                                                    'repo':'example/project'}}})
        return self.records.create_task(data['task_id'],data['repository'],data['owner'],metadata=data['metadata'])

    def test_bound_profile_and_orders_accompany_dispatch(self):
        from monarchy.supervision import Court
        task=self.configured_task()
        operation=Court(self.records).prepare_dispatch('work')
        self.assertEqual(task['metadata']['binding']['profile']['model'],'gpt-6-astra')
        self.assertIn('<!-- rule:',operation['request']['text'])
        self.assertTrue(operation['request']['text'].endswith('Original task'))

    def test_pause_between_preparation_and_admission_blocks_send_not_readback(self):
        from monarchy.supervision import Court
        self.configured_task()
        operation=Court(self.records).prepare_dispatch('work')
        self.prefs.override('court.paused',True,owner_message='pause-after-prepare')
        with self.assertRaises(ValueError):
            self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared')
        self.assertEqual(self.records.get_operation(operation['operation_id'])['state'],'prepared')

    def test_changed_pin_requires_rebinding_even_when_worker_orders_are_unchanged(self):
        from monarchy.preferences import admission_check
        task=self.configured_task()
        (self.repo/'owner.json').write_text('{"voice.zone":"America/Los_Angeles","owner.slots":8}')
        self.git('commit','-am','Change capacity')
        newer=read_source(self.repo,self.git('rev-parse','HEAD'),'owner.json','owner')
        for box in self.prefs.founding(newer,self.project):
            self.records.answer_decision(box['decision_id'],{'accept':True},expected_revision=box['revision'],owner_message='approve-capacity')
        self.prefs.pin(newer,self.project,owner_message='pin-capacity',monarchy_revision='a'*40)
        with self.assertRaises(ValueError):admission_check(self.records,task)

    def test_widening_project_change_requires_its_exact_answered_box(self):
        self.pin()
        (self.repo/'project.json').write_text('{"project.repository":"example/project","project.required_checks":[]}')
        self.git('commit','-am','Change required checks')
        self.git('update-ref','refs/remotes/origin/main',self.git('rev-parse','HEAD'))
        project=read_source(self.repo,self.git('rev-parse','HEAD'),'project.json','project')
        boxes=self.prefs.founding(self.owner,project)
        self.assertEqual(len(boxes),1)
        self.assertIn('project.required_checks',boxes[0]['payload']['proposed']['project_widening'])
        with self.assertRaises(ValueError):
            self.prefs.pin(self.owner,project,owner_message='reference-without-answer',monarchy_revision='a'*40)

    def test_source_symlink_and_git_replacement_are_not_trusted(self):
        (self.repo/'alias.json').symlink_to('owner.json')
        self.git('add','alias.json');self.git('commit','-m','Add symbolic source')
        newer=self.git('rev-parse','HEAD')
        with self.assertRaises(ValueError):read_source(self.repo,newer,'alias.json','owner')
        (self.repo/'owner.json').write_text('{"voice.zone":"UTC"}')
        self.git('commit','-am','Replacement bytes')
        self.git('replace',self.sha,self.git('rev-parse','HEAD'))
        self.assertEqual(read_source(self.repo,self.sha,'owner.json','owner')['bytes'],self.owner['bytes'])

    def test_oversized_cumulative_override_is_rolled_back(self):
        self.pin()
        protected=['scratch-{}'.format(i) for i in range(64)]
        self.prefs.override('archive.protected_workspaces',protected,owner_message='protect-existing')
        with self.assertRaises(ValueError):
            self.prefs.override('archive.protected_workspaces',['extra-scratch'],owner_message='invalid-growth')
        self.assertEqual(self.prefs.show('example/project')['config']['archive.protected_workspaces']['value'],protected)

    def test_pause_before_adoption_blocks_legacy_admission(self):
        self.records.create_task('legacy','example/project','worker',metadata={})
        self.records.prepare_operation('legacy-op','legacy','send_message',{'generation':1})
        self.prefs.override('court.paused',True,owner_message='pause-before-adoption')
        with self.assertRaises(ValueError):
            self.records.set_operation_state('legacy-op','in_flight',expected_state='prepared')

    def test_oversized_orders_fail_before_founding(self):
        value=lambda prefix,count:[prefix+str(i).zfill(2)+'x'*253 for i in range(count)]
        data={'project.repository':'example/project','project.required_checks':value('c',64),
              'project.merge_labels':value('m',64),'project.priority_surfaces':value('p',40)}
        (self.repo/'project.json').write_text(json.dumps(data))
        self.git('commit','-am','Large project data')
        self.git('update-ref','refs/remotes/origin/main',self.git('rev-parse','HEAD'))
        project=read_source(self.repo,self.git('rev-parse','HEAD'),'project.json','project')
        with self.assertRaises(ValueError):self.prefs.founding(self.owner,project)
        self.assertFalse(self.records.has_pins())

    def test_combined_brief_and_orders_must_fit_before_registration(self):
        self.pin()
        data={'task_id':'large','repository':'example/project','owner':'worker',
              'metadata':{'brief':'x'*49152,'binding':{'session_id':'worker','repo':'example/project'}}}
        with self.assertRaises(ValueError):self.prefs.bind(data)

    def test_pin_checks_existing_overrides_together_with_candidate(self):
        self.prefs.override('voice.forbidden_characters',[chr(i) for i in range(0x500,0x540)],owner_message='restrict-characters')
        owner={'voice.zone':'UTC','voice.forbidden_characters':[chr(i) for i in range(0x400,0x440)]}
        (self.repo/'owner.json').write_text(json.dumps(owner))
        self.git('commit','-am','More owner restrictions')
        source=read_source(self.repo,self.git('rev-parse','HEAD'),'owner.json','owner')
        with self.assertRaises(ValueError):self.prefs.founding(source,self.project)
        self.assertFalse(self.records.has_pins())
