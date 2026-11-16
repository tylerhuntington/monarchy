"""Explicit, bounded Conductor cloud operations; persistence belongs to the caller.

Importing this module starts nothing. Native JSON is evidence of delivery and
identity, never a grant of authority. See docs/conductor-transport.md.
"""

import copy
import json
import math
import re
import subprocess
import time
import uuid
from urllib.parse import urlsplit


class TransportError(Exception):
    """A safe diagnostic that contains no native response or message text."""


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+\Z")
PROFILE_FIELDS = {"agent", "model", "effort", "fast_mode"}
STATES = {"prepared", "in_flight", "unknown", "confirmed", "failed"}
MAX_TEXT_BYTES = 48 * 1024


def _identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise TransportError("invalid " + field)
    return value


def _uuid(value, field):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise TransportError("invalid " + field) from None
    return value


def _text(value, field):
    try:
        valid = isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= MAX_TEXT_BYTES
    except UnicodeError:
        valid = False
    if not valid:
        raise TransportError("invalid or oversized " + field)
    return value


def _repo(value):
    if (not isinstance(value, str) or not REPOSITORY.fullmatch(value)
            or value.split("/")[1] in (".", "..")):
        raise TransportError("invalid repository")
    return value.lower()


def _native_repo(value):
    if not isinstance(value, str):
        raise TransportError("workspace repository is unobserved")
    if value.startswith("git@github.com:"):
        path = value[len("git@github.com:"):]
    else:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
                or parsed.query or parsed.fragment):
            raise TransportError("unsupported workspace repository identity")
        path = parsed.path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return _repo(path)


def _profile(value, complete=False):
    if not isinstance(value, dict) or not set(value) <= PROFILE_FIELDS:
        raise TransportError("invalid requested profile")
    if complete and set(value) != PROFILE_FIELDS:
        raise TransportError("session creation requires agent, model, effort, and fast_mode")
    for key, item in value.items():
        if key == "fast_mode":
            if type(item) is not bool:
                raise TransportError("fast_mode must be a boolean")
        else:
            _text(item, "profile " + key)
            if len(item) > 128 or item.startswith("-"):
                raise TransportError("invalid profile " + key)
    return value


def _binding(value):
    if not isinstance(value, dict):
        raise TransportError("invalid session binding")
    for key in ("workspace_id", "session_id"):
        _identifier(value.get(key), key)
    _repo(value.get("repo"))
    _profile(value.get("profile", {}))
    return value


def _operation(task_id, kind, request, operation_id):
    return {"operation_id": _uuid(operation_id or str(uuid.uuid4()), "operation_id"),
            "task_id": _identifier(task_id, "task_id"), "kind": kind,
            "request": copy.deepcopy(request), "state": "prepared", "result": None}


def prepare_message(task_id, binding, text, *, operation_id=None, message_id=None,
                    sender_session_id=None):
    """Make an intent to persist before sending; this helper performs no I/O."""
    _binding(binding)
    _text(text, "message")
    if sender_session_id is not None:
        _identifier(sender_session_id, "sender_session_id")
    return _operation(task_id, "send_message", {
        "binding": binding, "text": text,
        "message_id": _uuid(message_id or str(uuid.uuid4()), "message_id"),
        "sender_session_id": sender_session_id,
    }, operation_id)


def prepare_session(task_id, workspace_id, repo, profile, name, text, *,
                    operation_id=None, session_id=None, message_id=None,
                    sender_session_id=None):
    """Make a session intent with retained session and initial-message UUIDs."""
    _profile(profile, complete=True)
    result = prepare_message(task_id, {
        "workspace_id": workspace_id, "session_id": _uuid(session_id or str(uuid.uuid4()), "session_id"),
        "repo": repo, "profile": profile,
    }, text, operation_id=operation_id, message_id=message_id,
       sender_session_id=sender_session_id)
    result["kind"] = "create_session"
    result["request"]["name"] = _text(name, "session name")
    return result


def _message_event(value, destination=None):
    if not isinstance(value, dict) or value.get("type") != "userMessage":
        raise TransportError("not a native user-message event")
    _identifier(value.get("id"), "native event id")
    _identifier(value.get("sessionId"), "native recipient session")
    if destination is not None and value["sessionId"] != destination:
        raise TransportError("native recipient identity mismatch")
    content = value.get("content")
    if (not isinstance(content, dict) or content.get("type") != "userMessage"
            or content.get("eventId") != value["id"]
            or content.get("state") not in ("sent", "queued")):
        raise TransportError("invalid native message envelope")
    _identifier(content.get("id"), "native request id")
    _text(content.get("message"), "native message")
    return content


def classify_provenance(message):
    """Classify native metadata only. This CLI contract proves no human grant."""
    content = _message_event(message)
    sender = content.get("senderSessionId")
    if sender is not None:
        _identifier(sender, "native sender session")
        kind = "agent"
    elif content.get("senderApiKeyName") is not None:
        kind = "api_key"
    elif content.get("senderSource") is not None:
        kind = "external"
    else:
        kind = "unverified"
    return {"kind": kind, "sender_session_id": sender,
            "owner_authority": False, "event_id": message["id"]}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _json(text):
    return json.loads(text, object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def _report(envelope):
    fields = {"version", "kind", "court_id", "task_id", "attempt_id", "report_id",
              "sender_session_id", "recipient_session_id", "report"}
    if (not isinstance(envelope, dict) or set(envelope) != fields
            or type(envelope["version"]) is not int or envelope["version"] != 1
            or envelope["kind"] != "monarchy.report"):
        raise TransportError("invalid report envelope")
    for key in ("court_id", "task_id", "attempt_id", "sender_session_id", "recipient_session_id"):
        _identifier(envelope[key], key)
    _uuid(envelope["report_id"], "report_id")
    report = envelope["report"]
    required = {"status", "summary", "evidence", "next_action"}
    if (not isinstance(report, dict) or not required <= set(report)
            or report["status"] not in ("progress", "blocked", "complete", "failed", "decision")
            or not isinstance(report["evidence"], list) or len(report["evidence"]) > 100
            or any(not isinstance(item, dict) for item in report["evidence"])):
        raise TransportError("invalid report fields")
    optional = {"progress": {"routine"}, "complete": {"source_revision"},
                "decision": {"question", "recommendation"}}.get(report["status"], set())
    if not set(report) <= required | optional:
        raise TransportError("report fields do not match its status")
    if "routine" in report and type(report["routine"]) is not bool:
        raise TransportError("routine must be an explicit boolean")
    if "source_revision" in report and (not isinstance(report["source_revision"], str)
            or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", report["source_revision"])):
        raise TransportError("source_revision must be a full Git object id")
    if report["status"] == "decision":
        _text(report.get("question"), "decision question")
        if "recommendation" in report:
            _text(report["recommendation"], "decision recommendation")
    _text(report["summary"], "report summary")
    _text(report["next_action"], "report next action")
    return envelope


def report_text(envelope):
    """Serialize a report for a message; never serialize an approval envelope."""
    _report(envelope)
    try:
        text = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise TransportError("report is not serializable") from None
    return _text(text, "report")


class ConductorTransport:
    """A runner-compatible CLI adapter. Each public operation has one deadline."""

    def __init__(self, runner=None, *, timeout=15.0, max_pages=5, max_output_bytes=2 * 1024 * 1024):
        if (type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 120
                or type(max_pages) is not int or not 1 <= max_pages <= 100
                or type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 16 * 1024 * 1024):
            raise TransportError("invalid transport bounds")
        self.runner = runner or subprocess.run
        self.timeout = float(timeout)
        self.max_pages = max_pages
        self.max_output_bytes = max_output_bytes

    def _deadline(self):
        return time.monotonic() + self.timeout

    def _run(self, args, deadline, text=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("transport deadline reached")
        try:
            response = self.runner(["conductor", "--json"] + args, input=text,
                                   capture_output=True, text=True, check=False,
                                   timeout=remaining, shell=False)
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            raise TransportError("native command unavailable or timed out") from None
        if response.returncode:
            raise TransportError("native command failed (exit %s)" % response.returncode)
        try:
            if not isinstance(response.stdout, str) or len(response.stdout.encode("utf-8")) > self.max_output_bytes:
                raise ValueError()
            return _json(response.stdout)
        except (ValueError, UnicodeError, RecursionError):
            raise TransportError("invalid or oversized native JSON") from None

    def _workspace(self, binding, deadline):
        value = self._run(["workspace", "get", binding["workspace_id"]], deadline)
        if not isinstance(value, dict) or value.get("id") != binding["workspace_id"]:
            raise TransportError("native workspace identity mismatch")
        if _native_repo(value.get("repoUrl")) != _repo(binding["repo"]):
            raise TransportError("native workspace repository mismatch")
        return value

    def _binding(self, binding, deadline):
        _binding(binding)
        self._workspace(binding, deadline)
        state = self._run(["session", "status", binding["session_id"]], deadline)
        if (not isinstance(state, dict) or state.get("sessionId") != binding["session_id"]
                or state.get("workspaceId") != binding["workspace_id"]):
            raise TransportError("native session/workspace identity mismatch")
        _text(state.get("status"), "session status")
        value = self._run(["session", "get", binding["session_id"]], deadline)
        if not isinstance(value, dict) or value.get("id") != binding["session_id"]:
            raise TransportError("native session identity mismatch")
        actual = {key: value[native] for key, native in
                  (("model", "model"), ("effort", "effort"), ("fast_mode", "fastMode"))
                  if native in value and value[native] is not None}
        _profile(actual)
        expected = binding.get("profile", {})
        missing = []
        for key, requested in expected.items():
            if key not in actual:
                missing.append(key)
            elif type(actual[key]) is not type(requested) or actual[key] != requested:
                raise TransportError("native profile mismatch: " + key)
        return {"workspace_id": binding["workspace_id"], "session_id": binding["session_id"],
                "repo": _repo(binding["repo"]), "status": state["status"], "profile": actual,
                "profile_unobserved": sorted(missing), "profile_verified": bool(expected) and not missing,
                "resolved_model": value.get("resolvedModel")}

    def read_binding(self, binding):
        """Verify membership and observable profile; missing fields stay explicit."""
        return self._binding(binding, self._deadline())

    def _scan_message(self, request, deadline):
        offset = 0
        target = request["binding"]["session_id"]
        for _ in range(self.max_pages):
            page = self._run(["session", "message", target, "--limit", "100", "--offset", str(offset)], deadline)
            if (not isinstance(page, dict) or not isinstance(page.get("data"), list)
                    or type(page.get("hasMore")) is not bool
                    or type(page.get("offset")) is not int or page["offset"] != offset
                    or len(page["data"]) > 100):
                raise TransportError("invalid native transcript page")
            for message in page["data"]:
                if not isinstance(message, dict) or message.get("sessionId") != target:
                    raise TransportError("native transcript recipient mismatch")
                content = message.get("content")
                if (message.get("type") != "userMessage" or not isinstance(content, dict)
                        or content.get("id") != request["message_id"]):
                    continue
                content = _message_event(message, target)
                if content["message"] != request["text"]:
                    raise TransportError("retained message identity has different content")
                sender = request.get("sender_session_id")
                if sender is not None and content.get("senderSessionId") != sender:
                    raise TransportError("retained message sender mismatch")
                return {"message_id": content["id"], "event_id": message["id"],
                        "delivery_state": content["state"], "owner_authority": False}
            if not page["hasMore"]:
                raise TransportError("retained message is not yet observed")
            if not page["data"]:
                raise TransportError("native transcript made no pagination progress")
            offset += len(page["data"])
        raise TransportError("native transcript scan bound reached")

    def _validate_operation(self, operation, kind=None):
        if not isinstance(operation, dict):
            raise TransportError("invalid operation")
        value = copy.deepcopy(operation)
        _uuid(value.get("operation_id"), "operation_id")
        _identifier(value.get("task_id"), "task_id")
        if value.get("kind") not in ("send_message", "create_session") or (kind and value["kind"] != kind):
            raise TransportError("wrong operation kind")
        if value.get("state") not in STATES or not isinstance(value.get("request"), dict):
            raise TransportError("invalid operation state or request")
        request = value["request"]
        _binding(request.get("binding"))
        _uuid(request.get("message_id"), "message_id")
        _text(request.get("text"), "message")
        if request.get("sender_session_id") is not None:
            _identifier(request["sender_session_id"], "sender_session_id")
        if value["kind"] == "create_session":
            _uuid(request["binding"]["session_id"], "session_id")
            _profile(request["binding"].get("profile"), complete=True)
            _text(request.get("name"), "session name")
        return value

    def _reconcile(self, operation, deadline, observed=None):
        try:
            observed = observed or self._binding(operation["request"]["binding"], deadline)
            receipt = self._scan_message(operation["request"], deadline)
            operation.update(state="confirmed", result={**receipt, "binding": observed})
        except TransportError as exc:
            operation.update(state="unknown", result={"reason": str(exc)})
        return operation

    def reconcile(self, operation):
        """Only read original identities. Absence does not authorize another write."""
        value = self._validate_operation(operation)
        if value["state"] in ("confirmed", "failed"):
            return value
        return self._reconcile(value, self._deadline())

    def _execute(self, operation, persist, kind):
        value = self._validate_operation(operation, kind)
        if not callable(persist):
            raise TransportError("a durable persist callback is required")
        if value["state"] in ("confirmed", "failed"):
            return value
        deadline = self._deadline()
        if value["state"] != "prepared":
            result = self._reconcile(value, deadline)
            persist(copy.deepcopy(result))
            return result
        request = value["request"]
        binding = request["binding"]
        observed = None
        if kind == "send_message":
            observed = self._binding(binding, deadline)
            args = ["message", "create", "--session", binding["session_id"]]
        else:
            profile = binding["profile"]
            if not profile["fast_mode"]:
                raise TransportError("native CLI cannot explicitly disable fast mode; session creation is held")
            self._workspace(binding, deadline)
            args = ["session", "create", "--workspace", binding["workspace_id"],
                    "--session-id", binding["session_id"], "--name", request["name"],
                    "--agent", profile["agent"], "--model", profile["model"], "--effort", profile["effort"]]
            if profile["fast_mode"]:
                args.append("--fast-mode")
        args += ["--message-id", request["message_id"], "--message-file", "-"]
        value.update(state="in_flight", result=None)
        persist(copy.deepcopy(value))
        try:
            self._run(args, deadline, request["text"])
        except TransportError:
            pass  # Remote acceptance can precede a timeout or broken response.
        result = self._reconcile(value, deadline, observed)
        persist(copy.deepcopy(result))
        return result

    def send_message(self, operation, persist):
        return self._execute(operation, persist, "send_message")

    def create_session(self, operation, persist):
        return self._execute(operation, persist, "create_session")

    def accept_report(self, event_id, court_id, recipient_binding, members):
        """Read and validate a native report against the caller's active membership.

        members maps sender session IDs to their current binding, court_id,
        task_id, attempt_id and role. Old attempts must not remain active members.
        """
        _identifier(event_id, "native event id")
        _identifier(court_id, "court_id")
        deadline = self._deadline()
        self._binding(recipient_binding, deadline)
        native = self._run(["message", "get", event_id], deadline)
        content = _message_event(native, recipient_binding["session_id"])
        if native["id"] != event_id:
            raise TransportError("native report event identity mismatch")
        provenance = classify_provenance(native)
        if provenance["kind"] != "agent":
            raise TransportError("report has no native agent sender identity")
        try:
            envelope = _report(_json(content["message"]))
        except (ValueError, UnicodeError, RecursionError):
            raise TransportError("invalid report JSON") from None
        sender = provenance["sender_session_id"]
        if (envelope["court_id"] != court_id or envelope["sender_session_id"] != sender
                or envelope["recipient_session_id"] != recipient_binding["session_id"]):
            raise TransportError("report route does not match native identities")
        member = members.get(sender) if isinstance(members, dict) else None
        if (not isinstance(member, dict) or member.get("role") not in ("worker", "secretary")
                or member.get("session_id") != sender
                or any(member.get(key) != envelope[key] for key in ("court_id", "task_id", "attempt_id"))):
            raise TransportError("report sender does not own the active assignment")
        self._binding(member, deadline)
        return {"envelope": envelope, "provenance": provenance, "owner_authority": False}
