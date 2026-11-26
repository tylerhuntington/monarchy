"""Activation-bound measurement review, without native reads or grant changes."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monarchy.backlog_metrics import review_due
from monarchy.backlog import Backlog
from monarchy.preferences import digest
from monarchy.records import CourtRecords,RecordError,Conflict


PROJECT='example/project'
START=datetime(2026,1,1,tzinfo=timezone.utc)
END=START+timedelta(hours=48)
METRICS=('throughput','ci_cost','review_latency','queue_size')


def grant():
    return {'project':PROJECT,'grant_id':'grant-example','state':'active',
            'payload':{'activated_at':START.isoformat(),'review_hours':48}}


class BacklogMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.records=CourtRecords(Path(self.temp.name)/'metrics.db')
        self.addCleanup(self.records.close)
        self.backlog=Backlog(self.records)
        with patch('monarchy.backlog._now',return_value=START.isoformat()):
            proposal=self.backlog.propose(PROJECT,[{'kind':'issue','number':1}],owner_message='activation-request')
            self.records.answer_decision(proposal['decision_id'],{'accept':True},
                expected_revision=1,owner_message='actual-owner-answer')
            self.active=self.backlog.apply(proposal['decision_id'])

    def source(self,metric,data,*,suffix='',**changes):
        self.records.create_task('metrics-source',PROJECT,'collector')
        payload={'kind':'backlog.metrics-source','metric':metric,'project':PROJECT,
                 'grant_id':self.active['grant_id'],'window_start':START.isoformat(),
                 'window_end':END.isoformat(),'observed_at':(END+timedelta(seconds=10)).isoformat(),
                 'source_ref':'native-measurement-'+metric,'complete':True,'data':data}
        payload.update(changes)
        outcome_id='measurement-'+metric+suffix
        with patch('monarchy.records._now',return_value=(END+timedelta(seconds=20)).isoformat()):
            self.records.record_outcome(outcome_id,'metrics-source',payload)
        return {'outcome_id':outcome_id,'digest':digest(payload)}

    def test_due_time_is_bound_to_actual_activation_and_frozen_trial_length(self):
        before=review_due(grant(),now=(START+timedelta(hours=47)).isoformat())
        due=review_due(grant(),now=(START+timedelta(hours=48)).isoformat())
        self.assertEqual(before['check_id'],due['check_id'])
        self.assertEqual(due['due_at'],(START+timedelta(hours=48)).isoformat())
        self.assertFalse(before['due'])
        self.assertTrue(due['due'])
        self.assertEqual(due['kind'],'backlog-review')
        self.assertEqual(due['recipient'],'secretary')
        self.assertEqual(due['payload']['grant_id'],'grant-example')
        with self.assertRaises(RecordError):
            review_due(grant(),now=(START-timedelta(seconds=1)).isoformat())

    def test_unknown_measurements_open_one_exact_owner_box_without_changing_authority(self):
        from monarchy.backlog_metrics import review
        unknown={key:None for key in METRICS}
        with patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
            decision=review(self.records,PROJECT,unknown,observed_at=END.isoformat(),source_refs=unknown)
            self.assertEqual(review(self.records,PROJECT,unknown,
                observed_at=END.isoformat(),source_refs=unknown),decision)
        self.assertEqual(decision['task_id'],'court.backlog-review')
        self.assertEqual(decision['state'],'pending')
        self.assertEqual(decision['payload']['window'],{'start':START.isoformat(),
            'end':END.isoformat(),'hours':48.0})
        for metric in decision['payload']['metrics'].values():
            self.assertEqual(metric['state'],'unknown')
            self.assertIsNone(metric['value'])
        self.records.answer_decision(decision['decision_id'],{'accept':True},
            expected_revision=1,owner_message='review-recorded')
        with self.assertRaises(Conflict):
            self.backlog.apply(decision['decision_id'])
        self.assertEqual(self.backlog.state(PROJECT)['grant_id'],self.active['grant_id'])

    def test_measurements_are_derived_from_exact_retained_sources_and_measured_window(self):
        from monarchy.backlog_metrics import review
        sources={
            'throughput':self.source('throughput',[
                {'repository':PROJECT,'number':number,'source_revision':'a'*40,
                 'merged_at':(START+timedelta(hours=number)).isoformat()} for number in (1,2)]),
            'ci_cost':self.source('ci_cost',{'amount':'12.50','currency':'USD'}),
            'review_latency':self.source('review_latency',[
                {'candidate_id':'candidate-'+str(hours),'ready_at':(START+timedelta(hours=1)).isoformat(),
                 'reviewed_at':(START+timedelta(hours=1+hours)).isoformat()} for hours in (2,4)]),
            'queue_size':self.source('queue_size',['candidate-pending'])}
        measurements={'throughput':1.0,'ci_cost':{'amount':'12.50','currency':'USD'},
                      'review_latency':3.0,'queue_size':1}
        with patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
            result=review(self.records,PROJECT,measurements,observed_at=END.isoformat(),source_refs=sources)
        for metric,value in measurements.items():
            self.assertEqual(result['payload']['metrics'][metric]['state'],'known')
            self.assertEqual(result['payload']['metrics'][metric]['value'],value)
            self.assertEqual(result['payload']['metrics'][metric]['source'],sources[metric])


    def test_replay_does_not_return_unvalidated_revised_measurements(self):
        from monarchy.backlog_metrics import review
        unknown={key:None for key in METRICS}
        with patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
            first=review(self.records,PROJECT,unknown,observed_at=END.isoformat(),source_refs=unknown)
            changed=dict(first['payload'],window={'start':START.isoformat(),'end':END.isoformat(),'hours':99})
            self.records.revise_decision(first['decision_id'],changed,expected_revision=1)
            with self.assertRaises(Conflict):
                review(self.records,PROJECT,unknown,observed_at=END.isoformat(),source_refs=unknown)


    def test_complete_empty_sources_are_zero_but_incomplete_and_unsampled_are_unknown(self):
        from monarchy.backlog_metrics import review
        sources={key:self.source(key,[],complete=key!='ci_cost') for key in METRICS}
        measurements={'throughput':0.0,'ci_cost':None,'review_latency':None,'queue_size':0}
        with patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
            result=review(self.records,PROJECT,measurements,observed_at=END.isoformat(),source_refs=sources)
        values=result['payload']['metrics']
        self.assertEqual(values['throughput']['state'],'known')
        self.assertEqual(values['queue_size']['state'],'known')
        self.assertEqual(values['ci_cost']['reason'],'coverage-incomplete')
        self.assertEqual(values['review_latency']['reason'],'no-completed-reviews')

    def test_early_or_future_window_does_not_create_review_or_change_grant(self):
        from monarchy.backlog_metrics import review
        unknown={key:None for key in METRICS}
        for end in (END-timedelta(seconds=1),END+timedelta(minutes=2)):
            with self.subTest(end=end),patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
                with self.assertRaises(Conflict):
                    review(self.records,PROJECT,unknown,observed_at=end.isoformat(),source_refs=unknown)
        self.assertEqual(self.records.list_decisions(task_id='court.backlog-review'),[])
        self.assertEqual(self.backlog.state(PROJECT)['grant_id'],self.active['grant_id'])


    def test_source_provenance_window_and_coverage_types_are_exact(self):
        from monarchy.backlog_metrics import review
        changes=[{'window_start':(START+timedelta(seconds=1)).isoformat()},
                 {'window_end':(END-timedelta(seconds=1)).isoformat()},
                 {'observed_at':(END-timedelta(seconds=1)).isoformat()},
                 {'observed_at':(END+timedelta(minutes=2)).isoformat()},
                 {'project':'example/other'},{'grant_id':'old-grant'},{'complete':1}]
        for index,change in enumerate(changes):
            with self.subTest(change=change):
                source=self.source('throughput',[],suffix=str(index),**change)
                refs={key:source if key=='throughput' else None for key in METRICS}
                metrics={key:0.0 if key=='throughput' else None for key in METRICS}
                with patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
                    with self.assertRaises(RecordError):
                        review(self.records,PROJECT,metrics,observed_at=END.isoformat(),source_refs=refs)
        self.assertEqual(self.records.list_decisions(task_id='court.backlog-review'),[])

    def test_source_digest_and_aggregate_mismatch_never_produce_a_box(self):
        from monarchy.backlog_metrics import review
        reference=self.source('queue_size',['one'])
        refs={key:reference if key=='queue_size' else None for key in METRICS}
        values={key:0 if key=='queue_size' else None for key in METRICS}
        with patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
            with self.assertRaises(Conflict):
                review(self.records,PROJECT,values,observed_at=END.isoformat(),source_refs=refs)
            values['queue_size']=1
            reference['digest']='0'*64
            with self.assertRaises(Conflict):
                review(self.records,PROJECT,values,observed_at=END.isoformat(),source_refs=refs)
        self.assertEqual(self.records.list_decisions(task_id='court.backlog-review'),[])


    def test_duplicate_and_out_of_window_events_cannot_inflate_measurements(self):
        from monarchy.backlog_metrics import review
        row={'repository':PROJECT,'number':1,'source_revision':'a'*40,
             'merged_at':(START+timedelta(hours=1)).isoformat()}
        datasets=[[row,row],[dict(row,merged_at=END.isoformat())],
                  [dict(row,number=True)],[dict(row,source_revision='short')]]
        for index,data in enumerate(datasets):
            source=self.source('throughput',data,suffix=str(index))
            refs={key:source if key=='throughput' else None for key in METRICS}
            metrics={key:len(data)/2 if key=='throughput' else None for key in METRICS}
            with self.subTest(index=index),patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
                with self.assertRaises(RecordError):
                    review(self.records,PROJECT,metrics,observed_at=END.isoformat(),source_refs=refs)

    def test_changed_measurement_replay_conflicts_instead_of_opening_another_box(self):
        from monarchy.backlog_metrics import review
        unknown={key:None for key in METRICS}
        with patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(hours=2)).isoformat()):
            first=review(self.records,PROJECT,unknown,observed_at=END.isoformat(),source_refs=unknown)
            with self.assertRaises(Conflict):
                review(self.records,PROJECT,unknown,observed_at=(END+timedelta(hours=1)).isoformat(),source_refs=unknown)
            with CourtRecords(self.records.path) as reopened:
                again=review(reopened,PROJECT,unknown,observed_at=END.isoformat(),source_refs=unknown)
                self.assertEqual(again,first)
        self.assertEqual(len(self.records.list_decisions(task_id='court.backlog-review')),1)

    def test_replay_rechecks_current_review_task_custody(self):
        from monarchy.backlog_metrics import review
        unknown={key:None for key in METRICS}
        with patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
            review(self.records,PROJECT,unknown,observed_at=END.isoformat(),source_refs=unknown)
            self.records.assign_task('court.backlog-review','different-role',expected_generation=1)
            with self.assertRaises(Conflict):
                review(self.records,PROJECT,unknown,observed_at=END.isoformat(),source_refs=unknown)


    def test_invalid_cost_queue_and_latency_sources_are_rejected_before_aggregation(self):
        from monarchy.backlog_metrics import review
        latency=[{'candidate_id':'one','ready_at':(START+timedelta(hours=3)).isoformat(),
                  'reviewed_at':(START+timedelta(hours=2)).isoformat()}]
        cases=[('ci_cost',{'amount':'NaN','currency':'USD'},{'amount':'NaN','currency':'USD'}),
               ('ci_cost',{'amount':'-1','currency':'USD'},{'amount':'-1','currency':'USD'}),
               ('queue_size',['same','same'],2),('queue_size',[True],1),
               ('queue_size',['item-'+str(i) for i in range(101)],101),
               ('review_latency',latency,-1.0)]
        for index,(metric,data,declared) in enumerate(cases):
            reference=self.source(metric,data,suffix=str(index))
            refs={key:reference if key==metric else None for key in METRICS}
            values={key:declared if key==metric else None for key in METRICS}
            with self.subTest(metric=metric,index=index),patch('monarchy.backlog_metrics._now',return_value=(END+timedelta(minutes=1)).isoformat()):
                with self.assertRaises(RecordError):
                    review(self.records,PROJECT,values,observed_at=END.isoformat(),source_refs=refs)


if __name__=='__main__':
    unittest.main()
