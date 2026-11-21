import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("monarchy", Path(__file__).parents[1] / "bin/monarchy.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def task(task_id="task-1", repo="example/alpha", session="session-1", pr=7):
    return {"id": task_id, "repo": repo, "workspace_id": "workspace-1", "session_id": session,
            "stage": "Build", "brief": "briefs/task.md", "endpoint": "Reviewed PR", "pr": pr}


def native_session(session="session-1", workspace="workspace-1", status="working"):
    return {"sessionId": session, "workspaceId": workspace, "status": status}


def native_pr(repo="example/alpha", sha="a" * 40, state="open", merged=False):
    return {"number": 7, "base": {"repo": {"full_name": repo}}, "head": {"sha": sha},
            "state": state, "merged": merged}


def result(data, returncode=0):
    return subprocess.CompletedProcess([], returncode, json.dumps(data), "PRIVATE STDERR")


@contextlib.contextmanager
def clock():
    now = [0.0]
    def sleep(seconds):
        now[0] += seconds
    with patch.object(m.time, "monotonic", side_effect=lambda: now[0]), patch.object(m.time, "sleep", side_effect=sleep):
        yield


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.court = self.root / "court.json"
        self.state = self.root / "state.json"
        self.write_court([task()])

    def write_court(self, tasks):
        self.court.write_text(json.dumps({"version": 1, "tasks": tasks}))

    def test_empty_check_needs_no_host_or_github(self):
        self.write_court([])
        with patch.object(subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(m.main(["check", "--court", str(self.court)]), 0)
        run.assert_not_called()
        self.assertEqual(json.loads(out.getvalue()), {"valid": True, "tasks": 0})

    def test_rejects_bad_configuration(self):
        for field, value in (("id", "--help"), ("repo", "example/alpha?x=1"), ("pr", True),
                             ("endpoint", " "), ("session_id", "$(shell)")):
            with self.subTest(field=field):
                row = task()
                row[field] = value
                self.write_court([row])
                with self.assertRaises(m.Invalid):
                    m.load_court(self.court)

    def test_duplicate_task_or_session_rejected(self):
        for second in (task(session="session-2"), task("task-2")):
            self.write_court([task(), second])
            with self.assertRaises(m.Invalid):
                m.load_court(self.court)

    def test_dot_repository_is_supported_without_path_traversal(self):
        self.write_court([task(repo="example/.github")])
        self.assertEqual(m.load_court(self.court)["tasks"][0]["repo"], "example/.github")
        for repo in ("example/..", "example/.", "example/../other"):
            self.write_court([task(repo=repo)])
            with self.assertRaises(m.Invalid):
                m.load_court(self.court)

    def test_single_character_repository_owner_is_supported(self):
        self.write_court([task(repo="x/catalog")])
        self.assertEqual(m.load_court(self.court)["tasks"][0]["repo"], "x/catalog")

    def test_two_repositories_with_same_pr_keep_their_identity(self):
        self.write_court([task(), task("task-2", "example/beta", "session-2")])
        reads = [result(native_session()), result(native_pr()),
                 result(native_session("session-2")), result(native_pr("example/beta"))]
        with patch.object(subprocess, "run", side_effect=reads) as run:
            rows = m.observe(m.load_court(self.court), m.Reader())
        self.assertFalse(rows["task-1"]["errors"])
        self.assertFalse(rows["task-2"]["errors"])
        self.assertEqual(run.call_args_list[1].args[0], ["gh", "api", "repos/example/alpha/pulls/7"])
        self.assertEqual(run.call_args_list[3].args[0], ["gh", "api", "repos/example/beta/pulls/7"])
        self.assertFalse(run.call_args_list[0].kwargs["shell"])
        self.assertEqual(run.call_args_list[0].kwargs["timeout"], 15)

    def test_wrong_native_session_binding_is_an_error(self):
        for data in (native_session("wrong"), native_session(workspace="wrong"), [], {}):
            with self.subTest(data=data), patch.object(subprocess, "run", return_value=result(data)):
                with self.assertRaises(m.Invalid):
                    m.Reader().session(task())

    def test_wrong_or_incomplete_pr_is_an_error(self):
        for data in (native_pr(repo="example/wrong"), native_pr(sha="a" * 8),
                     native_pr(merged=True), {}, []):
            with self.subTest(data=data), patch.object(subprocess, "run", return_value=result(data)):
                with self.assertRaises(m.Invalid):
                    m.Reader().pr(task())

    def test_one_failed_row_does_not_hide_other_tasks_or_prs(self):
        self.write_court([task(), task("task-2", "example/beta", "session-2", None)])
        reads = [result({}, 1), result(native_pr()), result(native_session("session-2", status="idle"))]
        with patch.object(subprocess, "run", side_effect=reads):
            rows = m.observe(m.load_court(self.court), m.Reader())
        self.assertIsNone(rows["task-1"]["session"])
        self.assertEqual(rows["task-1"]["pr"]["head"], "a" * 40)
        self.assertTrue(rows["task-1"]["errors"])
        self.assertEqual(rows["task-2"]["session"], {"status": "idle"})
        self.assertTrue(m.report("snapshot", rows)["degraded"])
        self.assertNotIn("complete", json.dumps(rows))
        self.assertNotIn("PRIVATE", json.dumps(rows))

    def test_transport_failure_never_prints_native_payload(self):
        failures = [result({"token": "SECRET"}, 1),
                    subprocess.CompletedProcess([], 0, "SECRET not json", "PRIVATE")]
        for failure in failures:
            with patch.object(subprocess, "run", return_value=failure), self.assertRaises(m.Invalid) as caught:
                m.Reader().session(task())
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertNotIn("PRIVATE", str(caught.exception))
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("secret", 15)):
            with self.assertRaisesRegex(m.Invalid, "unavailable or timed out"):
                m.Reader().session(task())

    def test_idle_is_attention_not_completion_and_survives_restart(self):
        self.write_court([task(pr=None)])
        with patch.object(subprocess, "run", return_value=result(native_session(status="idle"))), clock():
            first = m.watch(self.court, self.state, 1, 3)
            second = m.watch(self.court, self.state, 1, 3)
        self.assertEqual(first["changes"], [{"task": "task-1", "kind": "initial-attention"}])
        self.assertEqual(second["reason"], "timeout")
        self.assertFalse(second["changes"])
        self.assertNotIn("completed", first)
        self.assertEqual(first["tasks"]["task-1"]["session"], {"status": "idle"})

    def test_initial_busy_run_saves_baseline_and_times_out_healthy(self):
        self.write_court([task(pr=None)])
        with patch.object(subprocess, "run", return_value=result(native_session())), clock():
            output = m.watch(self.court, self.state, 1, 3)
        self.assertEqual(output["reason"], "timeout")
        self.assertFalse(output["degraded"])
        self.assertTrue(self.state.exists())

    def test_timeout_preserves_timestamp_of_last_observation(self):
        self.write_court([task(pr=None)])
        origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with patch.object(subprocess, "run", return_value=result(native_session())) as run, clock(), patch.object(m, "datetime") as dates:
            dates.now.side_effect = lambda tz: origin + timedelta(seconds=m.time.monotonic())
            output = m.watch(self.court, self.state, 600, 600)
            self.assertEqual(m.time.monotonic(), 600)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(output["reason"], "timeout")
        self.assertEqual(output["observed_at"], origin.isoformat())

    def test_changed_head_and_new_binding_wake(self):
        with patch.object(subprocess, "run", side_effect=[result(native_session()), result(native_pr())]):
            before = m.observe(m.load_court(self.court), m.Reader())
        with patch.object(subprocess, "run", side_effect=[result(native_session()), result(native_pr(sha="b" * 40))]):
            after = m.observe(m.load_court(self.court), m.Reader())
        self.assertEqual(m.events(before, after)[0]["kind"], "observation-changed")
        row = task()
        row["endpoint"] = "Verified staging"
        self.write_court([row])
        with patch.object(subprocess, "run", side_effect=[result(native_session()), result(native_pr())]):
            rebound = m.observe(m.load_court(self.court), m.Reader())
        self.assertEqual(m.events(before, rebound)[0]["kind"], "configuration-changed")

    def test_error_recovery_is_a_change(self):
        self.write_court([task(pr=None)])
        with patch.object(subprocess, "run", return_value=result({}, 1)):
            before = m.observe(m.load_court(self.court), m.Reader())
        with patch.object(subprocess, "run", return_value=result(native_session())):
            after = m.observe(m.load_court(self.court), m.Reader())
        self.assertEqual(m.events(before, after)[0]["kind"], "observation-changed")

    def test_repeated_error_is_retained_without_repeated_change(self):
        self.write_court([task(pr=None)])
        with patch.object(subprocess, "run", return_value=result({}, 1)), clock():
            first = m.watch(self.court, self.state, 1, 3)
            repeated = m.watch(self.court, self.state, 1, 3)
        self.assertTrue(first["changes"])
        self.assertFalse(repeated["changes"])
        self.assertTrue(repeated["degraded"])

    def test_state_cannot_cross_courts_or_replace_court(self):
        m.save_state(self.state, self.root / "another.json", {})
        with self.assertRaisesRegex(m.Invalid, "different Monarchy installation"):
            m.watch(self.court, self.state, 1, 1)
        before = self.court.read_bytes()
        with self.assertRaisesRegex(m.Invalid, "different files"):
            m.watch(self.court, self.court, 1, 1)
        self.assertEqual(self.court.read_bytes(), before)

    def test_malformed_state_fails_instead_of_resetting_history(self):
        self.state.write_text("{broken")
        with self.assertRaises(m.Invalid):
            m.watch(self.court, self.state, 1, 1)
        self.assertEqual(self.state.read_text(), "{broken")

    def test_lock_prevents_overlapping_watcher(self):
        with m.state_lock(self.state):
            with self.assertRaisesRegex(m.Invalid, "another watcher"):
                m.watch(self.court, self.state, 1, 1)

    def test_config_reloaded_between_observations(self):
        self.write_court([task(pr=None)])
        def remove_tasks(_):
            self.write_court([])
        with patch.object(subprocess, "run", return_value=result(native_session())), patch.object(m.time, "sleep", side_effect=remove_tasks):
            output = m.watch(self.court, self.state, 0.001, 10)
        self.assertEqual(output["changes"], [{"task": "task-1", "kind": "configuration-changed"}])
        self.assertEqual(output["tasks"], {})

    def test_empty_watch_returns_immediately(self):
        self.write_court([])
        with patch.object(subprocess, "run") as run:
            output = m.watch(self.court, self.state, 30, 600)
        run.assert_not_called()
        self.assertEqual(output["reason"], "empty")

    def test_bad_timing_values_rejected(self):
        for value in ("0", "-1", "nan", "inf", "word"):
            with self.subTest(value=value), self.assertRaises(Exception):
                m.positive_seconds(value)


if __name__ == "__main__":
    unittest.main()
