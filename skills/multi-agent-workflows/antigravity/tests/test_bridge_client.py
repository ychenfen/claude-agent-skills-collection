"""Exercise the published client and worker together, without an IDE or model call."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SKILL = Path(__file__).resolve().parents[1]
WORKER = SKILL.parent / "bridge-worker" / "scripts"


class BridgeClientTests(unittest.TestCase):
    def test_three_channels_claim_verify_and_finish(self):
        for channel in (1, 2, 3):
            with self.subTest(channel=channel), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
                for other in (1, 2, 3):
                    env[f"BW_BRIDGE_ROOT_{other}"] = str(root / f"bridge{other}")
                bridge = root / f"bridge{channel}"
                task = root / "TASK.md"
                task.write_text("Local protocol smoke test; no model execution.\n")
                client = subprocess.Popen(
                    [sys.executable, str(SKILL / "scripts/ask_agy.py"), "--channel", str(channel),
                     "-t", "10", "-i", str(task), "Test receipt"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                )
                try:
                    deadline = time.monotonic() + 5
                    requests = []
                    while not requests and time.monotonic() < deadline:
                        requests = list((bridge / "inbox").glob("req_*.json"))
                        time.sleep(0.02)
                    self.assertEqual(len(requests), 1)
                    request = json.loads(requests[0].read_text())
                    self.assertEqual(request["channel"], channel)
                    claimed = subprocess.run(
                        [sys.executable, str(WORKER / "bw_claim.py"), "--channel", str(channel)],
                        env=env, capture_output=True, text=True, timeout=5,
                    )
                    self.assertEqual(claimed.returncode, 0, claimed.stderr)
                    run_dir = Path(claimed.stdout.strip())
                    artifact = run_dir / "output.txt"
                    artifact.write_text("Protocol round trip verified.\n")
                    delivery = run_dir / "delivery.json"
                    delivery.write_text(json.dumps({
                        "schema": "bridge-delivery/1", "task_id": request["id"], "channel": channel,
                        "status": "ok", "claims": [], "artifacts": [{"path": "output.txt",
                        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}],
                        "commands": [], "deviations": [], "pending_confirmation": [],
                        "labels": {"human_reviewed": False}, "fallbacks": [], "resources": [], "unverified": [],
                    }))
                    for script, extra in [("bw_verify.py", ["--strict"]), ("bw_finish.py", [])]:
                        result = subprocess.run([sys.executable, str(WORKER / script), str(delivery)] + extra,
                                                env=env, capture_output=True, text=True, timeout=5)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    stdout, stderr = client.communicate(timeout=5)
                    self.assertEqual(client.returncode, 0, stderr)
                    self.assertIn("Verified delivery:", stdout)
                    receipt = bridge / "outbox" / f"res_{request['id']}.json"
                    self.assertTrue(receipt.is_file())
                    for other in (1, 2, 3):
                        if other != channel:
                            self.assertFalse((root / f"bridge{other}").exists())
                finally:
                    if client.poll() is None:
                        client.kill()
                    client.communicate()

    def test_timeout_preserves_unclaimed_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, BW_BRIDGE_ROOT_1=temporary)
            result = subprocess.run([sys.executable, str(SKILL / "scripts/ask_agy.py"), "-t", "1", "No worker"],
                                    env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(len(list((Path(temporary) / "inbox").glob("req_*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
