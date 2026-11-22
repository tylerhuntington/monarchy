"""Explicit commands for the royalty. Reading help never opens state or starts agents."""
import argparse
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


def document(path):
    with Path(path).open('rb') as file:
        raw = file.read(65537)
    if len(raw) > 65536:
        raise RecordError('input document exceeds 64 KiB')
    value = _json(raw)
    _payload(value)
    return value


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
    deliver = commands.add_parser('deliver', help='explicitly execute or reconcile a journaled operation')
    deliver.add_argument('operation_id')
    deliver.add_argument('--current-head', help='fresh observed full head before a new internal PR answer send')
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


def output(value):
    print(json.dumps(value, sort_keys=True, indent=2))


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
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
            if command == 'delegation':
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
                result = court.prepare_dispatch(args.task, new_session=args.new_session)
            elif command == 'deliver':
                result = court.deliver(args.operation_id,
                    **({'current_head': args.current_head} if args.current_head is not None else {}))
            elif command == 'verify': result = court.verify(args.task, **document(args.file))
            output(result)
    except (ConfigError, OrdersError, HookError) as exc:
        p.exit(1, str(exc) + '\n')
    except (RecordError, TransportError, OSError, ValueError, KeyError, TypeError, RecursionError):
        # Input may contain private messages; never echo it in diagnostics.
        p.exit(1, 'Royalty command failed. Check the input, current assignment and private journal.\n')


if __name__ == '__main__':
    main()
