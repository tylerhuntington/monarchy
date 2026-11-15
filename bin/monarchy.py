#!/usr/bin/env python3
"""Read-only Conductor/GitHub observations for a supervised Monarchy court."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import os


class Invalid(Exception):
    """Invalid configuration or unavailable observation; no completion implied."""


ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
FIELDS = {"id", "repo", "workspace_id", "session_id", "stage", "brief", "endpoint", "pr"}


def read_json(path):
    try:
        if path.stat().st_size > 1_000_000:
            raise Invalid("JSON file exceeds 1 MB")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise Invalid("cannot read valid JSON from the selected file") from exc


def load_court(path):
    court = read_json(path)
    if (not isinstance(court, dict) or set(court) != {"version", "tasks"}
            or type(court["version"]) is not int or court["version"] != 1
            or not isinstance(court["tasks"], list) or len(court["tasks"]) > 100):
        raise Invalid("court requires version 1 and a tasks array of at most 100 entries")
    ids, sessions = set(), set()
    for task in court["tasks"]:
        if not isinstance(task, dict) or set(task) != FIELDS:
            raise Invalid("task fields must be id, repo, workspace_id, session_id, stage, brief, endpoint, pr")
        for field in ("id", "workspace_id", "session_id"):
            if not isinstance(task[field], str) or not ID.fullmatch(task[field]):
                raise Invalid(f"task {field} must be an identifier of at most 128 characters")
        if task["id"] in ids or task["session_id"] in sessions:
            raise Invalid("task IDs and session IDs must be unique within a court")
        ids.add(task["id"])
        sessions.add(task["session_id"])
        if (not isinstance(task["repo"], str) or not REPO.fullmatch(task["repo"])
                or task["repo"].split("/")[-1] in (".", "..")):
            raise Invalid("task repo must be owner/repository")
        for field in ("stage", "brief", "endpoint"):
            if not isinstance(task[field], str) or not task[field].strip() or len(task[field]) > 2000:
                raise Invalid(f"task {field} must be nonempty text of at most 2000 characters")
        if task["pr"] is not None and (type(task["pr"]) is not int or task["pr"] <= 0):
            raise Invalid("task pr must be a positive integer or null")
    return court


class Reader:
    def __init__(self, deadline=None):
        self.deadline = deadline

    def run(self, args):
        timeout = 15.0
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            if timeout <= 0:
                raise Invalid("observation deadline reached")
        try:
            result = subprocess.run(args, capture_output=True, text=True, check=False,
                                    timeout=timeout, shell=False)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            raise Invalid(f"{args[0]} unavailable or timed out") from exc
        if result.returncode:
            raise Invalid(f"{args[0]} read failed (exit {result.returncode})")
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise Invalid(f"{args[0]} returned invalid JSON") from exc

    def session(self, task):
        data = self.run(["conductor", "--json", "session", "status", task["session_id"]])
        if (not isinstance(data, dict) or data.get("sessionId") != task["session_id"]
                or data.get("workspaceId") != task["workspace_id"]):
            raise Invalid("Conductor session/workspace identity mismatch")
        status = data.get("status")
        if not isinstance(status, str) or not status.strip() or len(status) > 128:
            raise Invalid("Conductor returned an invalid session status")
        return {"status": status}

    def pr(self, task):
        data = self.run(["gh", "api", f"repos/{task['repo']}/pulls/{task['pr']}"])
        if not isinstance(data, dict):
            raise Invalid("GitHub returned an invalid PR")
        base = data.get("base")
        repo = base.get("repo") if isinstance(base, dict) else None
        name = repo.get("full_name") if isinstance(repo, dict) else None
        head = data.get("head")
        sha = head.get("sha") if isinstance(head, dict) else None
        if (type(data.get("number")) is not int or data["number"] != task["pr"]
                or not isinstance(name, str) or name.lower() != task["repo"].lower()):
            raise Invalid("GitHub PR/repository identity mismatch")
        if (data.get("state") not in ("open", "closed")
                or type(data.get("merged")) is not bool
                or not isinstance(sha, str) or not SHA.fullmatch(sha)
                or (data["merged"] and data["state"] != "closed")):
            raise Invalid("GitHub returned incomplete or inconsistent PR state")
        return {"state": data["state"], "merged": data["merged"], "head": sha}


def observe(court, reader):
    rows = {}
    for task in court["tasks"]:
        binding = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()
        row = {"binding": binding, "session": None, "pr": None, "errors": []}
        for field, read in (("session", reader.session), ("pr", reader.pr)):
            if field == "pr" and task["pr"] is None:
                continue
            try:
                row[field] = read(task)
            except Invalid as exc:
                row["errors"].append(f"{field}: {exc}")
        rows[task["id"]] = row
    return rows


def events(previous, current):
    changes = []
    if previous is None:
        for task_id, row in current.items():
            status = (row["session"] or {}).get("status")
            if row["errors"] or status in ("idle", "error", "cancelled"):
                changes.append({"task": task_id, "kind": "initial-attention"})
        return changes
    for task_id in sorted(set(previous) | set(current)):
        before, after = previous.get(task_id), current.get(task_id)
        if before is None or after is None or before["binding"] != after["binding"]:
            changes.append({"task": task_id, "kind": "configuration-changed"})
        elif before != after:
            changes.append({"task": task_id, "kind": "observation-changed"})
    return changes


def load_state(path, court_path):
    if not path.exists():
        return None
    state = read_json(path)
    if (not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1
            or state.get("court") != str(court_path.resolve())
            or not isinstance(state.get("tasks"), dict)):
        raise Invalid("state is invalid or belongs to a different court; use a separate state file")
    for task_id, row in state["tasks"].items():
        if (not isinstance(task_id, str) or not ID.fullmatch(task_id) or not isinstance(row, dict)
                or set(row) != {"binding", "session", "pr", "errors"}
                or not isinstance(row["binding"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["binding"])
                or not isinstance(row["errors"], list)
                or any(not isinstance(error, str) for error in row["errors"])
                or (row["session"] is not None and not isinstance(row["session"], dict))
                or (row["pr"] is not None and not isinstance(row["pr"], dict))):
            raise Invalid("state contains an invalid observation")
    return state["tasks"]


def save_state(path, court_path, rows):
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".monarchy-", delete=False) as stream:
            temp = Path(stream.name)
            json.dump({"version": 1, "court": str(court_path.resolve()), "tasks": rows}, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


@contextmanager
def state_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Invalid("another watcher owns this state file") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def report(reason, rows, changes=None, observed_at=None):
    return {"reason": reason, "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
            "tasks": rows, "changes": changes or [],
            "degraded": any(row["errors"] for row in rows.values())}


def watch(court_path, state_path, interval, timeout):
    court_path, state_path = court_path.resolve(), state_path.resolve()
    if court_path.resolve() == state_path.resolve():
        raise Invalid("court and state must be different files")
    deadline = time.monotonic() + timeout
    with state_lock(state_path):
        previous = load_state(state_path, court_path)
        while True:
            court = load_court(court_path)
            current = observe(court, Reader(deadline))
            observed_at = datetime.now(timezone.utc).isoformat()
            changes = events(previous, current)
            save_state(state_path, court_path, current)
            if changes:
                return report("changed", current, changes, observed_at)
            if not current:
                return report("empty", current, observed_at=observed_at)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return report("timeout", current, observed_at=observed_at)
            previous = current
            time.sleep(min(interval, remaining))
            if time.monotonic() >= deadline:
                return report("timeout", current, observed_at=observed_at)


def positive_seconds(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "status", "watch"):
        item = sub.add_parser(command)
        item.add_argument("--court", required=True, type=Path)
        if command == "watch":
            item.add_argument("--state", required=True, type=Path)
            item.add_argument("--interval", type=positive_seconds, default=30)
            item.add_argument("--timeout", type=positive_seconds, default=600)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            court = load_court(args.court)
            output = {"valid": True, "tasks": len(court["tasks"])}
        elif args.command == "status":
            output = report("snapshot", observe(load_court(args.court), Reader()))
        else:
            output = watch(args.court, args.state, args.interval, args.timeout)
        print(json.dumps(output, indent=2))
        return 1 if output.get("degraded") else 0
    except (Invalid, OSError) as exc:
        # Filesystem error text may contain private paths. Transport errors are
        # already sanitized by Reader and never include native stderr or stdout.
        message = str(exc) if isinstance(exc, Invalid) else "local file operation failed"
        print(json.dumps({"error": message}))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
