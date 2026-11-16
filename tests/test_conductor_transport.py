"""Offline tests: the injected runner never invokes native Conductor."""

import copy
import json
import subprocess
import unittest

from monarchy.conductor import (
    ConductorTransport, TransportError, prepare_message, prepare_session,
    report_text, classify_provenance,
)


WORKSPACE = "11111111-1111-4111-8111-111111111111"
SESSION = "22222222-2222-4222-8222-222222222222"
MESSAGE = "33333333-3333-4333-8333-333333333333"
SOURCE = "44444444-4444-4444-8444-444444444444"
SOURCE_WORKSPACE = "55555555-5555-4555-8555-555555555555"
PROFILE = {"agent": "codex", "model": "chosen-model", "effort": "high", "fast_mode": False}


def binding(session=SESSION, workspace=WORKSPACE):
    return {"workspace_id": workspace, "session_id": session,
            "repo": "example/project", "profile": dict(PROFILE)}


def workspace(wid=WORKSPACE):
    return {"id": wid, "repoUrl": "https://github.com/example/project.git", "state": "ready"}


def session(sid=SESSION):
    return {"id": sid, "model": "chosen-model", "resolvedModel": "native-model",
            "effort": "high", "fastMode": False}


def status(sid=SESSION, wid=WORKSPACE):
    return {"sessionId": sid, "workspaceId": wid, "status": "idle"}


def event(text="hello", request_id=MESSAGE, sender=SOURCE, destination=SESSION):
    content = {"id": request_id, "eventId": "native-event", "type": "userMessage",
               "message": text, "state": "sent"}
    if sender is not None:
        content["senderSessionId"] = sender
    return {"id": "native-event", "sessionId": destination, "type": "userMessage",
            "sessionIndex": 1, "content": content, "receivedAt": "2026-11-16T00:00:00Z"}


def page(messages=(), offset=0, more=False):
    return {"data": list(messages), "offset": offset, "hasMore": more}


class Runner:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.replies:
            raise AssertionError("unexpected native command: " + repr(args))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, subprocess.CompletedProcess):
            return reply
        return subprocess.CompletedProcess(args, 0, json.dumps(reply), "private stderr")


def native_failure():
    return subprocess.CompletedProcess([], 4, "private response", "private token")


class TransportTests(unittest.TestCase):
    def test_binding_checks_native_membership_and_exposes_unobserved_agent(self):
        run = Runner([workspace(), status(), session()])
        value = ConductorTransport(run).read_binding(binding())
        self.assertEqual(value["session_id"], SESSION)
        self.assertEqual(value["profile_unobserved"], ["agent"])
        self.assertFalse(value["profile_verified"])
        self.assertEqual(value["resolved_model"], "native-model")
        self.assertTrue(all(c[1]["shell"] is False for c in run.calls))
        self.assertTrue(all(0 < c[1]["timeout"] <= 15 for c in run.calls))

    def test_wrong_workspace_membership_is_rejected(self):
        run = Runner([workspace(), status(wid=SOURCE_WORKSPACE)])
        with self.assertRaises(TransportError):
            ConductorTransport(run).read_binding(binding())

    def test_wrong_repository_is_rejected(self):
        run = Runner([{**workspace(), "repoUrl": "https://github.com/other/project"}])
        with self.assertRaises(TransportError):
            ConductorTransport(run).read_binding(binding())

    def test_wrong_profile_is_rejected_without_fallback(self):
        for field, value in (("model", "other"), ("effort", "low"), ("fastMode", True)):
            with self.subTest(field=field):
                run = Runner([workspace(), status(), {**session(), field: value}])
                with self.assertRaises(TransportError):
                    ConductorTransport(run).read_binding(binding())

    def test_missing_profile_is_unobserved_not_a_match(self):
        run = Runner([workspace(), status(), {"id": SESSION}])
        value = ConductorTransport(run).read_binding(binding())
        self.assertEqual(set(value["profile_unobserved"]), set(PROFILE))
        self.assertFalse(value["profile_verified"])

    def test_errors_never_include_native_output(self):
        run = Runner([native_failure()])
        with self.assertRaises(TransportError) as caught:
            ConductorTransport(run).read_binding(binding())
        self.assertNotIn("private", str(caught.exception))

    def test_invalid_bounds_and_identifiers_fail_before_io(self):
        for timeout in (0, -1, float("inf"), float("nan"), True):
            with self.assertRaises(TransportError):
                ConductorTransport(Runner([]), timeout=timeout)
        run = Runner([])
        with self.assertRaises(TransportError):
            ConductorTransport(run).read_binding({**binding(), "session_id": "--help"})
        self.assertEqual(run.calls, [])

    def test_message_persists_before_write_and_reconciles_content_id(self):
        op = prepare_message("task-1", binding(), "hello", message_id=MESSAGE)
        run = Runner([workspace(), status(), session(),
                      {"messageId": MESSAGE, "state": "queued"}, page([event()])])
        persisted = []
        def persist(value):
            if value["state"] == "in_flight":
                self.assertEqual(len(run.calls), 3)
            persisted.append(copy.deepcopy(value))
        result = ConductorTransport(run).send_message(op, persist)
        self.assertEqual([r["state"] for r in persisted], ["in_flight", "confirmed"])
        self.assertEqual(result["state"], "confirmed")
        self.assertEqual(op["state"], "prepared")
        args, options = run.calls[3]
        self.assertEqual(args[-4:], ["--message-id", MESSAGE, "--message-file", "-"])
        self.assertEqual(options["input"], "hello")
        self.assertNotIn("hello", args)
        self.assertEqual(result["result"]["message_id"], MESSAGE)
        self.assertEqual(result["result"]["event_id"], "native-event")

    def test_persist_failure_prevents_native_write(self):
        op = prepare_message("task-1", binding(), "hello", message_id=MESSAGE)
        run = Runner([workspace(), status(), session()])
        def fail(_):
            raise OSError("disk unavailable")
        with self.assertRaises(OSError):
            ConductorTransport(run).send_message(op, fail)
        self.assertEqual(len(run.calls), 3)

    def test_uncertain_write_is_read_back_without_retry(self):
        op = prepare_message("task-1", binding(), "hello", message_id=MESSAGE)
        timeout = subprocess.TimeoutExpired(["conductor"], 15, output="secret")
        run = Runner([workspace(), status(), session(), timeout, page([event()])])
        result = ConductorTransport(run).send_message(op, lambda _: None)
        self.assertEqual(result["state"], "confirmed")
        self.assertEqual(sum("create" in c[0] for c in run.calls), 1)

    def test_uncertain_absence_stays_unknown_on_repeated_calls(self):
        op = prepare_message("task-1", binding(), "hello", message_id=MESSAGE)
        run = Runner([workspace(), status(), session(), native_failure(), page(),
                      workspace(), status(), session(), page()])
        adapter = ConductorTransport(run)
        op = adapter.send_message(op, lambda _: None)
        self.assertEqual(op["state"], "unknown")
        op = adapter.send_message(op, lambda _: None)
        self.assertEqual(op["state"], "unknown")
        self.assertEqual(sum("create" in c[0] for c in run.calls), 1)

    def test_recovered_in_flight_operation_only_reads(self):
        op = prepare_message("task-1", binding(), "hello", message_id=MESSAGE)
        op["state"] = "in_flight"
        run = Runner([workspace(), status(), session(), page([event()])])
        self.assertEqual(ConductorTransport(run).send_message(op, lambda _: None)["state"], "confirmed")
        self.assertFalse(any("create" in args for args, _ in run.calls))

    def test_request_id_collision_with_other_text_is_not_confirmed(self):
        op = prepare_message("task-1", binding(), "hello", message_id=MESSAGE)
        op["state"] = "unknown"
        run = Runner([workspace(), status(), session(), page([event(text="different")])])
        result = ConductorTransport(run).reconcile(op)
        self.assertEqual(result["state"], "unknown")

    def test_pagination_is_bounded_and_original_request_id_is_retained(self):
        op = prepare_message("task-1", binding(), "hello", message_id=MESSAGE)
        op["state"] = "unknown"
        run = Runner([workspace(), status(), session(), page([event(request_id=SOURCE)], more=True),
                      page([event()], offset=1)])
        result = ConductorTransport(run, max_pages=2).reconcile(op)
        self.assertEqual(result["state"], "confirmed")
        self.assertEqual(run.calls[-1][0][-2:], ["--offset", "1"])
        run = Runner([workspace(), status(), session(), page([event(request_id=SOURCE)], more=True)])
        result = ConductorTransport(run, max_pages=1).reconcile(op)
        self.assertEqual(result["state"], "unknown")

    def test_create_session_retains_both_ids_and_checks_profile_and_initial_message(self):
        op = prepare_session("task-1", WORKSPACE, "example/project", PROFILE, "Review", "hello",
                             session_id=SESSION, message_id=MESSAGE)
        run = Runner([workspace(), {"id": SESSION}, workspace(), status(), session(), page([event()])])
        saved = []
        result = ConductorTransport(run).create_session(op, lambda o: saved.append(copy.deepcopy(o)))
        self.assertEqual(result["state"], "confirmed")
        self.assertFalse(result["result"]["binding"]["profile_verified"])
        self.assertEqual([o["state"] for o in saved], ["in_flight", "confirmed"])
        args = run.calls[1][0]
        self.assertEqual(args[args.index("--session-id") + 1], SESSION)
        self.assertEqual(args[args.index("--message-id") + 1], MESSAGE)
        self.assertNotIn("--fast-mode", args)

    def test_create_session_requires_explicit_complete_requested_profile(self):
        with self.assertRaises(TransportError):
            prepare_session("task-1", WORKSPACE, "example/project", {"model": "default"}, "Review", "hello")

    def test_owner_provenance_is_never_inferred_from_missing_markers(self):
        native = event(sender=None)
        native["content"]["senderId"] = "owner-id"
        self.assertEqual(classify_provenance(native)["kind"], "unverified")
        self.assertFalse(classify_provenance(native)["owner_authority"])
        native["content"]["senderApiKeyName"] = "owner-key"
        self.assertEqual(classify_provenance(native)["kind"], "api_key")

    def report(self, **changes):
        envelope = {"version": 1, "kind": "monarchy.report", "court_id": "court-1",
                    "task_id": "task-1", "attempt_id": "attempt-1", "report_id": MESSAGE,
                    "sender_session_id": SOURCE, "recipient_session_id": SESSION,
                    "report": {"status": "complete", "summary": "Checked the requested result",
                               "evidence": [{"source": "fixture"}], "next_action": "Review"}}
        envelope.update(changes)
        return envelope

    def members(self):
        return {SOURCE: {**binding(SOURCE, SOURCE_WORKSPACE), "court_id": "court-1",
                         "task_id": "task-1", "attempt_id": "attempt-1", "role": "worker"}}

    def test_cross_workspace_report_uses_native_sender_and_local_assignment(self):
        text = report_text(self.report())
        native = event(text=text)
        run = Runner([workspace(), status(), session(), native,
                      workspace(SOURCE_WORKSPACE), status(SOURCE, SOURCE_WORKSPACE), session(SOURCE)])
        result = ConductorTransport(run).accept_report("native-event", "court-1", binding(), self.members())
        self.assertEqual(result["envelope"]["task_id"], "task-1")
        self.assertFalse(result["owner_authority"])
        self.assertEqual(result["provenance"]["sender_session_id"], SOURCE)

    def test_report_body_cannot_spoof_the_native_sender(self):
        native = event(text=report_text(self.report()), sender=None)
        native["content"]["senderId"] = "owner-id"
        run = Runner([workspace(), status(), session(), native])
        with self.assertRaises(TransportError):
            ConductorTransport(run).accept_report("native-event", "court-1", binding(), self.members())

    def test_wrong_attempt_and_court_are_rejected(self):
        for changes in ({"attempt_id": "old-attempt"}, {"court_id": "other-court"},
                        {"recipient_session_id": SOURCE}):
            with self.subTest(changes=changes):
                native = event(text=report_text(self.report(**changes)))
                run = Runner([workspace(), status(), session(), native])
                with self.assertRaises(TransportError):
                    ConductorTransport(run).accept_report("native-event", "court-1", binding(), self.members())

    def test_report_sender_workspace_is_verified(self):
        native = event(text=report_text(self.report()))
        run = Runner([workspace(), status(), session(), native,
                      workspace(SOURCE_WORKSPACE), status(SOURCE, WORKSPACE)])
        with self.assertRaises(TransportError):
            ConductorTransport(run).accept_report("native-event", "court-1", binding(), self.members())

    def test_report_does_not_accept_authority_message_kind(self):
        with self.assertRaises(TransportError):
            report_text(self.report(kind="monarchy.approval"))

    def test_decision_reports_require_a_question_and_can_recommend(self):
        envelope = self.report()
        envelope["report"].update(status="decision", question="Which scope should proceed?",
                                  recommendation="Keep the existing scope.")
        self.assertEqual(json.loads(report_text(envelope)), envelope)
        del envelope["report"]["question"]
        with self.assertRaises(TransportError):
            report_text(envelope)

    def test_routine_is_explicit_boolean_for_progress_only(self):
        envelope = self.report()
        envelope["report"].update(status="progress", routine=True)
        self.assertTrue(json.loads(report_text(envelope))["report"]["routine"])
        for change in ({"routine": "true"}, {"status": "complete"},
                       {"status": "decision", "question": "Approve?"}):
            bad = copy.deepcopy(envelope)
            bad["report"].update(change)
            with self.subTest(change=change), self.assertRaises(TransportError):
                report_text(bad)

    def test_completion_revision_requires_a_full_git_object_id(self):
        envelope = self.report()
        for revision in ("a" * 40, "b" * 64):
            envelope["report"]["source_revision"] = revision
            self.assertEqual(json.loads(report_text(envelope))["report"]["source_revision"], revision)
        for revision in ("a" * 8, "g" * 40, None):
            envelope["report"]["source_revision"] = revision
            with self.subTest(revision=revision), self.assertRaises(TransportError):
                report_text(envelope)

    def test_duplicate_report_json_keys_are_rejected(self):
        text = report_text(self.report()).replace('"court_id":"court-1"',
                                                 '"court_id":"wrong","court_id":"court-1"')
        run = Runner([workspace(), status(), session(), event(text=text)])
        with self.assertRaises(TransportError):
            ConductorTransport(run).accept_report("native-event", "court-1", binding(), self.members())


if __name__ == "__main__":
    unittest.main()
