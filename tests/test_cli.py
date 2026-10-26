# PROVENANCE (mirror of .provenance/ledger.jsonl; ledger wins)
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex/gpt-5.6-sol | 2026-10-26 | 4f14980 | provenance block added
# END PROVENANCE
"""CLI argument handling against a mocked manager."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_ondemand import cli
from llama_ondemand.client import ChatResult
from llama_ondemand.manager import LlamaRefused

CFG = {"weights_dir": "/m", "models": {"big": {"file": "big.gguf", "role": "workhorse"},
                                       "small": {"file": "small.gguf"}},
       "kind_model": {"triage": "small"}}


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "c.json"
        self.path.write_text(json.dumps(CFG))
        self.mgr = mock.MagicMock()
        self.mgr.chat.return_value = ChatResult("<think>hmm</think>answer", "", 1, 1, 0, 0, 0.1, "stop")
        self.mgr.status.return_value = {"up": False}
        for name in ("ensure", "start_job", "stop", "stop_if_idle", "stop_when_done", "release", "release_job"):
            getattr(self.mgr, name).return_value = {"ok": True}

    def run_cli(self, *args, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(["--config", str(self.path), *args], manager_factory=lambda cfg: self.mgr,
                                stdin=stdin)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_status_and_models(self):
        self.assertEqual(self.run_cli("status")[:2], (0, json.dumps({"up": False}, indent=2) + "\n"))
        code, out, _ = self.run_cli("models")
        self.assertEqual(sorted(json.loads(out)), ["big", "small"])

    def test_start_defaults_to_the_workhorse_and_releases_its_hold(self):
        self.assertEqual(self.run_cli("start")[0], 0)
        self.mgr.ensure.assert_called_once_with(None, model="big")
        self.mgr.release.assert_called_once_with()

    def test_start_with_hold(self):
        self.assertEqual(self.run_cli("start", "small", "--hold", "nightly", "--until", "07:00")[0], 0)
        self.mgr.start_job.assert_called_once_with("small", "nightly", "07:00")

    def test_usage_errors(self):
        self.assertEqual(self.run_cli("start", "small", "--until", "07:00")[0], 2)
        self.assertEqual(self.run_cli("start", "nope")[0], 2)
        self.assertEqual(self.run_cli("chat", "--kind", "lint", "hi")[0], 2)
        self.assertEqual(self.run_cli("chat", "   ")[0], 2)
        self.mgr.ensure.assert_not_called()

    def test_missing_config_is_a_usage_error(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--config", str(self.path) + ".missing", "status"])
        self.assertEqual(code, 2)
        self.assertIn("no config", err.getvalue())

    def test_stop_variants(self):
        self.run_cli("stop")
        self.run_cli("stop", "--if-idle")
        self.run_cli("stop", "--if-not-busy")
        self.mgr.stop.assert_called_once_with()
        self.mgr.stop_if_idle.assert_called_once_with()
        self.mgr.stop_when_done.assert_called_once_with()

    def test_chat_strips_reasoning_and_releases(self):
        code, out, _ = self.run_cli("chat", "--system", "be brief", "--max-tokens", "16", "question")
        self.assertEqual((code, out), (0, "answer\n"))
        self.mgr.ensure.assert_called_once_with(None, model="big", job=None)
        messages = self.mgr.chat.call_args.args[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertEqual(self.mgr.chat.call_args.kwargs, {"max_tokens": 16})
        self.mgr.release.assert_called_once_with()
        self.mgr.stop_when_done.assert_not_called()

    def test_chat_by_kind_from_stdin_and_stop_after(self):
        code, out, _ = self.run_cli("chat", "--kind", "triage", "--stop-after", "--show-reasoning",
                                    stdin=io.StringIO("from stdin"))
        self.assertEqual(out, "<think>hmm</think>answer\n")
        self.mgr.ensure.assert_called_once_with("triage", model=None, job=None)
        self.assertEqual(self.mgr.chat.call_args.args[0][-1]["content"], "from stdin")
        self.mgr.stop_when_done.assert_called_once_with()

    def test_refusal_exits_one(self):
        self.mgr.ensure.side_effect = LlamaRefused("port 8091 is held by a foreign server")
        code, _, err = self.run_cli("chat", "hi")
        self.assertEqual(code, 1)
        self.assertIn("foreign", err)


if __name__ == "__main__":
    unittest.main()
