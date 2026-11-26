"""Bounded durable supervision checks. Observations never perform actions."""
from datetime import datetime, timedelta, timezone, time
import copy
import hashlib
import json
from zoneinfo import ZoneInfo

from .records import (Conflict, RecordError, StaleGeneration, _generation, _identifier,
                      _now, _payload, _limit, _offset, _REPOSITORY)
from .config import ConfigError
from .conversation import effective_config, Conversation, prompt_policy
from .supervision import identity
from .conductor import _uuid


def timestamp(value):
    try:
        if type(value) is not str:
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise RecordError('cadence timestamp must include an ISO 8601 offset') from None


def _time(value):
    return timestamp(value).isoformat()


class Cadence:
    def __init__(self, records):
        self.records = records
        self.db = records._connection

    def _task(self, task_id, generation):
        _generation(generation)
        task = self.records.get_task(task_id)
        if task['generation'] != generation:
            raise StaleGeneration('cadence evidence belongs to an earlier assignment')
        return task

    @staticmethod
    def _project(project):
        if type(project) is not str or not _REPOSITORY.fullmatch(project):
            raise RecordError('cadence project must be a repository identity')
        return project

    def observation(self, observation_id):
        _identifier(observation_id, 'observation_id')
        row = self.db.execute('SELECT * FROM cadence_observations WHERE observation_id=?',
                              (observation_id,)).fetchone()
        if row is None:
            raise RecordError('cadence observation does not exist')
        return self.records._decode(row)

    def observe(self, task_id, observation_id, *, generation, observed_at, native_status,
                watched_event=None, report_expected_since=None, progress_ref=None):
        _identifier(observation_id, 'observation_id')
        at = _time(observed_at)
        if type(native_status) is not str or native_status not in {'working', 'idle', 'unknown'}:
            raise RecordError('native status must be working, idle, or unknown')
        payload = {'native_status': native_status, 'watched_event': watched_event,
                   'report_expected_since': report_expected_since, 'progress_ref': progress_ref}
        _payload(payload)
        with self.records._transaction():
            task = self._task(task_id, generation)
            if progress_ref is not None:
                report = self._reference(task, {'kind':'event','id':progress_ref})
                if (report['kind'] not in {'progress','completed'} or not report['payload'].get('evidence')
                        or timestamp(report['created_at']) > timestamp(at)):
                    raise Conflict('progress requires retained new evidence observed before this reading')
                payload['progress_token'] = hashlib.sha256(_payload(
                    {'evidence':report['payload']['evidence']}).encode()).hexdigest()
            if watched_event is not None:
                if (type(watched_event) is not dict or set(watched_event) != {'name','until','source_ref'}
                        or type(watched_event['name']) is not str or not watched_event['name'].strip()
                        or len(watched_event['name']) > 256):
                    raise RecordError('watched event requires a bounded name, end time, and retained source')
                until = _time(watched_event['until'])
                source = self._reference(task, watched_event['source_ref'])
                if (watched_event['source_ref']['kind'] != 'outcome'
                        or source['payload'].get('kind') != 'watched-event'
                        or source['payload'].get('name') != watched_event['name']
                        or _time(source['payload'].get('until')) != until
                        or timestamp(source['created_at']) > timestamp(at)
                        or timestamp(until) <= timestamp(at)):
                    raise Conflict('named event differs from retained watcher coverage')
                payload['watched_event'] = dict(watched_event,until=until)
            if report_expected_since is not None:
                since = _time(report_expected_since)
                existing = self.db.execute("SELECT payload FROM checks WHERE task_id=? AND generation=? "
                    "AND kind='report-overdue' LIMIT 1001", (task_id,generation)).fetchall()
                if len(existing) > 1000 or not any(json.loads(r[0]).get('since') == since for r in existing):
                    raise Conflict('observation must refer to a retained report expectation')
                payload['report_expected_since'] = since
            encoded = _payload(payload)
            old = self.db.execute('SELECT * FROM cadence_observations WHERE observation_id=?',
                                  (observation_id,)).fetchone()
            if old:
                if (old['task_id'], old['generation'], old['observed_at'], old['payload']) != (
                        task_id, generation, at, encoded):
                    raise Conflict('observation identity already has different evidence')
            else:
                self.db.execute('INSERT INTO cadence_observations '
                    '(observation_id,task_id,generation,observed_at,payload,created_at) VALUES (?,?,?,?,?,?)',
                    (observation_id, task_id, generation, at, encoded, _now()))
        return self.observation(observation_id)

    def _config(self, project):
        return effective_config(self.records, project)

    def _config_digest(self, project):
        config = self._config(project)
        # Restrictive transient controls gate admission, without changing the
        # schedule identity when an owner later resumes the same configuration.
        values = {k:v for k,v in config.items() if not k.startswith('court.')}
        pin = self.records.latest_pin(project)['pin_id'] if self.records.has_pins() else None
        return hashlib.sha256(_payload({'pin':pin,'config':values}).encode()).hexdigest()

    def _holds(self, check, now):
        reasons = []
        try:
            config = self._config(check['project'])
        except (RecordError,ConfigError):
            return ['configuration-unavailable']
        if check['config_digest'] != self._config_digest(check['project']):
            reasons.append('configuration-changed')
        if self.records.has_pins():
            from .preferences import Preferences
            if Preferences(self.records).show(check['project'])['held']:
                reasons.append('configuration-drift')
        for key in ('paused', 'stopped'):
            if config['court.' + key]['value']:
                reasons.append('royalty-' + key)
        if check['task_id']:
            task = self.records.get_task(check['task_id'])
            if task['generation'] != check['generation']:
                reasons.append('stale-generation')
            if not self._task_current(task,config):
                reasons.append('task-admission-held')
        if timestamp(check['due_at']) > now:
            reasons.append('not-due')
        if check['kind'].startswith('idle-'):
            if check['payload'].get('progress_token')!=self._progress(check['task_id'],check['generation'],now):
                reasons.append('superseded-progress')
            observation = self._latest(check['task_id'], check['generation'], now)
            if not observation or observation['payload']['native_status'] != 'idle':
                reasons.append('idle-unconfirmed')
            elif (now - timestamp(observation['observed_at'])).total_seconds() > config['cadence.stale_minutes']['value']*60:
                reasons.append('native-status-stale')
            elif self._watched(observation, now):
                reasons.append('watched-event')
        if check['recipient']=='queen':
            reasons.extend(self._owner_holds(check,now,config))
        if check['kind']=='backlog-review':
            from .backlog import Backlog
            grant=Backlog(self.records).state(check['project'])
            if grant['state']!='active' or grant['grant_id']!=check['payload']['grant_id'] or grant['held_reasons']:
                reasons.append('backlog-grant-changed')
        return reasons

    def _route(self, project, global_scope=False):
        rows=self.db.execute("SELECT metadata FROM tasks WHERE task_id NOT LIKE 'court.%' "
            + ('' if global_scope else 'AND repository=? ') + 'LIMIT 1001',
            () if global_scope else (project,)).fetchall()
        if len(rows)>1000:
            raise RecordError('Queen route census exceeds this pass budget')
        sessions={json.loads(row[0]).get('queen_binding',{}).get('session_id') for row in rows}
        if len(sessions)!=1 or None in sessions:
            return None
        session=next(iter(sessions))
        try:
            _uuid(session,'queen_session')
        except (ValueError,TypeError):
            return None
        return session

    def _owner_holds(self, check, now, config):
        reasons=[]
        zone=config['voice.zone']['value']
        if not self.records.has_pins() or not zone:
            reasons.append('unconfirmed-timezone')
        if config['court.away']['value']:
            reasons.append('owner-away')
        queen=self._route(check['project'],check['payload'].get('global_scope',False))
        if not queen or queen!=check['payload'].get('queen_session'):
            reasons.append('queen-route-unavailable')
        elif prompt_policy(Conversation(self.records).status(queen),
                config['prompts.abandoned_minutes']['value'],now=now)!='available':
            reasons.append('queen-prompt-held')
        if check['kind']=='reminder':
            if zone:
                local=now.astimezone(ZoneInfo(zone))
                start=config['cadence.reminder_start']['value']
                if not start<=local.strftime('%H:%M')<config['cadence.reminder_end']['value']:
                    reasons.append('outside-reminder-window')
                slot=(local.hour*60+local.minute-(int(start[:2])*60+int(start[3:])))//config['cadence.reminder_minutes']['value']
                bucket=local.date().isoformat()+':'+str(slot)
                if check['payload'].get('calendar_bucket')!=bucket:
                    reasons.append('obsolete-calendar-occurrence')
            decision=self.records.get_decision(check['payload']['decision_id'])
            if decision['state']!='pending' or decision['revision']!=check['payload']['decision_revision']:
                reasons.append('decision-no-longer-pending')
        if check['kind']=='digest':
            if zone and check['payload'].get('local_date')!=now.astimezone(ZoneInfo(zone)).date().isoformat():
                reasons.append('obsolete-calendar-occurrence')
            _,_,census_reasons=self._census(check['project'],now,config)
            if 'census-missing' in census_reasons:
                reasons.append('census-missing')
        return reasons

    def _task_current(self, task, config):
        """Read-only supervision ignores Away, unlike actual operation admission."""
        if not self.records.has_pins():
            return not task['metadata'].get('config_pin')
        from .preferences import Preferences
        from .orders import render
        view = Preferences(self.records).show(task['repository'])
        meta = task['metadata']
        role = meta.get('profile_role')
        if (view['held'] or meta.get('config_pin') != view['pin_id']
                or role not in {'queen','secretary','worker'}
                or meta.get('binding',{}).get('profile') != config['profiles.'+str(role)]['value']
                or hashlib.sha256(meta.get('standing_orders','').encode()).hexdigest() != meta.get('orders_sha256')):
            return False
        variants = []
        for away in (False,True):
            for layers in (['defaults'],['overrides']):
                candidate = copy.deepcopy(config)
                candidate['court.away'] = {'value':away,'layers':layers,'why':{}}
                variants.append(render(role,candidate)['sha256'])
        return meta.get('orders_sha256') in variants

    def _check(self, row, now):
        check = dict(row)
        for key in ('payload', 'receipt', 'admission'):
            if check[key] is not None:
                check[key] = json.loads(check[key])
                _payload(check[key])
        check['held_reasons'] = self._holds(check, now)
        notices=self.db.execute('SELECT n.* FROM cadence_notices n JOIN cadence_notice_checks c '
            'ON c.notification_id=n.notification_id WHERE c.check_id=? ORDER BY n.created_at,n.notification_id LIMIT 101',
            (check['check_id'],)).fetchall()
        if len(notices)>100:
            raise RecordError('check notification history exceeds its read bound')
        check['notification_intents']=[dict(row) for row in notices]
        return check

    def get(self, check_id, *, now=None):
        _identifier(check_id, 'check_id')
        row = self.db.execute('SELECT * FROM checks WHERE check_id=?', (check_id,)).fetchone()
        if row is None:
            raise RecordError('cadence check does not exist')
        return self._check(row, timestamp(now or _now()))

    def _put(self, task, kind, due_at, payload=None, recipient='secretary', project=None, check_id=None):
        task_id = task['task_id'] if task else None
        generation = task['generation'] if task else None
        project = task['repository'] if task else project
        at = due_at.isoformat()
        payload = {} if payload is None else payload
        config_digest = self._config_digest(project)
        check_id = check_id or identity('cadence-check', _payload({'project': project, 'task_id': task_id,
            'generation': generation, 'kind': kind, 'due_at': at, 'payload': payload,'config':config_digest}))
        self.db.execute('INSERT OR IGNORE INTO checks '
            '(check_id,project,task_id,generation,kind,recipient,due_at,payload,config_digest,state) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (check_id, project, task_id, generation, kind, recipient, at, _payload(payload),config_digest, 'pending'))
        return check_id

    def _reference(self, task, ref):
        if type(ref) is not dict or set(ref) != {'kind','id'}:
            raise RecordError('cadence source requires an exact kind and id')
        getters = {'event': self.records.get_event, 'outcome': self.records.get_outcome,
                   'operation': self.records.get_operation}
        if type(ref['kind']) is not str or ref['kind'] not in getters:
            raise RecordError('unsupported cadence source kind')
        row = getters[ref['kind']](ref['id'])
        generation = row.get('generation') if ref['kind'] == 'event' else row.get(
            'request' if ref['kind'] == 'operation' else 'payload', {}).get('generation')
        if type(generation) is not int or row['task_id'] != task['task_id'] or generation != task['generation']:
            raise Conflict('cadence source differs from the current task assignment')
        return row

    def expect(self, task_id, expectation_id, *, generation, since, source_ref):
        _identifier(expectation_id, 'expectation_id')
        at = _time(since)
        payload = {'expectation_id':expectation_id, 'since':at, 'source_ref':source_ref}
        _payload(payload)
        check_id = identity('cadence-expectation', expectation_id)
        with self.records._transaction():
            task = self._task(task_id, generation)
            source = self._reference(task, source_ref)
            if timestamp(source['created_at']) > timestamp(at):
                raise Conflict('report expectation precedes its retained source')
            old = self.db.execute('SELECT * FROM checks WHERE check_id=?', (check_id,)).fetchone()
            if old:
                if old['task_id'] != task_id or old['generation'] != generation or old['payload'] != _payload(payload):
                    raise Conflict('report expectation identity already has different evidence')
            else:
                due_at = timestamp(at) + timedelta(minutes=self._config(task['repository'])[
                    'cadence.report_overdue_minutes']['value'])
                self._put(task, 'report-overdue', due_at, payload, check_id=check_id)
        return self.get(check_id)

    def complete(self, check_id, receipt_id, receipt, *, completed_at):
        _identifier(receipt_id, 'receipt_id')
        encoded = _payload(receipt)
        at = _time(completed_at)
        with self.records._transaction():
            check = self.get(check_id, now=at)
            if check['state'] == 'completed':
                if (check['receipt_id'],check['receipt'],check['completed_at']) != (receipt_id,receipt,at):
                    raise Conflict('check already has a different completion receipt')
                return check
            if self.db.execute('SELECT 1 FROM checks WHERE receipt_id=?', (receipt_id,)).fetchone():
                raise Conflict('completion receipt is already bound to another check')
            task = self._task(check['task_id'], check['generation']) if check['task_id'] else None
            if check['kind']=='backlog-review':
                if set(receipt)!={'decision_id','decision_digest'}:
                    raise RecordError('backlog review check requires one exact retained review box')
                decision=self.records.get_decision(receipt['decision_id'])
                body=decision['payload']
                if (decision['task_id']!='court.backlog-review' or decision['revision']!=1
                        or body.get('kind')!='backlog.review' or body.get('grant_id')!=check['payload']['grant_id']
                        or body.get('project')!=check['project']
                        or body.get('window',{}).get('start')!=check['payload']['activated_at']
                        or hashlib.sha256(_payload(body).encode()).hexdigest()!=receipt['decision_digest']
                        or not timestamp(check['due_at'])<=timestamp(decision['created_at'])<=timestamp(at)):
                    raise Conflict('review box does not fulfill this exact trial check')
            elif check['kind'] in {'report-overdue','status','stale-status'}:
                if set(receipt) != {'event_id'}:
                    raise RecordError('report check requires one exact report event')
                source = self._reference(task, {'kind':'event','id':receipt['event_id']})
                if source['kind'] not in {'progress','completed','blocked','failed','decision'}:
                    raise Conflict('completion source is not a worker report')
                baseline = check['payload'].get('since', check['due_at'])
                if not timestamp(baseline) <= timestamp(source['created_at']) <= timestamp(at):
                    raise Conflict('completion report does not follow the check obligation')
            elif check['kind'] == 'sweep':
                if set(receipt) != {'observation_id'}:
                    raise RecordError('sweep completion requires one exact observation')
                source = self.observation(receipt['observation_id'])
                if (source['task_id'] != task['task_id'] or source['generation'] != task['generation']
                        or not timestamp(check['due_at']) <= timestamp(source['observed_at']) <= timestamp(at)):
                    raise Conflict('sweep completion requires a current observation after its deadline')
            elif check['kind'] in {'idle-action','idle-sharper'}:
                if set(receipt) != {'operation_id','action','deadline'}:
                    raise RecordError('idle steer receipt requires operation, action, and deadline')
                action = receipt['action']
                if type(action) is not str or not action.strip() or len(action) > 2000 or '\n' in action:
                    raise RecordError('idle steer requires one bounded concrete action')
                deadline = _time(receipt['deadline'])
                operation = self._reference(task, {'kind':'operation','id':receipt['operation_id']})
                request = operation['request']
                if (operation['kind'] != 'send_message' or operation['state'] != 'confirmed' or not operation['result']
                        or request.get('binding') != task['metadata'].get('binding')
                        or not request.get('binding', {}).get('session_id')
                        or request.get('sender_session_id') != task['metadata'].get('secretary_binding',{}).get('session_id')
                        or request.get('text') != '[steer] ' + action + '\nDeadline: ' + deadline
                        or not timestamp(check['due_at']) <= timestamp(operation['updated_at']) <= timestamp(at)
                        or timestamp(deadline) <= timestamp(at)):
                    raise Conflict('idle receipt must match a confirmed scoped steer and future deadline')
            elif check['kind'] == 'idle-blocker':
                if set(receipt) != {'outcome_id'}:
                    raise RecordError('idle blocker requires one exact retained outcome')
                outcome = self._reference(task, {'kind':'outcome','id':receipt['outcome_id']})
                if (outcome['payload'].get('kind') != 'blocked' or outcome['payload'].get('source_check') != check_id
                        or not timestamp(check['due_at'])<=timestamp(outcome['created_at'])<=timestamp(at)):
                    raise Conflict('blocker outcome differs from this idle obligation')
            elif check['kind'] in {'reminder','digest'}:
                if set(receipt)!={'operation_id'}:
                    raise RecordError('owner check requires one exact confirmed forward operation')
                operation=self.records.get_operation(receipt['operation_id'])
                request=operation['request']
                if (operation['kind']!='send_message' or operation['state']!='confirmed' or not operation['result']
                        or request.get('route')!='queen-forward'
                        or request.get('binding',{}).get('session_id')!=check['payload'].get('queen_session')
                        or not timestamp(check['due_at'])<=timestamp(operation['updated_at'])<=timestamp(at)):
                    raise Conflict('owner check requires confirmed delivery of its exact Queen forward')
                self._owner_source(check,operation,timestamp(at))
            else:
                raise RecordError('unsupported cadence completion kind')
            self.db.execute("UPDATE checks SET state='completed',receipt_id=?,receipt=?,completed_at=? "
                            'WHERE check_id=?', (receipt_id,encoded,at,check_id))
        return self.get(check_id, now=at)

    def _owner_source(self,check,operation,now,admission=False):
        request=operation['request']
        outcome=self.records.get_outcome(request.get('source_outcome'))
        source=outcome['payload']
        source_task=self.records.get_task(operation['task_id'])
        if (check['kind'] not in {'reminder','digest'} or check['recipient']!='queen'
                or operation['kind']!='send_message' or request.get('route')!='queen-forward'
                or request.get('binding',{}).get('session_id')!=check['payload'].get('queen_session')
                or outcome['task_id']!=operation['task_id'] or source_task['repository']!=check['project']
                or type(source.get('generation')) is not int or type(request.get('generation')) is not int
                or source['generation']!=request['generation']
                or source.get('source_check')!=check['check_id'] or source.get('kind')!='cadence-'+check['kind']
                or not timestamp(check['due_at'])<=timestamp(outcome['created_at'])<=timestamp(operation['created_at'])<=now):
            raise Conflict('owner forward source differs from this cadence obligation')
        if check['kind']=='reminder' and any(source.get(key)!=check['payload'][key]
                for key in ('decision_id','decision_revision')):
            raise Conflict('reminder source differs from the pending decision revision')
        if not admission:
            frozen=check['admission']
            if (not frozen or frozen.get('operation_id')!=operation['operation_id']
                    or frozen.get('source_outcome')!=outcome['outcome_id']
                    or frozen.get('source_digest')!=hashlib.sha256(_payload(source).encode()).hexdigest()
                    or not timestamp(outcome['created_at'])<=timestamp(frozen.get('admitted_at'))<=timestamp(operation['updated_at'])):
                raise Conflict('completion requires the exact retained cadence admission evidence')
        if check['kind']=='digest':
            _identifier(source.get('census_id'),'census_id')
            census=self.db.execute('SELECT * FROM cadence_census WHERE census_id=?',
                                   (source['census_id'],)).fetchone()
            if (not census or census['project']!=check['project']
                    or source.get('census_digest')!=hashlib.sha256(census['payload'].encode()).hexdigest()
                    or timestamp(census['created_at'])>timestamp(outcome['created_at'])
                    or timestamp(census['observed_at'])>timestamp(outcome['created_at'])):
                raise Conflict('digest source requires a retained roster predating its outcome and forward')
            # The source binds the projection actually available when the
            # outcome was retained; later readback does not rewrite that history.
            if admission:
                config=self._config(check['project'])
                _,slots,warnings=self._census(check['project'],timestamp(outcome['created_at']),config,
                                              snapshot=self.records._decode(census))
                if source.get('slots')!=slots or source.get('warnings')!=warnings:
                    raise Conflict('digest source differs from its retained observation projection')
                latest,current_slots,current_warnings=self._census(check['project'],now,config)
                if (latest is None or latest['census_id']!=source['census_id']
                        or current_slots!=slots or current_warnings!=warnings):
                    raise Conflict('digest roster or observations changed before delivery')

    def _latest(self, task_id, generation, now):
        row = self.db.execute('SELECT * FROM cadence_observations WHERE task_id=? AND generation=? '
            'AND observed_at<=? ORDER BY observed_at DESC,sequence DESC LIMIT 1',
            (task_id,generation,now.isoformat())).fetchone()
        return self.records._decode(row) if row else None

    def _watched(self, observation, now):
        watched = observation['payload']['watched_event']
        return watched is not None and timestamp(watched['until']) > now

    def _idle(self, task, config, now):
        observation = self._latest(task['task_id'],task['generation'],now)
        if (not observation or observation['payload']['native_status'] != 'idle' or self._watched(observation,now)
                or (now-timestamp(observation['observed_at'])).total_seconds() > config['cadence.stale_minutes']['value']*60):
            return
        token=self._progress(task['task_id'],task['generation'],now)
        rows = self.db.execute("SELECT * FROM checks WHERE task_id=? AND generation=? "
            "AND kind IN ('idle-action','idle-sharper','idle-blocker') ORDER BY due_at,check_id LIMIT 1001",
            (task['task_id'],task['generation'])).fetchall()
        if len(rows) > 1000:
            raise RecordError('cadence idle history exceeds this pass budget')
        history = [self._check(row,now) for row in rows if json.loads(row['payload']).get('progress_token') == token
                   and row['config_digest']==self._config_digest(task['repository'])]
        if any(row['state']=='pending' for row in history):
            return
        completed = {row['kind']:row for row in history}
        kind = 'idle-action'
        if 'idle-blocker' in completed:
            return
        if 'idle-action' in completed:
            previous = completed.get('idle-sharper',completed['idle-action'])
            if (timestamp(observation['observed_at']) <= timestamp(previous['completed_at'])
                    or timestamp(observation['observed_at']) < timestamp(previous['receipt']['deadline'])):
                return
            kind = 'idle-blocker' if 'idle-sharper' in completed else 'idle-sharper'
        self._put(task,kind,timestamp(observation['observed_at']),
                  {'observation_id':observation['observation_id'],'progress_token':token})

    def _progress(self,task_id,generation,now):
        progress = self.db.execute('SELECT payload FROM cadence_observations WHERE task_id=? AND generation=? '
            'AND observed_at<=? ORDER BY observed_at DESC,sequence DESC LIMIT 1001',
            (task_id,generation,now.isoformat())).fetchall()
        if len(progress) > 1000:
            raise RecordError('cadence progress history exceeds this pass budget')
        return next((json.loads(row[0]).get('progress_token') for row in progress
                      if json.loads(row[0]).get('progress_token')), None)

    def _periodic(self, task, kind, minutes, now):
        base = timestamp(task['created_at'])
        if kind in {'status','stale-status'}:
            report = self.db.execute("SELECT created_at FROM events WHERE task_id=? AND generation=? "
                "AND kind IN ('progress','completed','blocked','failed','decision') AND created_at<=? "
                'ORDER BY sequence DESC LIMIT 1', (task['task_id'],task['generation'],now.isoformat())).fetchone()
            if report:
                base = max(base,timestamp(report[0]))
        seconds = minutes * 60
        count = int((now - base).total_seconds() // seconds)
        if count < 1:
            return
        pending = self.db.execute("SELECT 1 FROM checks WHERE task_id=? AND generation=? "
            "AND kind=? AND state='pending' AND config_digest=? LIMIT 1",
            (task['task_id'],task['generation'],kind,self._config_digest(task['repository']))).fetchone()
        if not pending:
            self._put(task, kind, base + timedelta(seconds=count * seconds))

    @staticmethod
    def _local_at(day, clock, zone):
        hour,minute=map(int,clock.split(':'))
        wall=datetime.combine(day,time(hour,minute))
        # One occurrence per wall date/slot. Nonexistent spring times use the
        # first valid later minute; repeated autumn times use the first fold.
        for step in range(181):
            candidate=(wall+timedelta(minutes=step)).replace(tzinfo=zone,fold=0)
            utc=candidate.astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None)==candidate.replace(tzinfo=None):
                return utc
        raise RecordError('configured local cadence time has no bounded valid occurrence')

    def _pending_decisions(self):
        rows=self.db.execute("SELECT * FROM decisions WHERE state='pending' ORDER BY decision_id LIMIT 1001").fetchall()
        if len(rows)>1000:
            raise RecordError('pending decision census exceeds this pass budget')
        return [self.records._decode(row) for row in rows]

    def _decision_project(self, decision):
        task=self.records.get_task(decision['task_id'])
        if not task['task_id'].startswith('court.'):
            return task['repository']
        project=decision['payload'].get('project')
        return project if type(project) is str and _REPOSITORY.fullmatch(project) else None

    def _owner_due(self, projects, now, project_filter):
        representative=(min(projects) if projects else
                        self.records.latest_pin()['project'] if self.records.has_pins() else '')
        for project in sorted(projects):
            if project_filter and project!=project_filter:
                continue
            try:
                config=self._config(project)
            except (RecordError,ConfigError):
                continue
            zone_name=config['voice.zone']['value']
            if not self.records.has_pins() or not zone_name:
                continue
            zone=ZoneInfo(zone_name)
            local=now.astimezone(zone)
            digest_at=self._local_at(local.date(),config['cadence.digest_time']['value'],zone)
            if now>=digest_at:
                self._put(None,'digest',digest_at,{'local_date':local.date().isoformat(),
                    'queen_session':self._route(project)},recipient='queen',project=project)
        for decision in self._pending_decisions():
            scoped=self._decision_project(decision)
            project=scoped or representative
            if project_filter and project!=project_filter:
                continue
            try:
                config=self._config(project)
            except (RecordError,ConfigError):
                continue
            zone_name=config['voice.zone']['value']
            payload={'decision_id':decision['decision_id'],'decision_revision':decision['revision'],
                     'global_scope':scoped is None,'queen_session':self._route(project,scoped is None)}
            if not self.records.has_pins() or not zone_name:
                at=timestamp(decision['created_at'])
                bucket='unconfirmed-timezone'
            else:
                zone=ZoneInfo(zone_name)
                local=now.astimezone(zone)
                start=config['cadence.reminder_start']['value']
                end=config['cadence.reminder_end']['value']
                if not start<=local.strftime('%H:%M')<end:
                    continue
                start_min=int(start[:2])*60+int(start[3:])
                elapsed=local.hour*60+local.minute-start_min
                interval=config['cadence.reminder_minutes']['value']
                slot=elapsed//interval
                minute=start_min+slot*interval
                at=self._local_at(local.date(),'%02d:%02d'%(minute//60,minute%60),zone)
                if at<timestamp(decision['created_at']):
                    at=timestamp(decision['created_at'])
                bucket=local.date().isoformat()+':'+str(slot)
            check_id=identity('cadence-reminder',_payload({'decision':decision['decision_id'],
                'revision':decision['revision'],'bucket':bucket}))
            payload['calendar_bucket']=bucket
            self._put(None,'reminder',at,payload,recipient='queen',project=project,check_id=check_id)

    def due(self, *, now, limit=100, project=None, offset=0):
        current = timestamp(now)
        _limit(limit)
        _offset(offset)
        if project is not None and (type(project) is not str or not _REPOSITORY.fullmatch(project)):
            raise RecordError('cadence project must be a repository identity')
        with self.records._transaction():
            rows = self.db.execute("SELECT * FROM tasks WHERE task_id NOT LIKE 'court.%' ORDER BY task_id LIMIT 1001").fetchall()
            if len(rows) > 1000:
                raise RecordError('cadence task census exceeds this bounded pass')
            for row in rows:
                task = self.records._decode(row)
                if project and task['repository']!=project:
                    continue
                try:
                    config = self._config(task['repository'])
                except (RecordError,ConfigError):
                    continue  # Retained checks still show their explicit hold.
                for kind, key in [('sweep','cadence.sweep_minutes'), ('status','cadence.status_minutes'),
                                  ('stale-status','cadence.stale_minutes')]:
                    self._periodic(task, kind, config[key]['value'], current)
                self._idle(task,config,current)
            self._owner_due({row['repository'] for row in rows},current,project)
            checks = self.db.execute("SELECT * FROM checks WHERE state='pending' AND due_at<=? "
                + ('AND project=? ' if project else '') + 'ORDER BY due_at,check_id LIMIT ? OFFSET ?',
                (current.isoformat(),project,limit,offset) if project else (current.isoformat(),limit,offset)).fetchall()
            return [self._check(row, current) for row in checks]

    def _secretary(self, check, session):
        _uuid(session, 'secretary_session')
        tasks = self.db.execute('SELECT * FROM tasks WHERE repository=? ORDER BY task_id LIMIT 1001',
                                (check['project'],)).fetchall()
        if len(tasks) > 1000:
            raise RecordError('Secretary roster exceeds this bounded pass')
        relevant = [self.records._decode(row) for row in tasks
                    if check['task_id'] is None or row['task_id'] == check['task_id']]
        if not relevant or any(task['metadata'].get('secretary_binding', {}).get('session_id') != session
                               for task in relevant):
            raise Conflict('cadence notice requires the current registered Secretary')
        if any(not self._task_current(task,self._config(task['repository'])) for task in relevant):
            raise Conflict('cadence notice requires current task configuration custody')

    def unnotified(self, checks, secretary_session):
        _uuid(secretary_session, 'secretary_session')
        if type(checks) is not list or len(checks) > 100:
            raise RecordError('notice selection requires at most 100 checks')
        result = []
        for check in checks:
            _identifier(check['check_id'], 'check_id')
            if not self.db.execute('SELECT 1 FROM cadence_notice_checks WHERE secretary_session=? AND check_id=?',
                                   (secretary_session, check['check_id'])).fetchone():
                result.append(check)
        return result

    def get_notice(self, notification_id):
        _identifier(notification_id, 'notification_id')
        row = self.db.execute('SELECT * FROM cadence_notices WHERE notification_id=?',
                              (notification_id,)).fetchone()
        if row is None:
            raise RecordError('cadence notification intent does not exist')
        result = dict(row)
        result['check_ids'] = [r[0] for r in self.db.execute(
            'SELECT check_id FROM cadence_notice_checks WHERE notification_id=? ORDER BY check_id',
            (notification_id,))]
        return result

    def prepare_notice(self, check_ids, notification_id, *, secretary_session, created_at):
        from .records import _identifiers
        ids = sorted(_identifiers(check_ids))
        _identifier(notification_id, 'notification_id')
        _uuid(secretary_session, 'secretary_session')
        at = _time(created_at)
        with self.records._transaction():
            old = self.db.execute('SELECT 1 FROM cadence_notices WHERE notification_id=?',
                                  (notification_id,)).fetchone()
            if old:
                notice = self.get_notice(notification_id)
                if notice['check_ids'] != ids or notice['secretary_session'] != secretary_session:
                    raise Conflict('notification identity already has different intent')
                return notice
            for check_id in ids:
                check = self.get(check_id, now=at)
                self._secretary(check, secretary_session)
                if check['state'] != 'pending' or check['held_reasons'] or check['due_at'] > at:
                    raise Conflict('cadence check is not available for a notification intent')
                if not self.unnotified([check], secretary_session):
                    raise Conflict('cadence check already has an uncertain notification intent')
            self.db.execute('INSERT INTO cadence_notices VALUES (?,?,?,?)',
                            (notification_id, secretary_session, 'prepared', at))
            for check_id in ids:
                self.db.execute('INSERT INTO cadence_notice_checks VALUES (?,?,?)',
                                (notification_id, secretary_session, check_id))
        return self.get_notice(notification_id)

    def census(self, project, census_id, *, observed_at, authority_ref, slots):
        self._project(project)
        _identifier(census_id,'census_id')
        _identifier(authority_ref,'authority_ref')
        at = _time(observed_at)
        if type(slots) is not list or len(slots) > 100:
            raise RecordError('builder census requires an explicit roster of at most 100 slots')
        payload = {'authority_ref':authority_ref,'slots':slots}
        encoded = _payload(payload)
        with self.records._transaction():
            seen = set()
            for slot in slots:
                if type(slot) is not dict or not {'slot_id','status'} <= set(slot):
                    raise RecordError('builder slot requires identity and observed status')
                _identifier(slot['slot_id'],'slot_id')
                if slot['slot_id'] in seen:
                    raise RecordError('builder census contains duplicate slots')
                seen.add(slot['slot_id'])
                if type(slot['status']) is not str or slot['status'] not in {'working','idle','unknown'}:
                    raise RecordError('builder slot status must be working, idle, or unknown')
                if 'task_id' in slot:
                    if set(slot) != {'slot_id','status','task_id','generation','observation_id'}:
                        raise RecordError('assigned builder slot requires its exact observation')
                    task = self._task(slot['task_id'],slot['generation'])
                    observation = self.observation(slot['observation_id'])
                    if (task['repository'] != project or observation['task_id'] != slot['task_id']
                            or observation['generation'] != slot['generation']
                            or observation['payload']['native_status'] != slot['status']
                            or timestamp(observation['observed_at']) > timestamp(at)):
                        raise Conflict('builder slot differs from its retained current observation')
                elif set(slot) != {'slot_id','status'} or slot['status'] == 'working':
                    raise RecordError('working builder slot requires a registered task observation')
            old = self.db.execute('SELECT * FROM cadence_census WHERE census_id=?',(census_id,)).fetchone()
            if old:
                if (old['project'],old['observed_at'],old['payload']) != (project,at,encoded):
                    raise Conflict('census identity already has a different roster')
            else:
                self.db.execute('INSERT INTO cadence_census(census_id,project,observed_at,payload,created_at) '
                    'VALUES(?,?,?,?,?)',(census_id,project,at,encoded,_now()))
        return self.records._decode(self.db.execute('SELECT * FROM cadence_census WHERE census_id=?',
                                                    (census_id,)).fetchone())

    def _census(self, project, now, config, snapshot=None):
        if snapshot is None:
            row = self.db.execute('SELECT * FROM cadence_census WHERE project=? AND observed_at<=? '
                'ORDER BY observed_at DESC,sequence DESC LIMIT 1',(project,now.isoformat())).fetchone()
            if row is None:
                return None,[],['census-missing']
            snapshot = self.records._decode(row)
        slots = copy.deepcopy(snapshot['payload']['slots'])
        reasons = []
        max_age = config['cadence.stale_minutes']['value']*60
        snapshot_stale = (now-timestamp(snapshot['observed_at'])).total_seconds() > max_age
        for slot in slots:
            stale = snapshot_stale
            if 'task_id' in slot:
                observation = self.observation(slot['observation_id'])
                latest=self._latest(slot['task_id'],slot['generation'],now)
                if latest and latest['observation_id']!=slot['observation_id']:
                    slot['status']='unknown'
                    slot['reason']='observation-superseded'
                stale = (stale or self.records.get_task(slot['task_id'])['generation'] != slot['generation']
                         or (now-timestamp(observation['observed_at'])).total_seconds() > max_age)
            if stale:
                slot['status'] = 'unknown'
                slot['reason'] = 'stale'
            if slot['status'] == 'unknown':
                reasons.append('census-unknown')
        if snapshot_stale or any(s.get('reason') == 'stale' for s in slots):
            reasons.append('census-stale')
        return snapshot,slots,sorted(set(reasons))

    def digest(self, project, *, now):
        self._project(project)
        current = timestamp(now)
        config = self._config(project)
        snapshot,slots,warnings = self._census(project,current,config)
        reasons=['census-missing'] if snapshot is None else []
        zone = config['voice.zone']['value']
        if not self.records.has_pins() or not zone:
            reasons.append('unconfirmed-timezone')
        local=current.astimezone(ZoneInfo(zone)) if zone else None
        reasons.extend(self._holds({'project':project,'task_id':None,'generation':None,
            'kind':'digest','recipient':'queen','config_digest':self._config_digest(project),
            'due_at':current.isoformat(),'payload':{'queen_session':self._route(project),
                'local_date':local.date().isoformat() if local else None}},current))
        return {'project':project,'observed_at':current.isoformat(),
                'local_time':local.isoformat() if local else None,
                'census_id':snapshot['census_id'] if snapshot else None,
                'census_digest':hashlib.sha256(_payload(snapshot['payload']).encode()).hexdigest() if snapshot else None,
                'authority_ref':snapshot['payload']['authority_ref'] if snapshot else None,
                'slots':slots,'warnings':warnings,'held_reasons':sorted(set(reasons))}


def cadence_admission_check(records, operation, *, now):
    """Fence a cadence forward in the existing prepared-to-in-flight transaction."""
    if operation['request'].get('route')!='queen-forward':
        return
    source=records.get_outcome(operation['request'].get('source_outcome'))
    if source['payload'].get('kind') not in {'cadence-reminder','cadence-digest'}:
        return
    cadence=Cadence(records)
    check=cadence.get(source['payload'].get('source_check'),now=now)
    if check['state']!='pending' or check['held_reasons'] or check['admission'] is not None:
        raise Conflict('cadence check holds this owner forward')
    cadence._owner_source(check,operation,timestamp(now),admission=True)
    rows=records._connection.execute("SELECT * FROM operations WHERE state IN ('in_flight','unknown','confirmed') "
                                    'ORDER BY operation_id LIMIT 10001').fetchall()
    if len(rows)>10000:
        raise RecordError('cadence delivery history exceeds this pass budget')
    for row in rows:
        other=records._decode(row)
        if other['operation_id']==operation['operation_id'] or other['request'].get('route')!='queen-forward':
            continue
        outcome=records.get_outcome(other['request'].get('source_outcome'))
        if outcome['payload'].get('source_check')==check['check_id']:
            raise Conflict('cadence check already has an uncertain or confirmed delivery')
    receipt={'operation_id':operation['operation_id'],'source_outcome':source['outcome_id'],
             'source_digest':hashlib.sha256(_payload(source['payload']).encode()).hexdigest(),
             'admitted_at':_time(now)}
    records._connection.execute('UPDATE checks SET admission=? WHERE check_id=?',
                                (_payload(receipt),check['check_id']))
