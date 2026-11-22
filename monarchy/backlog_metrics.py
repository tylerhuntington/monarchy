"""Activation-bound backlog review. Measurements never grant new authority."""
from datetime import datetime, timedelta, timezone
import math
import re

from .preferences import REVISION,digest
from .records import Conflict, RecordError, _identifier, _now, _payload
from .supervision import identity


METRICS=('throughput','ci_cost','review_latency','queue_size')
UNITS={'throughput':'merged PRs per day','ci_cost':'currency',
       'review_latency':'hours','queue_size':'candidates'}
SOURCE_FIELDS={'kind','metric','project','grant_id','window_start','window_end',
               'observed_at','source_ref','complete','data'}


def _time(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError,OverflowError):
        raise RecordError('backlog review requires an offset timestamp') from None


def review_due(grant, *, now):
    """Describe one durable preparation obligation; schedule or send nothing."""
    try:
        grant_id=_identifier(grant['grant_id'],'grant_id')
        start=_time(grant['payload']['activated_at'])
        hours=grant['payload']['review_hours']
        if type(hours) is not int or not 1<=hours<=168:
            raise RecordError('backlog trial hours are invalid')
        current=_time(now)
        if current<start:
            raise RecordError('backlog activation is in the future')
        due_at=start+timedelta(hours=hours)
        return {'check_id':identity('backlog-review-check',grant_id),
                'project':grant['project'],'kind':'backlog-review','recipient':'secretary',
                'due_at':due_at.isoformat(),'due':current>=due_at,
                'payload':{'grant_id':grant_id,'activated_at':start.isoformat(),'review_hours':hours}}
    except (KeyError,TypeError):
        raise RecordError('backlog review requires a retained activation') from None


def _rows(value):
    if type(value) is not list or len(value)>100:
        raise RecordError('backlog metric source requires at most 100 rows')
    return value


def _value(metric,data,project,start,end):
    if metric=='ci_cost':
        if (type(data) is not dict or set(data)!={'amount','currency'}
                or type(data['amount']) is not str
                or not re.fullmatch(r'(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?',data['amount'])
                or type(data['currency']) is not str or not re.fullmatch('[A-Z]{3}',data['currency'])):
            raise RecordError('CI cost requires a bounded nonnegative decimal amount and currency')
        return dict(data)
    rows=_rows(data)
    if metric=='queue_size':
        for candidate in rows:
            _identifier(candidate,'candidate_id')
        if len(set(rows))!=len(rows):
            raise RecordError('sign-off queue snapshot contains duplicate candidates')
        return len(rows)
    seen=set()
    latencies=[]
    for row in rows:
        if metric=='throughput':
            if (type(row) is not dict or set(row)!={'repository','number','source_revision','merged_at'}
                    or row['repository']!=project or type(row['number']) is not int
                    or not 1<=row['number']<=2**31-1 or type(row['source_revision']) is not str
                    or not REVISION.fullmatch(row['source_revision'])):
                raise RecordError('throughput requires exact merged PR identities and full revisions')
            identity_key=(row['repository'],row['number'])
            if not start<=_time(row['merged_at'])<end:
                raise Conflict('merged PR is outside the measured trial window')
        else:
            if type(row) is not dict or set(row)!={'candidate_id','ready_at','reviewed_at'}:
                raise RecordError('review latency requires exact ready and review observations')
            identity_key=_identifier(row['candidate_id'],'candidate_id')
            ready,reviewed=_time(row['ready_at']),_time(row['reviewed_at'])
            if not start<=ready<=reviewed<end:
                raise Conflict('review latency is outside the measured trial window')
            latencies.append((reviewed-ready).total_seconds()/3600)
        if identity_key in seen:
            raise RecordError('backlog metric source contains duplicate observations')
        seen.add(identity_key)
    if metric=='throughput':
        return round(len(rows)*86400/(end-start).total_seconds(),6)
    return round(sum(latencies)/len(latencies),6) if latencies else None


def _measurement(records,grant,metric,declared,reference,start,end,current):
    value=None
    reason='source-unavailable'
    if reference is not None:
        if (type(reference) is not dict or set(reference)!={'outcome_id','digest'}
                or type(reference['digest']) is not str or not re.fullmatch('[0-9a-f]{64}',reference['digest'])):
            raise RecordError('backlog metric requires an exact retained source reference')
        source=records.get_outcome(reference['outcome_id'])
        payload=source['payload']
        if (digest(payload)!=reference['digest'] or set(payload)!=SOURCE_FIELDS
                or payload['kind']!='backlog.metrics-source' or payload['metric']!=metric
                or payload['project']!=grant['project'] or payload['grant_id']!=grant['grant_id']
                or records.get_task(source['task_id'])['repository']!=grant['project']):
            raise Conflict('backlog measurement source differs from this activation or metric')
        _identifier(payload['source_ref'],'source_ref')
        if type(payload['complete']) is not bool:
            raise RecordError('backlog measurement coverage must be explicit')
        observed=_time(payload['observed_at'])
        if (_time(payload['window_start'])!=start or _time(payload['window_end'])!=end
                or not end<=observed<=_time(source['created_at'])<=current):
            raise Conflict('backlog source window is mismatched, premature, or future')
        if payload['complete']:
            value=_value(metric,payload['data'],grant['project'],start,end)
            reason=None if value is not None else 'no-completed-reviews'
        else:
            reason='coverage-incomplete'
    if value is None:
        matches=declared is None
    elif type(value) is float:
        matches=type(declared) in {int,float} and math.isfinite(declared) and declared==value
    else:
        matches=type(declared) is type(value) and declared==value
    if not matches:
        raise Conflict('declared backlog measurement differs from its retained source')
    return {'state':'unknown' if value is None else 'known','value':value,'unit':UNITS[metric],
            'reason':reason,'source':dict(reference) if reference is not None else None}


def review(records, project, metrics, *, observed_at, source_refs):
    """Retain an informational owner box; never apply a capacity or scope grant.

    Sources are trusted adapter records, not authenticated native observations.
    The window ends at observed_at and begins at the actual retained activation.
    """
    from .backlog import Backlog,project_name
    project=project_name(project)
    if type(metrics) is not dict or set(metrics)!=set(METRICS):
        raise RecordError('backlog review requires all four explicit measurements')
    if type(source_refs) is not dict or set(source_refs)!=set(METRICS):
        raise RecordError('backlog review requires all four explicit source references')
    _payload(metrics)
    _payload(source_refs)
    with records._transaction():
        grant=Backlog(records).state(project)
        if grant['state']!='active':
            raise Conflict('backlog review requires the current retained activation')
        current=_time(_now())
        end=_time(observed_at)
        due=review_due(grant,now=current.isoformat())
        if end>current or end<_time(due['due_at']):
            raise Conflict('backlog measurement window is future or earlier than the trial review')
        start=_time(grant['payload']['activated_at'])
        measured={}
        for key in METRICS:
            measured[key]=_measurement(records,grant,key,metrics[key],source_refs[key],start,end,current)
        payload={'kind':'backlog.review','generation':1,'project':project,
                 'grant_id':grant['grant_id'],'review_hours':grant['payload']['review_hours'],
                 'window':{'start':start.isoformat(),'end':end.isoformat(),
                           'hours':(end-start).total_seconds()/3600},
                 'metrics':measured,'answer_effect':'review-record-only',
                 'question':'How should this measured backlog trial be recorded?',
                 'options':['Record Review (Recommended)','Request Separate Scope Proposal']}
        task_id='court.backlog-review'
        decision_id=identity('backlog-review-decision',grant['grant_id'])
        encoded=_payload(payload)
        db=records._connection
        task_meta=_payload({'kind':'backlog-review'})
        at=current.isoformat()
        db.execute('INSERT OR IGNORE INTO tasks VALUES(?,?,?,?,?,?,?)',
                   (task_id,'monarchy/court','queen',1,task_meta,at,at))
        task=records.get_task(task_id)
        if (task['repository'],task['owner'],task['generation'],_payload(task['metadata']))!=(
                'monarchy/court','queen',1,task_meta):
            raise Conflict('backlog review task custody changed')
        previous=db.execute('SELECT * FROM decisions WHERE decision_id=? ORDER BY revision DESC LIMIT 1',
                            (decision_id,)).fetchone()
        if previous:
            if previous['task_id']!=task_id or previous['payload']!=encoded:
                raise Conflict('backlog review already retains a different measured window or evidence')
            return records.get_decision(decision_id)
        db.execute('INSERT INTO decisions(decision_id,revision,task_id,payload,state,created_at) '
                   'VALUES(?,?,?,?,?,?)',(decision_id,1,task_id,encoded,'pending',at))
        return records.get_decision(decision_id)
