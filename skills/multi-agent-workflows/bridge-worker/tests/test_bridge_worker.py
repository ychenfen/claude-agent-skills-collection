"""CLI and evidence regressions; all bridge roots and writes stay in this workspace."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from bw_common import atomic_json, atomic_write, file_sha256
from bw_verify import compare_value, json_pointer, verify_delivery


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".bw-test-", dir=str(ROOT))
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.roots = {1: self.work / "bridge1", 2: self.work / "bridge2"}
        for root in self.roots.values():
            (root / "inbox").mkdir(parents=True)
        overrides = {"BW_BRIDGE_ROOT_1": str(self.roots[1]), "BW_BRIDGE_ROOT_2": str(self.roots[2]),
                     "PYTHONDONTWRITEBYTECODE": "1"}
        self.environment_patch = patch.dict(os.environ, overrides)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)
        self.env = os.environ.copy()
        self.delivery_path = self.work / "delivery.json"
        self.data = {"schema": "bridge-delivery/1", "task_id": "test", "channel": 1, "status": "ok",
                     "claims": [], "artifacts": [], "commands": [], "deviations": [],
                     "pending_confirmation": [], "labels": {"human_reviewed": False},
                     "fallbacks": [], "resources": [], "unverified": []}

    def cli(self, script, *args, **kwargs):
        return subprocess.run([sys.executable, str(SCRIPTS / script)] + [str(a) for a in args],
                              cwd=str(self.work), env=self.env, capture_output=True, text=True,
                              timeout=kwargs.pop("timeout", 25), **kwargs)

    def save(self):
        atomic_json(self.delivery_path, self.data)

    def verify(self, strict=False):
        self.save()
        return verify_delivery(self.delivery_path, strict=strict)

    def assertFailure(self, result, text):
        self.assertGreater(result.failed, 0, result.as_dict())
        self.assertTrue(any(row["level"] == "FAIL" and text in row["reason"] for row in result.results), result.as_dict())

    def artifact(self, name, contents):
        path = self.work / name
        atomic_write(path, contents)
        self.data["artifacts"].append({"path": name, "sha256": file_sha256(path)})
        return path

    def claim(self, value="1.24", actual="1.245"):
        atomic_write(self.work / "source.json", '{"number":' + actual + '}\n')
        self.data["claims"] = [{"id": "score", "value": value, "source": {
            "path": "source.json", "kind": "json", "pointer": "/number"}}]

    def report(self, text):
        self.artifact("report.md", text)
        self.data["report"] = "report.md"

    def receipt_path(self):
        return self.roots[self.data["channel"]] / "outbox" / ("res_" + self.data["task_id"] + ".json")


class VerifyTests(WorkspaceTest):
    def test_artifact_sha_mismatch(self):
        self.artifact("output.txt", "original")
        atomic_write(self.work / "output.txt", "changed")
        self.assertFailure(self.verify(), "SHA-256 mismatch")

    def test_missing_artifact(self):
        self.data["artifacts"] = [{"path": "absent", "sha256": "a" * 64}]
        self.assertGreater(self.verify().failed, 0)

    def test_claim_value_mismatch(self):
        self.claim("1.25", "1.230")
        self.assertFailure(self.verify(), "not '1.25'")

    def test_rounding_places_and_modes(self):
        for expected, actual, mode in (("1.24", "1.245", "ROUND_HALF_EVEN"),
                                       ("1.25", "1.245", "ROUND_HALF_UP"),
                                       ("1.240", "1.2404", "ROUND_HALF_EVEN"),
                                       ("2", "2.5", "ROUND_HALF_EVEN"),
                                       ("-1.25", "-1.245", "ROUND_HALF_UP"),
                                       ("9007199254740993", "9007199254740993", "ROUND_HALF_EVEN")):
            with self.subTest(expected=expected):
                self.claim(expected, actual)
                result = self.verify()
                self.assertEqual(result.failed, 0, result.as_dict())
                self.assertTrue(any(mode in row["reason"] for row in result.results))
        self.claim("1.240", "1.245")
        self.assertGreater(self.verify().failed, 0)

    def test_numeric_nonfinite_and_string_equality(self):
        self.assertEqual(compare_value("ready", "ready"), "string equality")
        for actual, expected in (("wrong", "ready"), ("nan", "NaN"), ("Infinity", "2")):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                compare_value(actual, expected)

    def test_json_pointer_rfc6901_and_root(self):
        document = {"a/b": {"~": [7]}, "": "empty"}
        self.assertEqual(json_pointer(document, "/a~1b/~0/0"), 7)
        self.assertEqual(json_pointer(document, "/"), "empty")
        self.assertIs(json_pointer(document, ""), document)
        for pointer in ("/a~2b", "/a~1b/~0/01", "/a~1b/~0/-"):
            with self.subTest(pointer=pointer), self.assertRaises((ValueError, KeyError)):
                json_pointer(document, pointer)

    def test_csv_unique_and_text_capture(self):
        atomic_write(self.work / "data.csv", "key,value\na,1.245\nb,7\n")
        atomic_write(self.work / "data.txt", "score=1.245\n")
        self.data["claims"] = [
            {"id": "csv", "value": "1.25", "source": {"path": "data.csv", "kind": "csv", "where": {"key": "a"}, "column": "value"}},
            {"id": "text", "value": "1.24", "source": {"path": "data.txt", "kind": "text", "regex": r"^score=(?P<n>[\d.]+)$", "group": "n"}},
        ]
        self.assertEqual(self.verify().failed, 0)
        atomic_write(self.work / "data.csv", "key,value\na,1.245\na,1.245\n")
        self.assertFailure(self.verify(), "matched 2 rows")
        atomic_write(self.work / "data.csv", "key,value\nb,1.245\n")
        self.assertFailure(self.verify(), "matched 0 rows")
        atomic_write(self.work / "data.txt", "score=1.245\nscore=1.245\n")
        self.assertFailure(self.verify(), "matched 2 places")

    def test_unregistered_report_number_has_line(self):
        self.report("Results\nThe score is 6.70.\n")
        self.assertFailure(self.verify(), "line 2: 6.70")

    def test_chinese_adjacent_numbers_are_scanned(self):
        self.report("日期2026-11-10，时间12:34:56。\n准确率0.85，共120行。\n")
        result = self.verify()
        self.assertFailure(result, "line 2: 0.85")
        self.assertFailure(result, "line 2: 120")
        self.data["report_exempt_numbers"] = ["0.85", "120"]
        self.assertEqual(self.verify().failed, 0)

    def test_report_skips_code_hex_dates_timestamps(self):
        self.report("Date 2026-11-10T12:30:05.100Z, time 23:59:00.\n"
                    "Hex 0x12345 and abcdef1234567890.\n"
                    "`123.456` and ``789.01``.\n"
                    "```python\nnumber = 654.321\n```\n"
                    "~~~text\n987.65\n~~~\n"
                    "`multiline\n444.55\ncode`\nSmall 7.\n")
        self.assertEqual(self.verify().failed, 0)

    def test_long_integer_is_not_mistaken_for_hex(self):
        self.report("Count 1234567890123456\n")
        self.assertFailure(self.verify(), "1234567890123456")

    def test_report_strict_and_exempt_numbers(self):
        self.report("Trial 7, score 1.24, ratio 12.5%, count 120\n")
        self.claim("1.24")
        self.data["report_exempt_numbers"] = ["12.5", "120"]
        self.assertEqual(self.verify().failed, 0)
        self.assertFailure(self.verify(strict=True), "line 1: 7")
        self.data["report_exempt_numbers"].append("7")
        self.assertEqual(self.verify(strict=True).failed, 0)

    def test_numeric_report_exemptions(self):
        self.report("Count 123, rate 1.25%\n")
        self.data["report_exempt_numbers"] = [123, 1.25]
        self.assertEqual(self.verify().failed, 0)

    def test_report_must_be_artifact(self):
        atomic_write(self.work / "report.md", "No numbers")
        self.data["report"] = "report.md"
        self.assertGreater(self.verify().failed, 0)

    def test_unauthorized_deviation(self):
        self.data["deviations"] = [{"what": "changed endpoint", "why": "busy", "authorized_by": None}]
        self.assertGreater(self.verify().failed, 0)
        self.data["deviations"][0]["authorized_by"] = "Task section 2"
        self.assertEqual(self.verify().failed, 0)

    def test_pending_confirmation_forces_non_ok(self):
        self.data["pending_confirmation"] = ["May I change endpoint?"]
        self.assertGreater(self.verify().failed, 0)
        self.data["status"] = "blocked"
        self.assertEqual(self.verify().failed, 0)

    def test_resources_must_be_released_with_log(self):
        resource = {"kind": "test", "name": "local", "released": False, "evidence_log": None}
        self.data["resources"] = [resource]
        self.assertFailure(self.verify(), "not been released")
        resource["released"] = True
        self.assertFailure(self.verify(), "evidence_log is missing")
        atomic_write(self.work / "release.log", "released\n")
        resource["evidence_log"] = "release.log"
        self.assertEqual(self.verify().failed, 0)

    def test_fallback_count_is_sourced(self):
        self.claim("1.24")
        self.data["fallbacks"] = [{"name": "parse", "count": 1, "source": {"path": "source.json", "kind": "json", "pointer": "/number"}}]
        self.assertEqual(self.verify().failed, 0)
        self.data["fallbacks"][0]["count"] = 2
        self.assertGreater(self.verify().failed, 0)

    def test_killed_command_requires_last_related_success(self):
        atomic_write(self.work / "run.log", "log\n")
        first = {"name": "score", "cmd": ["sleep", "30"], "exit_code": 75, "killed_reason": "stall_timeout", "log_path": "run.log"}
        self.data["commands"] = [first]
        self.assertFailure(self.verify(), "no subsequent successful rerun")
        second = dict(first, cmd=["echo", "done"], exit_code=0, killed_reason=None)
        self.data["commands"].append(second)
        self.assertEqual(self.verify().failed, 0)
        self.data["commands"].append(dict(second, exit_code=1))
        self.assertGreater(self.verify().failed, 0)
        # Matching cmd also works when the name changes or is absent.
        self.data["commands"] = [first, dict(first, name="retry", exit_code=0, killed_reason=None)]
        self.assertEqual(self.verify().failed, 0)

    def test_command_log_and_integer_exit_code_required(self):
        self.data["commands"] = [{"cmd": "echo", "exit_code": True, "log_path": "missing"}]
        self.assertFailure(self.verify(), "exit_code must be an integer")
        self.data["commands"][0]["exit_code"] = 0
        self.assertFailure(self.verify(), "log_path does not exist")

    def test_channel_claim_mismatch_and_missing_warning(self):
        self.assertTrue(any(row["level"] == "WARN" for row in self.verify().results))
        claim = self.roots[1] / "runs" / "test" / "claim.json"
        atomic_json(claim, {"channel": 2})
        self.assertFailure(self.verify(), "channel differs")
        atomic_json(claim, {"channel": 1})
        self.assertEqual(self.verify().failed, 0)

    def test_malformed_schema_reports_failure(self):
        for payload in ([], {}, dict(self.data, status="unknown"), dict(self.data, channel=True),
                        dict(self.data, task_id="../escape"), dict(self.data, claims=[None])):
            with self.subTest(payload=payload):
                atomic_json(self.delivery_path, payload)
                result = self.cli("bw_verify.py", self.delivery_path)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_json_summary_and_usage_exit_code(self):
        self.save()
        summary = self.work / "verify.json"
        result = self.cli("bw_verify.py", self.delivery_path, "--json-out", summary)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(summary.read_text())["failed"], 0)
        self.assertEqual(self.cli("bw_verify.py").returncode, 2)


class ClaimTests(WorkspaceTest):
    def request(self, identifier="first", channel=1, **fields):
        path = self.roots[1] / "inbox" / ("req_" + identifier + ".json")
        atomic_json(path, dict({"id": identifier, "channel": channel}, **fields))
        return path

    def test_prompt_only_request_with_null_files_is_claimable(self):
        # Exact payload shape written by ~/.local/bin/ask-agy for prompt-only requests.
        path = self.roots[1] / "inbox" / "req_100_ab.json"
        atomic_json(path, {"id": "100_ab", "created_at": 1.0, "prompt": "ping",
                           "input_file": None, "output_file": None})
        result = self.cli("bw_claim.py", "--channel", 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = Path(result.stdout.strip().splitlines()[-1])
        metadata = json.loads((run_dir / "claim.json").read_text())
        self.assertTrue(metadata["input_file"].endswith("req_100_ab.json.claimed"))
        self.assertTrue(metadata["output_file"].endswith("outbox/res_100_ab.json"))

    def test_adopt_records_listener_claimed_request_once_and_only_in_own_channel(self):
        claimed = self.roots[1] / "inbox" / "req_200_cd.json.claimed"
        atomic_json(claimed, {"id": "200_cd", "prompt": "ping", "input_file": None, "output_file": None})
        other = self.cli("bw_claim.py", "--channel", 2, "--req-id", "200_cd", "--adopt")
        self.assertEqual(other.returncode, 1)
        first = self.cli("bw_claim.py", "--channel", 1, "--req-id", "200_cd", "--adopt")
        self.assertEqual(first.returncode, 0, first.stderr)
        metadata = json.loads((Path(first.stdout.strip().splitlines()[-1]) / "claim.json").read_text())
        self.assertTrue(metadata["adopted"])
        second = self.cli("bw_claim.py", "--channel", 1, "--req-id", "200_cd", "--adopt")
        self.assertEqual(second.returncode, 1)

    def test_cross_channel_rejected_without_consuming(self):
        request = self.request(channel=2)
        result = self.cli("bw_claim.py", "--channel", 1)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(request.exists())
        self.assertFalse((self.roots[1] / "runs").exists())

    def test_duplicate_claim_fails_and_metadata_matches(self):
        request = self.request()
        expected_sha = file_sha256(request)
        result = self.cli("bw_claim.py", "--channel", 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = Path(result.stdout.strip().splitlines()[-1])
        metadata = json.loads((run_dir / "claim.json").read_text())
        self.assertEqual(metadata["id"], "first")
        self.assertEqual(metadata["channel"], 1)
        self.assertEqual(metadata["input_sha256"], expected_sha)
        self.assertTrue(Path(metadata["input_file"]).exists())
        self.assertIn("claimed_at_utc", metadata)
        self.assertIsInstance(metadata["pid"], int)
        self.assertEqual(self.cli("bw_claim.py", "--channel", 1).returncode, 1)

    def test_oldest_request_and_explicit_id(self):
        old = self.request("old")
        new = self.request("new")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        first = self.cli("bw_claim.py", "--channel", 1)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(first.stdout.strip().endswith("/old"))
        second = self.cli("bw_claim.py", "--channel", 1, "--req-id", "new")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertTrue(second.stdout.strip().endswith("/new"))

    def test_channel_isolation_and_optional_channel_field(self):
        other = self.roots[2] / "inbox" / "req_second.json"
        atomic_json(other, {"id": "second"})
        self.assertEqual(self.cli("bw_claim.py", "--channel", 1).returncode, 1)
        result = self.cli("bw_claim.py", "--channel", 2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().startswith(str(self.roots[2])))

    def test_explicit_input_hash_and_output_path(self):
        input_path = self.work / "task.md"
        atomic_write(input_path, "Task body\n")
        output = self.work / "expected.json"
        self.request(input_file=str(input_path), output_file=str(output))
        result = self.cli("bw_claim.py", "--channel", 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = json.loads((Path(result.stdout.strip()) / "claim.json").read_text())
        self.assertEqual(metadata["input_sha256"], file_sha256(input_path))
        self.assertEqual(metadata["input_file"], str(input_path))
        self.assertEqual(metadata["output_file"], str(output))

    def test_two_workers_only_one_wins(self):
        self.request()
        command = [sys.executable, str(SCRIPTS / "bw_claim.py"), "--channel", "1"]
        processes = [subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for process in processes:
            process.communicate(timeout=10)
        self.assertEqual(sorted(p.returncode for p in processes), [0, 1])


class RunnerTests(WorkspaceTest):
    def run_command(self, command, hard=8, stall=2, name="job", progress=None, interval=1):
        args = ["--run-dir", self.work / "run", "--name", name, "--hard-timeout", hard,
                "--stall-timeout", stall, "--heartbeat-interval", interval]
        for path in progress or []:
            args += ["--progress-file", path]
        return self.cli("bw_run.py", *(args + ["--"] + command))

    def heartbeat(self):
        return json.loads((self.work / "run" / "heartbeat.json").read_text())

    def records(self):
        return [json.loads(line) for line in (self.work / "run" / "commands.jsonl").read_text().splitlines()]

    def test_stall_timeout_sleep_returns_75(self):
        result = self.run_command(["/bin/sleep", "30"], stall=2, interval=1)
        self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
        heartbeat = self.heartbeat()
        self.assertEqual(heartbeat["state"], "killed_stall")
        self.assertGreaterEqual(heartbeat["elapsed_s"], 2)
        self.assertEqual(heartbeat["progress_bytes"], 0)
        self.assertEqual(self.records()[-1]["exit_code"], 75)
        self.assertEqual(self.records()[-1]["killed_reason"], "stall_timeout")
        with self.assertRaises(ProcessLookupError):
            os.kill(heartbeat["pid"], 0)

    def test_hard_timeout_returns_124(self):
        result = self.run_command(["/bin/sleep", "30"], hard=0.5, stall=5)
        self.assertEqual(result.returncode, 124, result.stdout + result.stderr)
        self.assertEqual(self.heartbeat()["state"], "killed_timeout")
        self.assertEqual(self.records()[-1]["killed_reason"], "hard_timeout")

    def test_growing_progress_file_avoids_stall(self):
        progress = self.work / "progress.bin"
        code = ("import sys,time; sys.path.insert(0,sys.argv[1]); from bw_common import atomic_write; "
                "[(atomic_write(sys.argv[2], b'x'*(i+1)),time.sleep(.4)) for i in range(8)]")
        result = self.run_command([sys.executable, "-c", code, str(SCRIPTS), str(progress)],
                                  hard=8, stall=1.5, progress=[progress, self.work / "not_created"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.heartbeat()["state"], "exited")
        self.assertEqual(self.heartbeat()["progress_bytes"], 8)

    def test_growing_log_avoids_stall(self):
        code = "import time; [(print('progress',flush=True),time.sleep(.35)) for _ in range(6)]"
        result = self.run_command([sys.executable, "-c", code], stall=1.2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(self.heartbeat()["progress_bytes"], 0)

    def test_normal_exit_combined_log_and_atomic_append(self):
        code = "import sys; print('stdout'); print('stderr',file=sys.stderr); sys.exit(7)"
        result = self.run_command([sys.executable, "-c", code])
        self.assertEqual(result.returncode, 7, result.stderr)
        log = self.work / "run" / "job.log"
        self.assertIn("stdout", log.read_text())
        self.assertIn("stderr", log.read_text())
        self.assertEqual(self.records()[0]["log_sha256"], file_sha256(log))
        result = self.run_command([sys.executable, "-c", "print('retry')"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([r["exit_code"] for r in self.records()], [7, 0])
        self.assertIsNone(self.records()[1]["killed_reason"])
        self.assertFalse(list((self.work / "run").glob(".*.running.*")))

    def test_launch_failure_is_recorded(self):
        result = self.run_command([str(self.work / "nonexistent")])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.heartbeat()["state"], "exited")
        self.assertEqual(self.records()[0]["exit_code"], 1)

    def test_wrapper_sigterm_cleans_child_and_records_exit(self):
        command = [sys.executable, str(SCRIPTS / "bw_run.py"), "--run-dir", str(self.work / "run"),
                   "--name", "job", "--hard-timeout", "20", "--stall-timeout", "15", "--", "/bin/sleep", "30"]
        process = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not (self.work / "run" / "heartbeat.json").exists():
                if time.monotonic() > deadline:
                    self.fail("initial heartbeat was not published")
                time.sleep(.02)
            child_pid = self.heartbeat()["pid"]
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 143, stdout + stderr)
            self.assertEqual(self.heartbeat()["state"], "exited")
            self.assertEqual(self.records()[-1]["killed_reason"], "signal_15")
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_timeouts_must_be_positive_and_required(self):
        basic = ["--run-dir", self.work, "--name", "test"]
        for extra in ([], ["--hard-timeout", "2"], ["--hard-timeout", "nan", "--stall-timeout", "2"],
                      ["--hard-timeout", "2", "--stall-timeout", "0"]):
            with self.subTest(extra=extra):
                result = self.cli("bw_run.py", *(basic + extra + ["--", "/bin/sleep", "1"]))
                self.assertEqual(result.returncode, 2, result.stderr)


class RenderFinishTests(WorkspaceTest):
    def test_render_checks_source_and_unknown_id_before_writing(self):
        self.claim()
        self.save()
        template = self.work / "template.md"
        report = self.work / "rendered.md"
        atomic_write(template, "score={{c:score}}\n")
        result = self.cli("bw_render.py", self.delivery_path, template, "-o", report)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report.read_text(), "score=1.24\n")
        self.claim(actual="9.999")
        self.save()
        result = self.cli("bw_render.py", self.delivery_path, template, "-o", report)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(report.read_text(), "score=1.24\n")
        atomic_write(template, "{{c:unknown}}\n")
        result = self.cli("bw_render.py", self.delivery_path, template, "-o", report)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown claim id", result.stderr)

    def test_finish_verification_failure_does_not_write_receipt(self):
        self.claim(actual="9")
        self.save()
        result = self.cli("bw_finish.py", self.delivery_path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(self.receipt_path().exists())

    def test_blocked_and_failed_write_error_receipt(self):
        for status in ("blocked", "failed"):
            with self.subTest(status=status):
                self.data["status"] = status
                self.data["unverified"] = ["Input is missing"]
                self.data["artifacts"] = [{"path": "missing.txt", "sha256": "0" * 64}]
                self.save()
                result = self.cli("bw_finish.py", self.delivery_path)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                receipt = json.loads(self.receipt_path().read_text())
                self.assertEqual(receipt["status"], "error")
                self.assertEqual(receipt["error"], status + ": Input is missing")
                self.assertGreater(receipt["verify"]["failed"], 0)
                self.assertEqual(receipt["delivery_sha256"], file_sha256(self.delivery_path))

    def test_blocked_without_reason_or_invalid_schema_rejected(self):
        self.data["status"] = "blocked"
        self.save()
        self.assertEqual(self.cli("bw_finish.py", self.delivery_path).returncode, 1)
        self.assertFalse(self.receipt_path().exists())
        self.data["pending_confirmation"] = ["Need permission"]
        self.data["schema"] = "wrong"
        self.save()
        self.assertEqual(self.cli("bw_finish.py", self.delivery_path).returncode, 1)
        self.assertFalse(self.receipt_path().exists())

    def test_finish_ok_receipt_in_correct_channel(self):
        self.data["channel"] = 2
        self.claim()
        self.report("Score 1.24\n")
        self.save()
        result = self.cli("bw_finish.py", self.delivery_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(self.receipt_path().read_text())
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["response"], "Score 1.24\n")
        self.assertEqual(receipt["verify"]["failed"], 0)
        self.assertFalse((self.roots[1] / "outbox").exists())

    def test_example_delivery_passes_and_render_matches(self):
        example = ROOT / "templates" / "delivery.example.json"
        result = self.cli("bw_verify.py", example)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        template = ROOT / "templates" / "example" / "report.template.md"
        report = self.work / "example-report.md"
        result = self.cli("bw_render.py", example, template, "-o", report)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(report.read_bytes(), (template.parent / "report.md").read_bytes())


if __name__ == "__main__":
    unittest.main()
