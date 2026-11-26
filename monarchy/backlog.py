"""Owner-scoped backlog authority and dispatch custody. No external actions."""
import hashlib
import json
from pathlib import Path
import subprocess
import copy

from .config import ConfigError, defaults_digest, resolve
from .preferences import Preferences, accepted, digest
from .records import (Conflict, RecordError, _REPOSITORY, _generation, _identifier,
                      _now, _payload, owner_answered)
from .supervision import identity

ENDPOINT = 'prepare-and-review'
MAX_REFERENCES = 20


def project_name(value):
    if type(value) is not str or not _REPOSITORY.fullmatch(value):
        raise RecordError('backlog requires an exact repository')
    return value.lower()


def _references(values):
    if values is None:
        return None
    if type(values) is not list or not 1 <= len(values) <= MAX_REFERENCES:
        raise RecordError('backlog scope requires 1-20 exact tracked references')
    checked=[]
    for value in values:
        if (type(value) is not dict or set(value)!={'kind','number'}
                or type(value['kind']) is not str or value['kind'] not in {'issue','pull-request'}
                or type(value['number']) is not int or not 1 <= value['number'] <= 2**31-1):
            raise RecordError('backlog reference requires an issue or pull-request and positive number')
        checked.append(dict(value))
    if len({(v['kind'],v['number']) for v in checked})!=len(checked):
        raise RecordError('backlog references must be distinct')
    return sorted(checked,key=lambda row:(row['kind'],row['number']))


def source_digest():
    root=Path(__file__).parent
    files=list(root.glob('*.py'))+list((root/'orders').glob('*.md'))
    return digest({str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(files)})


def writer_branch(task):
    value=task['metadata'].get('writer_branch')
    if type(value) is not dict or set(value)!={'repository','ref'}:
        raise Conflict('writer dispatch requires explicit physical repository and branch custody')
    repository=project_name(value['repository']).lower()
    if repository!=task['repository'].lower():
        raise Conflict('writer repository must match this authorized project')
    branch=value['ref']
    if type(branch) is not str or not branch or len(branch)>255:
        raise RecordError('writer branch requires a bounded Git branch name')
    ref=branch if branch.startswith('refs/heads/') else 'refs/heads/'+branch
    if branch.startswith('refs/') and not branch.startswith('refs/heads/'):
        raise RecordError('writer custody requires a heads ref')
    try:
        checked=subprocess.run(['git','check-ref-format',ref],capture_output=True,timeout=3)
    except (OSError,subprocess.TimeoutExpired):
        raise RecordError('could not validate the writer branch') from None
    if checked.returncode or ref=='refs/heads/HEAD':
        raise RecordError('writer branch is not a valid canonical heads ref')
    return {'repository':repository,'ref':ref}


def dispatch_fields(task):
    meta=task['metadata']
    mode=meta.get('execution_mode')
    if mode not in ('writer','read-only'):
        raise Conflict('new worker work requires explicit writer or read-only execution mode')
    if mode=='read-only':
        if meta.get('writer_branch') is not None or meta.get('backlog') is not None:
            raise Conflict('read-only mode cannot carry writer or backlog authority')
        return {'route':'worker-dispatch','execution_mode':mode}
    return {'route':'worker-dispatch','execution_mode':mode,'writer_branch':writer_branch(task),
            'reservation_id':identity('writer-reservation',task['task_id']+':'+str(task['generation']))}


def reserve_dispatch(records,operation,*,backlog_snapshot=None,idle_source=None):
    """Called only inside the transaction inserting the prepared operation."""
    task=records.get_task(operation['task_id'])
    fields=dispatch_fields(task)
    from .preferences import admission_check
    admission_check(records,task)
    binding=task['metadata'].get('binding')
    if (type(binding) is not dict or binding.get('session_id')!=task['owner']
            or binding.get('repo')!=task['repository'] or operation['request'].get('binding')!=binding):
        raise Conflict('dispatch must preserve the exact current native binding and profile')
    if (type(operation['request'].get('generation')) is not int
            or operation['request']['generation']!=task['generation']
            or any(operation['request'].get(k)!=v for k,v in fields.items())):
        raise Conflict('dispatch differs from its current assignment and custody')
    if fields['execution_mode']=='read-only':
        return
    config,frozen,_=policy(records,task['repository'],current=True)
    grant=None
    if task['metadata'].get('backlog') is not None:
        grant=_backlog_task(records,task,backlog_snapshot=backlog_snapshot,fresh=True)
    branch=fields['writer_branch']
    db=records._connection
    if db.execute("SELECT 1 FROM dispatch_reservations WHERE project=? AND state='held' AND legacy=1 LIMIT 1",
                  (task['repository'].lower(),)).fetchone():
        raise Conflict('legacy writer branch custody is unknown; reconcile and prove the worker stopped')
    count=db.execute("SELECT COUNT(*) FROM dispatch_reservations WHERE project=? AND state='held'",
                     (task['repository'].lower(),)).fetchone()[0]
    cap=_project_cap(records,task['repository'],config)
    if count>=cap:
        raise Conflict('prepared and unresolved writer reservations fill the builder cap')
    if db.execute("SELECT 1 FROM dispatch_reservations WHERE state='held' AND "
                  '((writer_repository=? AND branch_ref=?) OR session_id=?) LIMIT 1',
                  (branch['repository'],branch['ref'],task['owner'])).fetchone():
        raise Conflict('the branch or worker session already has retained writer custody')
    payload={'policy':frozen,'binding':task['metadata']['binding'],'writer_branch':branch,
             'grant_id':grant['grant_id'] if grant else None}
    if grant:
        payload['candidate_id']=task['metadata']['backlog']['candidate']['candidate_id']
    if idle_source is not None:
        if grant is None:
            raise Conflict('idle pull requires an active backlog grant')
        _idle_source(records,task,idle_source,config)
        payload['idle_source']=idle_source
    db.execute('INSERT INTO dispatch_reservations '
        '(reservation_id,project,writer_repository,branch_ref,task_id,generation,session_id,operation_id,payload,state,created_at) '
        'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
        (fields['reservation_id'],task['repository'].lower(),branch['repository'],branch['ref'],task['task_id'],
         task['generation'],task['owner'],operation['operation_id'],_payload(payload),'held',_now()))


def worker_admission_check(records,operation,*,backlog_snapshot=None,now=None):
    """New worker messages need explicit mode; only dispatch reserves a writer."""
    if operation['kind'] not in {'send_message','create_session'} or operation['request'].get('route')=='queen-forward':
        return
    task=records.get_task(operation['task_id'])
    fields=dispatch_fields(task)
    request=operation['request']
    if type(request.get('generation')) is not int or request['generation']!=task['generation']:
        raise Conflict('worker message requires the current assignment generation')
    binding=task['metadata'].get('binding')
    if (type(binding) is not dict or binding.get('session_id')!=task['owner']
            or binding.get('repo')!=task['repository'] or request.get('binding')!=binding):
        raise Conflict('worker message must preserve the exact current native binding and profile')
    if fields['execution_mode']=='read-only':
        records._connection.execute("UPDATE dispatch_reservations SET last_admitted_at=? WHERE session_id=? AND state='held'",
                                    (now or _now(),task['owner']))
        return
    row=records._connection.execute("SELECT * FROM dispatch_reservations WHERE task_id=? AND generation=? AND state='held'",
                                    (task['task_id'],task['generation'])).fetchone()
    if row is None:
        raise Conflict('writer message requires retained branch custody from dispatch')
    reservation=records._decode(row)
    if (reservation['session_id']!=task['owner'] or reservation['payload']['writer_branch']!=fields['writer_branch']
            or reservation['payload']['binding']!=task['metadata'].get('binding')):
        raise Conflict('writer custody differs from its current task and native session')
    config,current,_=policy(records,task['repository'],current=True)
    if reservation['payload']['policy']!=current:
        raise Conflict('writer configuration changed after reservation')
    if (operation['operation_id']==reservation['operation_id']
            and reservation['payload'].get('idle_source') is not None):
        _idle_source(records,task,reservation['payload']['idle_source'],config,
                     reservation_id=reservation['reservation_id'])
    count=records._connection.execute("SELECT COUNT(*) FROM dispatch_reservations WHERE project=? AND state='held'",
                                      (task['repository'].lower(),)).fetchone()[0]
    cap=_project_cap(records,task['repository'],config)
    if reservation['payload']['grant_id'] is not None:
        grant=_backlog_task(records,task,backlog_snapshot=backlog_snapshot,
                            fresh=operation['operation_id']==reservation['operation_id'])
        if (grant['grant_id']!=reservation['payload']['grant_id']
                or task['metadata']['backlog']['candidate']['candidate_id']!=reservation['payload']['candidate_id']):
            raise Conflict('backlog grant or candidate differs from writer custody')
        cap=min(cap,grant['payload']['builder_cap'])
    if count>cap:
        raise Conflict('retained writer reservations exceed the current builder cap')
    at=now or _now()
    records._connection.execute('UPDATE dispatch_reservations SET admitted_at=COALESCE(admitted_at,?),last_admitted_at=? '
                                'WHERE reservation_id=?',(at,at,reservation['reservation_id']))


def _candidate_grant(records,project,grant_id,candidate,*,fresh_snapshot=None,fresh=False):
    from .backlog_selection import validate_candidate,validate_frozen_candidate
    project=project_name(project)
    grant=Backlog(records).state(project)
    if grant['state']!='active' or grant['grant_id']!=grant_id or grant['held_reasons']:
        raise Conflict('backlog requires the exact current active project grant')
    config,_,_=policy(records,project,current=True)
    if fresh:
        if fresh_snapshot is None:
            raise Conflict('backlog dispatch requires a fresh source read receipt')
        checked=validate_candidate(candidate,fresh_snapshot,config=config)
    else:
        checked=validate_frozen_candidate(candidate,config=config)
    if checked['repository']!=project or checked['branch_repository']!=project:
        raise Conflict('backlog candidate and physical writer must belong to the granted project')
    refs=_references(checked['selection']['snapshot']['references'])
    if grant['payload']['references'] is not None and refs!=grant['payload']['references']:
        raise Conflict('candidate window differs from the exact granted reference allowlist')
    return grant,checked


def _project_cap(records,project,config):
    grant=Backlog(records)._latest(project_name(project))
    configured=config['backlog.builder_cap']['value']
    if grant and grant['state']=='active':
        cap=grant['payload'].get('builder_cap')
        if type(cap) is not int or cap<1:
            raise Conflict('active backlog grant has invalid builder capacity')
        return min(configured,cap)
    return configured


def _idle_source(records,task,source,config,*,reservation_id=None):
    from .cadence import Cadence,timestamp
    if type(source) is not dict or set(source)!={'task_id','generation','first_observation_id','last_observation_id'}:
        raise RecordError('idle pull requires exact first and last native observation identities')
    _generation(source['generation'])
    prior=records.get_task(source['task_id'])
    if (prior['generation']!=source['generation'] or prior['owner']!=task['owner']
            or project_name(prior['repository'])!=project_name(task['repository'])):
        raise Conflict('idle observations do not belong to this current worker assignment')
    cadence=Cadence(records)
    first=cadence.observation(source['first_observation_id'])
    last=cadence.observation(source['last_observation_id'])
    now=timestamp(_now()); start=timestamp(first['observed_at']); end=timestamp(last['observed_at'])
    if (first['observation_id']==last['observation_id']
            or any(row['task_id']!=prior['task_id'] or row['generation']!=prior['generation'] for row in (first,last))
            or (end-start).total_seconds()<config['backlog.idle_minutes']['value']*60
            or not 0<=(now-end).total_seconds()<=60):
        raise Conflict('idle pull requires a complete interval and a recent distinct native reading')
    latest=records._connection.execute('SELECT observation_id FROM cadence_observations '
        'WHERE task_id=? AND generation=? ORDER BY observed_at DESC,sequence DESC LIMIT 1',
        (prior['task_id'],prior['generation'])).fetchone()
    rows=records._connection.execute('SELECT * FROM cadence_observations WHERE task_id=? AND generation=? '
        'AND observed_at>=? AND observed_at<=? ORDER BY observed_at,sequence LIMIT 1001',
        (prior['task_id'],prior['generation'],first['observed_at'],last['observed_at'])).fetchall()
    if latest[0]!=last['observation_id'] or len(rows)>1000:
        raise Conflict('idle observation history changed or exceeds the bounded pass')
    activity=records._connection.execute('SELECT o.* FROM cadence_observations o JOIN tasks t ON t.task_id=o.task_id '
        'WHERE t.owner=? AND o.generation=t.generation AND o.task_id<>? AND o.observed_at>=? LIMIT 1001',
        (task['owner'],prior['task_id'],first['observed_at'])).fetchall()
    if len(activity)>1000 or any(timestamp(row['observed_at'])>=end or
            records._decode(row)['payload']['native_status']!='idle' or
            records._decode(row)['payload']['watched_event'] is not None or
            records._decode(row)['payload']['progress_ref'] is not None for row in activity):
        raise Conflict('another assignment has newer or conflicting native session activity')
    for row in rows:
        observation=records._decode(row)
        facts=observation['payload']
        if facts['native_status']!='idle' or facts['progress_ref'] is not None or facts['watched_event'] is not None:
            raise Conflict('unknown, working, progress or named-event observations do not prove idle eligibility')
    if records._connection.execute("SELECT 1 FROM events WHERE task_id=? AND generation=? "
        "AND kind IN ('progress','completed') AND created_at>? AND created_at<=? LIMIT 1",
        (prior['task_id'],prior['generation'],first['observed_at'],now.isoformat())).fetchone():
        raise Conflict('new task progress interrupts the idle interval')
    if records._connection.execute("SELECT 1 FROM events e JOIN tasks t ON t.task_id=e.task_id WHERE t.owner=? "
        "AND e.generation=t.generation AND e.kind IN ('progress','completed') AND e.created_at>? LIMIT 1",
        (task['owner'],first['observed_at'])).fetchone():
        raise Conflict('worker session progress interrupts the idle interval')
    operations=records._connection.execute("SELECT * FROM operations WHERE kind IN ('send_message','create_session') "
        "AND state<>'prepared' AND updated_at>=? LIMIT 1001",(first['observed_at'],)).fetchall()
    if len(operations)>1000:
        raise RecordError('worker activity exceeds idle admission budget')
    for raw in operations:
        op=records._decode(raw)
        binding=op['request'].get('binding')
        if op['request'].get('route')!='queen-forward' and type(binding) is dict and binding.get('session_id')==task['owner']:
            raise Conflict('new worker-directed activity interrupts the idle interval')
    old=records._connection.execute('SELECT reservation_id,state,created_at,released_at FROM dispatch_reservations '
        'WHERE session_id=? LIMIT 1001',(task['owner'],)).fetchall()
    if len(old)>1000 or any(row['reservation_id']!=reservation_id and
            (row['state']=='held' or timestamp(row['released_at'])>=start) for row in old):
        raise Conflict('retained writer custody or an already-consumed idle interval holds this pull')


def _backlog_task(records,task,*,backlog_snapshot=None,fresh=False):
    source=task['metadata'].get('backlog')
    if type(source) is not dict or set(source)!={'grant_id','candidate'}:
        raise Conflict('backlog assignment requires an exact grant and frozen candidate')
    grant,candidate=_candidate_grant(records,task['repository'],source['grant_id'],source['candidate'],
                                    fresh_snapshot=backlog_snapshot,fresh=fresh)
    if writer_branch(task)!={'repository':candidate['branch_repository'],'ref':'refs/heads/'+candidate['branch']}:
        raise Conflict('writer branch differs from the selected tracked item')
    return grant


def policy(records, project, *, current=False):
    project=project_name(project)
    if records._connection.execute("SELECT 1 FROM overrides WHERE lower(project)=? AND project<>? LIMIT 1",
                                    (project,project)).fetchone():
        raise Conflict('project configuration aliases require explicit canonical reconciliation')
    if records.has_pins():
        view=(Preferences(records).require_current(project) if current else Preferences(records).show(project))
        config=view['config']
        held=['configuration-drift'] if view['held'] else []
        pin_id=view['pin_id']
    else:
        config=resolve(overrides=records.config_overrides(project))
        pin_id=None
        held=[]
    for key in ('court.paused','court.stopped'):
        if config[key]['value']:
            held.append(key)
    if current and held:
        raise Conflict('backlog configuration is held')
    frozen={'pin_id':pin_id,'defaults_digest':defaults_digest(),
            'effective_digest':digest({k:v for k,v in config.items() if not k.startswith('court.')}),
            'source_digest':source_digest(),
            'qualification':'pinned' if pin_id else 'legacy-unpinned'}
    return config,frozen,held


class Backlog:
    def __init__(self,records):
        self.records=records
        self.db=records._connection

    def _latest(self,project):
        row=self.db.execute('SELECT * FROM backlog_events WHERE project=? ORDER BY sequence DESC LIMIT 1',
                            (project,)).fetchone()
        return self.records._decode(row) if row else None

    def state(self,project):
        project=project_name(project)
        row=self._latest(project)
        if row is None:
            return {'project':project,'state':'inactive','grant_id':None,'event_id':None,
                    'payload':None,'created_at':None,'held_reasons':[]}
        reasons=[]
        if row['state']=='active':
            try:
                _,current,reasons=policy(self.records,project)
                if current!=row['payload']['policy']:
                    reasons.append('grant-configuration-changed')
            except (RecordError,ConfigError):
                reasons=['configuration-unavailable']
        return {'project':project,'state':row['state'],
                'grant_id':row['event_id'] if row['state']=='active' else row['payload']['grant_id'],
                'event_id':row['event_id'],'payload':row['payload'],'created_at':row['created_at'],
                'held_reasons':reasons}

    def propose(self,project,references=None,*,owner_message,builder_cap=None):
        project=project_name(project)
        refs=_references(references)
        _identifier(owner_message,'owner_message')
        with self.records._transaction():
            config,frozen,_=policy(self.records,project,current=True)
            cap=config['backlog.builder_cap']['value'] if builder_cap is None else builder_cap
            if type(cap) is not int or not 1<=cap<=config['backlog.builder_cap']['value']:
                raise RecordError('backlog builder cap must respect the configured bound')
            latest=self._latest(project)
            payload={'kind':'backlog.proposal','generation':1,'project':project,'references':refs,
                     'scope':'project-backlog' if refs is None else 'reference-allowlist',
                     'builder_cap':cap,'endpoint':ENDPOINT,'policy':frozen,
                     'review_hours':config['backlog.review_hours']['value'],
                     'selection_order':config['backlog.selection_order']['value'],
                     'checkpoint':latest['event_id'] if latest else None,'request_owner_message':owner_message,
                     'question':'Activate this exact scoped backlog through preparation and independent review?',
                     'options':['Activate This Scope (Recommended)','Keep Current State']}
            decision_id=identity('backlog-proposal',digest(payload))
            existing=self.db.execute('SELECT 1 FROM decisions WHERE decision_id=?',(decision_id,)).fetchone()
            if existing:
                return self.records.get_decision(decision_id)
            now=_now()
            self.db.execute('INSERT OR IGNORE INTO tasks VALUES(?,?,?,?,?,?,?)',
                ('court.backlog','monarchy/court','queen',1,_payload({'kind':'backlog-policy'}),now,now))
            self.db.execute('INSERT INTO decisions(decision_id,revision,task_id,payload,state,created_at) '
                'VALUES(?,?,?,?,?,?)',(decision_id,1,'court.backlog',_payload(payload),'pending',now))
            return self.records.get_decision(decision_id)

    def apply(self,decision_id):
        with self.records._transaction():
            decision=self.records.get_decision(decision_id)
            payload=decision['payload']
            if (decision['task_id']!='court.backlog' or payload.get('kind')!='backlog.proposal'
                    or not owner_answered(decision) or not accepted(decision['answer'])):
                raise Conflict('backlog activation requires an exact owner-answered proposal')
            project=project_name(payload.get('project'))
            event_id=identity('backlog-grant',decision_id+':'+str(decision['revision']))
            if self.db.execute('SELECT 1 FROM backlog_events WHERE event_id=?',(event_id,)).fetchone():
                return self.state(project)
            config,current,_=policy(self.records,project,current=True)
            latest=self._latest(project)
            if (current!=payload.get('policy') or payload.get('checkpoint')!=(latest['event_id'] if latest else None)
                    or payload.get('endpoint')!=ENDPOINT or _references(payload.get('references'))!=payload['references']
                    or payload.get('scope')!=('project-backlog' if payload['references'] is None else 'reference-allowlist')
                    or type(payload.get('builder_cap')) is not int
                    or not 1<=payload['builder_cap']<=config['backlog.builder_cap']['value']
                    or payload.get('selection_order')!=config['backlog.selection_order']['value']
                    or payload.get('review_hours')!=config['backlog.review_hours']['value']):
                raise Conflict('backlog scope or configuration changed before activation')
            now=_now()
            grant={k:payload[k] for k in ('scope','references','builder_cap','endpoint','policy','selection_order','review_hours')}
            grant.update(decision_id=decision_id,decision_revision=decision['revision'],
                         owner_message=decision['owner_message'],activated_at=now)
            self.db.execute('INSERT INTO backlog_events(event_id,project,state,payload,created_at) VALUES(?,?,?,?,?)',
                            (event_id,project,'active',_payload(grant),now))
            from .backlog_metrics import review_due
            from .cadence import Cadence,timestamp
            due=review_due(self.state(project),now=now)
            Cadence(self.records)._put(None,due['kind'],timestamp(due['due_at']),due['payload'],
                recipient=due['recipient'],project=project,check_id=due['check_id'])
        return self.state(project)

    def revoke(self,project,*,owner_message):
        project=project_name(project)
        _identifier(owner_message,'owner_message')
        event_id=identity('backlog-revoke',project+':'+owner_message)
        with self.records._transaction():
            if self.db.execute('SELECT 1 FROM backlog_events WHERE event_id=?',(event_id,)).fetchone():
                return self.state(project)
            previous=self.state(project)
            payload={'grant_id':previous['grant_id'],'owner_message':owner_message,
                     'checkpoint':previous['event_id']}
            self.db.execute('INSERT INTO backlog_events(event_id,project,state,payload,created_at) VALUES(?,?,?,?,?)',
                            (event_id,project,'revoked',_payload(payload),_now()))
        return self.state(project)

    def reservation(self,reservation_id):
        _identifier(reservation_id,'reservation_id')
        row=self.db.execute('SELECT * FROM dispatch_reservations WHERE reservation_id=?',(reservation_id,)).fetchone()
        if row is None:
            raise RecordError('writer reservation does not exist')
        result=self.records._decode(row)
        if result['release_receipt'] is not None:
            result['release_receipt']=json.loads(result['release_receipt'])
            _payload(result['release_receipt'])
        return result

    def bind(self,data,candidate,grant_id):
        _payload(data)
        result=copy.deepcopy(data)
        if set(result)!={'task_id','repository','owner','metadata'} or type(result['metadata']) is not dict:
            raise RecordError('backlog binding requires exact task assignment data')
        project=project_name(result['repository'])
        if result['repository']!=project:
            raise Conflict('new backlog assignments require canonical repository identity')
        grant,candidate=_candidate_grant(self.records,project,grant_id,candidate)
        meta=result['metadata']
        if any(key in meta for key in ('execution_mode','writer_branch','backlog','authority_ref')):
            raise Conflict('backlog binding must not replace existing execution authority')
        meta.update(execution_mode='writer',writer_branch={'repository':project,'ref':candidate['branch']},
                    authority_ref=grant['payload']['owner_message'],
                    backlog={'grant_id':grant_id,'candidate':candidate})
        writer_branch(result)
        if self.records.has_pins():
            result=Preferences(self.records).bind(result)
        _payload(result)
        return result

    def prepare(self,task_id,candidate,fresh_snapshot,*,idle_source=None,new_session=False):
        task=self.records.get_task(task_id)
        if task['metadata'].get('backlog',{}).get('candidate')!=candidate:
            raise Conflict('preparation candidate differs from the frozen assignment')
        from .supervision import Court
        return Court(self.records).prepare_dispatch(task_id,new_session=new_session,
            backlog_snapshot=fresh_snapshot,idle_source=idle_source)

    def pull(self,data,classifications,*,idle_source,reader=None,new_session=False):
        from .backlog_selection import GitHubBacklog,select
        from .supervision import Court
        _payload(data)
        project=project_name(data.get('repository'))
        grant=self.state(project)
        if grant['state']!='active' or grant['held_reasons']:
            raise Conflict('idle pull requires an active current project backlog grant')
        config,_,_=policy(self.records,project,current=True)
        _idle_source(self.records,data,idle_source,config)
        if type(classifications) is not list or not 1<=len(classifications)<=MAX_REFERENCES:
            raise RecordError('idle pull requires a bounded current classification window')
        refs=grant['payload']['references']
        if refs is None:
            refs=_references([row.get('reference') if type(row) is dict else None for row in classifications])
        snapshot=(reader or GitHubBacklog()).read(project,refs)
        result=select(snapshot,config,classifications)
        candidate=result['candidate']
        if candidate is None:
            return {'candidate':None,'held':result['held'],'operation':None}
        with self.records._transaction():
            bound=self.bind(data,candidate,grant['grant_id'])
            self.records._create_task(bound['task_id'],bound['repository'],bound['owner'],metadata=bound['metadata'])
            operation=Court(self.records)._prepare_dispatch(bound['task_id'],new_session=new_session,
                backlog_snapshot=snapshot,idle_source=idle_source)
        return {'candidate':candidate,'held':result['held'],'operation':operation}

    def review(self,project,metrics,*,observed_at,source_refs):
        from .backlog_metrics import review
        return review(self.records,project,metrics,observed_at=observed_at,source_refs=source_refs)

    def release(self,reservation_id,receipt_id,receipt):
        _identifier(receipt_id,'receipt_id')
        encoded=_payload(receipt)
        with self.records._transaction():
            row=self.reservation(reservation_id)
            if row['state']=='released':
                if row['release_receipt_id']!=receipt_id or row['release_receipt']!=receipt:
                    raise Conflict('writer reservation already has a different release receipt')
                return row
            if self.db.execute('SELECT 1 FROM dispatch_reservations WHERE release_receipt_id=?',(receipt_id,)).fetchone():
                raise Conflict('writer release receipt already belongs to another reservation')
            operation=self.records.get_operation(row['operation_id'])
            now=_now()
            if receipt.get('kind')=='never-admitted':
                if (set(receipt)!={'kind','operation_id'} or receipt['operation_id']!=operation['operation_id']
                        or operation['state']!='prepared' or row['admitted_at'] is not None or row['legacy']):
                    raise Conflict('release requires exact never-admitted custody evidence')
                self.db.execute("UPDATE operations SET state='failed',result=?,updated_at=? WHERE operation_id=?",
                    (_payload({'cancelled_before_admission':True}),now,operation['operation_id']))
            elif receipt.get('kind')=='writer-stopped':
                self._stopped(row,receipt,now)
            else:
                raise Conflict('release requires explicit never-admitted or stopped-process evidence')
            self.db.execute("UPDATE dispatch_reservations SET state='released',release_receipt_id=?,release_receipt=?,released_at=? "
                'WHERE reservation_id=?',(receipt_id,encoded,now,reservation_id))
        return self.reservation(reservation_id)

    def _stopped(self,row,receipt,now):
        from .cadence import timestamp
        if set(receipt)!={'kind','outcome_id'}:
            raise RecordError('stopped-process release requires an exact retained outcome')
        outcome=self.records.get_outcome(receipt['outcome_id'])
        body=outcome['payload']
        required={'kind','generation','session_id','writer_repository','branch_ref','native_status',
                  'processes_stopped','background_work_clear','observed_at','evidence_refs'}
        if (set(body)!=required or body['kind']!='writer-custody' or outcome['task_id']!=row['task_id']
                or type(body['generation']) is not int or body['generation']!=row['generation']
                or body['session_id']!=row['session_id'] or body['writer_repository']!=row['writer_repository']
                or body['branch_ref']!=(None if row['legacy'] else row['branch_ref'])
                or body['native_status']!='idle' or body['processes_stopped'] is not True
                or body['background_work_clear'] is not True
                or type(body['evidence_refs']) is not list or not 1<=len(body['evidence_refs'])<=20):
            raise Conflict('retained evidence does not prove this exact writer stopped')
        for ref in body['evidence_refs']:_identifier(ref,'custody evidence reference')
        observed=timestamp(body['observed_at'])
        if not timestamp(row['created_at'])<=observed<=timestamp(outcome['created_at'])<=timestamp(now):
            raise Conflict('custody evidence is outside the reservation and release interval')
        if row['last_admitted_at'] is not None and observed<timestamp(row['last_admitted_at']):
            raise Conflict('stopped-process evidence predates the last admitted worker message')
        operations=self.db.execute("SELECT * FROM operations LIMIT 10001").fetchall()
        if len(operations)>10000:
            raise RecordError('writer operation history exceeds release budget')
        for raw in operations:
            op=self.records._decode(raw)
            if op['request'].get('route')=='queen-forward':continue
            binding=op['request'].get('binding')
            if op['task_id']!=row['task_id'] and (type(binding) is not dict or binding.get('session_id')!=row['session_id']):
                continue
            if op['state'] in {'in_flight','unknown'}:
                raise Conflict('reconcile all uncertain worker operations before releasing custody')
            # Admission of a later message may have restarted the process. Readback
            # may update the original operation after observation without a new send.
            if op['operation_id']!=row['operation_id'] and op['state'] in {'confirmed','failed'} and timestamp(op['created_at'])>observed:
                raise Conflict('later worker work requires fresh stopped-process evidence')
