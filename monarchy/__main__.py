"""Explicit court commands. Reading help never opens state or starts agents."""
import argparse
import json
from pathlib import Path

from .records import CourtRecords, RecordError
from .conductor import ConductorTransport, TransportError
from .supervision import Court


def document(path):
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise RecordError('input document exceeds 64 KiB')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RecordError('input document must be a JSON object')
    return value


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', required=True, help='private SQLite path outside the source checkout')
    commands = p.add_subparsers(dest='command', required=True)
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
    dispatch = commands.add_parser('prepare-dispatch', help='journal a brief without launching or sending')
    dispatch.add_argument('task'); dispatch.add_argument('--new-session', action='store_true')
    deliver = commands.add_parser('deliver', help='explicitly execute or reconcile a journaled operation')
    deliver.add_argument('operation_id')
    verify = commands.add_parser('verify', help='record independent, source-bound review evidence')
    verify.add_argument('task'); verify.add_argument('file')
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        with CourtRecords(args.state) as records:
            court = Court(records, ConductorTransport())
            command = args.command
            if command == 'register':
                data = document(args.file)
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
            elif command == 'prepare-answer': result = court.prepare_answer(args.decision_id)
            elif command == 'prepare-dispatch':
                result = court.prepare_dispatch(args.task, new_session=args.new_session)
            elif command == 'deliver': result = court.deliver(args.operation_id)
            elif command == 'verify': result = court.verify(args.task, **document(args.file))
            print(json.dumps(result, sort_keys=True, indent=2))
    except (RecordError, TransportError, OSError, ValueError, KeyError, TypeError):
        # Input may contain private messages; never echo it in diagnostics.
        p.exit(1, 'Court command failed. Check the input, current assignment and private journal.\n')


if __name__ == '__main__':
    main()
