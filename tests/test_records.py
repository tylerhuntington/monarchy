"""Behavioral tests for private, durable royalty records."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest

from monarchy.records import Conflict, CourtRecords, RecordError, StaleGeneration


class CourtRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "court" / "records.sqlite3"

    def test_duplicate_event_survives_restart_and_conflict_is_rejected(self):
        with CourtRecords(self.path) as records:
            task = records.create_task("task-1", "example/project", "worker-1")
            event = records.record_event(
                "event-1", "task-1", task["generation"], "worker-1",
                "progress", {"message": "building", "count": 1},
            )
        with CourtRecords(self.path) as records:
            retry = records.record_event(
                "event-1", "task-1", 1, "worker-1", "progress",
                {"count": 1, "message": "building"},
            )
            self.assertEqual(event, retry)
            with self.assertRaises(Conflict):
                records.record_event(
                    "event-1", "task-1", 1, "worker-1", "progress",
                    {"message": "different"},
                )
            self.assertEqual(records.get_event("event-1"), event)

    def test_claim_acknowledges_only_its_actor_and_frozen_event_set(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            records.record_event("event-1", "task-1", 1, "worker-1", "progress", {})
            claim = records.claim_events("secretary-1", "task-1", limit=1)
            records.record_event("event-2", "task-1", 1, "worker-1", "progress", {})
            with self.assertRaises(Conflict):
                records.ack_events(claim["claim_id"], "secretary-2", ["event-1"])
            with self.assertRaises(Conflict):
                records.ack_events(claim["claim_id"], "secretary-1", ["event-1", "event-2"])
            self.assertIsNone(records.get_event("event-1")["processed_at"])
        with CourtRecords(self.path) as records:
            self.assertEqual(records.claim_events("secretary-1", "task-1"), claim)
            records.ack_events(claim["claim_id"], "secretary-1", ["event-1"])
            records.ack_events(claim["claim_id"], "secretary-1", ["event-1"])
            self.assertIsNotNone(records.get_event("event-1")["processed_at"])
            self.assertIsNone(records.get_event("event-2")["processed_at"])
            next_claim = records.claim_events("secretary-2", "task-1")
            self.assertEqual(next_claim["event_ids"], ["event-2"])

    def test_reassignment_fences_old_writers_and_claims_without_losing_events(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            original = records.record_event("event-1", "task-1", 1, "worker-1", "progress", {})
            old_claim = records.claim_events("secretary-1", "task-1")
            updated = records.assign_task("task-1", "worker-2", expected_generation=1)
            self.assertEqual(updated["generation"], 2)
            with self.assertRaises(StaleGeneration):
                records.assign_task("task-1", "worker-3", expected_generation=1)
            with self.assertRaises(StaleGeneration):
                records.record_event("event-2", "task-1", 1, "worker-1", "progress", {})
            with self.assertRaises(Conflict):
                records.record_event("event-2", "task-1", 2, "worker-1", "progress", {})
            with self.assertRaises(StaleGeneration):
                records.ack_events(old_claim["claim_id"], "secretary-1", ["event-1"])
            self.assertEqual(records.record_event("event-1", "task-1", 1, "worker-1", "progress", {}), original)
            new_claim = records.claim_events("secretary-2", "task-1")
            self.assertEqual(new_claim["generation"], 2)
            self.assertEqual(new_claim["event_ids"], ["event-1"])
            records.ack_events(new_claim["claim_id"], "secretary-2", ["event-1"])
            self.assertIsNone(records.claim_events("secretary-2", "task-1"))

    def test_outcome_presentation_is_not_processing_and_survives_restart(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            outcome = records.record_outcome("outcome-1", "task-1", {"result": "review needed"}, recipient="queen-1")
            presentation = records.present_outcomes("queen-1", limit=1)
            self.assertIsNone(records.present_outcomes("queen-2"))
            self.assertIsNone(records.get_outcome("outcome-1")["processed_at"])
        with CourtRecords(self.path) as records:
            self.assertEqual(records.present_outcomes("queen-1"), presentation)
            self.assertEqual(records.record_outcome("outcome-1", "task-1", {"result": "review needed"}, recipient="queen-1"), outcome)
            with self.assertRaises(Conflict):
                records.record_outcome("outcome-1", "task-1", {"result": "changed"}, recipient="queen-1")
            records.record_outcome("outcome-2", "task-1", {"result": "new result"}, recipient="queen-1")
            with self.assertRaises(Conflict):
                records.process_outcomes(presentation["presentation_id"], "queen-2", ["outcome-1"])
            with self.assertRaises(Conflict):
                records.process_outcomes(presentation["presentation_id"], "queen-1", ["outcome-1", "outcome-2"])
            self.assertIsNone(records.get_outcome("outcome-1")["processed_at"])
            records.process_outcomes(presentation["presentation_id"], "queen-1", ["outcome-1"])
            records.process_outcomes(presentation["presentation_id"], "queen-1", ["outcome-1"])
            self.assertEqual(records.present_outcomes("queen-1")["outcome_ids"], ["outcome-2"])

    def test_pending_decision_survives_progress_done_and_outcome_processing(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            decision = records.open_decision("decision-1", "task-1", {"question": "Which format?"})
            for index, kind in enumerate(("progress", "done")):
                records.record_event(f"event-{index}", "task-1", 1, "worker-1", kind, {"claimed": "approved"})
            records.record_outcome("outcome-1", "task-1", {"result": "done"})
            shown = records.present_outcomes("queen")
            records.process_outcomes(shown["presentation_id"], "queen", shown["outcome_ids"])
        with CourtRecords(self.path) as records:
            self.assertEqual(records.get_decision("decision-1"), decision)
            self.assertEqual(records.get_decision("decision-1")["state"], "pending")
            answered = records.answer_decision(
                "decision-1", {"format": "csv"}, expected_revision=1, owner_message="owner-message-1",
            )
            self.assertEqual(answered["state"], "answered")
            self.assertEqual(answered["owner_message"], "owner-message-1")
            self.assertEqual(records.answer_decision(
                "decision-1", {"format": "csv"}, expected_revision=1, owner_message="owner-message-1",
            ), answered)
            with self.assertRaises(Conflict):
                records.answer_decision("decision-1", {"format": "json"}, expected_revision=1, owner_message="owner-message-1")

    def test_unknown_operation_survives_restart_and_cannot_be_reprepared(self):
        request = {"message_id": "native-message-1", "text": "continue", "session_id": "worker-1"}
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            prepared = records.prepare_operation("operation-1", "task-1", "send_message", request)
            self.assertEqual(prepared["state"], "prepared")
            records.set_operation_state("operation-1", "in_flight", expected_state="prepared")
            unknown = records.set_operation_state("operation-1", "unknown", expected_state="in_flight", result={"reason": "response lost"})
        with CourtRecords(self.path) as records:
            self.assertEqual(records.get_operation("operation-1"), unknown)
            self.assertEqual(records.prepare_operation("operation-1", "task-1", "send_message", request), unknown)
            with self.assertRaises(Conflict):
                records.prepare_operation("operation-1", "task-1", "send_message", {"text": "changed"})
            with self.assertRaises(Conflict):
                records.set_operation_state("operation-1", "in_flight", expected_state="unknown")
            confirmed = records.set_operation_state("operation-1", "confirmed", expected_state="unknown", result={"native_id": "native-message-1"})
            self.assertEqual(records.set_operation_state("operation-1", "confirmed", expected_state="unknown", result={"native_id": "native-message-1"}), confirmed)
            with self.assertRaises(Conflict):
                records.set_operation_state("operation-1", "failed", expected_state="confirmed")

    def test_task_metadata_is_immutable_until_assignment_compare_and_swap(self):
        metadata = {"brief": "Inspect the export", "source": "a" * 40, "binding": {"workspace": "space-1"}}
        with CourtRecords(self.path) as records:
            task = records.create_task("task-1", "example/project", "worker-1", metadata=metadata)
            self.assertEqual(task["metadata"], metadata)
            with self.assertRaises(Conflict):
                records.create_task("task-1", "example/project", "worker-1", metadata={"brief": "changed"})
            next_task = records.assign_task("task-1", "reviewer-1", expected_generation=1)
            self.assertEqual(next_task["metadata"], metadata)
            changed = records.assign_task("task-1", "worker-2", expected_generation=2, metadata={"source": "b" * 40})
            self.assertEqual(changed["metadata"], {"source": "b" * 40})

    def test_changed_decision_cannot_reuse_an_earlier_answer(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            records.open_decision("decision-1", "task-1", {"generation": 1, "question": "Use CSV?"})
            records.answer_decision("decision-1", {"yes": True}, expected_revision=1, owner_message="message-1")
            current = records.revise_decision("decision-1", {"generation": 2, "question": "Use JSON?"}, expected_revision=1)
            self.assertEqual(current["revision"], 2)
            self.assertEqual(current["state"], "pending")
            self.assertIsNone(current["answer"])
            old = records.get_decision("decision-1", revision=1)
            self.assertEqual(old["state"], "superseded")
            self.assertEqual(old["answer"], {"yes": True})
            with self.assertRaises(Conflict):
                records.answer_decision("decision-1", {"yes": True}, expected_revision=1, owner_message="message-1")
            with self.assertRaises(Conflict):
                records.revise_decision("decision-1", {"question": "stale"}, expected_revision=1)

    def test_original_decision_creation_replays_without_replacing_later_revisions(self):
        original = {"generation": 1, "question": "Continue?"}
        revised = {"generation": 1, "question": "A clarified question?"}
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            records.open_decision("decision-1", "task-1", original)
            records.revise_decision("decision-1", revised, expected_revision=1)
            current = records.answer_decision("decision-1", {"yes": True}, expected_revision=2, owner_message="message-2")
        with CourtRecords(self.path) as records:
            self.assertEqual(records.open_decision("decision-1", "task-1", original), current)
            self.assertEqual(records.get_decision("decision-1"), current)
            with self.assertRaises(Conflict):
                records.open_decision("decision-1", "task-1", revised)
            with self.assertRaises(Conflict):
                records.open_decision("decision-1", "task-1", {"question": "unrelated"})
            records.create_task("task-2", "example/project", "worker-2")
            with self.assertRaises(Conflict):
                records.open_decision("decision-1", "task-2", original)

    def test_bounded_queries_paginate_and_filter_without_dropping_pending_work(self):
        with CourtRecords(self.path) as records:
            for index in range(3):
                suffix = str(index)
                task_id = "task-" + suffix
                records.create_task(task_id, "example/project", "worker-1")
                records.record_event("event-" + suffix, task_id, 1, "worker-1", "done", {})
                records.record_outcome("outcome-" + suffix, task_id, {})
                records.open_decision("decision-" + suffix, task_id, {})
                records.prepare_operation("operation-" + suffix, task_id, "send_message", {})
            for listing, key in ((records.list_tasks, "task_id"), (records.list_events, "event_id"),
                                 (records.list_outcomes, "outcome_id"), (records.list_decisions, "decision_id"),
                                 (records.list_operations, "operation_id")):
                with self.subTest(listing=listing.__name__):
                    first = listing(limit=2)
                    second = listing(limit=2, offset=2)
                    self.assertEqual(len(first), 2)
                    self.assertEqual(len(second), 1)
                    self.assertEqual(len({item[key] for item in first + second}), 3)
                    self.assertEqual(listing(limit=2, offset=4), [])
                    with self.assertRaises(RecordError):
                        listing(limit=101)
                    with self.assertRaises(RecordError):
                        listing(offset=-1)
            records.answer_decision("decision-0", {}, expected_revision=1, owner_message="message-1")
            records.revise_decision("decision-0", {"new": True}, expected_revision=1)
            self.assertEqual(len(records.list_decisions(task_id="task-0", state="pending")), 1)
            self.assertEqual(records.list_decisions(state="answered"), [])
            records.set_operation_state("operation-0", "in_flight", expected_state="prepared")
            self.assertEqual(len(records.list_operations(states=["prepared"])), 2)
            self.assertEqual(len(records.list_events(task_id="task-1", processed=False)), 1)
            self.assertEqual(records.list_outcomes(recipient="another-queen"), [])
            for index in range(101):
                records.open_decision(f"additional-{index:03}", "task-0", {})
            self.assertEqual(len(records.list_decisions(task_id="task-0", state="pending")), 100)
            self.assertEqual(len(records.list_decisions(task_id="task-0", state="pending", offset=100)), 2)

    def test_send_admission_is_exclusive_and_assignment_is_fenced_until_reconciled(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            records.prepare_operation("operation-1", "task-1", "send_message", {"generation": 1})
            records.set_operation_state("operation-1", "in_flight", expected_state="prepared")
            with self.assertRaises(Conflict):
                records.set_operation_state("operation-1", "in_flight", expected_state="prepared")
            with self.assertRaises(Conflict):
                records.assign_task("task-1", "worker-2", expected_generation=1)
            records.set_operation_state("operation-1", "unknown", expected_state="in_flight")
            with self.assertRaises(Conflict):
                records.assign_task("task-1", "worker-2", expected_generation=1)
            records.set_operation_state("operation-1", "confirmed", expected_state="unknown")
            records.prepare_operation("operation-2", "task-1", "send_message", {"generation": 1})
            records.assign_task("task-1", "worker-2", expected_generation=1)
            with self.assertRaises(StaleGeneration):
                records.set_operation_state("operation-2", "in_flight", expected_state="prepared")
            self.assertEqual(records.get_operation("operation-2")["state"], "prepared")

    def test_decision_delivery_is_fenced_against_revision_and_pending_answers(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            records.open_decision("decision-1", "task-1", {"question": "Continue?"})
            request = {"generation": 1, "decision_id": "decision-1", "decision_revision": 1}
            records.prepare_operation("operation-1", "task-1", "send_message", request)
            with self.assertRaises(Conflict):
                records.set_operation_state("operation-1", "in_flight", expected_state="prepared")
            records.answer_decision("decision-1", {"yes": True}, expected_revision=1, owner_message="message-1")
            records.set_operation_state("operation-1", "in_flight", expected_state="prepared")
            with self.assertRaises(Conflict):
                records.revise_decision("decision-1", {"question": "Change scope?"}, expected_revision=1)
            records.set_operation_state("operation-1", "unknown", expected_state="in_flight")
            with self.assertRaises(Conflict):
                records.revise_decision("decision-1", {"question": "Change scope?"}, expected_revision=1)
            records.set_operation_state("operation-1", "confirmed", expected_state="unknown")
            records.prepare_operation("operation-2", "task-1", "send_message", request)
            records.revise_decision("decision-1", {"question": "Change scope?"}, expected_revision=1)
            with self.assertRaises(Conflict):
                records.set_operation_state("operation-2", "in_flight", expected_state="prepared")
            for invalid in ({"decision_id": "decision-1"}, {"decision_revision": 1},
                            {"decision_id": "../escape", "decision_revision": 1},
                            {"decision_id": "decision-1", "decision_revision": True}):
                with self.assertRaises(RecordError):
                    records.prepare_operation("invalid", "task-1", "send_message", invalid)
            records.create_task("task-2", "example/project", "worker-2")
            with self.assertRaises(Conflict):
                records.prepare_operation("cross-task", "task-2", "send_message", request)

    def test_existing_records_are_validated_as_data_and_foreign_schema_is_rejected(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
        with sqlite3.connect(self.path) as raw:
            raw.execute("UPDATE tasks SET owner = '../untrusted'")
        with CourtRecords(self.path) as records:
            with self.assertRaises(RecordError):
                records.get_task("task-1")
        with sqlite3.connect(self.path) as raw:
            raw.execute("UPDATE tasks SET owner = 'worker-1', metadata = ?", ('{"too_big":"' + 'x' * 65536 + '"}',))
        with CourtRecords(self.path) as records:
            with self.assertRaises(RecordError):
                records.get_task("task-1")
        with sqlite3.connect(self.path) as raw:
            raw.execute("CREATE TRIGGER foreign_behavior AFTER INSERT ON tasks BEGIN DELETE FROM events; END")
        with self.assertRaises(RecordError):
            CourtRecords(self.path)

    def concurrently(self, count, action):
        barrier = Barrier(count)

        def run(index):
            with CourtRecords(self.path) as records:
                barrier.wait(timeout=10)
                try:
                    return action(records, index)
                except Conflict as exc:
                    return exc

        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(run, range(count)))

    def test_concurrent_events_deduplicate_reject_conflicts_and_preserve_distinct_writes(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
        identical = self.concurrently(8, lambda records, index: records.record_event(
            "same-event", "task-1", 1, "worker-1", "progress", {"value": 1},
        ))
        self.assertTrue(all(row == identical[0] for row in identical))
        conflicting = self.concurrently(8, lambda records, index: records.record_event(
            "conflicting-event", "task-1", 1, "worker-1", "progress", {"value": index},
        ))
        self.assertEqual(sum(isinstance(row, Conflict) for row in conflicting), 7)
        distinct = self.concurrently(8, lambda records, index: records.record_event(
            f"event-{index}", "task-1", 1, "worker-1", "progress", {},
        ))
        self.assertEqual(len({row["sequence"] for row in distinct}), 8)
        with CourtRecords(self.path) as records:
            self.assertEqual(len(records.list_events()), 10)

    def test_concurrent_claims_are_disjoint_and_repeated_actor_claim_is_stable(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            for index in range(10):
                records.record_event(f"event-{index}", "task-1", 1, "worker-1", "progress", {})
        claims = self.concurrently(5, lambda records, index: records.claim_events(f"secretary-{index}", "task-1", limit=2))
        self.assertEqual(len({event for claim in claims for event in claim["event_ids"]}), 10)
        repeated = self.concurrently(5, lambda records, index: records.claim_events("secretary-0", "task-1"))
        self.assertTrue(all(claim["claim_id"] == claims[0]["claim_id"] for claim in repeated))
        with CourtRecords(self.path) as records:
            self.assertIsNone(records.claim_events("secretary-other", "task-1"))

    def test_concurrent_reassignment_and_send_admission_have_one_winner(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            records.prepare_operation("operation-1", "task-1", "send_message", {"generation": 1})
        admission = self.concurrently(8, lambda records, index: records.set_operation_state(
            "operation-1", "in_flight", expected_state="prepared",
        ))
        self.assertEqual(sum(isinstance(row, Conflict) for row in admission), 7)
        with CourtRecords(self.path) as records:
            records.set_operation_state("operation-1", "confirmed", expected_state="in_flight")
            records.prepare_operation("operation-2", "task-1", "send_message", {"generation": 1})
        race = self.concurrently(2, lambda records, index: (
            records.assign_task("task-1", "worker-2", expected_generation=1) if index == 0
            else records.set_operation_state("operation-2", "in_flight", expected_state="prepared")
        ))
        self.assertEqual(sum(isinstance(row, Conflict) for row in race), 1)
        with CourtRecords(self.path) as records:
            operation = records.get_operation("operation-2")
            if operation["state"] == "in_flight":
                self.assertEqual(records.get_task("task-1")["generation"], 1)
                records.set_operation_state("operation-2", "confirmed", expected_state="in_flight")
            generation = records.get_task("task-1")["generation"]
        assignments = self.concurrently(8, lambda records, index: records.assign_task(
            "task-1", f"worker-{index + 3}", expected_generation=generation,
        ))
        self.assertEqual(sum(isinstance(row, StaleGeneration) for row in assignments), 7)

    def test_concurrent_decision_revision_and_answer_admission_have_one_winner(self):
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            records.open_decision("decision-1", "task-1", {"question": "Continue?"})
            records.answer_decision("decision-1", {"yes": True}, expected_revision=1, owner_message="message-1")
            records.prepare_operation("operation-1", "task-1", "send_message", {
                "generation": 1, "decision_id": "decision-1", "decision_revision": 1,
            })
        results = self.concurrently(2, lambda records, index: (
            records.revise_decision("decision-1", {"question": "Change scope?"}, expected_revision=1)
            if index == 0 else records.set_operation_state("operation-1", "in_flight", expected_state="prepared")
        ))
        self.assertEqual(sum(isinstance(row, Conflict) for row in results), 1)
        with CourtRecords(self.path) as records:
            operation = records.get_operation("operation-1")
            decision = records.get_decision("decision-1")
            if operation["state"] == "in_flight":
                self.assertEqual((decision["revision"], decision["state"]), (1, "answered"))
            else:
                self.assertEqual((decision["revision"], decision["state"]), (2, "pending"))

    def test_abrupt_process_exit_preserves_committed_work_and_unknown_effects(self):
        script = """
import os, sys
from monarchy.records import CourtRecords
records = CourtRecords(sys.argv[1])
records.create_task('task-1', 'example/project', 'worker-1')
records.record_event('event-1', 'task-1', 1, 'worker-1', 'progress', {})
records.record_outcome('outcome-1', 'task-1', {})
records.open_decision('decision-1', 'task-1', {'question': 'Continue?'})
records.prepare_operation('operation-1', 'task-1', 'send_message', {'generation': 1})
records.set_operation_state('operation-1', 'in_flight', expected_state='prepared')
os._exit(17)
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        with CourtRecords(self.path) as records:
            self.assertEqual(records.claim_events("secretary", "task-1")["event_ids"], ["event-1"])
            self.assertEqual(records.present_outcomes("queen")["outcome_ids"], ["outcome-1"])
            self.assertEqual(records.get_decision("decision-1")["state"], "pending")
            self.assertEqual(records.get_operation("operation-1")["state"], "in_flight")
            with self.assertRaises(Conflict):
                records.set_operation_state("operation-1", "in_flight", expected_state="prepared")

    def test_invalid_input_is_bounded_and_database_permissions_are_private(self):
        nested = {}
        for _ in range(18):
            nested = {"nested": nested}
        invalid_payloads = [{"text": "x" * 65536}, {"bad": float("nan")}, {"bad": object()},
                            {"bad": 2**64}, {"bad": "\ud800"}, {"many": [0] * 5000}, nested]
        with CourtRecords(self.path) as records:
            records.create_task("task-1", "example/project", "worker-1")
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
            for payload in invalid_payloads:
                with self.subTest(payload_type=type(payload).__name__), self.assertRaises(RecordError):
                    records.record_event("bad-event", "task-1", 1, "worker-1", "progress", payload)
            for identifier in ("../path", "", "x" * 129, "bad\n", 1):
                with self.assertRaises(RecordError):
                    records.record_event(identifier, "task-1", 1, "worker-1", "progress", {})
            with self.assertRaises(RecordError):
                records.record_event("bad-generation", "task-1", True, "worker-1", "progress", {})
            self.assertEqual(records.list_events(), [])
        os.chmod(self.path, 0o644)
        with self.assertRaises(RecordError):
            CourtRecords(self.path)
        os.chmod(self.path, 0o600)
        link = self.path.with_name("linked.sqlite3")
        link.symlink_to(self.path)
        with self.assertRaises(RecordError):
            CourtRecords(link)


if __name__ == "__main__":
    unittest.main()
