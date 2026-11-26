"""Bounded GitHub reads and source-bound selection, never dispatch authority.

Classification is supplied by a trusted local adapter. These functions do not
authenticate that adapter, infer authority from issue prose, or reserve writers.
The caller must read again before each new dispatch admission. GitHub and the
local operation transaction cannot form one atomic remote snapshot.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import subprocess
import time

from .config import KEYS
from .preferences import REVISION, digest
from .records import Conflict, RecordError, _REPOSITORY, _identifier, _payload


MAX_REFERENCES = 20
MAX_SNAPSHOT_AGE_SECONDS = 60
KINDS = {'issue', 'pull-request'}
CLASSIFICATION_FIELDS = {'reference','source_digest','bucket','priority','size','wanted',
                        'dependencies','dependencies_complete','ownership','planned_branch',
                        'priority_surface','evidence_ref'}
POLICY_KEYS = {'selection_order':'backlog.selection_order',
               'priority_surfaces':'project.priority_surfaces',
               'priority_milestones':'project.priority_milestones'}
ITEM_FIELDS = {'repository','kind','number','node_id','state','state_reason','updated_at',
               'title_digest','body_digest','labels','assignees','milestone','complete',
               'dependencies','linked_prs','related_issues','merged','source_revision',
               'branch_repository','branch','source_digest'}
_CONNECTIONS = '''labels(first:100){nodes{name} pageInfo{hasNextPage}}
assignees(first:100){nodes{id} pageInfo{hasNextPage}} milestone{title}'''
_DEPENDENCIES = '''blockedBy(first:100){nodes{id number state stateReason
repository{nameWithOwner}} pageInfo{hasNextPage}}'''
_LINKED_PRS = '''closedByPullRequestsReferences(first:100,includeClosedPrs:true){
nodes{id number state merged headRefName headRefOid repository{nameWithOwner}
headRepository{nameWithOwner}} pageInfo{hasNextPage}}'''
QUERY = '''query MonarchyBacklog($owner:String!,$name:String!,$number:Int!){
repository(owner:$owner,name:$name){nameWithOwner defaultBranchRef{name target{oid}}
issueOrPullRequest(number:$number){__typename
... on Issue{id number state stateReason updatedAt title body ''' + _CONNECTIONS + _DEPENDENCIES + _LINKED_PRS + '''}
... on PullRequest{id number state updatedAt title body merged headRefName headRefOid
headRepository{nameWithOwner} ''' + _CONNECTIONS + '''
closingIssuesReferences(first:100){nodes{id number state stateReason updatedAt title body
repository{nameWithOwner} ''' + _DEPENDENCIES + '''} pageInfo{hasNextPage}}}}}}'''


def _repo(value):
    if type(value) is not str or not _REPOSITORY.fullmatch(value) or any(
            part in {'.', '..'} for part in value.split('/')):
        raise RecordError('backlog repository identity is invalid')
    return value.lower()


def _text(value, maximum=256):
    if (type(value) is not str or not 0 < len(value) <= maximum
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise RecordError('backlog source text is invalid')
    return value


def _number(value):
    if type(value) is not int or not 1 <= value <= 2**31-1:
        raise RecordError('backlog tracking number is invalid')
    return value


def _sha(value):
    if type(value) is not str or not REVISION.fullmatch(value):
        raise RecordError('backlog source requires a full revision')
    return value


def _at(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise RecordError('backlog observation requires an offset timestamp') from None


def _branch(value):
    _text(value)
    if (value=='@' or value.startswith(('-', '/', 'refs/')) or value.endswith(('/', '.', '.lock'))
            or '..' in value or '@{' in value or '//' in value
            or any(c in value for c in ' ~^:?*[\\')
            or any(part.startswith('.') or part.endswith('.lock') for part in value.split('/'))):
        raise RecordError('backlog branch is invalid')
    return value


def _references(values):
    if type(values) is not list or not 1 <= len(values) <= MAX_REFERENCES:
        raise RecordError('backlog scope requires 1 through 20 exact references')
    result = []
    for value in values:
        if (type(value) is not dict or set(value) != {'kind', 'number'}
                or type(value['kind']) is not str or value['kind'] not in KINDS):
            raise RecordError('backlog reference is invalid')
        result.append({'kind': value['kind'], 'number': _number(value['number'])})
    if len({(r['kind'], r['number']) for r in result}) != len(result):
        raise RecordError('backlog scope contains duplicate references')
    return sorted(result, key=lambda r: (r['kind'], r['number']))


def _nodes(value):
    if (type(value) is not dict or type(value.get('nodes')) is not list
            or len(value['nodes']) > 100 or type(value.get('pageInfo')) is not dict
            or type(value['pageInfo'].get('hasNextPage')) is not bool):
        raise RecordError('backlog relationship completeness is unavailable')
    return value['nodes'], not value['pageInfo']['hasNextPage']


def _content(value):
    if type(value) is not str or len(value.encode('utf-8')) > 65536:
        raise RecordError('backlog source content exceeds its bound')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _dependency(value):
    if type(value) is not dict or value.get('state') not in {'OPEN', 'CLOSED'}:
        raise RecordError('backlog dependency state is invalid')
    reason = value.get('stateReason')
    if reason not in {None, 'COMPLETED', 'NOT_PLANNED', 'REOPENED', 'DUPLICATE'}:
        raise RecordError('backlog dependency disposition is unknown')
    return {'repository': _repo(value['repository']['nameWithOwner']),
            'number': _number(value['number']), 'node_id': _text(value['id']),
            'state': value['state'], 'state_reason': reason}


def _linked_pr(value):
    if (type(value) is not dict or value.get('state') not in {'OPEN', 'CLOSED', 'MERGED'}
            or type(value.get('merged')) is not bool
            or value['merged'] != (value['state'] == 'MERGED')):
        raise RecordError('backlog linked PR state is invalid')
    return {'repository': _repo(value['repository']['nameWithOwner']),
            'number': _number(value['number']), 'node_id': _text(value['id']),
            'state': value['state'], 'merged': value['merged'],
            'branch_repository': _repo(value['headRepository']['nameWithOwner']),
            'branch': _branch(value['headRefName']), 'source_revision': _sha(value['headRefOid'])}


def _ordered(values, fields):
    keys = [tuple(value[field] for field in fields) for value in values]
    if len(set(keys)) != len(keys):
        raise RecordError('backlog source contains duplicate identities')
    return [value for _, value in sorted(zip(keys, values), key=lambda pair: pair[0])]


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise RecordError('backlog source contains duplicate JSON members')
        result[key]=value
    return result


def _nonfinite(value):
    raise RecordError('backlog source contains invalid JSON numbers')


def _item(repository, reference, data):
    repo = data['data']['repository']
    if _repo(repo['nameWithOwner']) != repository:
        raise Conflict('backlog source repository differs from requested scope')
    value = repo['issueOrPullRequest']
    expected = 'Issue' if reference['kind'] == 'issue' else 'PullRequest'
    if (value['__typename'] != expected or type(value['number']) is not int
            or value['number'] != reference['number']):
        raise Conflict('backlog source identity differs from requested scope')
    labels, labels_complete = _nodes(value['labels'])
    assignees, assignees_complete = _nodes(value['assignees'])
    item = {'repository': repository, **reference, 'node_id': _text(value['id']),
            'state': value['state'], 'state_reason': value.get('stateReason'),
            'updated_at': _at(value['updatedAt']), 'title_digest': _content(value['title']),
            'body_digest': _content(value['body']),
            'labels': sorted(_text(v['name']) for v in labels),
            'assignees': sorted(_text(v['id']) for v in assignees),
            'milestone': _text(value['milestone']['title']) if value['milestone'] else None,
            'complete': labels_complete and assignees_complete,
            'dependencies': [], 'linked_prs': [], 'related_issues': []}
    if expected == 'PullRequest':
        if (value['state'] not in {'OPEN','CLOSED','MERGED'} or type(value.get('merged')) is not bool
                or value['merged'] != (value['state'] == 'MERGED')):
            raise RecordError('backlog PR state is inconsistent')
        item.update(merged=value['merged'], source_revision=_sha(value['headRefOid']),
                    branch_repository=_repo(value['headRepository']['nameWithOwner']),
                    branch=_branch(value['headRefName']))
        issues, complete = _nodes(value['closingIssuesReferences'])
        item['complete'] &= complete
        dependencies_by_id={}
        for issue in issues:
            related = _dependency(issue)
            related.update(updated_at=_at(issue['updatedAt']), title_digest=_content(issue['title']),
                           body_digest=_content(issue['body']))
            item['related_issues'].append(related)
            dependencies, complete = _nodes(issue['blockedBy'])
            item['complete'] &= complete
            for dependency in _ordered([_dependency(v) for v in dependencies],('repository','number')):
                key=(dependency['repository'],dependency['number'])
                if key in dependencies_by_id and dependencies_by_id[key]!=dependency:
                    raise Conflict('backlog dependency changed within the source read')
                dependencies_by_id[key]=dependency
        item['dependencies']=list(dependencies_by_id.values())
    else:
        if value['state'] not in {'OPEN','CLOSED'}:
            raise RecordError('backlog issue state is invalid')
        item.update(merged=False, source_revision=_sha(repo['defaultBranchRef']['target']['oid']),
                    branch_repository=repository, branch=None)
        dependencies, complete = _nodes(value['blockedBy'])
        item['complete'] &= complete
        item['dependencies'] = [_dependency(v) for v in dependencies]
        linked, complete = _nodes(value['closedByPullRequestsReferences'])
        item['complete'] &= complete
        item['linked_prs'] = [_linked_pr(v) for v in linked]
    for field in ('dependencies','linked_prs','related_issues'):
        item[field] = _ordered(item[field], ('repository','number'))
    item['source_digest'] = digest(item)
    return item


class GitHubBacklog:
    """Read an explicit candidate window with fixed GraphQL queries and hard bounds.

    This window does not establish whole-repository coverage. The grant layer
    decides whether project-wide authority or an exact allowlist covers it.
    """
    def __init__(self, *, runner=subprocess.run, timeout=30, max_bytes=1048576,
                 now=lambda: datetime.now(timezone.utc), clock=time.monotonic):
        if type(timeout) not in {int,float} or not math.isfinite(timeout) or not 0<timeout<=60:
            raise RecordError('backlog timeout must be positive and at most 60 seconds')
        if type(max_bytes) is not int or not 1<=max_bytes<=1048576:
            raise RecordError('backlog response bound must be at most 1048576 bytes')
        self.runner, self.timeout, self.max_bytes = runner, timeout, max_bytes
        self.now, self.clock = now, clock

    def read(self, project, references):
        repository, refs = _repo(project), _references(references)
        owner, name = repository.split('/')
        deadline = self.clock() + self.timeout
        items = []
        remaining_bytes=self.max_bytes
        for reference in refs:
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise RecordError('backlog source read deadline reached')
            request = {'query': QUERY, 'variables': {'owner': owner, 'name': name, 'number': reference['number']}}
            try:
                response = self.runner(['gh','api','graphql','--input','-'], input=json.dumps(request),
                    capture_output=True, text=True, check=False, timeout=remaining, shell=False)
                if response.returncode:
                    raise RecordError('backlog source read failed')
                if type(response.stdout) is not str or len(response.stdout.encode('utf-8')) > remaining_bytes:
                    raise RecordError('backlog source response exceeds its bound')
                remaining_bytes-=len(response.stdout.encode('utf-8'))
                data = json.loads(response.stdout, object_pairs_hook=_unique, parse_constant=_nonfinite)
                if type(data) is not dict or data.get('errors'):
                    raise RecordError('backlog source read is incomplete')
                item=_item(repository,reference,data)
                _stored_item(item)
                items.append(item)
            except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, KeyError, TypeError, RecursionError):
                raise RecordError('backlog source is unavailable or invalid') from None
            if self.clock() >= deadline:
                raise RecordError('backlog source read deadline reached')
        value = {'repository': repository, 'references': refs, 'items': items}
        result={**value,'observed_at':_at(self.now().isoformat()),'digest':digest(value)}
        _payload(result)
        return result


def _stored_item(item):
    if type(item) is not dict or set(item)!=ITEM_FIELDS:
        raise RecordError('backlog item schema is invalid')
    _references([{key:item[key] for key in ('kind','number')}])
    for key in ('repository','branch_repository'):
        if _repo(item[key])!=item[key]:
            raise RecordError('backlog repository must be canonical')
    _text(item['node_id'])
    _sha(item['source_revision'])
    _at(item['updated_at'])
    if type(item['complete']) is not bool or type(item['merged']) is not bool:
        raise RecordError('backlog source certainty is invalid')
    if (type(item['state']) is not str or item['state'] not in {'OPEN','CLOSED','MERGED'}
            or type(item['state_reason']) not in {str,type(None)}
            or item['state_reason'] not in {None,'COMPLETED','NOT_PLANNED','REOPENED','DUPLICATE'}):
        raise RecordError('backlog item state is invalid')
    if item['kind']=='issue':
        if item['branch'] is not None or item['merged'] or item['state']=='MERGED':
            raise RecordError('backlog issue has invalid PR fields')
    elif item['merged']!=(item['state']=='MERGED'):
        raise RecordError('backlog PR state is invalid')
    else:
        _branch(item['branch'])
    for field in ('source_digest','title_digest','body_digest'):
        if type(item[field]) is not str or not re.fullmatch('[0-9a-f]{64}',item[field]):
            raise RecordError('backlog content digest is invalid')
    for field in ('labels','assignees'):
        values=item[field]
        if type(values) is not list or len(values)>100:
            raise RecordError('backlog source list exceeds its bound')
        for value in values:
            _text(value)
        if values!=sorted(set(values)):
            raise RecordError('backlog source list is duplicated or unordered')
    if item['milestone'] is not None:
        _text(item['milestone'])
    for field in ('dependencies','linked_prs','related_issues'):
        values=item[field]
        if type(values) is not list or len(values)>100:
            raise RecordError('backlog relationship list exceeds its bound')
        for value in values:
            base={'repository','number','node_id','state'}
            extra=({'merged','branch_repository','branch','source_revision'} if field=='linked_prs'
                   else {'state_reason','updated_at','title_digest','body_digest'} if field=='related_issues'
                   else {'state_reason'})
            if type(value) is not dict or set(value)!=base|extra:
                raise RecordError('backlog relationship schema is invalid')
            if _repo(value['repository'])!=value['repository']:
                raise RecordError('backlog relationship repository must be canonical')
            _number(value['number'])
            _text(value['node_id'])
            if type(value['state']) is not str or value['state'] not in {'OPEN','CLOSED','MERGED'}:
                raise RecordError('backlog relationship state is invalid')
            if field=='linked_prs':
                if type(value['merged']) is not bool or value['merged']!=(value['state']=='MERGED'):
                    raise RecordError('backlog linked PR is inconsistent')
                _repo(value['branch_repository'])
                _branch(value['branch'])
                _sha(value['source_revision'])
            else:
                if (value['state']=='MERGED' or type(value['state_reason']) not in {str,type(None)}
                        or value['state_reason'] not in {None,'COMPLETED','NOT_PLANNED','REOPENED','DUPLICATE'}):
                    raise RecordError('backlog dependency state is invalid')
                if field=='related_issues':
                    _at(value['updated_at'])
                    for key in ('title_digest','body_digest'):
                        if type(value[key]) is not str or not re.fullmatch('[0-9a-f]{64}',value[key]):
                            raise RecordError('backlog relationship digest is invalid')
        if values!=_ordered(values,('repository','number')):
            raise RecordError('backlog relationships must have canonical order')


def _snapshot(value):
    _payload(value)
    if (not {'repository','references','items','digest'} <= set(value)
            or not set(value) <= {'repository','references','items','digest','observed_at'}):
        raise RecordError('backlog snapshot is malformed')
    if 'observed_at' in value:
        _at(value['observed_at'])
    project = _repo(value['repository'])
    refs = _references(value['references'])
    if type(value['items']) is not list or len(value['items']) != len(refs):
        raise RecordError('backlog snapshot does not cover its scope')
    items = copy.deepcopy(value['items'])
    for ref,item in zip(refs,items):
        _stored_item(item)
        if (type(item) is not dict or item.get('repository') != project
                or any(item.get(k) != v for k,v in ref.items())
                or item.get('source_digest') != digest({k:v for k,v in item.items() if k!='source_digest'})):
            raise Conflict('backlog source digest or scope changed')
    result = {'repository':project,'references':refs,'items':items}
    if value['digest'] != digest(result):
        raise Conflict('backlog snapshot digest changed')
    return {**result,'digest':value['digest']}


def _policy(config):
    try:
        result = {name:copy.deepcopy(config[key]['value']) for name,key in POLICY_KEYS.items()}
    except (KeyError,TypeError):
        raise RecordError('backlog selection requires effective project settings') from None
    if (type(result['selection_order']) is not list
            or any(type(v) is not str for v in result['selection_order'])
            or len(result['selection_order']) != len(KEYS['backlog.selection_order']['default'])
            or set(result['selection_order']) != set(KEYS['backlog.selection_order']['default'])):
        raise RecordError('backlog selection order is invalid')
    for key in ('priority_surfaces','priority_milestones'):
        if type(result[key]) is not list or len(result[key]) > 64:
            raise RecordError('backlog priority policy is invalid')
        for item in result[key]:
            _text(item)
    return result


def _classifications(snapshot, values):
    if type(values) is not list or len(values)>MAX_REFERENCES:
        raise RecordError('backlog classification exceeds its bound')
    known = {(r['kind'],r['number']) for r in snapshot['references']}
    result = {}
    for value in values:
        if type(value) is not dict or set(value)!=CLASSIFICATION_FIELDS:
            raise RecordError('backlog classification is malformed')
        _payload(value)
        for field in ('priority','size'):
            if value[field] is not None and (type(value[field]) is not int or not 0<=value[field]<=1000000):
                raise RecordError('backlog classification rank is invalid')
        for field in ('wanted','dependencies_complete'):
            if value[field] is not None and type(value[field]) is not bool:
                raise RecordError('backlog classification certainty is invalid')
        if value['bucket'] is not None and value['bucket'] not in KEYS['backlog.selection_order']['default']:
            raise RecordError('backlog classification category is invalid')
        if type(value['ownership']) is not str or value['ownership'] not in {'clear','owned','unknown'}:
            raise RecordError('backlog ownership classification is invalid')
        _identifier(value['evidence_ref'],'evidence_ref')
        if value['priority_surface'] is not None:
            _text(value['priority_surface'])
        if value['planned_branch'] is not None:
            _branch(value['planned_branch'])
        dependencies=value['dependencies']
        if type(dependencies) is not list or len(dependencies)>100:
            raise RecordError('backlog dependencies exceed their bound')
        for dependency in dependencies:
            if type(dependency) is not dict or set(dependency)!={'repository','number'}:
                raise RecordError('backlog dependency reference is invalid')
            if _repo(dependency['repository'])!=dependency['repository']:
                raise RecordError('backlog dependency repository must be canonical')
            _number(dependency['number'])
        _ordered(dependencies,('repository','number'))
        reference = _references([value['reference']])[0]
        key=(reference['kind'],reference['number'])
        if key not in known or key in result:
            raise RecordError('backlog classification scope is duplicated or foreign')
        result[key]=copy.deepcopy(value)
    return result


def select(snapshot, config, classifications):
    """Select the next eligible item in this exact scope; grant no authority."""
    source = _snapshot(snapshot)
    policy = _policy(config)
    facts = _classifications(source,classifications)
    eligible,held = [],[]
    for item in source['items']:
        reference={'kind':item['kind'],'number':item['number']}
        fact=facts.get((item['kind'],item['number']))
        if fact is None:
            held.append({'reference':reference,'reasons':['classification-missing']})
            continue
        if fact['source_digest']!=item['source_digest']:
            held.append({'reference':reference,'reasons':['classification-stale']})
            continue
        reasons=[]
        if fact['bucket'] is None or fact['priority'] is None or fact['size'] is None:
            reasons.append('classification-unknown')
        if fact['wanted'] is not True:
            reasons.append('not-wanted' if fact['wanted'] is False else 'wanted-unknown')
        if fact['dependencies_complete'] is not True:
            reasons.append('dependencies-unresolved')
        if fact['ownership']!='clear':
            reasons.append('ownership-'+fact['ownership'])
        if item['kind']=='pull-request':
            expected='open-prs' if item['state']=='OPEN' else 'wanted-parked-prs'
            if item['merged'] or fact['bucket']!=expected:
                reasons.append('category-source-mismatch')
            if item['state']=='CLOSED' and not any(v['state']=='OPEN' for v in item['related_issues']):
                reasons.append('parked-issue-not-open')
            if fact['planned_branch'] is not None:
                reasons.append('branch-source-mismatch')
        elif item['state']!='OPEN' or fact['bucket'] in {'open-prs','wanted-parked-prs'}:
            reasons.append('category-source-mismatch')
        elif fact['planned_branch'] is None:
            reasons.append('planned-branch-missing')
        if fact['bucket']=='priority-epics' and not (
                fact['priority_surface'] in policy['priority_surfaces']
                or item['milestone'] in policy['priority_milestones']):
            reasons.append('project-priority-unconfirmed')
        if item['complete'] is not True:
            reasons.append('source-incomplete')
        if item['assignees']:
            reasons.append('native-assignment-present')
        if any(pr['state']=='OPEN' for pr in item['linked_prs']):
            reasons.append('existing-open-pr')
        dependencies={(v['repository'],v['number']):v for v in item['dependencies']}
        for ref in fact['dependencies']:
            key=(ref['repository'],ref['number'])
            if key not in dependencies:
                dependencies[key]=next((v for v in source['items'] if v['kind']=='issue'
                    and (v['repository'],v['number'])==key),None)
        if any(v is None or v['state']!='CLOSED' or v['state_reason']!='COMPLETED'
               for v in dependencies.values()):
            reasons.append('dependencies-unresolved')
        if reasons:
            held.append({'reference':reference,'reasons':sorted(reasons)})
            continue
        rank=[policy['selection_order'].index(fact['bucket']),fact['priority'],fact['size'],
              item['kind'],item['number']]
        branch=item['branch'] if item['kind']=='pull-request' else fact['planned_branch']
        eligible.append((rank,item,fact,branch))
    if not eligible:
        return {'candidate':None,'held':held}
    rank,item,fact,branch=min(eligible,key=lambda value:value[0])
    selection={'snapshot':source,'classifications':[facts[k] for k in sorted(facts)],'policy':policy}
    candidate={key:copy.deepcopy(item[key]) for key in ('repository','kind','number','node_id',
               'source_revision','branch_repository','source_digest')}
    candidate.update(branch=branch,snapshot_digest=source['digest'],classification_digest=digest(
        {'classifications':selection['classifications']}),rank=rank,selection=selection)
    candidate['candidate_id']='backlog.'+digest(candidate)
    _payload(candidate)
    return {'candidate':candidate,'held':held}


def validate_frozen_candidate(candidate, *, config=None):
    """Recompute saved selection for binding only; prove no source freshness."""
    _payload(candidate)
    try:
        selection=candidate['selection']
        source=_snapshot(selection['snapshot'])
        policy=selection['policy']
        frozen_config={key:{'value':policy[name]} for name,key in POLICY_KEYS.items()}
        if config is not None and _policy(config)!=policy:
            raise Conflict('backlog selection policy changed')
        expected=select(source,frozen_config,selection['classifications'])['candidate']
        if expected is None or _payload(expected)!=_payload(candidate):
            raise Conflict('backlog candidate differs from its frozen selection')
    except (KeyError,TypeError,IndexError):
        raise RecordError('backlog candidate is malformed') from None
    return copy.deepcopy(candidate)


def validate_candidate(candidate, fresh_snapshot, *, config=None, now=None):
    """Recompute selection against a separately obtained fresh read.

    This function does not authenticate the fresh read or perform it. The core
    supplies current config and separately enforces grants and branch custody.
    """
    frozen=validate_frozen_candidate(candidate,config=config)
    if type(fresh_snapshot) is not dict or 'observed_at' not in fresh_snapshot:
        raise RecordError('backlog admission requires a separate source read receipt')
    current=datetime.now(timezone.utc) if now is None else now
    current=_at(current.isoformat() if isinstance(current,datetime) else current)
    observed=_at(fresh_snapshot['observed_at'])
    age=(datetime.fromisoformat(current)-datetime.fromisoformat(observed)).total_seconds()
    if not 0<=age<=MAX_SNAPSHOT_AGE_SECONDS:
        raise Conflict('backlog source read receipt is stale or from the future')
    if _snapshot(fresh_snapshot)!=frozen['selection']['snapshot']:
        raise Conflict('backlog source changed before admission')
    return frozen
