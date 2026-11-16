"""Integrated offline qualification: real records and adapter, simulated native CLI.

The native fixture persists separately from the court so a process can die after
remote acceptance and before a local receipt. It never launches a real agent.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile

from monarchy.conductor import ConductorTransport, TransportError, report_text
from monarchy.records import CourtRecords, Conflict
from monarchy.skills import build_package, inspect_package
from monarchy.supervision import Court


ROOT = Path(__file__).resolve().parents[1]
TASK = "qualify-export"
COURT = "qualification-court"
WORKSPACE = "11111111-1111-4111-8111-111111111111"
WORKER = "22222222-2222-4222-8222-222222222222"
SECRETARY_WORKSPACE = "33333333-3333-4333-8333-333333333333"
SECRETARY = "44444444-4444-4444-8444-444444444444"
PROFILE = {"agent": "codex", "model": "fixture-model", "effort": "high", "fast_mode": False}
SOURCE = "a" * 40
LATER_SOURCE = "b" * 40
WORKER_BINDING = {"session_id": WORKER, "workspace_id": WORKSPACE,
                  "repo": "example/project", "profile": PROFILE}
SECRETARY_BINDING = {"session_id": SECRETARY, "workspace_id": SECRETARY_WORKSPACE,
                     "repo": "example/coordination", "profile": PROFILE}


def stable_id(label):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "monarchy-qualification:" + label))


def sha(data):
    return hashlib.sha256(data).hexdigest()


class NativeFixture:
    """A file-backed subprocess.run-compatible Conductor boundary, not a Court stub."""

    def __init__(self, path, *, crash_after_send=False):
        self.path = Path(path)
        self.crash_after_send = crash_after_send
        self.calls = []
        if not self.path.exists():
            self.save({
                "workspaces": {
                    WORKSPACE: "https://github.com/example/project.git",
                    SECRETARY_WORKSPACE: "https://github.com/example/coordination.git",
                },
                "sessions": {
                    WORKER: {"workspace_id": WORKSPACE, "profile": PROFILE},
                    SECRETARY: {"workspace_id": SECRETARY_WORKSPACE, "profile": PROFILE},
                },
                "events": [], "mutations": [], "hide_messages": False,
                "timeout_after_send": False,
            })

    def load(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def configure(self, **changes):
        state = self.load()
        state.update(changes)
        self.save(state)

    @staticmethod
    def event(message_id, text, sender, destination, event_id=None):
        event_id = event_id or stable_id("event:" + message_id)
        return {"id": event_id, "sessionId": destination, "type": "userMessage",
                "receivedAt": "2026-11-16T00:00:00Z",
                "content": {"id": message_id, "eventId": event_id, "type": "userMessage",
                            "message": text, "state": "sent", "senderSessionId": sender}}

    def worker_report(self, label, status, *, generation=1, source=None, **extra):
        report = {"status": status, "summary": "Fixture evidence for " + label,
                  "evidence": [{"source": "isolated-native-fixture", "label": label}],
                  "next_action": "Continue within the task brief."}
        report.update(extra)
        if source is not None:
            report["source_revision"] = source
        envelope = {"version": 1, "kind": "monarchy.report", "court_id": COURT,
                    "task_id": TASK, "attempt_id": str(generation),
                    "report_id": stable_id("report:" + label), "sender_session_id": WORKER,
                    "recipient_session_id": SECRETARY, "report": report}
        native = self.event(stable_id("native-request:" + label), report_text(envelope),
                            WORKER, SECRETARY)
        state = self.load()
        state["events"].append(native)
        self.save(state)
        return native["id"]

    def __call__(self, argv, **kwargs):
        assert argv[:2] == ["conductor", "--json"]
        assert kwargs["shell"] is False
        assert 0 < kwargs["timeout"] <= 15
        self.calls.append((copy.deepcopy(argv), copy.deepcopy(kwargs)))
        command = argv[2:]
        state = self.load()
        if command[:2] == ["workspace", "get"]:
            wid = command[2]
            payload = {"id": wid, "repoUrl": state["workspaces"][wid]}
        elif command[:2] == ["session", "status"]:
            sid = command[2]
            payload = {"sessionId": sid, "workspaceId": state["sessions"][sid]["workspace_id"],
                       "status": "idle"}
        elif command[:2] == ["session", "get"]:
            sid = command[2]
            profile = state["sessions"][sid]["profile"]
            # The inspected native session contract does not expose agent type.
            payload = {"id": sid, "model": profile["model"], "effort": profile["effort"],
                       "fastMode": profile["fast_mode"], "resolvedModel": profile["model"]}
        elif command[:2] == ["session", "message"]:
            sid = command[2]
            offset = int(command[command.index("--offset") + 1])
            limit = int(command[command.index("--limit") + 1])
            events = [] if state["hide_messages"] else [
                item for item in state["events"] if item["sessionId"] == sid]
            payload = {"data": events[offset:offset + limit], "offset": offset,
                       "hasMore": len(events) > offset + limit}
        elif command[:2] == ["message", "get"]:
            matches = [item for item in state["events"] if item["id"] == command[2]]
            if not matches:
                return subprocess.CompletedProcess(argv, 4, "", "fixture event not found")
            payload = matches[0]
        elif command[:2] == ["message", "create"]:
            destination = command[command.index("--session") + 1]
            message_id = command[command.index("--message-id") + 1]
            assert command[command.index("--message-file") + 1] == "-"
            assert kwargs["input"] not in argv
            state["mutations"].append({"kind": "send", "message_id": message_id,
                                       "destination": destination})
            state["events"].append(self.event(message_id, kwargs["input"], SECRETARY, destination))
            self.save(state)
            if self.crash_after_send:
                os._exit(73)  # Acceptance persisted; no return, receipt or clean SQLite close.
            if state["timeout_after_send"]:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            payload = {"messageId": message_id, "state": "sent"}
        else:
            raise AssertionError("Unexpected native command: " + repr(command))
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")


class CourtQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.database = self.directory / "court.sqlite3"
        self.native_path = self.directory / "native.json"
        self.native = NativeFixture(self.native_path)
        self.records = CourtRecords(self.database)
        self.court = Court(self.records, ConductorTransport(self.native))
        self.records.create_task(TASK, "example/project", WORKER, metadata={
            "authority_ref": "trusted-fixture-owner:request-1",
            "brief": "Investigate the export failure. Return a verified review of the exact source revision.",
            "court_id": COURT, "binding": WORKER_BINDING,
            "secretary_binding": SECRETARY_BINDING,
        })

    def tearDown(self):
        if self.records is not None:
            self.records.close()
        self.temp.cleanup()

    def restart(self):
        if self.records is not None:
            self.records.close()
        self.native = NativeFixture(self.native_path)
        self.records = CourtRecords(self.database)
        self.court = Court(self.records, ConductorTransport(self.native))

    def ingest_report(self, label, status, **extra):
        event_id = self.native.worker_report(label, status, **extra)
        self.court.ingest(TASK, event_id)
        return event_id

    def verify(self, source=SOURCE, observed=SOURCE):
        return self.court.verify(TASK, source_revision=source, observed_revision=observed,
                                 reviewer="independent-fixture-reviewer",
                                 evidence={"checks": [{"command": "isolated fixture check",
                                                       "result": "passed", "source_revision": source}]})

    def test_request_dispatch_decision_answer_and_verified_result_survive_restart(self):
        dispatch = self.court.prepare_dispatch(TASK)
        self.assertEqual(dispatch["state"], "prepared")
        self.assertEqual(self.native.load()["mutations"], [])
        self.assertEqual(self.court.deliver(dispatch["operation_id"])["state"], "confirmed")

        self.ingest_report("routine", "progress", routine=True)
        self.assertEqual(self.court.tick(TASK)["consumed"], 1)
        self.assertIsNone(self.court.inbox())
        self.ingest_report("choice", "decision", question="Should archived rows be included?",
                           recommendation="Keep the original scope.")
        self.court.tick(TASK)
        decision = self.records.list_decisions(task_id=TASK, state="pending")[0]
        presented = self.court.inbox()
        self.assertEqual(presented["outcomes"][0]["payload"]["decision_id"], decision["decision_id"])

        self.restart()
        self.assertEqual(self.court.inbox()["presentation_id"], presented["presentation_id"])
        self.assertEqual(self.court.status(TASK)["next_action"], "owner_decision")
        answer = self.court.answer(decision["decision_id"], {"text": "Keep the original scope."},
                                   expected_revision=decision["revision"],
                                   owner_message="trusted-fixture-owner:answer-1")
        self.assertEqual(answer["state"], "answered")
        delivery = self.court.prepare_answer(decision["decision_id"])
        self.assertEqual(self.court.status(TASK)["next_action"], "deliver_prepared_operation")
        self.records.process_outcomes(presented["presentation_id"], "queen", presented["outcome_ids"])

        self.restart()
        self.assertEqual(self.court.deliver(delivery["operation_id"])["state"], "confirmed")
        self.ingest_report("finished", "complete", source=SOURCE)
        self.court.tick(TASK)
        self.assertEqual(self.court.status(TASK)["next_action"], "verify_result")
        self.assertFalse(self.court.status(TASK)["complete"])
        outcome = self.verify()

        self.restart()
        self.assertTrue(self.court.status(TASK)["complete"])
        final_presentation = self.court.inbox()
        self.assertEqual(final_presentation["outcome_ids"], [outcome["outcome_id"]])
        self.assertEqual(final_presentation["outcomes"][0]["payload"]["source_revision"], SOURCE)
        self.assertEqual(len(self.native.load()["mutations"]), 2)
        self.records.process_outcomes(final_presentation["presentation_id"], "queen",
                                      final_presentation["outcome_ids"])
        self.restart()
        self.assertIsNone(self.court.inbox())
        self.assertEqual(self.records.get_decision(decision["decision_id"])["owner_message"],
                         "trusted-fixture-owner:answer-1")

    def test_process_death_after_native_acceptance_reconciles_without_resending(self):
        dispatch = self.court.prepare_dispatch(TASK)
        self.records.close()
        self.records = None
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT)
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--crash-after-native-send",
             str(self.database), str(self.native_path), dispatch["operation_id"]],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(process.returncode, 73, process.stderr)
        self.restart()
        recovered = self.records.get_operation(dispatch["operation_id"])
        self.assertEqual(recovered["state"], "in_flight")
        self.assertEqual(len(self.native.load()["mutations"]), 1)
        confirmed = self.court.deliver(dispatch["operation_id"])
        self.assertEqual(confirmed["state"], "confirmed")
        self.assertEqual(confirmed["result"]["message_id"], dispatch["request"]["message_id"])
        self.assertEqual(len(self.native.load()["mutations"]), 1)
        self.assertFalse(any(call[0][2:4] == ["message", "create"] for call in self.native.calls))

    def test_unknown_send_survives_restart_and_later_readback_without_resend(self):
        dispatch = self.court.prepare_dispatch(TASK)
        self.native.configure(timeout_after_send=True, hide_messages=True)
        self.assertEqual(self.court.deliver(dispatch["operation_id"])["state"], "unknown")
        self.assertEqual(self.court.status(TASK)["next_action"], "reconcile_delivery")
        self.restart()
        self.assertEqual(self.court.deliver(dispatch["operation_id"])["state"], "unknown")
        self.native.configure(hide_messages=False)
        self.assertEqual(self.court.deliver(dispatch["operation_id"])["state"], "confirmed")
        self.assertEqual(len(self.native.load()["mutations"]), 1)

    def test_lost_doorbell_and_repeated_presentation_leave_the_decision_pending(self):
        self.ingest_report("lost-doorbell", "decision", question="Which supported option?")
        self.court.tick(TASK)
        # No Queen read or notification occurs. Only the durable outcome exists.
        self.restart()
        first = self.court.inbox()
        self.assertEqual(len(first["outcomes"]), 1)
        self.assertIsNone(first["outcomes"][0]["processed_at"])
        self.restart()
        again = self.court.inbox()
        self.assertEqual(again["presentation_id"], first["presentation_id"])
        self.assertEqual(len(self.records.list_decisions(task_id=TASK, state="pending")), 1)
        self.assertEqual(self.court.notification_policy("unknown"), "hold")
        self.assertEqual(self.court.notification_policy("open"), "hold")
        self.assertEqual(self.native.load()["mutations"], [])

    def test_native_report_replay_creates_one_durable_decision_and_outcome(self):
        event_id = self.ingest_report("replay", "decision", question="Keep the current scope?")
        self.court.ingest(TASK, event_id)
        self.court.tick(TASK)
        self.restart()
        self.court.ingest(TASK, event_id)
        self.assertEqual(self.court.tick(TASK)["consumed"], 0)
        self.assertEqual(len(self.records.list_events(task_id=TASK)), 1)
        self.assertEqual(len(self.records.list_decisions(task_id=TASK)), 1)
        self.assertEqual(len(self.records.list_outcomes(task_id=TASK)), 1)

    def test_old_review_cannot_qualify_a_later_source_or_different_completion(self):
        self.ingest_report("first-source", "complete", source=SOURCE)
        self.court.tick(TASK)
        with self.assertRaises(Conflict):
            self.verify(source=SOURCE, observed=LATER_SOURCE)
        with self.assertRaises(Conflict):
            self.verify(source=LATER_SOURCE, observed=LATER_SOURCE)
        self.assertFalse(self.court.status(TASK)["complete"])
        self.assertIsNone(self.court.inbox())
        self.ingest_report("later-source", "complete", source=LATER_SOURCE)
        self.court.tick(TASK)
        with self.assertRaises(Conflict):
            self.verify(source=SOURCE, observed=LATER_SOURCE)
        self.verify(source=LATER_SOURCE, observed=LATER_SOURCE)
        self.assertTrue(self.court.status(TASK)["complete"])

    def test_completion_and_presentation_ack_do_not_erase_an_unanswered_decision(self):
        self.ingest_report("unanswered", "decision", question="Is the expanded scope authorized?")
        self.ingest_report("premature-done", "complete", source=SOURCE)
        self.court.tick(TASK)
        shown = self.court.inbox()
        self.records.process_outcomes(shown["presentation_id"], "queen", shown["outcome_ids"])
        self.restart()
        self.assertIsNone(self.court.inbox())
        self.assertEqual(len(self.records.list_decisions(task_id=TASK, state="pending")), 1)
        self.assertEqual(self.court.status(TASK)["next_action"], "owner_decision")
        with self.assertRaises(Conflict):
            self.verify()
        self.assertFalse(self.court.status(TASK)["complete"])

    def test_recorded_answer_is_still_an_obligation_until_delivery_is_prepared_and_confirmed(self):
        self.ingest_report("answer-obligation", "decision", question="Keep the original scope?")
        self.ingest_report("done-before-answer-delivery", "complete", source=SOURCE)
        self.court.tick(TASK)
        decision = self.records.list_decisions(task_id=TASK, state="pending")[0]
        self.court.answer(decision["decision_id"], {"text": "Keep the original scope."},
                          expected_revision=decision["revision"],
                          owner_message="trusted-fixture-owner:undelivered-answer")
        self.restart()
        self.assertNotEqual(self.court.status(TASK)["next_action"], "verify_result")
        with self.assertRaises(Conflict):
            self.verify()
        delivery = self.court.prepare_answer(decision["decision_id"])
        with self.assertRaises(Conflict):
            self.verify()
        self.court.deliver(delivery["operation_id"])
        self.verify()
        self.assertTrue(self.court.status(TASK)["complete"])

    def test_prepared_answer_cannot_send_after_its_question_was_superseded(self):
        self.ingest_report("superseded", "decision", question="Choose the original option?")
        self.court.tick(TASK)
        decision = self.records.list_decisions(task_id=TASK, state="pending")[0]
        self.court.answer(decision["decision_id"], {"text": "Yes, the original option."},
                          expected_revision=decision["revision"],
                          owner_message="trusted-fixture-owner:superseded-answer")
        old_delivery = self.court.prepare_answer(decision["decision_id"])
        revised = self.records.revise_decision(
            decision["decision_id"], {**decision["payload"], "question": "A materially different choice?"},
            expected_revision=decision["revision"])
        self.court.answer(revised["decision_id"], {"text": "Use the new option."},
                          expected_revision=revised["revision"],
                          owner_message="trusted-fixture-owner:new-answer")
        self.restart()
        with self.assertRaises(Conflict):
            self.court.deliver(old_delivery["operation_id"])
        self.assertEqual(self.native.load()["mutations"], [])

    def test_decision_revision_change_during_native_preflight_blocks_send_admission(self):
        self.ingest_report("revision-race", "decision", question="The original question?")
        self.court.tick(TASK)
        decision = self.records.list_decisions(task_id=TASK, state="pending")[0]
        self.court.answer(decision["decision_id"], {"text": "The original answer."},
                          expected_revision=decision["revision"],
                          owner_message="trusted-fixture-owner:racing-answer")
        delivery = self.court.prepare_answer(decision["decision_id"])
        changed = []
        def race(argv, **kwargs):
            response = self.native(argv, **kwargs)
            if argv[2:5] == ["session", "get", WORKER] and not changed:
                changed.append(self.records.revise_decision(
                    decision["decision_id"], {**decision["payload"], "question": "A replacement question?"},
                    expected_revision=decision["revision"]))
            return response
        self.court.transport = ConductorTransport(race)
        with self.assertRaises(Conflict):
            self.court.deliver(delivery["operation_id"])
        self.assertEqual(len(changed), 1)
        self.assertEqual(self.native.load()["mutations"], [])

    def test_crash_between_outcome_and_event_ack_replays_without_duplicate_outcome(self):
        self.ingest_report("triage-crash", "decision", question="Which option is intended?")
        def failed_ack(*args, **kwargs):
            raise OSError("injected failure after durable outcome")
        self.records.ack_events = failed_ack
        with self.assertRaises(OSError):
            self.court.tick(TASK)
        self.assertEqual(len(self.records.list_outcomes(task_id=TASK)), 1)
        self.assertEqual(len(self.records.list_events(task_id=TASK, processed=False)), 1)
        self.restart()
        self.assertEqual(self.court.tick(TASK)["consumed"], 1)
        self.assertEqual(len(self.records.list_outcomes(task_id=TASK)), 1)
        self.assertEqual(len(self.records.list_decisions(task_id=TASK)), 1)
        self.assertEqual(self.records.list_events(task_id=TASK, processed=False), [])

    def test_report_from_retired_assignment_cannot_enter_current_inbox(self):
        old_event = self.native.worker_report("retired", "decision", question="Old question?")
        task = self.records.get_task(TASK)
        self.records.assign_task(TASK, WORKER, expected_generation=task["generation"],
                                 metadata=task["metadata"])
        with self.assertRaises(TransportError):
            self.court.ingest(TASK, old_event)
        self.assertEqual(self.records.list_events(task_id=TASK), [])
        self.assertIsNone(self.court.inbox())

    def test_selected_skills_and_project_policy_survive_a_separate_worker_checkout(self):
        source = self.directory / "skill-source"
        shutil.copytree(ROOT / ".agents/skills", source / ".agents/skills")
        project = self.directory / "project"
        project.mkdir()
        policy = b"Use the target project's own review and delivery rules.\n"
        (project / "AGENTS.md").write_bytes(policy)
        outgoing = self.directory / "outgoing.zip"
        selected = ["monarchy-checkpoint", "monarchy-verify"]
        registry_path = ".agents/skills/registry.json"
        manifest = build_package(source, selected, outgoing,
                                 expected_hashes={registry_path: sha((source / registry_path).read_bytes())},
                                 context_root=project, context_files={"AGENTS.md": sha(policy)})
        worker_checkout = self.directory / "independent-worker"
        worker_checkout.mkdir()
        received = worker_checkout / "context.zip"
        shutil.copyfile(outgoing, received)
        package_pin = sha(received.read_bytes())
        shutil.rmtree(source)
        shutil.rmtree(project)
        outgoing.unlink()
        self.assertEqual(inspect_package(received, expected_sha256=package_pin), manifest)
        with zipfile.ZipFile(received) as archive:
            self.assertEqual(archive.read("project/AGENTS.md"), policy)
            for skill in selected:
                self.assertIn(f"skills/{skill}/references/output.md", archive.namelist())
                self.assertIn(f"skills/{skill}/agents/openai.yaml", archive.namelist())
            self.assertNotIn("skills/monarchy-dispatch/SKILL.md", archive.namelist())


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--crash-after-native-send":
        records = CourtRecords(sys.argv[2])
        runner = NativeFixture(sys.argv[3], crash_after_send=True)
        Court(records, ConductorTransport(runner)).deliver(sys.argv[4])
        raise SystemExit("fixture failed to reach its crash point")
    unittest.main()
