"""Grant-bound backlog dispatch without GitHub writes or native actions."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import tempfile
import unittest

from monarchy.backlog import Backlog
from monarchy.records import CourtRecords, Conflict
from monarchy.preferences import Preferences
from monarchy.supervision import Court
from monarchy.records import RecordError

PROJECT = 'example/project'
REFERENCES = [{'kind':'issue','number':17}]
WORKSPACE='11111111-1111-4111-8111-111111111111'
PROFILE={'agent':'codex','model':'gpt-6-astra','effort':'ultra','fast_mode':True}


class BacklogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'royalty.db'
        self.records = CourtRecords(self.path)
        self.addCleanup(self.records.close)
        self.backlog = Backlog(self.records)

    def writer(self,task_id,branch,number=2,repository=PROJECT):
        session=('%08d-2222-4222-8222-222222222222'%number)
        return self.records.create_task(task_id,repository,session,metadata={
            'execution_mode':'writer','writer_branch':{'repository':repository,'ref':branch},
            'binding':{'repo':repository,'session_id':session,'workspace_id':WORKSPACE,'profile':PROFILE},
            'authority_ref':'original-owner-work','brief':'Prepare the scoped change.'})

    def activate(self,refs=REFERENCES):
        proposal=self.backlog.propose(PROJECT,refs,owner_message='activation',builder_cap=1)
        self.records.answer_decision(proposal['decision_id'],{'accept':True},expected_revision=1,owner_message='owner-yes')
        return self.backlog.apply(proposal['decision_id'])

    def selected(self,number=17):
        from test_backlog_selection import native,NativeReads
        from monarchy.backlog_selection import GitHubBacklog,select
        from monarchy.backlog import policy
        reader=GitHubBacklog(runner=NativeReads({number:native(number,'Issue')}))
        snapshot=reader.read(PROJECT,[{'kind':'issue','number':number}])
        fact={'reference':{'kind':'issue','number':number},'source_digest':snapshot['items'][0]['source_digest'],
              'bucket':'other-bugs','priority':1,'size':1,'wanted':True,'dependencies':[],
              'dependencies_complete':True,'ownership':'clear','planned_branch':'work/issue-'+str(number),
              'priority_surface':None,'evidence_ref':'tracked-classification'}
        candidate=select(snapshot,policy(self.records,PROJECT)[0],[fact])['candidate']
        return candidate,snapshot,[fact],reader

    def bound(self,candidate,grant,task_id='selected',number=8):
        session=('%08d-2222-4222-8222-222222222222'%number)
        data={'task_id':task_id,'repository':PROJECT,'owner':session,
              'metadata':{'brief':'Prepare and review the tracked change.',
                  'binding':{'repo':PROJECT,'session_id':session,'workspace_id':WORKSPACE,'profile':PROFILE}}}
        result=self.backlog.bind(data,candidate,grant['grant_id'])
        self.records.create_task(result['task_id'],result['repository'],result['owner'],metadata=result['metadata'])
        return result

    def test_only_exact_owner_activation_creates_a_durable_project_grant(self):
        proposal = self.backlog.propose(PROJECT,REFERENCES,owner_message='request-activation',builder_cap=1)
        self.assertEqual(self.backlog.state(PROJECT)['state'],'inactive')
        with self.assertRaises(Conflict):
            self.backlog.apply(proposal['decision_id'])
        self.records.answer_decision(proposal['decision_id'],{'accept':True},
            expected_revision=proposal['revision'],owner_message='owner-activation')
        active=self.backlog.apply(proposal['decision_id'])
        self.assertEqual(active['state'],'active')
        self.assertEqual(active['payload']['references'],REFERENCES)
        self.assertEqual(active['payload']['builder_cap'],1)
        with CourtRecords(self.path) as other:
            self.assertEqual(Backlog(other).state(PROJECT),active)
            self.assertEqual(Backlog(other).apply(proposal['decision_id']),active)
        self.assertEqual(self.backlog.state('example/other')['state'],'inactive')

    def test_grant_origin_cannot_activate_and_revocation_fences_old_owner_answer(self):
        proposal=self.backlog.propose(PROJECT,REFERENCES,owner_message='activation',builder_cap=1)
        self.records.answer_decision(proposal['decision_id'],{'accept':True},
            expected_revision=1,owner_message='owner-yes')
        self.records._connection.execute("UPDATE decisions SET answered_by='grant:existing',owner_message=NULL WHERE decision_id=?",
                                         (proposal['decision_id'],))
        with self.assertRaises(Conflict):self.backlog.apply(proposal['decision_id'])
        self.assertEqual(self.backlog.state(PROJECT)['state'],'inactive')
        self.records._connection.execute("UPDATE decisions SET answered_by='owner',owner_message='owner-yes' WHERE decision_id=?",
                                         (proposal['decision_id'],))
        self.backlog.revoke(PROJECT,owner_message='owner-revoke')
        with self.assertRaises(Conflict):self.backlog.apply(proposal['decision_id'])

    def test_away_does_not_change_grant_but_pause_holds_and_revoke_survives_restart(self):
        proposal=self.backlog.propose(PROJECT,REFERENCES,owner_message='activation',builder_cap=1)
        self.records.answer_decision(proposal['decision_id'],{'accept':True},expected_revision=1,owner_message='owner-yes')
        grant=self.backlog.apply(proposal['decision_id'])
        prefs=Preferences(self.records)
        prefs.override('court.away',True,owner_message='away')
        self.assertEqual(self.backlog.state(PROJECT)['held_reasons'],[])
        prefs.override('court.paused',True,owner_message='pause')
        self.assertIn('court.paused',self.backlog.state(PROJECT)['held_reasons'])
        revoked=self.backlog.revoke(PROJECT,owner_message='revoke')
        self.assertEqual(revoked['state'],'revoked')
        self.assertEqual(revoked['grant_id'],grant['grant_id'])
        with CourtRecords(self.path) as other:
            self.assertEqual(Backlog(other).state(PROJECT),revoked)
            self.assertEqual(Backlog(other).apply(proposal['decision_id'])['state'],'revoked')

    def test_rejecting_new_scope_keeps_existing_grant_without_promising_inactive(self):
        first=self.backlog.propose(PROJECT,REFERENCES,owner_message='activation',builder_cap=1)
        self.records.answer_decision(first['decision_id'],{'accept':True},expected_revision=1,owner_message='owner-yes')
        grant=self.backlog.apply(first['decision_id'])
        later=self.backlog.propose(PROJECT,[{'kind':'issue','number':18}],owner_message='different-scope',builder_cap=1)
        self.assertIn('Keep Current State',later['payload']['options'])
        self.records.answer_decision(later['decision_id'],{'accept':False},expected_revision=1,owner_message='owner-no')
        with self.assertRaises(Conflict):self.backlog.apply(later['decision_id'])
        self.assertEqual(self.backlog.state(PROJECT),grant)

    def test_all_writer_dispatches_reserve_canonical_branch_before_native_effect(self):
        self.writer('one','work/item')
        self.writer('two','refs/heads/work/item',3,repository='Example/Project')
        first=Court(self.records).prepare_dispatch('one')
        self.assertEqual(first['request']['writer_branch'],{'repository':PROJECT,'ref':'refs/heads/work/item'})
        self.assertEqual(Court(self.records).prepare_dispatch('one'),first)
        with self.assertRaises(Conflict):Court(self.records).prepare_dispatch('two')
        with CourtRecords(self.path) as other:
            with self.assertRaises(Conflict):Court(other).prepare_dispatch('two')
        self.assertEqual(self.records.get_operation(first['operation_id'])['state'],'prepared')

    def test_generic_worker_message_cannot_bypass_explicit_mode_and_writer_reservation(self):
        self.records.create_task('legacy',PROJECT,'legacy-worker')
        self.records.prepare_operation('generic','legacy','send_message',{'generation':1,'text':'Read status'})
        with self.assertRaises(Conflict):
            self.records.set_operation_state('generic','in_flight',expected_state='prepared')
        self.writer('writer','work/unreserved',3)
        self.records.prepare_operation('writer-message','writer','send_message',{'generation':1,'text':'Continue'})
        with self.assertRaises(Conflict):
            self.records.set_operation_state('writer-message','in_flight',expected_state='prepared')
        binding={'repo':PROJECT,'session_id':'reader','workspace_id':WORKSPACE,'profile':PROFILE}
        self.records.create_task('reader',PROJECT,'reader',metadata={'execution_mode':'read-only','binding':binding})
        self.records.prepare_operation('read-message','reader','send_message',{'generation':1,'binding':binding,'text':'Read status'})
        self.assertEqual(self.records.set_operation_state('read-message','in_flight',expected_state='prepared')['state'],'in_flight')

    def test_worker_message_cannot_replace_the_confirmed_profile_or_target_binding(self):
        task=self.writer('writer','work/item')
        Court(self.records).prepare_dispatch('writer')
        bad=dict(task['metadata']['binding'],profile={})
        self.records.prepare_operation('profile-bypass','writer','send_message',
            {'generation':1,'binding':bad,'text':'Continue'})
        with self.assertRaises(Conflict):
            self.records.set_operation_state('profile-bypass','in_flight',expected_state='prepared')

    def test_repository_case_alias_cannot_escape_restrictive_cap_or_create_second_grant(self):
        Preferences(self.records).override('backlog.builder_cap',1,project=PROJECT,owner_message='limit')
        self.writer('one','work/one')
        self.writer('two','work/two',3,repository='EXAMPLE/PROJECT')
        Court(self.records).prepare_dispatch('one')
        with self.assertRaises(Conflict):Court(self.records).prepare_dispatch('two')
        proposal=self.backlog.propose('EXAMPLE/PROJECT',REFERENCES,owner_message='activation',builder_cap=1)
        self.records.answer_decision(proposal['decision_id'],{'accept':True},expected_revision=1,owner_message='owner-yes')
        grant=self.backlog.apply(proposal['decision_id'])
        self.assertEqual(grant['project'],PROJECT)
        self.assertEqual(self.backlog.state('EXAMPLE/PROJECT'),self.backlog.state(PROJECT))

    def test_project_grant_does_not_require_enumerating_future_items(self):
        proposal=self.backlog.propose(PROJECT,owner_message='project-activation',builder_cap=1)
        self.assertEqual(proposal['payload']['scope'],'project-backlog')
        self.assertIsNone(proposal['payload']['references'])
        self.records.answer_decision(proposal['decision_id'],{'accept':True},expected_revision=1,owner_message='owner-yes')
        self.assertIsNone(self.backlog.apply(proposal['decision_id'])['payload']['references'])

    def test_prepared_cancellation_releases_exact_branch_and_prevents_late_send(self):
        self.writer('one','work/item')
        self.writer('two','work/item',3)
        operation=Court(self.records).prepare_dispatch('one')
        reservation_id=operation['request']['reservation_id']
        with self.assertRaises(Conflict):self.records.assign_task('one','replacement',expected_generation=1)
        released=self.backlog.release(reservation_id,'cancel-1',
            {'kind':'never-admitted','operation_id':operation['operation_id']})
        self.assertEqual(released['state'],'released')
        self.assertEqual(self.records.get_operation(operation['operation_id'])['state'],'failed')
        with self.assertRaises(Conflict):
            self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared')
        self.assertEqual(Court(self.records).prepare_dispatch('two')['state'],'prepared')

    def test_actual_selected_candidate_needs_fresh_receipt_and_current_grant_at_admission(self):
        grant=self.activate()
        candidate,snapshot,_,_=self.selected()
        self.bound(candidate,grant)
        operation=self.backlog.prepare('selected',candidate,snapshot)
        with self.assertRaises(Conflict):
            self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared')
        self.backlog.revoke(PROJECT,owner_message='revoke-before-send')
        with self.assertRaises(Conflict):
            self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared',backlog_snapshot=snapshot)
        self.assertEqual(self.records.get_operation(operation['operation_id'])['state'],'prepared')

    def test_project_scope_accepts_new_tracked_item_but_allowlist_stays_exact(self):
        grant=self.activate(None)
        candidate,snapshot,_,_=self.selected(18)
        self.bound(candidate,grant)
        self.assertEqual(self.backlog.prepare('selected',candidate,snapshot)['state'],'prepared')
        self.backlog.revoke(PROJECT,owner_message='stop-project-grant')
        allow=self.activate(REFERENCES)
        with self.assertRaises(Conflict):self.bound(candidate,allow,task_id='outside-allowlist',number=9)

    def test_fresh_dispatch_admits_once_and_unknown_reconciles_after_revoke(self):
        grant=self.activate()
        candidate,snapshot,_,_=self.selected()
        self.bound(candidate,grant)
        operation=self.backlog.prepare('selected',candidate,snapshot)
        admitted=self.records.set_operation_state(operation['operation_id'],'in_flight',
            expected_state='prepared',backlog_snapshot=snapshot)
        self.assertEqual(admitted['state'],'in_flight')
        self.records.set_operation_state(operation['operation_id'],'unknown',expected_state='in_flight')
        self.backlog.revoke(PROJECT,owner_message='owner-stop')
        confirmed=self.records.set_operation_state(operation['operation_id'],'confirmed',expected_state='unknown',
            result={'native_id':'retained-readback'})
        self.assertEqual(confirmed['state'],'confirmed')
        self.assertEqual(self.backlog.reservation(operation['request']['reservation_id'])['state'],'held')


    def idle(self,*,status='idle',minutes=20):
        from monarchy.cadence import Cadence
        self.records.create_task('idle-source',PROJECT,'00000008-2222-4222-8222-222222222222')
        now=datetime.now(timezone.utc)
        cadence=Cadence(self.records)
        cadence.observe('idle-source','idle-first',generation=1,observed_at=(now-timedelta(minutes=minutes)).isoformat(),native_status='idle')
        cadence.observe('idle-source','idle-last',generation=1,observed_at=now.isoformat(),native_status=status)
        return {'task_id':'idle-source','generation':1,'first_observation_id':'idle-first','last_observation_id':'idle-last'}

    def test_idle_pull_uses_real_distinct_observations_and_one_bounded_read(self):
        grant=self.activate()
        candidate,_,facts,reader=self.selected()
        source=self.idle()
        data={'task_id':'pulled','repository':PROJECT,'owner':'00000008-2222-4222-8222-222222222222',
              'metadata':{'brief':'Prepare the selected tracked item.', 'binding':{
                  'repo':PROJECT,'session_id':'00000008-2222-4222-8222-222222222222',
                  'workspace_id':WORKSPACE,'profile':PROFILE}}}
        result=self.backlog.pull(data,facts,idle_source=source,reader=reader)
        self.assertEqual(result['operation']['state'],'prepared')
        self.assertEqual(result['candidate']['candidate_id'],candidate['candidate_id'])
        self.assertEqual(len(self.records.list_operations()),1)
        self.assertEqual(self.records.get_task('pulled')['metadata']['backlog']['grant_id'],grant['grant_id'])
        with self.assertRaises(Conflict):
            self.backlog.pull(dict(data,task_id='second-pull'),facts,idle_source=source,reader=reader)
        with self.assertRaises(RecordError):self.records.get_task('second-pull')
        self.backlog.release(result['operation']['request']['reservation_id'],'cancel-pull',
            {'kind':'never-admitted','operation_id':result['operation']['operation_id']})
        with self.assertRaises(Conflict):
            self.backlog.pull(dict(data,task_id='reused-idle'),facts,idle_source=source,reader=reader)
        with self.assertRaises(RecordError):self.records.get_task('reused-idle')

    def test_unknown_or_short_idle_does_not_create_a_pull_assignment(self):
        self.activate()
        _,_,facts,reader=self.selected()
        source=self.idle(status='unknown',minutes=19)
        data={'task_id':'held-pull','repository':PROJECT,'owner':'00000008-2222-4222-8222-222222222222',
              'metadata':{'brief':'Prepare.', 'binding':{'repo':PROJECT,
                  'session_id':'00000008-2222-4222-8222-222222222222','workspace_id':WORKSPACE,'profile':PROFILE}}}
        with self.assertRaises(Conflict):self.backlog.pull(data,facts,idle_source=source,reader=reader)
        with self.assertRaises(RecordError):self.records.get_task('held-pull')
        self.assertEqual(self.records.list_operations(),[])

    def test_progress_after_latest_idle_observation_holds_preparation_and_admission(self):
        self.activate()
        candidate,snapshot,_,_=self.selected()
        source=self.idle()
        self.bound(candidate,self.backlog.state(PROJECT))
        operation=self.backlog.prepare('selected',candidate,snapshot,idle_source=source)
        self.records.record_event('late-progress','idle-source',1,'00000008-2222-4222-8222-222222222222',
            'progress',{'summary':'Actual new work','evidence':'new-result'})
        with self.assertRaises(Conflict):
            self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared',
                backlog_snapshot=snapshot)

    def custody(self,task,operation,outcome_id='stopped-proof'):
        reservation=self.backlog.reservation(operation['request']['reservation_id'])
        body={'kind':'writer-custody','generation':task['generation'],'session_id':task['owner'],
              'writer_repository':PROJECT,'branch_ref':reservation['branch_ref'],
              'native_status':'idle','processes_stopped':True,'background_work_clear':True,
              'observed_at':datetime.now(timezone.utc).isoformat(),'evidence_refs':['native-process-readback']}
        return self.records.record_outcome(outcome_id,task['task_id'],body)

    def test_stopped_process_evidence_releases_only_after_uncertain_delivery_is_reconciled(self):
        task=self.writer('one','work/item')
        operation=Court(self.records).prepare_dispatch('one')
        self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared')
        self.records.set_operation_state(operation['operation_id'],'unknown',expected_state='in_flight')
        self.custody(task,operation)
        receipt={'kind':'writer-stopped','outcome_id':'stopped-proof'}
        with self.assertRaises(Conflict):self.backlog.release(operation['request']['reservation_id'],'release',receipt)
        self.records.set_operation_state(operation['operation_id'],'confirmed',expected_state='unknown')
        self.assertEqual(self.backlog.release(operation['request']['reservation_id'],'release',receipt)['state'],'released')
        self.writer('two','work/item',3)
        self.assertEqual(Court(self.records).prepare_dispatch('two')['state'],'prepared')

    def test_v6_unknown_writer_history_is_preserved_and_holds_new_project_writers(self):
        self.records.create_task('legacy',PROJECT,'legacy-session')
        self.records.prepare_operation('old-launch','legacy','create_session',
            {'generation':1,'binding':{'repo':PROJECT,'session_id':'legacy-session'},'text':'Original work'})
        self.records._connection.execute("UPDATE operations SET state='unknown' WHERE operation_id='old-launch'")
        old=self.records.get_operation('old-launch')
        self.records.close()
        import sqlite3
        with sqlite3.connect(str(self.path)) as db:
            db.execute('DROP TABLE dispatch_reservations')
            db.execute('DROP TABLE backlog_events')
            db.execute('PRAGMA user_version=6')
        self.records=CourtRecords(self.path)
        self.addCleanup(self.records.close)
        self.backlog=Backlog(self.records)
        self.assertEqual(self.records.get_operation('old-launch'),old)
        self.writer('new','work/new')
        with self.assertRaises(Conflict):Court(self.records).prepare_dispatch('new')
        held=self.records._connection.execute("SELECT * FROM dispatch_reservations WHERE state='held'").fetchall()
        self.assertEqual(len(held),1)
        self.assertEqual(held[0]['legacy'],1)
        self.records.set_operation_state('old-launch','confirmed',expected_state='unknown')
        with self.assertRaises(Conflict):Court(self.records).prepare_dispatch('new')
        with CourtRecords(self.path) as reopened:
            self.assertEqual(reopened._connection.execute('SELECT count(*) FROM dispatch_reservations').fetchone()[0],1)

    def test_other_assignment_activity_in_same_native_session_interrupts_idle_pull(self):
        self.activate()
        candidate,snapshot,_,_=self.selected()
        source=self.idle()
        self.bound(candidate,self.backlog.state(PROJECT))
        from monarchy.cadence import Cadence
        self.records.create_task('other-current-work',PROJECT,'00000008-2222-4222-8222-222222222222')
        Cadence(self.records).observe('other-current-work','other-working',generation=1,
            observed_at=datetime.now(timezone.utc).isoformat(),native_status='working')
        with self.assertRaises(Conflict):self.backlog.prepare('selected',candidate,snapshot,idle_source=source)

    def test_stop_receipt_before_later_admitted_steer_cannot_release_writer(self):
        task=self.writer('one','work/item')
        operation=Court(self.records).prepare_dispatch('one')
        self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared')
        self.records.set_operation_state(operation['operation_id'],'confirmed',expected_state='in_flight')
        self.records.prepare_operation('later-steer','one','send_message',
            {'generation':1,'binding':task['metadata']['binding'],'text':'Continue scoped work.'})
        self.custody(task,operation)
        self.records.set_operation_state('later-steer','in_flight',expected_state='prepared')
        self.records.set_operation_state('later-steer','confirmed',expected_state='in_flight')
        with self.assertRaises(Conflict):
            self.backlog.release(operation['request']['reservation_id'],'stale-stop',
                {'kind':'writer-stopped','outcome_id':'stopped-proof'})

    def test_same_session_read_only_activity_after_stop_proof_holds_release(self):
        task=self.writer('one','work/item')
        operation=Court(self.records).prepare_dispatch('one')
        self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared')
        self.records.set_operation_state(operation['operation_id'],'confirmed',expected_state='in_flight')
        self.custody(task,operation)
        self.records.create_task('reader',PROJECT,task['owner'],metadata={
            'execution_mode':'read-only','binding':task['metadata']['binding']})
        self.records.prepare_operation('read-after-stop','reader','send_message',
            {'generation':1,'binding':task['metadata']['binding'],'text':'Read current status.'})
        self.records.set_operation_state('read-after-stop','in_flight',expected_state='prepared')
        self.records.set_operation_state('read-after-stop','confirmed',expected_state='in_flight')
        with self.assertRaises(Conflict):
            self.backlog.release(operation['request']['reservation_id'],'stale-stop',
                {'kind':'writer-stopped','outcome_id':'stopped-proof'})

    def test_activation_schedules_one_durable_trial_review_at_actual_start_plus_48_hours(self):
        from monarchy.cadence import Cadence,timestamp
        from monarchy.supervision import identity
        grant=self.activate()
        check_id=identity('backlog-review-check',grant['grant_id'])
        check=Cadence(self.records).get(check_id)
        self.assertEqual(check['recipient'],'secretary')
        self.assertEqual(timestamp(check['due_at'])-timestamp(grant['payload']['activated_at']),timedelta(hours=48))
        self.assertIn('not-due',check['held_reasons'])
        with CourtRecords(self.path) as reopened:
            self.assertEqual(Cadence(reopened).get(check_id)['payload']['grant_id'],grant['grant_id'])

    def test_concurrent_last_slot_reservation_has_one_durable_winner(self):
        import concurrent.futures
        import threading
        Preferences(self.records).override('backlog.builder_cap',1,project=PROJECT,owner_message='one-slot')
        self.writer('one','work/one',2)
        self.writer('two','work/two',3)
        barrier=threading.Barrier(2)
        def reserve(task_id):
            with CourtRecords(self.path) as records:
                barrier.wait()
                try:return Court(records).prepare_dispatch(task_id)['operation_id']
                except Conflict:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,['one','two']))
        self.assertEqual(sum(value is not None for value in results),1)
        self.assertEqual(len(self.records.list_operations()),1)

    def test_active_trial_cap_also_bounds_independently_authorized_project_writers(self):
        self.activate()
        self.writer('manual-one','work/one',2)
        self.writer('manual-two','work/two',3)
        Court(self.records).prepare_dispatch('manual-one')
        with self.assertRaises(Conflict):Court(self.records).prepare_dispatch('manual-two')
        self.backlog.revoke(PROJECT,owner_message='end-trial')
        self.assertEqual(Court(self.records).prepare_dispatch('manual-two')['state'],'prepared')

    def test_later_read_only_assignment_does_not_erase_legacy_writer_custody(self):
        import sqlite3
        self.records.create_task('old',PROJECT,'old-writer')
        self.records.prepare_operation('old-write','old','send_message',{'generation':1,
            'binding':{'repo':PROJECT,'session_id':'old-writer'},'text':'Original work'})
        self.records._connection.execute("UPDATE operations SET state='confirmed' WHERE operation_id='old-write'")
        self.records.assign_task('old','new-reader',expected_generation=1,metadata={'execution_mode':'read-only'})
        self.records.close()
        with sqlite3.connect(str(self.path)) as db:
            db.execute('DROP TABLE dispatch_reservations')
            db.execute('DROP TABLE backlog_events')
            db.execute('PRAGMA user_version=6')
        self.records=CourtRecords(self.path)
        self.addCleanup(self.records.close)
        self.backlog=Backlog(self.records)
        row=self.records._connection.execute('SELECT * FROM dispatch_reservations').fetchone()
        self.assertIsNotNone(row)
        self.assertEqual((row['generation'],row['session_id']),(1,'old-writer'))

    def test_named_event_on_another_same_session_assignment_prevents_idle_pull(self):
        from monarchy.cadence import Cadence
        self.activate()
        candidate,snapshot,_,_=self.selected()
        source=self.idle()
        self.bound(candidate,self.backlog.state(PROJECT))
        self.records.create_task('other',PROJECT,'00000008-2222-4222-8222-222222222222')
        until=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
        self.records.record_outcome('watching','other',{'kind':'watched-event','generation':1,'name':'CI','until':until})
        Cadence(self.records).observe('other','watching-observation',generation=1,
            observed_at=datetime.now(timezone.utc).isoformat(),native_status='idle',
            watched_event={'name':'CI','until':until,'source_ref':{'kind':'outcome','id':'watching'}})
        Cadence(self.records).observe('idle-source','new-last',generation=1,
            observed_at=datetime.now(timezone.utc).isoformat(),native_status='idle')
        source['last_observation_id']='new-last'
        with self.assertRaises(Conflict):self.backlog.prepare('selected',candidate,snapshot,idle_source=source)


    def test_retained_trial_review_box_completes_only_its_exact_scheduled_check(self):
        from unittest.mock import patch
        from monarchy.cadence import Cadence
        from monarchy.preferences import digest
        from monarchy.supervision import identity
        start=datetime.now(timezone.utc)-timedelta(hours=49)
        with patch('monarchy.backlog._now',return_value=start.isoformat()):
            grant=self.activate()
        unknown={key:None for key in ('throughput','ci_cost','review_latency','queue_size')}
        decision=self.backlog.review(PROJECT,unknown,observed_at=(start+timedelta(hours=48)).isoformat(),source_refs=unknown)
        check_id=identity('backlog-review-check',grant['grant_id'])
        cadence=Cadence(self.records)
        with self.assertRaises(Conflict):
            cadence.complete(check_id,'wrong-review',{'decision_id':decision['decision_id'],'decision_digest':'0'*64},
                             completed_at=datetime.now(timezone.utc).isoformat())
        completed=cadence.complete(check_id,'review-prepared',
            {'decision_id':decision['decision_id'],'decision_digest':digest(decision['payload'])},
            completed_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(completed['state'],'completed')
        self.assertEqual(self.records.get_decision(decision['decision_id'])['state'],'pending')


if __name__ == '__main__':
    unittest.main()
