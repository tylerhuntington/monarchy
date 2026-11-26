"""Private transactional records. This module performs no external actions."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid


MAX_PAYLOAD_BYTES = 65536
MAX_BATCH_SIZE = 100
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
_OPERATION_TRANSITIONS = {
    "prepared": {"in_flight", "failed"},
    "in_flight": {"unknown", "confirmed", "failed"},
    "unknown": {"confirmed", "failed"},
    "confirmed": set(),
    "failed": set(),
}


class RecordError(ValueError):
    """The requested record operation is invalid or cannot be completed."""


class Conflict(RecordError):
    """An identity or expected state disagrees with a durable record."""


class StaleGeneration(Conflict):
    """The assignment changed since the caller obtained its generation."""


def _identifier(value, name="id"):
    if type(value) is not str or not _ID.fullmatch(value):
        raise RecordError(f"{name} must be 1-128 letters, numbers, dots, colons, underscores, or hyphens")
    return value


def _generation(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise RecordError("generation must be a positive 64-bit integer")
    return value


def _payload(value):
    if type(value) is not dict:
        raise RecordError("payload must be a JSON object")
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if depth > 16 or nodes > 4096:
            raise RecordError("payload is too deeply nested or has too many values")
        if item is None or type(item) is bool:
            return
        if type(item) is str:
            if len(item) > MAX_PAYLOAD_BYTES:
                raise RecordError("payload is too large")
            return
        if type(item) is int and -(2**63) <= item < 2**63:
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                visit(child, depth + 1)
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str or len(key) > 256:
                    raise RecordError("payload keys must be strings of at most 256 characters")
                visit(child, depth + 1)
            return
        raise RecordError("payload contains a value that is not bounded JSON")

    visit(value, 0)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise RecordError("payload exceeds 65536 UTF-8 bytes")
    except (UnicodeError, TypeError, ValueError) as exc:
        if isinstance(exc, RecordError):
            raise
        raise RecordError("payload cannot be encoded as JSON") from exc
    return encoded


def _now():
    return datetime.now(timezone.utc).isoformat()


def _limit(value):
    if type(value) is not int or not 1 <= value <= MAX_BATCH_SIZE:
        raise RecordError("limit must be an integer from 1 through 100")
    return value


def _identifiers(values):
    if type(values) is not list or not 1 <= len(values) <= MAX_BATCH_SIZE:
        raise RecordError("acknowledgment requires 1-100 explicit record IDs")
    checked = [_identifier(value) for value in values]
    if len(set(checked)) != len(checked):
        raise RecordError("acknowledgment IDs must be distinct")
    return checked


def _offset(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise RecordError("offset must be a nonnegative 64-bit integer")
    return value


def _decision_reference(request):
    fields = {"decision_id", "decision_revision"}
    present = fields.intersection(request)
    if not present:
        return None
    if present != fields:
        raise RecordError("operation decision reference requires its ID and revision")
    return (_identifier(request["decision_id"], "decision_id"),
            _generation(request["decision_revision"]))


def owner_answered(decision):
    """Provenance check for an already authenticated trusted-local owner route."""
    return (decision['state'] == 'answered' and decision.get('answered_by') == 'owner'
            and bool(decision.get('owner_message')) and decision.get('answer') is not None)


class CourtRecords:
    """One private royalty database, used only by trusted local callers.

    Actor fields enforce application ownership, not authentication. Each thread
    or process should open its own instance. Constructing an instance only
    creates/opens local records; it starts no worker, hook, or watcher.
    """

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK
            descriptor = os.open(self.path, flags, 0o600)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise RecordError("database must be a private regular file (mode 0600)")
            finally:
                os.close(descriptor)
            self._connection = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute("PRAGMA trusted_schema = OFF")
            with self._transaction():
                version = self._connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2, 3, 4, 5, 6, 7):
                    raise RecordError("unsupported royalty database version")
                if self._connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type IN ('trigger', 'view') LIMIT 1"
                ).fetchone():
                    raise RecordError("royalty database must not contain triggers or views")
                if version in (3, 4, 5, 6, 7) and not self._connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='prompt_observations'"
                ).fetchone():
                    raise RecordError('royalty database is missing prompt history')
                if version in (5, 6, 7) and not self._connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='delegation_events'"
                ).fetchone():
                    raise RecordError('royalty database is missing delegation history')
                self._connection.execute("""CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, repository TEXT NOT NULL,
                    owner TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation > 0),
                    metadata TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    generation INTEGER NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    processed_by TEXT, processed_at TEXT
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id), generation INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('active', 'processed', 'released')),
                    created_at TEXT NOT NULL
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS claim_events (
                    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
                    event_id TEXT NOT NULL REFERENCES events(event_id),
                    PRIMARY KEY(claim_id, event_id)
                )""")
                self._connection.execute("CREATE INDEX IF NOT EXISTS pending_events ON events(task_id, processed_at, sequence)")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS outcomes (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, outcome_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id), recipient TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    processed_by TEXT, processed_at TEXT
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS presentations (
                    presentation_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('active', 'processed')), created_at TEXT NOT NULL
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS presented_outcomes (
                    presentation_id TEXT NOT NULL REFERENCES presentations(presentation_id),
                    outcome_id TEXT NOT NULL REFERENCES outcomes(outcome_id),
                    PRIMARY KEY(presentation_id, outcome_id)
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id), payload TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending', 'answered', 'superseded')),
                    answer TEXT, owner_message TEXT, created_at TEXT NOT NULL, answered_at TEXT,
                    answered_by TEXT,
                    PRIMARY KEY(decision_id, revision)
                )""")
                decision_columns = {row['name'] for row in self._connection.execute('PRAGMA table_info(decisions)')}
                if 'answered_by' not in decision_columns:
                    if version in (5, 6, 7):
                        raise RecordError('royalty database is missing answer provenance')
                    self._connection.execute('ALTER TABLE decisions ADD COLUMN answered_by TEXT')
                    for legacy in self._connection.execute(
                        "SELECT decision_id,revision,owner_message FROM decisions WHERE state IN ('answered','superseded') "
                        'AND answer IS NOT NULL AND owner_message IS NOT NULL').fetchall():
                        if type(legacy['owner_message']) is str and _ID.fullmatch(legacy['owner_message']):
                            self._connection.execute("UPDATE decisions SET answered_by='owner' "
                                'WHERE decision_id=? AND revision=?', (legacy['decision_id'], legacy['revision']))
                self._connection.execute("""CREATE TABLE IF NOT EXISTS delegation_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                    project TEXT NOT NULL, category TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('ask','delegated','ask-again-later')),
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                )""")
                self._connection.execute('CREATE INDEX IF NOT EXISTS delegation_scope '
                                         'ON delegation_events(project,category,sequence)')
                self._connection.execute("""CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    kind TEXT NOT NULL, request TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('prepared', 'in_flight', 'unknown', 'confirmed', 'failed')),
                    result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS pins (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, pin_id TEXT NOT NULL UNIQUE,
                    project TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS overrides (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL,
                    setting TEXT NOT NULL, value TEXT NOT NULL,
                    owner_message TEXT NOT NULL, created_at TEXT NOT NULL
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS prompt_observations (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    prompt_id TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('open','closed','unknown')),
                    observed_at TEXT NOT NULL,
                    reason TEXT CHECK(reason IS NULL OR
                        (reason='native-cancelled' AND state='unknown') OR
                        (reason='answer-required' AND state='open'))
                )""")
                columns = {row['name'] for row in self._connection.execute(
                    'PRAGMA table_info(prompt_observations)')}
                if 'reason' not in columns:
                    if version in (4, 5, 6, 7):
                        raise RecordError('royalty database is missing prompt cancellation metadata')
                    # Old unknown rows stay ambiguous. No historical callback is
                    # inferred to be a native cancellation during migration.
                    self._connection.execute("""ALTER TABLE prompt_observations ADD COLUMN
                        reason TEXT CHECK(reason IS NULL OR
                            (reason='native-cancelled' AND state='unknown') OR
                            (reason='answer-required' AND state='open'))""")
                self._connection.execute("CREATE INDEX IF NOT EXISTS prompt_sessions ON prompt_observations(session_id,sequence)")
                if version in (6, 7) and not self._connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='cadence_observations'"
                ).fetchone():
                    raise RecordError('royalty database is missing cadence history')
                self._connection.execute("""CREATE TABLE IF NOT EXISTS cadence_observations (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, observation_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id), generation INTEGER NOT NULL,
                    observed_at TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                )""")
                self._connection.execute('CREATE INDEX IF NOT EXISTS cadence_task_observations '
                                         'ON cadence_observations(task_id,generation,sequence)')
                if version in (6, 7) and not self._connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='checks'"
                ).fetchone():
                    raise RecordError('royalty database is missing cadence checks')
                self._connection.execute("""CREATE TABLE IF NOT EXISTS checks (
                    check_id TEXT PRIMARY KEY, project TEXT NOT NULL,
                    task_id TEXT REFERENCES tasks(task_id), generation INTEGER,
                    kind TEXT NOT NULL, recipient TEXT NOT NULL CHECK(recipient IN ('queen','secretary')),
                    due_at TEXT NOT NULL, payload TEXT NOT NULL, config_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','completed')),
                    receipt_id TEXT UNIQUE, receipt TEXT, completed_at TEXT, admission TEXT,
                    CHECK((state='pending' AND receipt_id IS NULL AND receipt IS NULL AND completed_at IS NULL)
                       OR (state='completed' AND receipt_id IS NOT NULL AND receipt IS NOT NULL AND completed_at IS NOT NULL))
                )""")
                self._connection.execute('CREATE INDEX IF NOT EXISTS cadence_pending '
                                         'ON checks(project,state,due_at)')
                for table in ('cadence_notices', 'cadence_notice_checks'):
                    if version in (6, 7) and not self._connection.execute(
                        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)
                    ).fetchone():
                        raise RecordError('royalty database is missing cadence notice history')
                self._connection.execute("""CREATE TABLE IF NOT EXISTS cadence_notices (
                    notification_id TEXT PRIMARY KEY, secretary_session TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state='prepared'), created_at TEXT NOT NULL
                )""")
                self._connection.execute("""CREATE TABLE IF NOT EXISTS cadence_notice_checks (
                    notification_id TEXT NOT NULL REFERENCES cadence_notices(notification_id),
                    secretary_session TEXT NOT NULL, check_id TEXT NOT NULL REFERENCES checks(check_id),
                    PRIMARY KEY(secretary_session,check_id)
                )""")
                if version in (6, 7) and not self._connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='cadence_census'"
                ).fetchone():
                    raise RecordError('royalty database is missing cadence census history')
                self._connection.execute("""CREATE TABLE IF NOT EXISTS cadence_census (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, census_id TEXT NOT NULL UNIQUE,
                    project TEXT NOT NULL, observed_at TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                )""")
                cadence_columns = {
                    'checks': {'check_id','project','task_id','generation','kind','recipient','due_at',
                               'payload','config_digest','state','receipt_id','receipt','completed_at','admission'},
                    'cadence_observations': {'sequence','observation_id','task_id','generation','observed_at','payload','created_at'},
                    'cadence_census': {'sequence','census_id','project','observed_at','payload','created_at'},
                    'cadence_notices': {'notification_id','secretary_session','state','created_at'},
                    'cadence_notice_checks': {'notification_id','secretary_session','check_id'},
                }
                for table, required in cadence_columns.items():
                    columns = {row['name'] for row in self._connection.execute('PRAGMA table_info(' + table + ')')}
                    if columns != required:
                        raise RecordError('royalty database has malformed cadence history')
                if version == 7 and not self._connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='backlog_events'"
                ).fetchone():
                    raise RecordError('royalty database is missing backlog history')
                self._connection.execute("""CREATE TABLE IF NOT EXISTS backlog_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                    project TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','revoked')),
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                )""")
                self._connection.execute('CREATE INDEX IF NOT EXISTS backlog_project '
                                         'ON backlog_events(project,sequence)')
                if version == 7 and not self._connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='dispatch_reservations'"
                ).fetchone():
                    raise RecordError('royalty database is missing writer custody')
                self._connection.execute("""CREATE TABLE IF NOT EXISTS dispatch_reservations (
                    reservation_id TEXT PRIMARY KEY, project TEXT NOT NULL,
                    writer_repository TEXT NOT NULL, branch_ref TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id), generation INTEGER NOT NULL,
                    session_id TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
                    payload TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('held','released')), admitted_at TEXT,
                    created_at TEXT NOT NULL, release_receipt_id TEXT UNIQUE,
                    release_receipt TEXT, released_at TEXT, legacy INTEGER NOT NULL DEFAULT 0 CHECK(legacy IN (0,1)),
                    last_admitted_at TEXT
                )""")
                expected_backlog={
                    'backlog_events':{'sequence','event_id','project','state','payload','created_at'},
                    'dispatch_reservations':{'reservation_id','project','writer_repository','branch_ref','task_id',
                        'generation','session_id','operation_id','payload','state','admitted_at','created_at',
                        'release_receipt_id','release_receipt','released_at','legacy','last_admitted_at'}}
                for table,columns in expected_backlog.items():
                    if {row['name'] for row in self._connection.execute('PRAGMA table_info('+table+')')}!=columns:
                        raise RecordError('royalty database has malformed backlog custody history')
                self._connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS writer_branch_custody "
                    "ON dispatch_reservations(writer_repository,branch_ref) WHERE state='held' AND legacy=0")
                self._connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS writer_session_custody "
                    "ON dispatch_reservations(session_id) WHERE state='held' AND legacy=0")
                if version<7:
                    for raw in self._connection.execute("SELECT * FROM operations WHERE kind IN ('send_message','create_session') "
                            "AND state IN ('in_flight','unknown','confirmed')").fetchall():
                        operation=self._decode(raw)
                        task=self.get_task(operation['task_id'])
                        if (operation['request'].get('route')=='queen-forward'
                                or operation['request'].get('execution_mode')=='read-only'):
                            continue
                        binding=operation['request'].get('binding',{})
                        generation=operation['request'].get('generation',task['generation'])
                        _generation(generation)
                        session=binding.get('session_id',task['owner']) if type(binding) is dict else task['owner']
                        _identifier(session,'legacy_session')
                        reservation_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'monarchy:legacy-writer:'+operation['operation_id']))
                        payload={'legacy':True,'operation_id':operation['operation_id'],'binding':binding}
                        self._connection.execute('INSERT INTO dispatch_reservations '
                            '(reservation_id,project,writer_repository,branch_ref,task_id,generation,session_id,'
                            'operation_id,payload,state,admitted_at,created_at,last_admitted_at,legacy) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)',
                            (reservation_id,task['repository'].lower(),task['repository'].lower(),'legacy-unmapped',
                             task['task_id'],generation,session,operation['operation_id'],_payload(payload),'held',
                             operation['created_at'],operation['created_at'],operation['updated_at']))
                self._connection.execute("PRAGMA user_version = 7")
        except (OSError, sqlite3.Error) as exc:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise RecordError("could not open the private royalty database") from exc
        except RecordError:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise

    def put_pin(self, pin_id, project, payload, *, approve):
        """Atomically recheck answered decisions and retain immutable source bytes."""
        _identifier(pin_id, 'pin_id')
        encoded = _payload(payload)
        with self._transaction():
            approve()
            old = self._connection.execute('SELECT * FROM pins WHERE pin_id=?', (pin_id,)).fetchone()
            if old:
                if old['project'] != project or old['payload'] != encoded:
                    raise Conflict('pin identity already has different content')
                return self._pin(old)
            self._connection.execute('INSERT INTO pins(pin_id,project,payload,created_at) VALUES(?,?,?,?)',
                                     (pin_id, project, encoded, _now()))
            return self.get_pin(pin_id)

    @staticmethod
    def _pin(row):
        if row is None:
            raise RecordError('no approved configuration pin')
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        return result

    def get_pin(self, pin_id):
        return self._pin(self._connection.execute('SELECT * FROM pins WHERE pin_id=?', (pin_id,)).fetchone())

    def latest_pin(self, project=None):
        query = 'SELECT * FROM pins'
        args = ()
        if project is not None:
            query += ' WHERE project=?'
            args = (project,)
        return self._pin(self._connection.execute(query + ' ORDER BY sequence DESC LIMIT 1', args).fetchone())

    def has_pins(self):
        return self._connection.execute('SELECT 1 FROM pins LIMIT 1').fetchone() is not None

    def put_override(self, setting, value, project, owner_message, *, validate):
        _identifier(owner_message, 'owner_message')
        encoded = _payload({'value': value})
        with self._transaction():
            self._connection.execute(
                'INSERT INTO overrides(project,setting,value,owner_message,created_at) VALUES(?,?,?,?,?)',
                (project, setting, encoded, owner_message, _now()))
            validate()  # Roll back the new history row if its folded state is unusable.

    def config_overrides(self, project=''):
        from .controls import fold_overrides
        return fold_overrides(self, project)['config']

    def model_overrides(self):
        """Approved model receipts remain distinct from config-file input."""
        from .controls import fold_overrides
        return fold_overrides(self)['models']

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._connection.close()

    @contextmanager
    def _transaction(self):
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
            self._connection.execute("COMMIT")
        except Exception as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            if isinstance(exc, sqlite3.Error):
                raise RecordError("royalty record transaction failed") from exc
            raise

    def _get(self, table, key, identifier):
        # Table and key are private constants supplied by this module.
        row = self._connection.execute(
            f"SELECT * FROM {table} WHERE {key} = ?", (identifier,),
        ).fetchone()
        if row is None:
            raise RecordError(f"{table} record does not exist")
        return self._decode(row)

    @staticmethod
    def _decode(row):
        result = dict(row)
        for field in ("task_id", "event_id", "claim_id", "outcome_id", "presentation_id", "decision_id",
                      "operation_id", "actor", "owner", "recipient", "processed_by", "owner_message", "kind"):
            if field in result and result[field] is not None:
                _identifier(result[field], field)
        for field in ("generation", "revision", "sequence"):
            if field in result:
                _generation(result[field])
        if "repository" in result and (type(result["repository"]) is not str or not _REPOSITORY.fullmatch(result["repository"])):
            raise RecordError("stored record contains invalid repository")
        for field in ("payload", "request", "result", "answer", "metadata"):
            if field in result and result[field] is not None:
                try:
                    if type(result[field]) is not str or len(result[field].encode("utf-8")) > MAX_PAYLOAD_BYTES:
                        raise RecordError("stored record exceeds JSON size limit")
                    decoded = json.loads(result[field])
                    _payload(decoded)
                except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
                    raise RecordError("stored record contains invalid JSON") from exc
                result[field] = decoded
        if 'answered_by' in result:
            authority = result['answered_by']
            if result['answer'] is None:
                valid = authority is None and result['owner_message'] is None
            elif authority == 'owner':
                valid = bool(result['owner_message'])
            else:
                valid = (type(authority) is str and authority.startswith('grant:')
                         and bool(_ID.fullmatch(authority[6:])) and result['owner_message'] is None)
            if not valid:
                raise RecordError('stored decision has invalid answer provenance')
        return result

    def _list(self, table, *, conditions=(), values=(), order, limit, offset):
        _limit(limit)
        _offset(offset)
        where = " AND ".join(conditions) if conditions else "1"
        rows = self._connection.execute(
            f"SELECT * FROM {table} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*values, limit, offset),
        ).fetchall()
        return [self._decode(row) for row in rows]

    def list_tasks(self, *, limit=MAX_BATCH_SIZE, offset=0):
        return self._list("tasks", order="task_id", limit=limit, offset=offset)

    def list_events(self, *, task_id=None, processed=None, limit=MAX_BATCH_SIZE, offset=0):
        conditions, values = [], []
        if task_id is not None:
            conditions.append("task_id = ?")
            values.append(_identifier(task_id, "task_id"))
        if processed is not None:
            if type(processed) is not bool:
                raise RecordError("processed must be true, false, or None")
            conditions.append("processed_at IS NOT NULL" if processed else "processed_at IS NULL")
        return self._list("events", conditions=conditions, values=values, order="sequence", limit=limit, offset=offset)

    def list_outcomes(self, *, recipient=None, task_id=None, processed=None, limit=MAX_BATCH_SIZE, offset=0):
        conditions, values = [], []
        for field, value in (("recipient", recipient), ("task_id", task_id)):
            if value is not None:
                conditions.append(f"{field} = ?")
                values.append(_identifier(value, field))
        if processed is not None:
            if type(processed) is not bool:
                raise RecordError("processed must be true, false, or None")
            conditions.append("processed_at IS NOT NULL" if processed else "processed_at IS NULL")
        return self._list("outcomes", conditions=conditions, values=values, order="sequence", limit=limit, offset=offset)

    def list_decisions(self, *, task_id=None, state=None, limit=MAX_BATCH_SIZE, offset=0):
        conditions = ["revision = (SELECT MAX(d.revision) FROM decisions d WHERE d.decision_id = decisions.decision_id)"]
        values = []
        if task_id is not None:
            conditions.append("task_id = ?")
            values.append(_identifier(task_id, "task_id"))
        if state is not None:
            if type(state) is not str or state not in {"pending", "answered"}:
                raise RecordError("decision state must be pending or answered")
            conditions.append("state = ?")
            values.append(state)
        return self._list("decisions", conditions=conditions, values=values, order="decision_id", limit=limit, offset=offset)

    def list_operations(self, *, task_id=None, states=None, limit=MAX_BATCH_SIZE, offset=0):
        conditions, values = [], []
        if task_id is not None:
            conditions.append("task_id = ?")
            values.append(_identifier(task_id, "task_id"))
        if states is not None:
            if (type(states) not in (list, tuple) or not 1 <= len(states) <= len(_OPERATION_TRANSITIONS)
                    or any(type(state) is not str or state not in _OPERATION_TRANSITIONS for state in states)
                    or len(set(states)) != len(states)):
                raise RecordError("states must be a nonempty list of distinct operation states")
            conditions.append("state IN (" + ",".join("?" for _ in states) + ")")
            values.extend(states)
        return self._list("operations", conditions=conditions, values=values, order="operation_id", limit=limit, offset=offset)

    def create_task(self, task_id, repository, owner, *, metadata=None):
        with self._transaction():
            return self._create_task(task_id,repository,owner,metadata=metadata)

    def _create_task(self, task_id, repository, owner, *, metadata=None):
        _identifier(task_id, "task_id")
        _identifier(owner, "owner")
        if type(repository) is not str or not _REPOSITORY.fullmatch(repository):
            raise RecordError("repository must be owner/repository")
        encoded = _payload(metadata if metadata is not None else {})
        existing = self._connection.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if existing:
            task = self.get_task(task_id)
            if (task["repository"] != repository or task["owner"] != owner
                    or task["generation"] != 1 or _payload(task["metadata"]) != encoded):
                raise Conflict("task identity already has another assignment")
            return task
        now = _now()
        self._connection.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, 1, ?, ?, ?)", (task_id, repository, owner, encoded, now, now),
        )
        return self.get_task(task_id)

    def get_task(self, task_id):
        return self._get("tasks", "task_id", _identifier(task_id, "task_id"))

    def assign_task(self, task_id, owner, *, expected_generation, metadata=None):
        _identifier(task_id, "task_id")
        _identifier(owner, "owner")
        _generation(expected_generation)
        encoded = _payload(metadata) if metadata is not None else None
        with self._transaction():
            task = self.get_task(task_id)
            if task["generation"] != expected_generation:
                raise StaleGeneration("assignment changed before reassignment")
            if self._connection.execute("SELECT 1 FROM dispatch_reservations WHERE task_id=? AND state='held' LIMIT 1",
                                        (task_id,)).fetchone():
                raise Conflict('release retained writer custody before reassignment')
            if self._connection.execute(
                "SELECT 1 FROM operations WHERE task_id = ? AND state IN ('in_flight', 'unknown') LIMIT 1",
                (task_id,),
            ).fetchone():
                raise Conflict("reconcile unresolved operations before reassignment")
            if expected_generation == 2**63 - 1:
                raise RecordError("assignment generation is exhausted")
            self._connection.execute(
                "UPDATE tasks SET owner = ?, generation = generation + 1, metadata = ?, updated_at = ? WHERE task_id = ?",
                (owner, encoded if encoded is not None else _payload(task["metadata"]), _now(), task_id),
            )
            self._connection.execute(
                "UPDATE claims SET state = 'released' WHERE task_id = ? AND state = 'active'", (task_id,),
            )
            return self.get_task(task_id)

    def record_event(self, event_id, task_id, generation, actor, kind, payload):
        for name, value in (("event_id", event_id), ("task_id", task_id), ("actor", actor), ("kind", kind)):
            _identifier(value, name)
        _generation(generation)
        encoded = _payload(payload)
        with self._transaction():
            existing = self._connection.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
            if existing:
                expected = (task_id, generation, actor, kind, encoded)
                actual = tuple(existing[key] for key in ("task_id", "generation", "actor", "kind", "payload"))
                if actual != expected:
                    raise Conflict("event identity was reused with different content")
                return self.get_event(event_id)
            task = self.get_task(task_id)
            if task["generation"] != generation:
                raise StaleGeneration("event belongs to a stale task generation")
            if task["owner"] != actor:
                raise Conflict("event actor is not the assigned task owner")
            self._connection.execute(
                "INSERT INTO events (event_id, task_id, generation, actor, kind, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_id, task_id, generation, actor, kind, encoded, _now()),
            )
            return self.get_event(event_id)

    def get_event(self, event_id):
        return self._get("events", "event_id", _identifier(event_id, "event_id"))

    def _claim(self, claim_id):
        claim = self._get("claims", "claim_id", claim_id)
        rows = self._connection.execute(
            "SELECT e.event_id FROM claim_events m JOIN events e ON e.event_id = m.event_id WHERE m.claim_id = ? ORDER BY e.sequence",
            (claim_id,),
        ).fetchall()
        claim["event_ids"] = [row[0] for row in rows]
        claim["events"] = [self.get_event(event_id) for event_id in claim["event_ids"]]
        return claim

    def claim_events(self, actor, task_id, limit=MAX_BATCH_SIZE):
        _identifier(actor, "actor")
        _identifier(task_id, "task_id")
        _limit(limit)
        with self._transaction():
            task = self.get_task(task_id)
            existing = self._connection.execute(
                "SELECT claim_id FROM claims WHERE actor = ? AND task_id = ? AND state = 'active'",
                (actor, task_id),
            ).fetchone()
            if existing:
                return self._claim(existing[0])
            rows = self._connection.execute("""SELECT event_id FROM events e
                WHERE task_id = ? AND processed_at IS NULL AND NOT EXISTS (
                    SELECT 1 FROM claim_events m JOIN claims c ON c.claim_id = m.claim_id
                    WHERE m.event_id = e.event_id AND c.state = 'active'
                ) ORDER BY sequence LIMIT ?""", (task_id, limit)).fetchall()
            if not rows:
                return None
            claim_id = str(uuid.uuid4())
            self._connection.execute(
                "INSERT INTO claims VALUES (?, ?, ?, ?, 'active', ?)",
                (claim_id, actor, task_id, task["generation"], _now()),
            )
            self._connection.executemany(
                "INSERT INTO claim_events VALUES (?, ?)", ((claim_id, row[0]) for row in rows),
            )
            return self._claim(claim_id)

    def ack_events(self, claim_id, actor, event_ids):
        _identifier(claim_id, "claim_id")
        _identifier(actor, "actor")
        event_ids = _identifiers(event_ids)
        with self._transaction():
            claim = self._claim(claim_id)
            if claim["actor"] != actor:
                raise Conflict("claim belongs to another actor")
            if claim["generation"] != self.get_task(claim["task_id"])["generation"]:
                raise StaleGeneration("claim belongs to a stale assignment generation")
            if claim["state"] == "released":
                raise Conflict("claim was released")
            if not set(event_ids).issubset(claim["event_ids"]):
                raise Conflict("acknowledgment includes events outside the claim")
            self._connection.executemany(
                "UPDATE events SET processed_by = ?, processed_at = ? WHERE event_id = ? AND processed_at IS NULL",
                ((actor, _now(), event_id) for event_id in event_ids),
            )
            remaining = self._connection.execute("""SELECT 1 FROM claim_events m
                JOIN events e ON e.event_id = m.event_id
                WHERE m.claim_id = ? AND e.processed_at IS NULL LIMIT 1""", (claim_id,)).fetchone()
            if not remaining:
                self._connection.execute("UPDATE claims SET state = 'processed' WHERE claim_id = ?", (claim_id,))
            return self._claim(claim_id)

    def record_outcome(self, outcome_id, task_id, payload, *, recipient="queen"):
        _identifier(outcome_id, "outcome_id")
        _identifier(task_id, "task_id")
        _identifier(recipient, "recipient")
        encoded = _payload(payload)
        with self._transaction():
            existing = self._connection.execute("SELECT * FROM outcomes WHERE outcome_id = ?", (outcome_id,)).fetchone()
            if existing:
                if (existing["task_id"], existing["recipient"], existing["payload"]) != (task_id, recipient, encoded):
                    raise Conflict("outcome identity was reused with different content")
                return self.get_outcome(outcome_id)
            self.get_task(task_id)
            self._connection.execute(
                "INSERT INTO outcomes (outcome_id, task_id, recipient, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (outcome_id, task_id, recipient, encoded, _now()),
            )
            return self.get_outcome(outcome_id)

    def get_outcome(self, outcome_id):
        return self._get("outcomes", "outcome_id", _identifier(outcome_id, "outcome_id"))

    def _presentation(self, presentation_id):
        presentation = self._get("presentations", "presentation_id", presentation_id)
        rows = self._connection.execute(
            "SELECT o.outcome_id FROM presented_outcomes m JOIN outcomes o ON o.outcome_id = m.outcome_id WHERE m.presentation_id = ? ORDER BY o.sequence",
            (presentation_id,),
        ).fetchall()
        presentation["outcome_ids"] = [row[0] for row in rows]
        presentation["outcomes"] = [self.get_outcome(outcome_id) for outcome_id in presentation["outcome_ids"]]
        return presentation

    def present_outcomes(self, actor, limit=MAX_BATCH_SIZE):
        _identifier(actor, "actor")
        _limit(limit)
        with self._transaction():
            existing = self._connection.execute(
                "SELECT presentation_id FROM presentations WHERE actor = ? AND state = 'active'", (actor,),
            ).fetchone()
            if existing:
                return self._presentation(existing[0])
            rows = self._connection.execute(
                "SELECT outcome_id FROM outcomes WHERE recipient = ? AND processed_at IS NULL ORDER BY sequence LIMIT ?",
                (actor, limit),
            ).fetchall()
            if not rows:
                return None
            presentation_id = str(uuid.uuid4())
            self._connection.execute(
                "INSERT INTO presentations VALUES (?, ?, 'active', ?)", (presentation_id, actor, _now()),
            )
            self._connection.executemany(
                "INSERT INTO presented_outcomes VALUES (?, ?)", ((presentation_id, row[0]) for row in rows),
            )
            return self._presentation(presentation_id)

    def open_decision(self, decision_id, task_id, payload):
        """Replay immutable creation against revision one; return current state."""
        _identifier(decision_id, "decision_id")
        _identifier(task_id, "task_id")
        encoded = _payload(payload)
        with self._transaction():
            existing = self._connection.execute(
                "SELECT * FROM decisions WHERE decision_id = ? ORDER BY revision ASC LIMIT 1", (decision_id,),
            ).fetchone()
            if existing:
                if (existing["task_id"], existing["payload"]) != (task_id, encoded):
                    raise Conflict("decision identity was reused with different creation content")
                return self.get_decision(decision_id)
            self.get_task(task_id)
            self._connection.execute(
                "INSERT INTO decisions(decision_id,revision,task_id,payload,state,created_at) VALUES (?, 1, ?, ?, 'pending', ?)",
                (decision_id, task_id, encoded, _now()),
            )
            return self.get_decision(decision_id)

    def get_decision(self, decision_id, revision=None):
        _identifier(decision_id, "decision_id")
        if revision is not None:
            _generation(revision)
        row = self._connection.execute(
            "SELECT * FROM decisions WHERE decision_id = ? AND (? IS NULL OR revision = ?) ORDER BY revision DESC LIMIT 1",
            (decision_id, revision, revision),
        ).fetchone()
        if row is None:
            raise RecordError("decision record does not exist")
        return self._decode(row)

    def answer_decision(self, decision_id, answer, *, expected_revision, owner_message):
        """Record an actual owner answer supplied by a trusted local adapter."""
        with self._transaction():
            return self._answer_decision(decision_id, answer, expected_revision=expected_revision,
                                         owner_message=owner_message, answered_by='owner')

    def _answer_decision(self, decision_id, answer, *, expected_revision, owner_message, answered_by):
        if not self._connection.in_transaction:
            raise RecordError('answer requires a record transaction')
        _identifier(decision_id, "decision_id")
        if answered_by == 'owner':
            _identifier(owner_message, 'owner_message')
        elif (type(answered_by) is not str or not answered_by.startswith('grant:')
              or not _ID.fullmatch(answered_by[6:]) or owner_message is not None):
            raise RecordError('answer provenance is invalid')
        _generation(expected_revision)
        encoded = _payload(answer)
        decision = self.get_decision(decision_id)
        if decision['revision'] != expected_revision:
            raise Conflict('decision changed before the answer was recorded')
        if decision['state'] == 'answered':
            if (_payload(decision['answer']) != encoded or decision['owner_message'] != owner_message
                    or decision['answered_by'] != answered_by):
                raise Conflict('decision already has a different answer or authority')
            return decision
        if decision['state'] != 'pending':
            raise Conflict('decision is not pending')
        self._connection.execute(
            "UPDATE decisions SET state='answered',answer=?,owner_message=?,answered_at=?,answered_by=? "
            'WHERE decision_id=? AND revision=?',
            (encoded, owner_message, _now(), answered_by, decision_id, expected_revision))
        return self.get_decision(decision_id)

    def revise_decision(self, decision_id, payload, *, expected_revision):
        _identifier(decision_id, "decision_id")
        _generation(expected_revision)
        encoded = _payload(payload)
        with self._transaction():
            decision = self.get_decision(decision_id)
            if decision["revision"] != expected_revision:
                raise Conflict("decision changed before the revision")
            unresolved = self._connection.execute(
                "SELECT * FROM operations WHERE task_id = ? AND state IN ('in_flight', 'unknown')",
                (decision["task_id"],),
            )
            for row in unresolved:
                reference = _decision_reference(self._decode(row)["request"])
                if reference is not None and reference[0] == decision_id:
                    raise Conflict("reconcile the decision's unresolved delivery before revising it")
            if expected_revision == 2**63 - 1:
                raise RecordError("decision revision is exhausted")
            self._connection.execute(
                "UPDATE decisions SET state = 'superseded' WHERE decision_id = ? AND revision = ?",
                (decision_id, expected_revision),
            )
            self._connection.execute(
                "INSERT INTO decisions(decision_id,revision,task_id,payload,state,created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (decision_id, expected_revision + 1, decision["task_id"], encoded, _now()),
            )
            return self.get_decision(decision_id)

    def prepare_operation(self, operation_id, task_id, kind, request, *, current_head=None,
                          backlog_snapshot=None, idle_source=None):
        with self._transaction():
            return self._prepare_operation(operation_id,task_id,kind,request,current_head=current_head,
                                           backlog_snapshot=backlog_snapshot,idle_source=idle_source)

    def _prepare_operation(self, operation_id, task_id, kind, request, *, current_head=None,
                           backlog_snapshot=None, idle_source=None):
        _identifier(operation_id, "operation_id")
        _identifier(task_id, "task_id")
        _identifier(kind, "kind")
        encoded = _payload(request)
        decision_reference = _decision_reference(request)
        existing = self._connection.execute("SELECT * FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
        if existing:
            if (existing["task_id"], existing["kind"], existing["request"]) != (task_id, kind, encoded):
                raise Conflict("operation identity was reused with different content")
            return self._decode(existing)
        self.get_task(task_id)
        if decision_reference is not None:
            decision = self.get_decision(decision_reference[0])
            if decision["task_id"] != task_id:
                raise Conflict("operation decision belongs to another task")
            if (decision.get('answered_by') or '').startswith('grant:'):
                from .delegation import answer_admission_check
                answer_admission_check(self, {'task_id': task_id, 'kind': kind, 'request': request},
                                       current_head=current_head)
        now = _now()
        self._connection.execute(
            "INSERT INTO operations VALUES (?, ?, ?, ?, 'prepared', NULL, ?, ?)",
            (operation_id, task_id, kind, encoded, now, now),
        )
        if request.get('route')=='worker-dispatch':
            from .backlog import reserve_dispatch
            reserve_dispatch(self,self.get_operation(operation_id),backlog_snapshot=backlog_snapshot,
                             idle_source=idle_source)
        return self.get_operation(operation_id)

    def get_operation(self, operation_id):
        return self._get("operations", "operation_id", _identifier(operation_id, "operation_id"))

    def set_operation_state(self, operation_id, state, *, expected_state, result=None, current_head=None,
                            backlog_snapshot=None):
        _identifier(operation_id, "operation_id")
        if type(state) is not str or state not in _OPERATION_TRANSITIONS:
            raise RecordError("unrecognized operation state")
        if type(expected_state) is not str or expected_state not in _OPERATION_TRANSITIONS:
            raise RecordError("unrecognized expected operation state")
        encoded = _payload(result) if result is not None else None
        with self._transaction():
            operation = self.get_operation(operation_id)
            actual_result = _payload(operation["result"]) if operation["result"] is not None else None
            if state != "in_flight" and operation["state"] == state and actual_result == encoded:
                return operation
            if operation["state"] != expected_state:
                raise Conflict("operation changed before the state update")
            if state not in _OPERATION_TRANSITIONS[expected_state]:
                raise Conflict("operation transition is not allowed; unknown effects require reconciliation")
            if state == "in_flight" and "generation" in operation["request"]:
                generation = _generation(operation["request"]["generation"])
                if generation != self.get_task(operation["task_id"])["generation"]:
                    raise StaleGeneration("operation belongs to a stale assignment generation")
            if state == "in_flight":
                from .preferences import admission_check
                admission_check(self, self.get_task(operation["task_id"]))
                from .conversation import forward_admission_check
                forward_admission_check(self, operation)
                from .cadence import cadence_admission_check
                cadence_admission_check(self, operation, now=_now())
                from .backlog import worker_admission_check
                worker_admission_check(self, operation, now=_now(),backlog_snapshot=backlog_snapshot)
                reference = _decision_reference(operation["request"])
                if reference is not None:
                    decision = self.get_decision(reference[0])
                    if (decision["task_id"] != operation["task_id"]
                            or decision["revision"] != reference[1] or decision["state"] != "answered"):
                        raise Conflict("operation requires the current answered decision revision")
                    from .delegation import answer_admission_check
                    answer_admission_check(self, operation, current_head=current_head)
            self._connection.execute(
                "UPDATE operations SET state = ?, result = ?, updated_at = ? WHERE operation_id = ?",
                (state, encoded, _now(), operation_id),
            )
            return self.get_operation(operation_id)

    def process_outcomes(self, presentation_id, actor, outcome_ids):
        _identifier(presentation_id, "presentation_id")
        _identifier(actor, "actor")
        outcome_ids = _identifiers(outcome_ids)
        with self._transaction():
            presentation = self._presentation(presentation_id)
            if presentation["actor"] != actor:
                raise Conflict("presentation belongs to another actor")
            if not set(outcome_ids).issubset(presentation["outcome_ids"]):
                raise Conflict("processing includes outcomes outside the presentation")
            self._connection.executemany(
                "UPDATE outcomes SET processed_by = ?, processed_at = ? WHERE outcome_id = ? AND processed_at IS NULL",
                ((actor, _now(), outcome_id) for outcome_id in outcome_ids),
            )
            remaining = self._connection.execute("""SELECT 1 FROM presented_outcomes m
                JOIN outcomes o ON o.outcome_id = m.outcome_id
                WHERE m.presentation_id = ? AND o.processed_at IS NULL LIMIT 1""", (presentation_id,)).fetchone()
            if not remaining:
                self._connection.execute(
                    "UPDATE presentations SET state = 'processed' WHERE presentation_id = ?", (presentation_id,),
                )
            return self._presentation(presentation_id)
