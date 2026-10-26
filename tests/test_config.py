# PROVENANCE (mirror of .provenance/ledger.jsonl; ledger wins)
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex/gpt-5.6-sol | 2026-10-26 | 4f14980 | provenance block added
# reviewed-by: claude-code/claude-opus-5-5 | 2026-10-26 | APPROVE
# END PROVENANCE
"""Config loading: defaults, validation, env overrides, local vs ssh runner."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_ondemand import config

BASE = {"weights_dir": "~/models", "models": {"qwen": {"file": "qwen.gguf", "role": "workhorse"},
                                              "small": {"file": "small.gguf"}}}


class ConfigTests(unittest.TestCase):
    def test_defaults_and_local_runner(self):
        cfg = config.from_dict(BASE, environ={})
        self.assertEqual(cfg["port"], config.DEFAULTS["port"])
        self.assertEqual(cfg["runner"], ["sh", "-c"])
        self.assertEqual(cfg["state_dir"], "~/.local/state/llama-ondemand")

    def test_ssh_target_becomes_batch_mode_ssh(self):
        cfg = config.from_dict(dict(BASE, ssh="models@gpu-box"), environ={})
        self.assertEqual(cfg["runner"], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "models@gpu-box"])
        custom = ["ssh", "-i", "~/.ssh/key", "-p", "2222", "models@gpu-box"]
        self.assertEqual(config.from_dict(dict(BASE, ssh=custom), environ={})["runner"], custom)

    def test_environment_overrides(self):
        env = {"LLAMA_ONDEMAND_SSH": "me@other", "LLAMA_ONDEMAND_PORT": "9000",
               "LLAMA_ONDEMAND_STATE_DIR": "/tmp/state"}
        cfg = config.from_dict(dict(BASE, ssh="models@gpu-box"), environ=env)
        self.assertEqual((cfg["runner"][-1], cfg["port"], cfg["state_dir"]), ("me@other", 9000, "/tmp/state"))
        self.assertEqual(config.from_dict(dict(BASE, ssh="x@y"), environ={"LLAMA_ONDEMAND_SSH": "local"})["runner"],
                         ["sh", "-c"])
        with self.assertRaises(config.ConfigError):
            config.from_dict(BASE, environ={"LLAMA_ONDEMAND_PORT": "eighty"})

    def test_validation(self):
        bad = [
            {"weights_dir": "/m", "models": {}},
            {"weights_dir": "/m", "models": {"a": {}}},
            {"weights_dir": "/m", "models": {"a": {"file": "dir/a.gguf"}}},
            {"models": {"a": {"file": "a.gguf"}}},
            dict(BASE, port=0),
            dict(BASE, port=True),
            dict(BASE, kind_model={"lint": "missing"}),
            dict(BASE, default_model="missing"),
            dict(BASE, launcher="systemd-run"),
            dict(BASE, server_args=[1]),
            dict(BASE, ssh=42),
            dict(BASE, ssh=["ssh", ""]),
            dict(BASE, idle_second=60),  # a typo is an error, not a silently ignored key
            dict(BASE, server_args=["--host", "0.0.0.0"]),
            dict(BASE, server_args=["--port=9999"]),
            dict(BASE, server_args=["-m", "/other.gguf"]),
            dict(BASE, server_args=["--alias", "x"]),
            dict(BASE, kind_model=["review"]),
            dict(BASE, threads=0),
            dict(BASE, ctx=4096.5),
            dict(BASE, idle_seconds=float("nan")),
            dict(BASE, watch_poll_seconds="15"),
            dict(BASE, job_hold_window="nights"),
            {"weights_dir": "/m", "models": {"bad name": {"file": "a.gguf"}}},
            {"weights_dir": "/m", "models": {"a": {"file": "a.gguf", "role": "boss"}}},
            {"weights_dir": "/m", "models": {"a": {"file": "a.gguf", "reasoning_budget": "lots"}}},
            [],
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(config.ConfigError):
                config.from_dict(data, environ={})

    def test_harmless_server_args_are_allowed(self):
        cfg = config.from_dict(dict(BASE, server_args=["--no-webui", "--flash-attn", "on", "-ngl", "99"]), environ={})
        self.assertEqual(cfg["server_args"][0], "--no-webui")

    def test_default_model(self):
        self.assertEqual(config.default_model(config.from_dict(BASE, environ={})), "qwen")
        self.assertEqual(config.default_model(config.from_dict(dict(BASE, default_model="small"), environ={})),
                         "small")
        no_role = {"weights_dir": "/m", "models": {"b": {"file": "b.gguf"}, "a": {"file": "a.gguf"}}}
        self.assertEqual(config.default_model(config.from_dict(no_role, environ={})), "b")

    def test_load_from_file_and_env_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps(BASE))
            self.assertEqual(config.load(str(path), environ={})["models"]["qwen"]["file"], "qwen.gguf")
            self.assertEqual(config.load(None, environ={"LLAMA_ONDEMAND_CONFIG": str(path)})["port"],
                             config.DEFAULTS["port"])
            with self.assertRaisesRegex(config.ConfigError, "no config"):
                config.load(str(Path(tmp) / "missing.json"), environ={})
            path.write_text("{not json")
            with self.assertRaisesRegex(config.ConfigError, "cannot read"):
                config.load(str(path), environ={})

    def test_example_config_is_valid(self):
        example = Path(__file__).resolve().parent.parent / "examples" / "config.json"
        cfg = config.load(str(example), environ={})
        self.assertIn(config.default_model(cfg), cfg["models"])


if __name__ == "__main__":
    unittest.main()
