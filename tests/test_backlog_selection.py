"""Bounded source reads and deterministic selection, without native writes."""
import copy
from datetime import datetime, timezone
import json
import subprocess
import unittest

from monarchy.backlog_selection import GitHubBacklog
from monarchy.config import resolve
from monarchy.records import RecordError, Conflict


PROJECT = 'example/project'
HEAD = 'a' * 40
BASE = 'b' * 40
AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def connection(nodes=()):
    return {'nodes': list(nodes), 'pageInfo': {'hasNextPage': False}}


def native(number=1, kind='PullRequest'):
    value = {'__typename': kind, 'id': 'node-' + str(number), 'number': number,
             'state': 'OPEN', 'updatedAt': '2026-01-01T00:00:00Z',
             'title': 'Example tracked work', 'body': 'A bounded implementation.',
             'labels': connection(), 'milestone': None, 'assignees': connection()}
    if kind == 'PullRequest':
        value.update(merged=False, headRefName='work/Example', headRefOid=HEAD,
                     headRepository={'nameWithOwner': PROJECT}, closingIssuesReferences=connection())
    else:
        value.update(stateReason=None, blockedBy=connection(), closedByPullRequestsReferences=connection())
    return {'data': {'repository': {'nameWithOwner': PROJECT,
            'defaultBranchRef': {'name': 'main', 'target': {'oid': BASE}},
            'issueOrPullRequest': value}}}


def dependency(number=9, state='OPEN', reason=None):
    return {'id':'dependency-'+str(number),'number':number,'state':state,
            'stateReason':reason,'repository':{'nameWithOwner':PROJECT}}


def linked_pr(number=8):
    value=native(number)['data']['repository']['issueOrPullRequest']
    return {key:value[key] for key in ('id','number','state','merged','headRefName',
            'headRefOid','headRepository')} | {'repository':{'nameWithOwner':PROJECT}}


class NativeReads:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        number = json.loads(kwargs['input'])['variables']['number']
        return subprocess.CompletedProcess(args, 0, json.dumps(self.responses[number]), '')


class BacklogSelectionTests(unittest.TestCase):
    def snapshot(self, values):
        refs = [{'kind': 'issue' if v['data']['repository']['issueOrPullRequest']['__typename'] == 'Issue'
                 else 'pull-request', 'number': n} for n,v in values.items()]
        return GitHubBacklog(runner=NativeReads(values), now=lambda: AT).read(PROJECT, refs)

    def classification(self, item, **changes):
        result = {'reference': {'kind': item['kind'], 'number': item['number']},
                  'source_digest': item['source_digest'], 'bucket': 'open-prs',
                  'priority': 2, 'size': 2, 'wanted': True, 'dependencies': [],
                  'dependencies_complete': True, 'ownership': 'clear',
                  'planned_branch': None, 'priority_surface': None,
                  'evidence_ref': 'classification-evidence'}
        result.update(changes)
        return result

    def test_read_preserves_actual_branch_identity_and_semantic_digest(self):
        runner = NativeReads({1: native()})
        reader = GitHubBacklog(runner=runner, now=lambda: AT)
        reference = [{'kind': 'pull-request', 'number': 1}]
        first = reader.read(PROJECT, reference)
        later = GitHubBacklog(runner=runner, now=lambda: AT.replace(hour=1)).read(PROJECT, reference)
        self.assertEqual(first['items'][0]['branch'], 'work/Example')
        self.assertEqual(first['items'][0]['source_revision'], HEAD)
        self.assertEqual(first['items'][0]['branch_repository'], PROJECT)
        self.assertEqual(first['digest'], later['digest'])
        self.assertNotEqual(first['observed_at'], later['observed_at'])
        self.assertNotIn('body', first['items'][0])
        self.assertNotIn('title', first['items'][0])

    def test_select_uses_category_then_priority_then_size_with_stable_ties(self):
        from monarchy.backlog_selection import select, validate_candidate
        snapshot = self.snapshot({1: native(1), 2: native(2), 3: native(3,'Issue')})
        classifications = [self.classification(item, size=1 if item['number']==2 else 2,
            bucket='other-bugs' if item['kind']=='issue' else 'open-prs',
            priority=0 if item['kind']=='issue' else 2,
            planned_branch='work/new' if item['kind']=='issue' else None) for item in snapshot['items']]
        result = select(snapshot, resolve(), classifications)
        self.assertEqual(result['candidate']['number'], 2)
        self.assertEqual(result['held'], [])
        self.assertEqual(validate_candidate(result['candidate'], snapshot, now=AT), result['candidate'])
        reordered = copy.deepcopy(classifications)
        reordered.reverse()
        self.assertEqual(select(snapshot, resolve(), reordered)['candidate'], result['candidate'])

    def test_unknown_or_negative_classification_holds_without_defaulting_to_remaining(self):
        from monarchy.backlog_selection import select
        snapshot=self.snapshot({1:native()})
        for field,value in [('bucket',None),('priority',None),('size',None),('wanted',None),
                            ('wanted',False),('dependencies_complete',None),
                            ('dependencies_complete',False),('ownership','unknown'),('ownership','owned')]:
            with self.subTest(field=field,value=value):
                fact=self.classification(snapshot['items'][0],**{field:value})
                result=select(snapshot,resolve(),[fact])
                self.assertIsNone(result['candidate'])
                self.assertTrue(result['held'][0]['reasons'])

    def test_native_relationships_override_a_clear_classification(self):
        from monarchy.backlog_selection import select
        cases=[('blockedBy',connection([dependency()])),
               ('blockedBy',connection([dependency(state='CLOSED',reason='NOT_PLANNED')])),
               ('blockedBy',{'nodes':[],'pageInfo':{'hasNextPage':True}}),
               ('assignees',connection([{'id':'active-assignee'}])),
               ('closedByPullRequestsReferences',connection([linked_pr()]))]
        for key,value in cases:
            with self.subTest(key=key,value=value):
                response=native(1,'Issue')
                response['data']['repository']['issueOrPullRequest'][key]=value
                snapshot=self.snapshot({1:response})
                fact=self.classification(snapshot['items'][0],bucket='other-bugs',planned_branch='work/new')
                result=select(snapshot,resolve(),[fact])
                self.assertIsNone(result['candidate'], result['held'])
                self.assertTrue(result['held'])

    def test_closed_pr_requires_wanted_parked_category_and_a_current_open_issue(self):
        from monarchy.backlog_selection import select
        response=native()
        pr=response['data']['repository']['issueOrPullRequest']
        pr['state']='CLOSED'
        snapshot=self.snapshot({1:response})
        fact=self.classification(snapshot['items'][0],bucket='wanted-parked-prs')
        self.assertIsNone(select(snapshot,resolve(),[fact])['candidate'])
        issue=native(9,'Issue')['data']['repository']['issueOrPullRequest']
        issue['repository']={'nameWithOwner':PROJECT}
        pr['closingIssuesReferences']=connection([issue])
        snapshot=self.snapshot({1:response})
        fact=self.classification(snapshot['items'][0],bucket='wanted-parked-prs')
        self.assertEqual(select(snapshot,resolve(),[fact])['candidate']['number'],1)
        fact['bucket']='open-prs'
        self.assertIsNone(select(snapshot,resolve(),[fact])['candidate'])
        pr.update(state='MERGED',merged=True)
        snapshot=self.snapshot({1:response})
        fact=self.classification(snapshot['items'][0],bucket='wanted-parked-prs')
        self.assertIsNone(select(snapshot,resolve(),[fact])['candidate'])

    def test_priority_epic_requires_an_actual_configured_priority_surface_or_milestone(self):
        from monarchy.backlog_selection import select
        response=native(1,'Issue')
        snapshot=self.snapshot({1:response})
        fact=self.classification(snapshot['items'][0],bucket='priority-epics',planned_branch='work/new')
        self.assertIsNone(select(snapshot,resolve(),[fact])['candidate'])
        config=resolve(project={'project.priority_surfaces':['Example Surface']})
        fact['priority_surface']='Example Surface'
        self.assertIsNotNone(select(snapshot,config,[fact])['candidate'])
        fact['priority_surface']=None
        response['data']['repository']['issueOrPullRequest']['milestone']={'title':'Example Milestone'}
        snapshot=self.snapshot({1:response})
        fact['source_digest']=snapshot['items'][0]['source_digest']
        self.assertIsNone(select(snapshot,config,[fact])['candidate'])
        config=resolve(project={'project.priority_milestones':['Example Milestone']})
        self.assertIsNotNone(select(snapshot,config,[fact])['candidate'])

    def test_reader_rejects_ambiguous_json_and_late_reads_without_echoing_sources(self):
        plain=json.dumps(native())
        samples=[plain[:-1]+',"private":NaN}', plain[:-1]+',"private":Infinity}',
                 plain.replace('"number": 1','"number": 8, "number": 1')]
        for raw in samples:
            with self.subTest(raw=raw[:25]):
                def runner(args, **kwargs):
                    return subprocess.CompletedProcess(args,0,raw,'PRIVATE ERROR')
                with self.assertRaises(RecordError) as error:
                    GitHubBacklog(runner=runner).read(PROJECT,[{'kind':'pull-request','number':1}])
                self.assertNotIn('PRIVATE',str(error.exception))
                self.assertNotIn('private',str(error.exception))
        ticks=iter([0,0,31])
        with self.assertRaises(RecordError):
            GitHubBacklog(runner=NativeReads({1:native()}),clock=lambda:next(ticks)).read(
                PROJECT,[{'kind':'pull-request','number':1}])


    def test_input_bounds_reject_bool_identifiers_unbounded_reads_and_forged_item_types(self):
        from monarchy.backlog_selection import select
        from monarchy.preferences import digest
        for references in ([{'kind':[], 'number':1}], [{'kind':'issue','number':True}],
                           [{'kind':'issue','number':1}]*2,
                           [{'kind':'issue','number':n} for n in range(1,22)]):
            with self.subTest(references=references):
                with self.assertRaises(RecordError):
                    GitHubBacklog(runner=NativeReads({})).read(PROJECT,references)
        for kwargs in ({'timeout':True},{'timeout':float('nan')},{'timeout':61},
                       {'max_bytes':True},{'max_bytes':1048577}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RecordError):
                GitHubBacklog(**kwargs)
        snapshot=self.snapshot({1:native()})
        for key,value in [('number',True),('complete',1),('source_revision','short'),('branch','@')]:
            changed=copy.deepcopy(snapshot)
            item=changed['items'][0]
            item[key]=value
            item['source_digest']=digest({k:v for k,v in item.items() if k!='source_digest'})
            changed['digest']=digest({k:changed[k] for k in ('repository','references','items')})
            fact=self.classification(item)
            with self.subTest(key=key),self.assertRaises(RecordError):
                select(changed,resolve(),[fact])


    def test_shared_completed_dependency_is_not_confused_with_conflicting_source_edges(self):
        from monarchy.backlog_selection import select
        response=native()
        issues=[]
        for number in (10,11):
            issue=native(number,'Issue')['data']['repository']['issueOrPullRequest']
            issue['repository']={'nameWithOwner':PROJECT}
            issue['blockedBy']=connection([dependency(state='CLOSED',reason='COMPLETED')])
            issues.append(issue)
        response['data']['repository']['issueOrPullRequest']['closingIssuesReferences']=connection(issues)
        snapshot=self.snapshot({1:response})
        self.assertEqual(len(snapshot['items'][0]['dependencies']),1)
        self.assertIsNotNone(select(snapshot,resolve(),[self.classification(snapshot['items'][0])])['candidate'])
        issues[1]['blockedBy']['nodes'][0]['state']='OPEN'
        with self.assertRaises(RecordError):
            self.snapshot({1:response})


    def test_admission_rejects_tampered_candidate_and_requires_a_separate_read_receipt(self):
        from monarchy.backlog_selection import select,validate_candidate
        snapshot=self.snapshot({1:native()})
        fact=self.classification(snapshot['items'][0],priority=0)
        candidate=select(snapshot,resolve(),[fact])['candidate']
        changed=copy.deepcopy(candidate)
        changed['rank'][1]=False
        with self.assertRaises(Conflict):
            validate_candidate(changed,snapshot,config=resolve(),now=AT)
        with self.assertRaises(RecordError):
            validate_candidate(candidate,candidate['selection']['snapshot'],config=resolve(),now=AT)
        current=copy.deepcopy(snapshot)
        current['observed_at']='2026-01-01T01:00:00+00:00'
        self.assertEqual(validate_candidate(candidate,current,config=resolve(),now=AT.replace(hour=1)),candidate)
        order=list(reversed(resolve()['backlog.selection_order']['value']))
        with self.assertRaises(Conflict):
            validate_candidate(candidate,current,config=resolve(project={'backlog.selection_order':order}),now=AT.replace(hour=1))


    def test_full_order_and_configured_permutation_choose_only_eligible_scope_items(self):
        from monarchy.backlog_selection import select
        responses={n:native(n,'PullRequest' if n<3 else 'Issue') for n in range(1,7)}
        parked=responses[2]['data']['repository']['issueOrPullRequest']
        parked['state']='CLOSED'
        issue=native(10,'Issue')['data']['repository']['issueOrPullRequest']
        issue['repository']={'nameWithOwner':PROJECT}
        parked['closingIssuesReferences']=connection([issue])
        config=resolve(project={'project.priority_surfaces':['Example Surface']})
        order=config['backlog.selection_order']['value']
        snapshot=self.snapshot(responses)
        facts=[self.classification(item,bucket=order[item['number']-1],
                priority_surface='Example Surface' if item['number']==3 else None,
                planned_branch='work/item-'+str(item['number']) if item['kind']=='issue' else None)
               for item in snapshot['items']]
        reverse=resolve(project={'project.priority_surfaces':['Example Surface'],
                                 'backlog.selection_order':list(reversed(order))})
        self.assertEqual(select(snapshot,reverse,facts)['candidate']['number'],6)
        for number in range(1,7):
            result=select(snapshot,config,facts)
            self.assertEqual(result['candidate']['number'],number)
            next(f for f in facts if f['reference']['number']==number)['wanted']=False
        self.assertIsNone(select(snapshot,config,facts)['candidate'])

    def test_changed_source_or_scope_invalidates_admission_and_classification(self):
        from monarchy.backlog_selection import select,validate_candidate
        snapshot=self.snapshot({1:native(),2:native(2)})
        facts=[self.classification(item) for item in snapshot['items']]
        candidate=select(snapshot,resolve(),facts)['candidate']
        changes=[('headRefOid','c'*40),('headRefName','work/Changed'),
                 ('body','Changed source.'),('labels',connection([{'name':'changed'}])),
                 ('assignees',connection([{'id':'assigned'}]))]
        for key,value in changes:
            with self.subTest(key=key):
                response=native()
                response['data']['repository']['issueOrPullRequest'][key]=value
                fresh=self.snapshot({1:response,2:native(2)})
                with self.assertRaises(Conflict):
                    validate_candidate(candidate,fresh,config=resolve(),now=AT)
                result=select(fresh,resolve(),facts)
                self.assertIn('classification-stale',result['held'][0]['reasons'])
        unrelated=native(2)
        unrelated['data']['repository']['issueOrPullRequest']['body']='Changed ranking evidence.'
        with self.assertRaises(Conflict):
            validate_candidate(candidate,self.snapshot({1:native(),2:unrelated}),config=resolve(),now=AT)
        with self.assertRaises(Conflict):
            validate_candidate(candidate,self.snapshot({1:native()}),config=resolve(),now=AT)
        original=copy.deepcopy((snapshot,facts,candidate))
        validate_candidate(candidate,snapshot,config=resolve(),now=AT)
        select(snapshot,resolve(),facts)
        self.assertEqual((snapshot,facts,candidate),original)

    def test_supplemental_dependencies_require_retained_complete_dispositions(self):
        from monarchy.backlog_selection import select
        response=native(2,'Issue')
        dependency_item=response['data']['repository']['issueOrPullRequest']
        dependency_item.update(state='CLOSED',stateReason='COMPLETED')
        snapshot=self.snapshot({1:native(1,'Issue'),2:response})
        item=next(v for v in snapshot['items'] if v['number']==1)
        fact=self.classification(item,bucket='other-bugs',planned_branch='work/new',
                                 dependencies=[{'repository':PROJECT,'number':2}])
        self.assertEqual(select(snapshot,resolve(),[fact])['candidate']['number'],1)
        fact['dependencies'][0]['number']=3
        self.assertIsNone(select(snapshot,resolve(),[fact])['candidate'])

    def test_reader_errors_and_relationship_caps_never_become_empty_evidence(self):
        from monarchy.backlog_selection import select
        for response in ({'errors':[{'message':'PRIVATE SOURCE'}]}, {'data':{'repository':None}},
                         {'data':{'repository':{'nameWithOwner':'other/project'}}}):
            with self.subTest(response=response),self.assertRaises(RecordError) as caught:
                GitHubBacklog(runner=NativeReads({1:response})).read(
                    PROJECT,[{'kind':'pull-request','number':1}])
            self.assertNotIn('PRIVATE SOURCE',str(caught.exception))
        for field in ('labels','assignees','closingIssuesReferences'):
            response=native()
            response['data']['repository']['issueOrPullRequest'][field]['pageInfo']['hasNextPage']=True
            snapshot=self.snapshot({1:response})
            self.assertIsNone(select(snapshot,resolve(),[self.classification(snapshot['items'][0])])['candidate'])
        with self.assertRaises(RecordError):
            GitHubBacklog(runner=NativeReads({1:native()}),max_bytes=100).read(
                PROJECT,[{'kind':'pull-request','number':1}])

    def test_fixed_query_is_read_only_and_supplied_values_never_become_shell_code(self):
        runner=NativeReads({1:native()})
        GitHubBacklog(runner=runner).read(PROJECT,[{'kind':'pull-request','number':1}])
        for args,kwargs in runner.calls:
            self.assertEqual(args,['gh','api','graphql','--input','-'])
            self.assertIs(kwargs['shell'],False)
            request=json.loads(kwargs['input'])
            self.assertTrue(request['query'].startswith('query MonarchyBacklog('))
            self.assertNotIn('mutation',request['query'])
            self.assertNotIn(PROJECT,request['query'])
            self.assertEqual(request['variables'],{'owner':'example','name':'project','number':1})


    def test_frozen_validation_checks_binding_without_claiming_a_fresh_read(self):
        from monarchy.backlog_selection import select,validate_frozen_candidate
        snapshot=self.snapshot({1:native()})
        candidate=select(snapshot,resolve(),[self.classification(snapshot['items'][0])])['candidate']
        self.assertEqual(validate_frozen_candidate(candidate,config=resolve()),candidate)
        candidate['selection']['classifications'][0]['wanted']=False
        with self.assertRaises(Conflict):
            validate_frozen_candidate(candidate,config=resolve())


    def test_reader_bounds_total_bytes_across_all_references(self):
        responses={n:native(n) for n in range(1,5)}
        for response in responses.values():
            response['data']['repository']['issueOrPullRequest']['body']='x'*5000
        with self.assertRaises(RecordError):
            GitHubBacklog(runner=NativeReads(responses),max_bytes=10000).read(
                PROJECT,[{'kind':'pull-request','number':n} for n in responses])


    def test_fresh_receipt_has_a_bounded_age_without_claiming_authenticated_provenance(self):
        from monarchy.backlog_selection import select,validate_candidate
        snapshot=self.snapshot({1:native()})
        candidate=select(snapshot,resolve(),[self.classification(snapshot['items'][0])])['candidate']
        self.assertEqual(validate_candidate(candidate,snapshot,config=resolve(),now=AT),candidate)
        self.assertEqual(validate_candidate(candidate,snapshot,config=resolve(),now=AT.replace(minute=1)),candidate)
        for now in (AT.replace(minute=1,second=1), AT.replace(year=2025)):
            with self.subTest(now=now),self.assertRaises(Conflict):
                validate_candidate(candidate,snapshot,config=resolve(),now=now)


    def test_reader_rejects_malformed_normalized_facts_before_returning_a_snapshot(self):
        for field,value in [('stateReason',['unknown']),('labels',connection([{'name':'same'},{'name':'same'}]))]:
            response=native(1,'Issue')
            response['data']['repository']['issueOrPullRequest'][field]=value
            with self.subTest(field=field),self.assertRaises(RecordError):
                self.snapshot({1:response})


if __name__ == '__main__':
    unittest.main()
