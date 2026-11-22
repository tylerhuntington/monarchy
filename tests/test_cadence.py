"""Durable cadence evidence without native or public actions."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from monarchy.records import CourtRecords, Conflict, RecordError, StaleGeneration
from monarchy.cadence import Cadence

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
SECRETARY = '44444444-4444-4444-8444-444444444444'
WORKER = '22222222-2222-4222-8222-222222222222'


class CadenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'royalty.db'
        self.records = CourtRecords(self.path)
        self.addCleanup(self.records.close)
        with patch('monarchy.records._now', return_value=NOW.isoformat()):
            self.records.create_task('task', 'example/project', 'worker', metadata={
                'binding': {'session_id': WORKER},
                'secretary_binding': {'session_id': SECRETARY}})
        self.cadence = Cadence(self.records)

    def observe(self, identity='native-read-1', minutes=0, status='idle', **kw):
        return self.cadence.observe('task', identity, generation=1,
            observed_at=(NOW + timedelta(minutes=minutes)).isoformat(), native_status=status, **kw)

    def pin(self, zone='America/Los_Angeles', reference='pin-1'):
        from monarchy.preferences import Preferences
        raw = json.dumps({'voice.zone':zone}).encode()
        owner = {'commit':'a'*40,'path':'owner.json','blob':hashlib.sha1(
            b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
            'sha256':hashlib.sha256(raw).hexdigest(),'bytes':raw.decode(),'layer':'owner','repository':''}
        raw = json.dumps({'project.repository':'example/project'}).encode()
        project = {'commit':'a'*40,'path':'project.json','blob':hashlib.sha1(
            b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
            'sha256':hashlib.sha256(raw).hexdigest(),'bytes':raw.decode(),'layer':'project','repository':'example/project'}
        prefs = Preferences(self.records)
        for box in prefs.founding(owner,project):
            self.records.answer_decision(box['decision_id'], {'accept':True},
                expected_revision=box['revision'],owner_message='owner-confirmation')
        prefs.pin(owner,project,owner_message=reference,monarchy_revision='b'*40)
        return prefs

    def bind_task(self, prefs):
        workspace='11111111-1111-4111-8111-111111111111'
        config=prefs.show('example/project')['config']
        data = prefs.bind({'task_id':'task','repository':'example/project','owner':WORKER,
            'metadata':{'brief':'Inspect a bounded task.',
                'binding':{'repo':'example/project','session_id':WORKER,'workspace_id':workspace},
                'secretary_binding':{'repo':'example/project','session_id':SECRETARY,'workspace_id':workspace,
                                     'profile':config['profiles.secretary']['value']},
                'queen_binding':{'repo':'example/project','session_id':'33333333-3333-4333-8333-333333333333',
                                 'workspace_id':workspace,'profile':config['profiles.queen']['value']}}})
        with patch('monarchy.records._now',return_value=NOW.isoformat()):
            return self.records.assign_task('task',WORKER,expected_generation=1,metadata=data['metadata'])

    def test_observation_replay_survives_restart_and_never_relabels_unknown(self):
        observation = self.observe(status='unknown')
        self.assertEqual(observation['payload']['native_status'], 'unknown')
        with CourtRecords(self.path) as other:
            retry = Cadence(other).observe('task', 'native-read-1', generation=1,
                observed_at=NOW.isoformat(), native_status='unknown')
            self.assertEqual(retry, observation)
            with self.assertRaises(Conflict):
                Cadence(other).observe('task', 'native-read-1', generation=1,
                    observed_at=NOW.isoformat(), native_status='idle')
        for generation in (True, 1.0, 0):
            with self.assertRaises(RecordError):
                self.cadence.observe('task', 'bad', generation=generation,
                    observed_at=NOW.isoformat(), native_status='idle')

    def test_due_is_bounded_durable_and_unknown_never_creates_idle_action(self):
        self.observe(status='unknown', minutes=30)
        now = (NOW + timedelta(minutes=30)).isoformat()
        rows = self.cadence.due(now=now)
        self.assertEqual({row['kind'] for row in rows}, {'sweep', 'status'})
        self.assertTrue(all(row['recipient'] == 'secretary' for row in rows))
        self.assertEqual(len(self.cadence.due(now=now, limit=1)), 1)
        with CourtRecords(self.path) as other:
            self.assertEqual(Cadence(other).due(now=now), rows)
        self.assertEqual({r['check_id'] for r in self.cadence.due(
            now=(NOW + timedelta(days=20)).isoformat()) if r['kind'] in {'sweep','status'}},
            {r['check_id'] for r in rows})

    def test_notice_is_durable_intent_not_completion_and_rechecks_pause(self):
        now = (NOW + timedelta(minutes=30)).isoformat()
        checks = self.cadence.due(now=now)
        notice = self.cadence.prepare_notice([checks[0]['check_id']], 'notice-1',
            secretary_session=SECRETARY, created_at=now)
        self.assertEqual(notice['state'], 'prepared')
        self.assertEqual(self.cadence.get(checks[0]['check_id'])['state'], 'pending')
        self.assertEqual(self.cadence.get(checks[0]['check_id'])['notification_intents'][0]['notification_id'],'notice-1')
        with CourtRecords(self.path) as other:
            cadence = Cadence(other)
            self.assertEqual(cadence.get_notice('notice-1'), notice)
            self.assertEqual([r['check_id'] for r in cadence.unnotified(checks, SECRETARY)],
                             [checks[1]['check_id']])
            with self.assertRaises(Conflict):
                cadence.prepare_notice([checks[0]['check_id']], 'notice-2',
                    secretary_session=SECRETARY, created_at=now)
        from monarchy.preferences import Preferences
        Preferences(self.records).override('court.paused', True, owner_message='pause-source')
        with self.assertRaises(Conflict):
            self.cadence.prepare_notice([checks[1]['check_id']], 'notice-3',
                secretary_session=SECRETARY, created_at=now)

    def test_report_expectation_and_receipt_bind_real_current_report(self):
        with patch('monarchy.records._now', return_value=NOW.isoformat()):
            self.records.record_outcome('brief-source', 'task', {'generation':1, 'kind':'assignment'})
        check = self.cadence.expect('task', 'expect-1', generation=1, since=NOW.isoformat(),
            source_ref={'kind':'outcome','id':'brief-source'})
        self.assertEqual(check['due_at'], (NOW + timedelta(minutes=20)).isoformat())
        now = (NOW + timedelta(minutes=21)).isoformat()
        self.assertIn(check['check_id'], [r['check_id'] for r in self.cadence.due(now=now)])
        with self.assertRaises(RecordError):
            self.cadence.complete(check['check_id'], 'receipt', {'event_id':'invented'}, completed_at=now)
        with patch('monarchy.records._now', return_value=now):
            self.records.record_event('report', 'task', 1, 'worker', 'progress', {'summary':'New evidence'})
        complete = self.cadence.complete(check['check_id'], 'receipt', {'event_id':'report'}, completed_at=now)
        self.assertEqual(complete['state'], 'completed')
        self.assertEqual(self.cadence.complete(check['check_id'], 'receipt',
            {'event_id':'report'}, completed_at=now), complete)
        self.assertNotIn(check['check_id'], [r['check_id'] for r in self.cadence.due(now=now)])
        with self.assertRaises(Conflict):
            self.cadence.expect('task', 'expect-1', generation=1, since=now,
                source_ref={'kind':'outcome','id':'brief-source'})

    def steer(self, check, number, at, deadline):
        action = 'Inspect the next scoped failure ' + str(number)
        request = {'generation':1,'binding':{'session_id':WORKER},
                   'sender_session_id':SECRETARY, 'text':'[steer] ' + action + '\nDeadline: ' + deadline}
        with patch('monarchy.records._now', return_value=at):
            self.records.prepare_operation('steer-'+str(number), 'task', 'send_message', request)
            self.records.set_operation_state('steer-'+str(number), 'in_flight', expected_state='prepared')
            self.records.set_operation_state('steer-'+str(number), 'confirmed', expected_state='in_flight',
                result={'native_id':'message-'+str(number)})
        return self.cadence.complete(check['check_id'], 'receipt-'+str(number),
            {'operation_id':'steer-'+str(number), 'action':action, 'deadline':deadline}, completed_at=at)

    def idle_checks(self, minute):
        return [r for r in self.cadence.due(now=(NOW+timedelta(minutes=minute)).isoformat())
                if r['kind'].startswith('idle-')]

    def test_idle_ladder_requires_confirmed_steers_deadlines_and_later_observations(self):
        self.observe()
        first = self.idle_checks(0)[0]
        self.assertEqual(first['kind'], 'idle-action')
        self.observe('poll-2', minutes=1)
        self.assertEqual([r['check_id'] for r in self.idle_checks(1)], [first['check_id']])
        self.steer(first, 1, (NOW+timedelta(minutes=2)).isoformat(), (NOW+timedelta(minutes=10)).isoformat())
        self.assertEqual(self.idle_checks(11), [])
        self.observe('idle-after-first', minutes=11)
        second = self.idle_checks(11)[0]
        self.assertEqual(second['kind'], 'idle-sharper')
        self.steer(second, 2, (NOW+timedelta(minutes=12)).isoformat(), (NOW+timedelta(minutes=20)).isoformat())
        self.observe('unknown-after-second', minutes=21, status='unknown')
        self.assertEqual(self.idle_checks(21), [])
        self.observe('working-is-not-progress', minutes=22, status='working')
        self.observe('idle-after-second', minutes=23)
        blocker = self.idle_checks(23)[0]
        self.assertEqual(blocker['kind'], 'idle-blocker')
        with patch('monarchy.records._now',return_value=(NOW+timedelta(minutes=25)).isoformat()):
            self.records.record_outcome('idle-blocked','task',{'generation':1,'kind':'blocked','source_check':blocker['check_id']})
        with self.assertRaises(Conflict):
            self.cadence.complete(blocker['check_id'],'blocked-receipt',{'outcome_id':'idle-blocked'},
                completed_at=(NOW+timedelta(minutes=24)).isoformat())

    def test_only_retained_new_evidence_resets_idle_and_named_watch_expires(self):
        self.observe()
        first = self.idle_checks(0)[0]
        self.steer(first, 1, (NOW+timedelta(minutes=1)).isoformat(), (NOW+timedelta(minutes=2)).isoformat())
        with patch('monarchy.records._now', return_value=(NOW+timedelta(minutes=3)).isoformat()):
            self.records.record_event('progress', 'task', 1, 'worker', 'progress',
                                      {'summary':'New result', 'evidence':['source-result-1']})
        self.observe('new-progress', minutes=3, status='working', progress_ref='progress')
        self.observe('fresh-idle', minutes=4)
        self.assertEqual(self.idle_checks(4)[0]['kind'], 'idle-action')
        until = (NOW+timedelta(minutes=20)).isoformat()
        with patch('monarchy.records._now', return_value=(NOW+timedelta(minutes=5)).isoformat()):
            self.records.record_outcome('watch', 'task', {'generation':1, 'kind':'watched-event',
                'name':'Exact CI result', 'until':until})
        self.observe('watched-idle', minutes=5, watched_event={
            'name':'Exact CI result', 'until':until, 'source_ref':{'kind':'outcome','id':'watch'}})
        pending = self.idle_checks(6)[0]
        self.assertIn('watched-event', pending['held_reasons'])
        self.assertNotIn('watched-event', self.idle_checks(20)[0]['held_reasons'])
        with self.assertRaises(RecordError):
            self.observe('bad-progress', minutes=6, progress_ref='missing')

    def test_actual_recent_report_prevents_false_stale_status(self):
        at = (NOW + timedelta(minutes=59)).isoformat()
        with patch('monarchy.records._now', return_value=at):
            self.records.record_event('fresh-report', 'task', 1, 'worker', 'progress', {'summary':'Current status'})
        rows = self.cadence.due(now=(NOW+timedelta(minutes=60)).isoformat())
        self.assertNotIn('stale-status', {r['kind'] for r in rows})
        rows = self.cadence.due(now=(NOW+timedelta(minutes=119)).isoformat())
        self.assertIn('stale-status', {r['kind'] for r in rows})

    def test_real_founding_records_are_not_scheduled_and_repin_holds_old_check(self):
        before = self.cadence.due(now=(NOW+timedelta(minutes=30)).isoformat())
        self.pin()
        rows = self.cadence.due(now=(NOW+timedelta(days=365)).isoformat())
        self.assertTrue(all(not (r['task_id'] or '').startswith('court.') for r in rows))
        self.assertIn('configuration-changed', self.cadence.get(before[0]['check_id'])['held_reasons'])

    def test_away_keeps_pinned_secretary_checks_available_but_pause_holds(self):
        prefs = self.pin()
        self.bind_task(prefs)
        now = (NOW+timedelta(minutes=30)).isoformat()
        prefs.override('court.away',True,owner_message='away-source')
        self.assertIn('owner-away',self.cadence.digest('example/project',now=now)['held_reasons'])
        check = next(r for r in self.cadence.due(now=now) if r['kind']=='sweep')
        self.assertEqual(check['held_reasons'],[])
        self.cadence.prepare_notice([check['check_id']],'away-notice',secretary_session=SECRETARY,created_at=now)
        prefs.override('court.paused',True,owner_message='pause-source')
        self.assertIn('royalty-paused',self.cadence.get(check['check_id'],now=now)['held_reasons'])

    def test_census_is_explicit_and_stale_never_becomes_idle(self):
        prefs=self.pin()
        task=self.bind_task(prefs)
        self.cadence.observe('task','census-observation',generation=task['generation'],
            observed_at=NOW.isoformat(),native_status='working')
        slots=[{'slot_id':'builder-1','status':'working','task_id':'task',
                'generation':task['generation'],'observation_id':'census-observation'}]
        saved=self.cadence.census('example/project','census-1',observed_at=NOW.isoformat(),
            authority_ref='actual-roster-source',slots=slots)
        self.assertEqual(saved['payload']['slots'],slots)
        digest=self.cadence.digest('example/project',now=NOW.isoformat())
        self.assertEqual(len(digest['slots']),1)
        self.assertEqual(digest['slots'][0]['status'],'working')
        stale=self.cadence.digest('example/project',now=(NOW+timedelta(minutes=61)).isoformat())
        self.assertEqual(stale['slots'][0]['status'],'unknown')
        self.assertIn('census-stale',stale['warnings'])
        self.assertNotEqual(len(digest['slots']),8)
        with self.assertRaises(Conflict):
            self.cadence.census('example/project','census-1',observed_at=NOW.isoformat(),
                authority_ref='actual-roster-source',slots=[])

    def test_local_calendar_and_owner_prompt_hold_leave_secretary_available(self):
        prefs=self.pin()
        task=self.bind_task(prefs)
        with patch('monarchy.records._now',return_value=NOW.isoformat()):
            self.records.open_decision('owner-box','task',{'generation':task['generation'],'question':'Choose the next action?'})
        at='2026-01-02T16:00:00+00:00'
        self.cadence.census('example/project','census-2',observed_at=at,
            authority_ref='actual-roster',slots=[{'slot_id':'available-1','status':'idle'}])
        rows=self.cadence.due(now=at)
        owner=[r for r in rows if r['recipient']=='queen']
        self.assertEqual({r['kind'] for r in owner},{'digest','reminder'})
        self.assertTrue(all('queen-prompt-held' in r['held_reasons'] for r in owner))
        self.assertTrue(any(r['recipient']=='secretary' and not r['held_reasons'] for r in rows))
        morning=next(r for r in owner if r['kind']=='digest')
        self.assertEqual(morning['due_at'],'2026-01-02T14:57:00+00:00')
        with CourtRecords(self.path) as other:
            self.assertEqual([r['check_id'] for r in Cadence(other).due(now=at)],
                             [r['check_id'] for r in rows])
        after=self.cadence.due(now='2026-01-03T04:00:00+00:00')
        self.assertTrue(all('outside-reminder-window' in r['held_reasons']
                            for r in after if r['kind']=='reminder'))

    def test_new_progress_holds_prior_idle_obligation_and_census_uses_no_superseded_status(self):
        self.observe()
        old=self.idle_checks(0)[0]
        with patch('monarchy.records._now',return_value=(NOW+timedelta(minutes=1)).isoformat()):
            self.records.record_event('new-evidence','task',1,'worker','progress',{'evidence':['new-source']})
        self.observe('new-idle',minutes=2,progress_ref='new-evidence')
        checks=self.idle_checks(2)
        prior=next(r for r in checks if r['check_id']==old['check_id'])
        self.assertIn('superseded-progress',prior['held_reasons'])
        self.assertEqual(sum(not r['held_reasons'] for r in checks),1)
        self.cadence.census('example/project','roster',observed_at=(NOW+timedelta(minutes=2)).isoformat(),
            authority_ref='roster-source',slots=[{'slot_id':'one','status':'idle','task_id':'task',
                'generation':1,'observation_id':'new-idle'}])
        self.observe('unknown-now',minutes=3,status='unknown')
        digest=self.cadence.digest('example/project',now=(NOW+timedelta(minutes=4)).isoformat())
        self.assertEqual(digest['slots'][0]['status'],'unknown')
        self.assertEqual(digest['slots'][0]['reason'],'observation-superseded')

    def test_owner_check_needs_confirmed_matching_forward_not_uncertain_send(self):
        from monarchy.conversation import Conversation
        prefs=self.pin()
        task=self.bind_task(prefs)
        at='2026-01-02T16:00:00+00:00'
        with patch('monarchy.records._now',return_value=NOW.isoformat()):
            self.records.open_decision('decision','task',{'generation':task['generation'],'question':'Choose?'})
        check=next(r for r in self.cadence.due(now=at) if r['kind']=='reminder')
        conversation=Conversation(self.records)
        queen=task['metadata']['queen_binding']['session_id']
        with patch('monarchy.conversation._now',return_value=at):
            conversation.observe(queen,'answered-box','open')
            conversation.observe(queen,'answered-box','close')
        with patch('monarchy.records._now',return_value=at):
            self.records.record_outcome('reminder-source','task',{'kind':'cadence-reminder',
                'generation':task['generation'],'source_check':check['check_id'],
                'decision_id':'decision','decision_revision':1})
            operation=conversation.prepare_forward('reminder-source','A scoped decision is still pending.')
            op=operation['operation_id']
            self.records.set_operation_state(op,'in_flight',expected_state='prepared')
            self.records.set_operation_state(op,'unknown',expected_state='in_flight',result={'uncertain':True})
            with self.assertRaises(Conflict):
                self.cadence.complete(check['check_id'],'delivery-receipt',{'operation_id':op},completed_at=at)
            self.records.set_operation_state(op,'confirmed',expected_state='unknown',result={'native_readback':'matched'})
        complete=self.cadence.complete(check['check_id'],'delivery-receipt',{'operation_id':op},completed_at=at)
        self.assertEqual(complete['state'],'completed')

    def test_global_decision_without_registered_route_is_visible_and_held(self):
        path=Path(self.temp.name)/'unrouted.db'
        with CourtRecords(path) as records:
            records.create_task('court.control','monarchy/court','queen')
            with patch('monarchy.records._now',return_value=NOW.isoformat()):
                records.open_decision('global-box','court.control',{'generation':1,'question':'Confirm the control?'})
            rows=Cadence(records).due(now=NOW.isoformat())
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['kind'],'reminder')
            self.assertIn('queen-route-unavailable',rows[0]['held_reasons'])

    def test_v5_migration_preserves_existing_records_and_rejects_missing_v6_column(self):
        task=self.records.get_task('task')
        self.records.close()
        with sqlite3.connect(self.path) as db:
            for table in ('cadence_notice_checks','cadence_notices','checks','cadence_observations','cadence_census'):
                db.execute('DROP TABLE '+table)
            db.execute('PRAGMA user_version=5')
        with CourtRecords(self.path) as upgraded:
            self.assertEqual(upgraded.get_task('task'),task)
            self.assertEqual(upgraded._connection.execute('PRAGMA user_version').fetchone()[0],6)
        with sqlite3.connect(self.path) as db:
            db.execute('ALTER TABLE checks DROP COLUMN config_digest')
        with self.assertRaises(RecordError):
            CourtRecords(self.path)

    def test_releasing_days_of_owner_hold_keeps_only_current_calendar_occurrences_ready(self):
        from monarchy.conversation import Conversation
        prefs=self.pin()
        task=self.bind_task(prefs)
        with patch('monarchy.records._now',return_value=NOW.isoformat()):
            self.records.open_decision('decision','task',{'generation':task['generation'],'question':'Choose?'})
        for at in ('2026-01-02T16:00:00+00:00','2026-01-02T18:00:00+00:00','2026-01-03T16:00:00+00:00'):
            self.cadence.due(now=at)
        at='2026-01-03T16:00:00+00:00'
        self.cadence.census('example/project','current-roster',observed_at=at,authority_ref='actual-roster',slots=[])
        with patch('monarchy.conversation._now',return_value=at):
            conversation=Conversation(self.records)
            queen=task['metadata']['queen_binding']['session_id']
            conversation.observe(queen,'owner-answer','open')
            conversation.observe(queen,'owner-answer','close')
        owner=[r for r in self.cadence.due(now=at) if r['recipient']=='queen']
        self.assertEqual(sum(not r['held_reasons'] for r in owner if r['kind']=='reminder'),1)
        self.assertEqual(sum(not r['held_reasons'] for r in owner if r['kind']=='digest'),1)

    def prepare_owner_forward(self,check,at,source_id,**extra):
        from monarchy.conversation import Conversation
        task=self.records.get_task('task')
        conversation=Conversation(self.records)
        queen=task['metadata']['queen_binding']['session_id']
        with patch('monarchy.conversation._now',return_value=at):
            conversation.observe(queen,source_id+'-box','open')
            conversation.observe(queen,source_id+'-box','close')
        with patch('monarchy.records._now',return_value=at):
            payload={'kind':'cadence-'+check['kind'],'generation':task['generation'],
                     'source_check':check['check_id'],**extra}
            if check['kind']=='reminder':
                payload.update({k:check['payload'][k] for k in ('decision_id','decision_revision')})
            self.records.record_outcome(source_id,'task',payload)
            return conversation.prepare_forward(source_id,'A retained cadence update is ready.')

    def test_delivery_admission_rechecks_occurrence_and_prevents_second_uncertain_effect(self):
        prefs=self.pin(); task=self.bind_task(prefs)
        with patch('monarchy.records._now',return_value=NOW.isoformat()):
            self.records.open_decision('decision','task',{'generation':task['generation'],'question':'Choose?'})
        at='2026-01-02T16:00:00+00:00'
        check=next(r for r in self.cadence.due(now=at) if r['kind']=='reminder')
        old=self.prepare_owner_forward(check,at,'old-forward')
        with patch('monarchy.records._now',return_value='2026-01-02T18:00:00+00:00'):
            with self.assertRaises(Conflict):
                self.records.set_operation_state(old['operation_id'],'in_flight',expected_state='prepared')
        first=self.prepare_owner_forward(check,at,'first-forward')
        second=self.prepare_owner_forward(check,at,'second-forward')
        with patch('monarchy.records._now',return_value=at):
            self.records.set_operation_state(first['operation_id'],'in_flight',expected_state='prepared')
            self.records.set_operation_state(first['operation_id'],'unknown',expected_state='in_flight',result={'uncertain':True})
            with self.assertRaises(Conflict):
                self.records.set_operation_state(second['operation_id'],'in_flight',expected_state='prepared')
        prefs.override('court.paused',True,owner_message='later-pause')
        self.records.set_operation_state(first['operation_id'],'confirmed',expected_state='unknown',result={'readback':'matched'})

    def test_digest_cannot_use_roster_created_after_its_source_outcome(self):
        prefs=self.pin();self.bind_task(prefs)
        at='2026-01-02T16:00:00+00:00'
        check=next(r for r in self.cadence.due(now=at) if r['kind']=='digest')
        self.cadence.census('example/project','current',observed_at=at,authority_ref='roster',slots=[])
        payload={'authority_ref':'roster','slots':[]}
        census_digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        operation=self.prepare_owner_forward(check,at,'future-roster-forward',census_id='future-roster',census_digest=census_digest)
        with patch('monarchy.records._now',return_value=at):
            with self.assertRaises(Conflict):
                self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared')
        # Historical imported confirmation still cannot be completed using a
        # roster that did not exist when its source outcome was retained.
        self.records._connection.execute("UPDATE operations SET state='confirmed',result=?,updated_at=? WHERE operation_id=?",
            (json.dumps({'historical_readback':'matched'}),at,operation['operation_id']))
        with patch('monarchy.cadence._now',return_value='2026-01-02T16:10:00+00:00'):
            self.cadence.census('example/project','future-roster',observed_at='2026-01-02T16:10:00+00:00',authority_ref='roster',slots=[])
        with self.assertRaises(Conflict):
            self.cadence.complete(check['check_id'],'invalid-backfill',{'operation_id':operation['operation_id']},
                                  completed_at='2026-01-02T16:11:00+00:00')

    def test_digest_forward_binds_projection_and_preserves_later_read_only_reconciliation(self):
        prefs=self.pin();task=self.bind_task(prefs)
        at='2026-01-02T16:00:00+00:00'
        self.cadence.observe('task','working',generation=task['generation'],observed_at=at,native_status='working')
        with patch('monarchy.cadence._now',return_value=at):
            self.cadence.census('example/project','roster',observed_at=at,authority_ref='actual-roster',slots=[
                {'slot_id':'builder','status':'working','task_id':'task','generation':task['generation'],'observation_id':'working'}])
        check=next(r for r in self.cadence.due(now=at) if r['kind']=='digest')
        preview=self.cadence.digest('example/project',now=at)
        operation=self.prepare_owner_forward(check,at,'digest-source',**{k:preview[k] for k in ('census_id','census_digest','slots','warnings')})
        with patch('monarchy.records._now',return_value=at):
            self.records.set_operation_state(operation['operation_id'],'in_flight',expected_state='prepared')
            self.records.set_operation_state(operation['operation_id'],'unknown',expected_state='in_flight',result={'uncertain':True})
        later='2026-01-02T16:10:00+00:00'
        self.cadence.observe('task','unknown',generation=task['generation'],observed_at=later,native_status='unknown')
        with patch('monarchy.records._now',return_value=later):
            self.records.set_operation_state(operation['operation_id'],'confirmed',expected_state='unknown',result={'readback':'matched'})
        self.records.assign_task('task','successor',expected_generation=task['generation'])
        result=self.cadence.complete(check['check_id'],'digest-readback',{'operation_id':operation['operation_id']},completed_at=later)
        self.assertEqual(result['state'],'completed')

    def test_digest_uses_owner_dst_offset_and_one_identity_per_local_day(self):
        self.bind_task(self.pin())
        before=self.cadence.due(now='2026-03-07T14:57:00+00:00')
        day_one=next(r for r in before if r['kind']=='digest')
        after=self.cadence.due(now='2026-03-08T13:57:00+00:00')
        day_two=[r for r in after if r['kind']=='digest' and r['payload']['local_date']=='2026-03-08']
        self.assertEqual(len(day_two),1)
        self.assertEqual(day_two[0]['due_at'],'2026-03-08T13:57:00+00:00')
        self.assertNotEqual(day_one['check_id'],day_two[0]['check_id'])
        with CourtRecords(self.path) as other:
            repeated=Cadence(other).due(now='2026-03-08T20:00:00+00:00')
            self.assertEqual([r['check_id'] for r in repeated if r['kind']=='digest' and
                r['payload']['local_date']=='2026-03-08'],[day_two[0]['check_id']])

    def test_global_reminder_identity_survives_new_representative_project(self):
        task=self.bind_task(self.pin())
        with patch('monarchy.records._now',return_value=NOW.isoformat()):
            self.records.create_task('court.control','monarchy/court','queen')
            self.records.open_decision('global-box','court.control',{'generation':1,'question':'Confirm the control?'})
        at='2026-01-02T16:00:00+00:00'
        first=next(r for r in self.cadence.due(now=at) if r['kind']=='reminder')
        with patch('monarchy.records._now',return_value=NOW.isoformat()):
            self.records.create_task('new-project-task','aaa/project','worker',metadata=task['metadata'])
        later=[r for r in self.cadence.due(now=at) if r['kind']=='reminder']
        self.assertEqual([r['check_id'] for r in later],[first['check_id']])


if __name__ == '__main__':
    unittest.main()
