"""Explicit commands for the royalty. Reading help never opens state or starts agents."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .records import CourtRecords, RecordError, _payload
from .conductor import ConductorTransport, TransportError, _json
from .supervision import Court
from .config import ConfigError, load, resolve
from .preferences import Preferences, read_source, _git
from .orders import render, OrdersError
from .conversation import Conversation
from .prompt_hooks import HookError, settings_snippet, lint_box
from .controls import Controls


def document(path, *, allow_list=False):
    with Path(path).open('rb') as file:
        raw = file.read(65537)
    if len(raw) > 65536:
        raise RecordError('input document exceeds 64 KiB')
    value = _json(raw)
    if allow_list:
        if type(value) is not list:
            raise RecordError('input document requires a JSON list')
        _payload({'items': value})
    else:
        _payload(value)
    return value


def cadence_document(path, required, optional=()):
    value = document(path)
    if type(value) is not dict or not set(required) <= set(value) or not set(value) <= set(required) | set(optional):
        raise RecordError('cadence input requires the expected fields')
    return value


def now_string(value=None):
    return value if value is not None else datetime.now(timezone.utc).isoformat()


def reread_backlog(path):
    """A saved snapshot supplies the intended scope, never fresh read proof."""
    from .backlog_selection import GitHubBacklog
    snapshot = document(path)
    if not {'repository', 'references'} <= set(snapshot):
        raise RecordError('backlog source file requires its repository and reference window')
    return GitHubBacklog().read(snapshot['repository'], snapshot['references'])


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', help='private SQLite path outside the source checkout')
    commands = p.add_subparsers(dest='command', required=True)
    config = commands.add_parser('config', help='validate, preview or pin royalty preferences')
    actions = config.add_subparsers(dest='config_action', required=True)
    check = actions.add_parser('check')
    check.add_argument('file'); check.add_argument('--layer', choices=('project', 'owner'), required=True)
    show = actions.add_parser('show')
    show.add_argument('key', nargs='?'); show.add_argument('--owner'); show.add_argument('--project')
    for action in ('founding', 'pin'):
        sub = actions.add_parser(action)
        sub.add_argument('--owner-repo', required=True); sub.add_argument('--owner-commit', required=True)
        sub.add_argument('--owner-file', default='owner.json')
        sub.add_argument('--project-repo'); sub.add_argument('--project-commit')
        sub.add_argument('--project-file', default='.agents/monarchy.json')
        if action == 'pin': sub.add_argument('--owner-message', required=True)
    override = actions.add_parser('override')
    override.add_argument('key'); override.add_argument('file')
    override.add_argument('--owner-message', required=True); override.add_argument('--project', default='')
    orders = commands.add_parser('orders', help='render hash-pinned role standing orders')
    orders.add_argument('role', choices=('queen', 'secretary', 'worker'))
    orders.add_argument('--owner'); orders.add_argument('--project')
    prompt = commands.add_parser('prompt', help='observe a native Queen prompt without recording answers')
    prompt.add_argument('action', choices=('open', 'close', 'cancel', 'unknown', 'status'))
    prompt.add_argument('--session', required=True); prompt.add_argument('--prompt-id')
    settings = commands.add_parser('prompt-settings', help='print opt-in hook settings without installing them')
    settings.add_argument('--script', required=True); settings.add_argument('--state-path', required=True)
    box = commands.add_parser('box-lint', help='validate optional decision box style')
    box.add_argument('file')
    forward = commands.add_parser('prepare-forward', help='journal a bounded Secretary summary without sending')
    forward.add_argument('outcome_id'); forward.add_argument('file')
    cadence = commands.add_parser('cadence', help='record observations and exact check receipts')
    check_actions = cadence.add_subparsers(dest='cadence_action', required=True)
    for action in ('observe', 'expect', 'census'):
        check_actions.add_parser(action).add_argument('file')
    check_actions.add_parser('get').add_argument('check_id')
    complete = check_actions.add_parser('complete')
    complete.add_argument('check_id'); complete.add_argument('file')
    complete.add_argument('--receipt-id', required=True); complete.add_argument('--completed-at')
    digest = check_actions.add_parser('digest')
    digest.add_argument('project'); digest.add_argument('--now')
    due = commands.add_parser('due', help='persist and list due checks without sending or completing them')
    due.add_argument('--project'); due.add_argument('--now'); due.add_argument('--limit', type=int, default=100)
    due.add_argument('--offset', type=int, default=0)
    wait = commands.add_parser('wait', help='perform one bounded Secretary wait without native actions')
    wait.add_argument('--project', required=True); wait.add_argument('--secretary-session', required=True)
    wait.add_argument('--max-seconds', type=int, default=6600)
    wait.add_argument('--poll-seconds', type=int, default=30)
    rearm = commands.add_parser('rearm-settings', help='print opt-in Secretary hook settings without installing them')
    rearm.add_argument('--script', required=True); rearm.add_argument('--state-path', required=True)
    rearm.add_argument('--project', required=True); rearm.add_argument('--secretary-session', required=True)
    delegation = commands.add_parser('delegation', help='record scoped grants without activating them by default')
    grant_actions = delegation.add_subparsers(dest='delegation_action', required=True)
    grant_actions.add_parser('categories').add_argument('project')
    state = grant_actions.add_parser('state')
    state.add_argument('project'); state.add_argument('category')
    propose = grant_actions.add_parser('propose')
    propose.add_argument('file'); propose.add_argument('--owner-message', required=True)
    followup = grant_actions.add_parser('followup')
    followup.add_argument('owner_decision_id'); followup.add_argument('--owner-message', required=True)
    grant_actions.add_parser('apply').add_argument('decision_id')
    revoke = grant_actions.add_parser('revoke')
    revoke.add_argument('project'); revoke.add_argument('category')
    revoke.add_argument('--owner-message', required=True)
    delegated_answer = grant_actions.add_parser('answer')
    delegated_answer.add_argument('decision_id'); delegated_answer.add_argument('file')
    delegated_answer.add_argument('--revision', type=int, required=True)
    delegated_answer.add_argument('--grant-id', required=True)
    delegated_answer.add_argument('--current-head', help='fresh observed full head for internal PR approval')
    backlog = commands.add_parser('backlog', help='select bounded work under an answered project grant')
    backlog_actions = backlog.add_subparsers(dest='backlog_action', required=True)
    backlog_actions.add_parser('state').add_argument('project')
    proposal = backlog_actions.add_parser('propose')
    proposal.add_argument('file'); proposal.add_argument('--owner-message', required=True)
    backlog_actions.add_parser('apply').add_argument('decision_id')
    revoke_backlog = backlog_actions.add_parser('revoke')
    revoke_backlog.add_argument('project'); revoke_backlog.add_argument('--owner-message', required=True)
    backlog_actions.add_parser('read', help='read fresh GitHub sources without remote writes').add_argument('file')
    selection = backlog_actions.add_parser('select')
    selection.add_argument('snapshot'); selection.add_argument('classifications')
    bind = backlog_actions.add_parser('bind', help='print a grant-bound task without registering or dispatching')
    bind.add_argument('file'); bind.add_argument('--candidate', required=True)
    bind.add_argument('--grant-id', required=True)
    prepare = backlog_actions.add_parser('prepare')
    prepare.add_argument('file'); prepare.add_argument('--snapshot', required=True)
    prepare.add_argument('--idle-source'); prepare.add_argument('--new-session', action='store_true')
    pull = backlog_actions.add_parser('pull', help='read, select and prepare one eligible idle assignment without sending')
    pull.add_argument('file'); pull.add_argument('--classifications', required=True)
    pull.add_argument('--idle-source', required=True); pull.add_argument('--new-session', action='store_true')
    release = backlog_actions.add_parser('release')
    release.add_argument('reservation_id'); release.add_argument('file')
    release.add_argument('--receipt-id', required=True)
    backlog_actions.add_parser('review').add_argument('file')
    control = commands.add_parser('control', help='record owner controls or apply an answered proposal')
    verbs = control.add_subparsers(dest='verb', required=True)
    for verb in ('bearings', 'decisions', 'pause', 'stop', 'away', 'resume', 'model', 'handoff'):
        sub = verbs.add_parser(verb)
        if verb in ('model', 'handoff'): sub.add_argument('file')
        if verb not in ('bearings', 'decisions'): sub.add_argument('--owner-message', required=True)
    verbs.add_parser('apply').add_argument('decision_id')
    register = commands.add_parser('register', help='record a task and its explicit native binding')
    register.add_argument('file')
    for name in ('tick', 'status'):
        commands.add_parser(name).add_argument('task')
    ingest = commands.add_parser('ingest', help='read a native report and verify its sender')
    ingest.add_argument('task'); ingest.add_argument('event_id')
    inbox = commands.add_parser('inbox', help='present, but do not consume, pending outcomes')
    inbox.add_argument('--actor', choices=('queen', 'secretary'), default='queen')
    ack = commands.add_parser('ack', help='acknowledge only specified presented outcomes')
    ack.add_argument('presentation_id'); ack.add_argument('outcome_ids', nargs='+')
    ack.add_argument('--actor', choices=('queen', 'secretary'), default='queen')
    answer = commands.add_parser('answer', help='record an answer obtained from the trusted owner channel')
    answer.add_argument('decision_id'); answer.add_argument('file')
    answer.add_argument('--revision', type=int, required=True)
    answer.add_argument('--owner-message', required=True)
    send_answer = commands.add_parser('prepare-answer', help='journal scoped answer delivery without sending')
    send_answer.add_argument('decision_id')
    send_answer.add_argument('--current-head', help='fresh observed full head for an internal PR answer')
    dispatch = commands.add_parser('prepare-dispatch', help='journal a brief without launching or sending')
    dispatch.add_argument('task'); dispatch.add_argument('--new-session', action='store_true')
    dispatch.add_argument('--backlog-snapshot'); dispatch.add_argument('--idle-source')
    deliver = commands.add_parser('deliver', help='explicitly execute or reconcile a journaled operation')
    deliver.add_argument('operation_id')
    deliver.add_argument('--current-head', help='fresh observed full head before a new internal PR answer send')
    deliver.add_argument('--backlog-snapshot', help='fresh source read for a new backlog send; reconciliation needs none')
    verify = commands.add_parser('verify', help='record independent, source-bound review evidence')
    verify.add_argument('task'); verify.add_argument('file')
    return p


def preview(args):
    owner = load(Path(args.owner).read_bytes(), 'owner') if args.owner else None
    project = load(Path(args.project).read_bytes(), 'project') if args.project else None
    return {'config': resolve(owner=owner, project=project), 'preview': True, 'held': False}


def sources(args):
    owner = read_source(args.owner_repo, args.owner_commit, args.owner_file, 'owner')
    if bool(args.project_repo) != bool(args.project_commit):
        raise ConfigError('project requires repository and commit together')
    project = read_source(args.project_repo, args.project_commit, args.project_file, 'project') if args.project_repo else None
    return owner, project


def output(value, *, compact=False):
    if compact:
        text = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        if len(text.encode('utf-8')) + 1 > 65536:
            raise RecordError('export exceeds the input document bound')
        print(text)
    else:
        print(json.dumps(value, sort_keys=True, indent=2))


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.command == 'rearm-settings':
            from .rearm import settings_snippet as rearm_settings
            output(rearm_settings(args.script, args.state_path, args.project, args.secretary_session))
            return
        if args.command == 'prompt-settings':
            output(settings_snippet(args.script, args.state_path))
            return
        if args.command == 'box-lint':
            box = document(args.file)
            if set(box) != {'question', 'options'}:
                raise HookError('box input requires exactly question and options')
            lint_box(box['question'], box['options'])
            output({'valid': True})
            return
        if args.command == 'config' and args.config_action == 'check':
            load(Path(args.file).read_bytes(), args.layer)
            output({'valid': True, 'layer': args.layer})
            return
        is_view = args.command == 'orders' or (args.command == 'config' and args.config_action == 'show')
        if is_view:
            if args.owner or not args.state:
                view = preview(args)
            else:
                with CourtRecords(args.state) as records:
                    view = Preferences(records).show(args.project or '')
                # Show effective values and provenance, not unrelated raw private files.
                view.pop('sources', None)
            if args.command == 'orders':
                if view['held']: raise ConfigError('configuration drift holds standing orders')
                output(render(args.role, view['config']))
            else:
                if args.key:
                    if args.key not in view['config']: raise ConfigError('unknown configuration key')
                    view['config'] = {args.key: view['config'][args.key]}
                output(view)
            return
        if not args.state:
            p.error('--state is required for royalty record commands')
        with CourtRecords(args.state) as records:
            court = Court(records, ConductorTransport())
            command = args.command
            if command in ('cadence', 'due'):
                from .cadence import Cadence
                cadence = Cadence(records)
                if command == 'due':
                    result = cadence.due(now=now_string(args.now), limit=args.limit,
                                         project=args.project, offset=args.offset)
                elif args.cadence_action == 'observe':
                    result = cadence.observe(**cadence_document(args.file,
                        {'task_id', 'observation_id', 'generation', 'observed_at', 'native_status'},
                        {'watched_event', 'report_expected_since', 'progress_ref'}))
                elif args.cadence_action == 'expect':
                    result = cadence.expect(**cadence_document(args.file,
                        {'task_id', 'expectation_id', 'generation', 'since', 'source_ref'}))
                elif args.cadence_action == 'census':
                    result = cadence.census(**cadence_document(args.file,
                        {'project', 'census_id', 'observed_at', 'authority_ref', 'slots'}))
                elif args.cadence_action == 'get':
                    result = cadence.get(args.check_id)
                elif args.cadence_action == 'complete':
                    result = cadence.complete(args.check_id, args.receipt_id, document(args.file),
                                              completed_at=now_string(args.completed_at))
                elif args.cadence_action == 'digest':
                    result = cadence.digest(args.project, now=now_string(args.now))
            elif command == 'wait':
                from .rearm import wait as wait_for_checks
                result = wait_for_checks(records, project=args.project, secretary_session=args.secretary_session,
                    max_seconds=args.max_seconds, poll_seconds=args.poll_seconds)
            elif command == 'delegation':
                from .delegation import Delegation
                grants = Delegation(records)
                action = args.delegation_action
                if action == 'categories':
                    result = grants.categories(args.project)
                elif action == 'state':
                    result = grants.state(args.project, args.category)
                elif action == 'propose':
                    proposal = document(args.file)
                    if type(proposal) is not dict or set(proposal) != {
                            'project', 'category', 'state', 'precedents'}:
                        raise RecordError('delegation proposal requires exact fields')
                    result = grants.propose(**proposal, owner_message=args.owner_message)
                elif action == 'apply':
                    result = grants.apply(args.decision_id)
                elif action == 'followup':
                    result = grants.followup(args.owner_decision_id, owner_message=args.owner_message)
                elif action == 'revoke':
                    result = grants.revoke(args.project, args.category,
                                           owner_message=args.owner_message)
                elif action == 'answer':
                    result = grants.answer(args.decision_id, document(args.file),
                        expected_revision=args.revision, grant_id=args.grant_id,
                        current_head=args.current_head)
            elif command == 'control':
                controls = Controls(records)
                if args.verb == 'apply':
                    result = controls.apply(args.decision_id)
                else:
                    result = controls.command(args.verb,
                        document(args.file) if args.verb in ('model', 'handoff') else None,
                        owner_message=getattr(args, 'owner_message', None))
            elif command == 'backlog':
                from .backlog import Backlog
                from .backlog_selection import GitHubBacklog, select
                from .conversation import effective_config
                backlog = Backlog(records)
                action = args.backlog_action
                if action == 'state':
                    result = backlog.state(args.project)
                elif action == 'propose':
                    data = cadence_document(args.file, {'project'}, {'references', 'builder_cap'})
                    result = backlog.propose(data['project'], data.get('references'),
                        builder_cap=data.get('builder_cap'), owner_message=args.owner_message)
                elif action == 'apply':
                    result = backlog.apply(args.decision_id)
                elif action == 'revoke':
                    result = backlog.revoke(args.project, owner_message=args.owner_message)
                elif action == 'read':
                    result = GitHubBacklog().read(**cadence_document(args.file, {'project', 'references'}))
                elif action == 'select':
                    snapshot = document(args.snapshot)
                    if type(snapshot) is not dict or type(snapshot.get('repository')) is not str:
                        raise RecordError('backlog snapshot requires its repository identity')
                    result = select(snapshot, effective_config(records, snapshot['repository']),
                                    document(args.classifications, allow_list=True))
                elif action == 'bind':
                    result = backlog.bind(document(args.file), document(args.candidate), args.grant_id)
                elif action == 'prepare':
                    data = cadence_document(args.file, {'task_id', 'candidate'})
                    result = backlog.prepare(**data, fresh_snapshot=reread_backlog(args.snapshot),
                        idle_source=document(args.idle_source) if args.idle_source else None,
                        new_session=args.new_session)
                elif action == 'release':
                    result = backlog.release(args.reservation_id, args.receipt_id, document(args.file))
                elif action == 'pull':
                    result = backlog.pull(document(args.file), document(args.classifications, allow_list=True),
                        idle_source=document(args.idle_source), new_session=args.new_session)
                elif action == 'review':
                    result = backlog.review(**cadence_document(args.file,
                        {'project', 'metrics', 'observed_at', 'source_refs'}))
            elif command == 'prompt':
                if args.action == 'status':
                    if args.prompt_id: raise RecordError('status does not accept a prompt ID')
                    result = Conversation(records).status(args.session)
                else:
                    result = Conversation(records).observe(args.session, args.prompt_id, args.action)
            elif command == 'prepare-forward':
                with Path(args.file).open('rb') as file:
                    raw = file.read(65537)
                if len(raw) > 65536: raise RecordError('forward file exceeds its bound')
                result = Conversation(records).prepare_forward(args.outcome_id, raw.decode('utf-8'))
            elif command == 'config':
                prefs = Preferences(records)
                if args.config_action == 'override':
                    values = load(Path(args.file).read_bytes(), 'overrides')
                    if set(values) != {args.key}: raise ConfigError('override file requires exactly one setting')
                    prefs.override(args.key, values[args.key], owner_message=args.owner_message, project=args.project)
                    result = {'recorded': True}
                else:
                    owner, project = sources(args)
                    if args.config_action == 'founding': result = {'decisions': prefs.founding(owner, project)}
                    else:
                        root = Path(__file__).resolve().parents[1]
                        if _git(root, 'status', '--porcelain'):
                            raise ConfigError('commit toolkit changes before pinning its revision')
                        revision = _git(root, 'rev-parse', 'HEAD').decode().strip()
                        result = prefs.pin(owner, project, owner_message=args.owner_message, monarchy_revision=revision)
                        result = {'pin_id': result['pin_id'], 'project': result['project']}
            elif command == 'register':
                data = Preferences(records).bind(document(args.file))
                result = records.create_task(data['task_id'], data['repository'], data['owner'],
                                             metadata=data['metadata'])
            elif command == 'tick': result = court.tick(args.task)
            elif command == 'status': result = court.status(args.task)
            elif command == 'ingest': result = court.ingest(args.task, args.event_id)
            elif command == 'inbox': result = court.inbox(actor=args.actor)
            elif command == 'ack':
                result = records.process_outcomes(args.presentation_id, args.actor, args.outcome_ids)
            elif command == 'answer':
                result = court.answer(args.decision_id, document(args.file), expected_revision=args.revision,
                                       owner_message=args.owner_message)
            elif command == 'prepare-answer':
                result = court.prepare_answer(args.decision_id,
                    **({'current_head': args.current_head} if args.current_head is not None else {}))
            elif command == 'prepare-dispatch':
                extra = {}
                if args.backlog_snapshot: extra['backlog_snapshot'] = reread_backlog(args.backlog_snapshot)
                if args.idle_source: extra['idle_source'] = document(args.idle_source)
                result = court.prepare_dispatch(args.task, new_session=args.new_session, **extra)
            elif command == 'deliver':
                extra = {}
                if args.current_head is not None: extra['current_head'] = args.current_head
                if args.backlog_snapshot and records.get_operation(args.operation_id)['state'] == 'prepared':
                    extra['backlog_snapshot'] = reread_backlog(args.backlog_snapshot)
                result = court.deliver(args.operation_id, **extra)
            elif command == 'verify': result = court.verify(args.task, **document(args.file))
            output(result, compact=command == 'backlog')
    except (ConfigError, OrdersError, HookError) as exc:
        p.exit(1, str(exc) + '\n')
    except (RecordError, TransportError, OSError, ValueError, KeyError, TypeError, RecursionError):
        # Input may contain private messages; never echo it in diagnostics.
        p.exit(1, 'Royalty command failed. Check the input, current assignment and private journal.\n')


if __name__ == '__main__':
    main()
