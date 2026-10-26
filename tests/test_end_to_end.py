# PROVENANCE (mirror of .provenance/ledger.jsonl; ledger wins)
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex/gpt-5.6-sol | 2026-10-26 | 4f14980 | provenance block added
# END PROVENANCE
"""Real processes, local mode: the CLI starts a stand-in llama-server, chats, and stops only its own server."""
import contextlib
import io
import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_ondemand import cli
from llama_ondemand.host import _http

HERE = Path(__file__).resolve().parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "uses /proc")
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="llama-ondemand-e2e-"))
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        server = bin_dir / "llama-server"
        server.write_text("#!%s\n" % sys.executable + (HERE / "fake_llama_server.py").read_text())
        server.chmod(server.stat().st_mode | stat.S_IXUSR)
        weights = self.tmp / "weights"
        weights.mkdir()
        (weights / "tiny.gguf").write_bytes(b"\0" * 1024)
        self.port = free_port()
        self.cfg_path = self.tmp / "config.json"
        self.cfg_path.write_text(json.dumps({
            "ssh": "local", "port": self.port, "state_dir": str(self.tmp / "state"),
            "server_bin": str(server), "weights_dir": str(weights), "python": sys.executable,
            "headroom_mib": 0, "start_timeout_seconds": 20, "idle_seconds": 300,
            "models": {"tiny": {"file": "tiny.gguf", "role": "workhorse"}},
        }))

    def tearDown(self):
        self.cli("stop")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--config", str(self.cfg_path), *args], stdin=stdin)
        return code, out.getvalue(), err.getvalue()

    def test_start_chat_stop(self):
        code, out, err = self.cli("status")
        self.assertEqual(code, 0, err)
        self.assertFalse(json.loads(out)["up"])
        code, out, err = self.cli("chat", "hello")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "echo: hello")
        st = json.loads(self.cli("status")[1])
        self.assertTrue(st["up"])
        self.assertTrue(st["owned"])
        self.assertEqual(st["model"], "tiny")
        code, out, _ = self.cli("stop")
        self.assertTrue(json.loads(out)["stopped"])
        deadline = time.time() + 10
        while time.time() < deadline and _http("GET", "http://127.0.0.1:%d/health" % self.port)[0] == 200:
            time.sleep(0.2)
        self.assertFalse(json.loads(self.cli("status")[1])["up"])

    def test_a_server_we_did_not_start_is_reused_and_never_stopped(self):
        import subprocess
        proc = subprocess.Popen([str(self.tmp / "bin" / "llama-server"), "--port", str(self.port), "--alias", "tiny"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.terminate)
        deadline = time.time() + 10
        while time.time() < deadline and _http("GET", "http://127.0.0.1:%d/health" % self.port)[0] != 200:
            time.sleep(0.1)
        code, out, err = self.cli("chat", "hi")
        self.assertEqual((code, out.strip()), (0, "echo: hi"), err)
        st = json.loads(self.cli("status")[1])
        self.assertEqual((st["up"], st["owned"]), (True, False))
        stopped = json.loads(self.cli("stop")[1])
        self.assertEqual(stopped, {"stopped": False, "reason": "not_owned"})
        self.assertIsNone(proc.poll())


if __name__ == "__main__":
    unittest.main()
