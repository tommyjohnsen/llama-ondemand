# PROVENANCE (mirror of .provenance/ledger.jsonl; ledger wins)
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex/gpt-5.6-sol | 2026-10-26 | 4f14980 | non-loopback redirect regression test and provenance block added
# reviewed-by: claude-code/claude-opus-5-5 | 2026-10-26 | APPROVE
# END PROVENANCE
"""The host helper: start on demand, reuse any healthy server, stop only ours and only when idle."""
import contextlib
import http.server
import io
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_ondemand import host as llama_remote
from llama_ondemand.host import Host

MIB = 1_048_576


@contextlib.contextmanager
def redirect_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://192.0.2.1/should-not-be-requested")
            self.end_headers()

        def log_message(self, format, *args):
            pass

    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError as exc:
        raise unittest.SkipTest("local sockets unavailable") from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class FakeWorld:
    """A llama host with a fake clock, fake processes and a fake HTTP server."""

    def __init__(self, tmp):
        self.t = 1_000_000.0
        self.procs = {}
        self.starts = {}  # pid -> /proc start time (fake)
        self.next_pid = 4000
        self.server = None  # {"model_id": str, "busy": bool} when something listens on the port
        self.spawned = []
        self.signals = []
        self.mem = 16_000
        self.free = 8_000  # `free -m` available (fake)
        self.posts = []
        self.weights = Path(tmp) / "weights"
        self.weights.mkdir()
        for name, mib in (("big.gguf", 7000), ("small.gguf", 1500), ("pilot.gguf", 5100)):
            with open(self.weights / name, "wb") as fh:
                fh.truncate(mib * MIB)
        self.cfg = {"port": 8091, "state_dir": str(Path(tmp) / "state"),
                    "server_bin": "/opt/llama/llama-server", "lib_dir": "/opt/llama",
                    "launcher": ["/opt/run-capped.sh", "{weights_bytes}"], "timezone": "Etc/GMT+5",
                    "weights_dir": str(self.weights), "ctx": 4096,
                    "threads": 6, "reasoning_budget": 1024, "headroom_mib": 3072, "idle_seconds": 300,
                    "watch_poll_seconds": 15, "start_timeout_seconds": 60, "chat_timeout_seconds": 600,
                    "models": {"workhorse-12b": {"file": "big.gguf", "role": "workhorse"},
                               "quick-2b": {"file": "small.gguf", "role": "quick"},
                               "pilot-8b": {"file": "pilot.gguf", "role": "pilot"},
                               "pilot-8b-noreason": {"file": "pilot.gguf", "role": "pilot",
                                                           "reasoning_budget": 0}}}

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def http(self, method, url, body=None, timeout=5.0):
        if self.server is None:
            return 0, ""
        path = url.split(str(self.cfg["port"]), 1)[1]
        if path == "/health":
            return 200, '{"status": "ok"}'
        if path == "/v1/models":
            return 200, json.dumps({"data": [{"id": self.server["model_id"]}]})
        if path == "/slots":
            return 200, json.dumps([{"id": 0, "is_processing": self.server.get("busy", False)}])
        if path == "/v1/chat/completions":
            self.posts.append((body, self.t))
            return 200, '{"choices": [{"message": {"content": "ok"}}]}'
        return 404, ""

    def spawn(self, argv, env, log):
        pid = self.next_pid
        self.next_pid += 1
        self.procs[pid] = argv
        self.starts[pid] = 50_000 + pid
        self.spawned.append((pid, argv, env))
        if "llama-server" in argv[2] if len(argv) > 2 else False:
            self.server = {"model_id": argv[argv.index("--alias") + 1], "pid": pid}
        return pid

    def alive(self, pid):
        return pid in self.procs

    def kill(self, pid, sig):
        self.signals.append((pid, sig))
        if pid not in self.procs:
            raise ProcessLookupError
        if sig in (signal.SIGTERM, signal.SIGKILL):
            del self.procs[pid]
            if self.server and self.server.get("pid") == pid:
                self.server = None

    def cmdline(self, pid):
        argv = self.procs.get(pid) or []
        return " ".join(str(a) for a in argv)

    def host(self):
        return Host(self.cfg, clock=self.clock, sleep=self.sleep, http=self.http, spawn=self.spawn,
                    pid_alive=self.alive, kill=self.kill, mem_available_mib=lambda: self.mem,
                    self_path="/state/llama_ondemand_host.py", proc_cmdline=self.cmdline, free_mib=lambda: self.free,
                    proc_starttime=lambda pid: self.starts.get(pid) if pid in self.procs else None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="llama-ondemand-")
        self.w = FakeWorld(self.tmp)
        self.h = self.w.host()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class StartTests(Base):
    def test_starts_capped_server_and_watcher_when_nothing_runs(self):
        st = self.h.start("workhorse-12b")
        self.assertTrue(st["up"])
        self.assertFalse(st["reused"])
        self.assertTrue(st["owned"])
        self.assertEqual(st["model"], "workhorse-12b")
        (pid, argv, env), (_, watch, _) = self.w.spawned
        self.assertEqual(argv[0], "/opt/run-capped.sh")
        self.assertEqual(argv[1], str(7000 * MIB))
        for flag, value in (("--host", "127.0.0.1"), ("--port", "8091"), ("-c", "4096"), ("-t", "6")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertNotIn("--no-mmap", argv)
        self.assertEqual(env["LD_LIBRARY_PATH"], "/opt/llama")
        self.assertEqual(watch[1:3], ["/state/llama_ondemand_host.py", "watch"])
        self.assertEqual(os.stat(self.w.cfg["state_dir"]).st_mode & 0o777, 0o700)
        state = json.loads((Path(self.w.cfg["state_dir"]) / "state.json").read_text())
        self.assertEqual(state["server_argv"], argv[2:])
        self.assertEqual(state["server_argv"][0], "/opt/llama/llama-server")
        self.assertEqual((state["pid"], state["pid_start"]), (pid, self.w.starts[pid]))

    def test_refuses_when_ram_is_short(self):
        self.w.mem = 7000 + 3072 - 1
        st = self.h.start("workhorse-12b")
        self.assertFalse(st["up"])
        self.assertIn("ram", st["error"])
        self.assertEqual(self.w.spawned, [])
        self.assertTrue(self.h.start("quick-2b")["up"])

    def test_reuses_a_foreign_server_without_spawning_or_owning_it(self):
        self.w.server = {"model_id": "/opt/other/weights/small.gguf"}
        st = self.h.start("workhorse-12b")
        self.assertTrue(st["up"])
        self.assertTrue(st["reused"])
        self.assertFalse(st["owned"])
        self.assertEqual(st["model"], "quick-2b")
        self.assertEqual(self.w.spawned, [])

    def test_reuses_our_running_server(self):
        self.h.start("quick-2b")
        st = self.h.start("workhorse-12b")
        self.assertTrue(st["reused"])
        self.assertEqual(len(self.w.spawned), 2)

    def test_unknown_model_or_missing_weights(self):
        self.assertIn("unknown", self.h.start("gpt")["error"])
        os.rename(self.w.weights / "small.gguf", self.w.weights / "gone.gguf")
        self.assertIn("missing", self.h.start("quick-2b")["error"])

    def test_server_that_never_gets_healthy_is_stopped(self):
        self.w.http = lambda *a, **k: (0, "")
        h = self.w.host()
        st = h.start("quick-2b")
        self.assertFalse(st["up"])
        self.assertEqual(h.read_state()["status"], "failed")
        self.assertIn(signal.SIGTERM, [s for _, s in self.w.signals])

    def test_unknown_foreign_model_is_named(self):
        self.w.server = {"model_id": "/x/other-7b.gguf"}
        self.assertEqual(self.h.status()["model"], "unknown:other-7b.gguf")



    def test_owned_rejects_pid_reuse(self):
        st = self.h.start("workhorse-12b")
        pid = st["pid"]
        # Replace the process table entry with an unrelated process that kept the PID.
        self.w.procs[pid] = ["/usr/bin/sleep", "3600"]
        self.assertFalse(self.h.owned())
        self.assertEqual(self.h.stop()["reason"], "not_owned")
        self.assertEqual(self.w.signals, [])  # never signalled the impostor


class StopTests(Base):
    def test_never_stops_a_foreign_server(self):
        self.w.server = {"model_id": "small.gguf"}
        self.assertEqual(self.h.stop(), {"stopped": False, "reason": "not_owned"})
        self.assertEqual(self.h.stop(only_if_idle=True)["reason"], "not_owned")
        self.assertEqual(self.w.signals, [])

    def test_idle_stop_waits_for_idle_seconds(self):
        self.h.start("workhorse-12b")
        self.w.t += 299
        self.assertEqual(self.h.stop(only_if_idle=True)["reason"], "active")
        self.w.t += 2
        self.assertTrue(self.h.stop(only_if_idle=True)["stopped"])
        self.assertFalse(self.h.status()["up"])
        self.assertEqual(self.h.read_state()["status"], "stopped")

    def test_busy_server_is_not_idle(self):
        self.h.start("workhorse-12b")
        self.w.server["busy"] = True
        self.w.t += 1000
        self.assertEqual(self.h.stop(only_if_idle=True)["reason"], "busy")
        self.w.server["busy"] = False
        self.assertEqual(self.h.stop(only_if_idle=True)["reason"], "active")  # busy refreshed the clock

    def test_chat_in_flight_blocks_idle_stop(self):
        self.h.start("workhorse-12b")
        self.w.t += 1000
        self.h.touch(ahead=600)
        self.assertEqual(self.h.stop(only_if_idle=True)["reason"], "active")
        self.assertLess(self.h.status()["idle_s"], 0)

    def test_watch_stops_after_idle_and_exits_when_server_gone(self):
        self.h.start("quick-2b")
        out = self.h.watch(max_loops=100)
        self.assertEqual(out["watch"], "stopped_idle")
        self.assertGreaterEqual(out["loops"], 300 // 15)
        self.assertEqual(self.h.watch(max_loops=3)["watch"], "server_gone")

    def test_stubborn_server_gets_sigkill(self):
        self.h.start("quick-2b")
        pid = self.h.read_state()["pid"]
        def stubborn(p, sig):
            self.w.signals.append((p, sig))
            if sig == signal.SIGKILL:
                self.w.procs.pop(p, None)
                self.w.server = None

        self.w.kill = stubborn
        h = self.w.host()
        self.assertTrue(h.stop()["stopped"])
        self.assertEqual([s for p, s in self.w.signals if p == pid][-2:], [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(h.read_state()["status"], "stopped")


class JobHoldTests(Base):
    """llama-ondemand start MODEL --hold JOB [--until]: fakes only, no real server."""

    def held(self, until_in=3600.0, model="pilot-8b", job="pilot-job"):
        st = self.h.start(model, job=job, until=self.w.t + until_in if until_in else None)
        self.assertTrue(st["up"], st)
        return st

    def test_held_start_spawns_and_status_names_holder_and_expiry(self):
        st = self.held()
        self.assertEqual(st["model"], "pilot-8b")
        hold = self.h.status()["hold"]
        self.assertEqual((hold["job"], hold["model"], hold["until"]), ("pilot-job", "pilot-8b",
                                                                         self.w.t + 3600))
        self.assertTrue(hold["until_local"].endswith("-05"))
        argv = self.w.spawned[0][1]
        self.assertEqual(argv[argv.index("-c") + 1], "4096")
        self.assertEqual(argv[argv.index("--host") + 1], "127.0.0.1")
        self.assertNotIn("--no-mmap", argv)

    def test_no_stop_touches_a_held_server(self):
        self.held()
        self.w.t += 3000  # long idle, still inside the hold
        for kwargs in ({}, {"only_if_idle": True}, {"only_if_not_busy": True}):
            with self.subTest(**kwargs):
                out = self.h.stop(**kwargs)
                self.assertEqual((out["stopped"], out["reason"]), (False, "held"))
                self.assertIn("pilot-job", out["detail"])
        self.assertEqual(self.h.watch(max_loops=3)["watch"], "max_loops")
        self.assertIsNotNone(self.w.server)

    def test_noreason_profile_shares_the_weights_with_reasoning_budget_0(self):
        st = self.held(model="pilot-8b-noreason")
        self.assertEqual(st["model"], "pilot-8b-noreason")
        argv = self.w.spawned[0][1]
        self.assertEqual(argv[argv.index("--reasoning-budget") + 1], "0")
        self.assertEqual(argv[argv.index("--alias") + 1], "pilot-8b-noreason")
        self.assertEqual(argv[argv.index("-m") + 1], str(self.w.weights / "pilot.gguf"))
        state = json.loads((Path(self.w.cfg["state_dir"]) / "state.json").read_text())
        self.assertEqual(state["server_argv"], argv[2:])
        self.assertTrue(self.h.owned())
        hold = self.h.status()["hold"]
        self.assertEqual((hold["job"], hold["model"]), ("pilot-job", "pilot-8b-noreason"))

    def test_the_reasoning_profile_is_unchanged(self):
        self.held()
        argv = self.w.spawned[0][1]
        self.assertEqual(argv[argv.index("--reasoning-budget") + 1], "1024")
        self.assertEqual(argv[argv.index("--alias") + 1], "pilot-8b")

    def test_the_holding_job_may_move_its_hold_to_the_noreason_profile(self):
        self.held()
        old = self.w.server["pid"]
        for model, job in (("pilot-8b-noreason", None), ("pilot-8b-noreason", "someone-else")):
            with self.subTest(job=job):
                out = self.h.start(model, job=job, until=self.w.t + 60 if job else None)
                self.assertFalse(out["up"])
                self.assertIn("held by job pilot-job", out["error"])
        self.assertEqual(self.w.signals, [])
        self.w.server["busy"] = True
        out = self.h.start("pilot-8b-noreason", job="pilot-job", until=self.w.t + 7200)
        self.assertFalse(out["up"])
        self.assertIn("busy", out["error"])
        self.w.server["busy"] = False
        out = self.h.start("pilot-8b-noreason", job="pilot-job", until=self.w.t + 7200)
        self.assertTrue(out["up"], out)
        self.assertEqual(out["model"], "pilot-8b-noreason")
        self.assertIn((old, signal.SIGTERM), self.w.signals)
        hold = self.h.status()["hold"]
        self.assertEqual((hold["job"], hold["model"], hold["until"]),
                         ("pilot-job", "pilot-8b-noreason", self.w.t + 7200))
        argv = self.w.spawned[-2][1] if "watch" in self.w.spawned[-1][1] else self.w.spawned[-1][1]
        self.assertEqual(argv[argv.index("--reasoning-budget") + 1], "0")
        out = self.h.stop(only_if_idle=True)
        self.assertEqual((out["stopped"], out["reason"]), (False, "held"))
        # Others are now refused for the new model too, and the holder can move back.
        out = self.h.start("pilot-8b-noreason", job="reviews", until=self.w.t + 60)
        self.assertFalse(out["up"])
        self.assertTrue(self.h.start("pilot-8b", job="pilot-job", until=self.w.t + 7200)["up"])
        self.assertEqual(self.h.status()["hold"]["model"], "pilot-8b")

    def _dead_on_arrival(self, *aliases):
        real = self.w.spawn

        def spawn(argv, env, log):
            pid = real(argv, env, log)
            if "--alias" in argv and argv[argv.index("--alias") + 1] in aliases:
                del self.w.procs[pid]  # crashed while loading
                self.w.server = None
            return pid
        self.w.spawn = spawn
        self.h = self.w.host()

    def test_a_holder_swap_that_cannot_fit_stops_nothing(self):
        self.held()
        pid = self.w.server["pid"]
        self.w.cfg["models"]["pilot-gone"] = {"file": "gone.gguf", "role": "pilot"}
        self.h = self.w.host()
        out = self.h.start("pilot-gone", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("weights missing", out["error"])
        self.w.mem = 3071  # with the 5100 MiB the held server frees: 8171 < 5100 + 3072
        out = self.h.start("pilot-8b-noreason", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("ram:", out["error"])
        self.assertEqual((self.w.signals, self.w.server["pid"]), ([], pid))
        self.assertEqual(self.h.status()["hold"]["model"], "pilot-8b")
        self.w.mem = 3072  # exactly enough once the held server is gone and its memory comes back
        real_kill = self.w.kill

        def kill(pid, sig):
            real_kill(pid, sig)
            self.w.mem += 5100
        self.w.kill = kill
        self.h = self.w.host()
        out = self.h.start("pilot-8b-noreason", job="pilot-job", until=self.w.t + 600)
        self.assertTrue(out["up"], out)
        self.assertEqual(self.h.status()["hold"]["model"], "pilot-8b-noreason")

    def test_a_failed_holder_swap_restores_the_held_model_and_keeps_the_hold(self):
        self.held()
        self._dead_on_arrival("pilot-8b-noreason")
        out = self.h.start("pilot-8b-noreason", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("restored pilot-8b", out["error"])
        self.assertEqual(self.w.server["model_id"], "pilot-8b")
        self.assertTrue(self.h.owned())
        hold = self.h.status()["hold"]
        self.assertEqual((hold["job"], hold["model"]), ("pilot-job", "pilot-8b"))
        argv = [a for _, a, _ in self.w.spawned if "--alias" in a][-1]
        self.assertEqual(argv[argv.index("--reasoning-budget") + 1], "1024")

    def test_a_swap_whose_restore_also_fails_keeps_the_hold_for_a_retry(self):
        self.held()
        self._dead_on_arrival("pilot-8b-noreason", "pilot-8b")
        out = self.h.start("pilot-8b-noreason", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("restoring pilot-8b also failed", out["error"])
        self.assertIsNone(self.w.server)
        self.assertEqual(self.h.status()["hold"]["job"], "pilot-job")
        out = self.h.start("workhorse-12b", job="reviews", until=self.w.t + 60)
        self.assertFalse(out["up"])
        self.assertIn("held by job pilot-job", out["error"])

    def test_a_swap_whose_launch_raises_restores_the_held_model(self):
        self.held()
        real = self.w.spawn
        calls = {"n": 0}

        def spawn(argv, env, log):
            if "watch" in argv and calls["n"] == 0:  # the noreason server spawned, then its watcher fails
                calls["n"] += 1
                raise OSError("watcher spawn failed")
            return real(argv, env, log)
        self.w.spawn = spawn
        self.h = self.w.host()
        out = self.h.start("pilot-8b-noreason", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("OSError: watcher spawn failed", out["error"])
        self.assertIn("restored pilot-8b", out["error"])
        self.assertEqual(self.w.server["model_id"], "pilot-8b")
        noreason = [pid for pid, a, _ in self.w.spawned if "pilot-8b-noreason" in a]
        self.assertEqual(len(noreason), 1)
        self.assertNotIn(noreason[0], self.w.procs)  # the half-started server was stopped
        self.assertTrue(self.h.owned())
        self.assertEqual(self.h.status()["hold"]["model"], "pilot-8b")

    def test_a_failed_launch_never_signals_a_reused_pid(self):
        self.held()
        real = self.w.spawn

        def spawn(argv, env, log):
            if "watch" in argv and any("pilot-8b-noreason" in str(a) for a in self.w.procs.get(self.w.next_pid - 1, [])):
                self.w.starts[self.w.next_pid - 1] += 7  # the server died and its PID was reused, same argv
                raise OSError("watcher spawn failed")
            return real(argv, env, log)
        self.w.spawn = spawn
        self.h = self.w.host()
        out = self.h.start("pilot-8b-noreason", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        reused = [pid for pid, a, _ in self.w.spawned if "pilot-8b-noreason" in a][0]
        self.assertNotIn(reused, [pid for pid, _ in self.w.signals])
        self.assertIn(reused, self.w.procs)

    def test_other_model_or_other_job_is_refused_naming_holder_and_expiry(self):
        self.held()
        for model, job in (("workhorse-12b", "reviews"), ("workhorse-12b", None), ("pilot-8b", "someone-else")):
            with self.subTest(model=model, job=job):
                out = self.h.start(model, job=job, until=self.w.t + 60 if job else None)
                self.assertFalse(out["up"])
                self.assertIn("held by job pilot-job for pilot-8b until ", out["error"])
                self.assertIn("-05", out["error"])
                self.assertIn("llama-ondemand release pilot-job", out["error"])
        self.assertEqual(len([p for p in self.w.spawned if "llama-server" in p[1][2]]), 1)
        self.assertTrue(self.h.start("pilot-8b", job="pilot-job", until=self.w.t + 7200)["up"])
        self.assertEqual(self.h.status()["hold"]["until"], self.w.t + 7200)  # the holder may renew

    def test_an_expired_hold_lets_stop_idle_stop_and_a_start_swap(self):
        self.held(until_in=600)
        self.w.t += 601
        st = self.h.status()
        self.assertIsNone(st["hold"])
        self.assertEqual(st["hold_expired"]["job"], "pilot-job")
        self.assertTrue(self.h.stop(only_if_idle=True)["stopped"])
        self.held(until_in=600)
        old = self.w.server["pid"]
        self.w.t += 601
        out = self.h.start("workhorse-12b", job="reviews", until=self.w.t + 600)  # swap: ours, idle, hold expired
        self.assertTrue(out["up"], out)
        self.assertEqual(out["model"], "workhorse-12b")
        self.assertIn((old, signal.SIGTERM), self.w.signals)

    def test_swap_never_stops_a_server_we_did_not_start(self):
        self.w.server = {"model_id": "/opt/other/weights/small.gguf"}
        out = self.h.start("pilot-8b", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("did not start", out["error"])
        self.assertEqual((self.w.spawned, self.w.signals), ([], []))

    def test_swap_waits_for_a_busy_server(self):
        self.h.start("workhorse-12b")
        self.w.server["busy"] = True
        out = self.h.start("pilot-8b", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("busy", out["error"])
        self.assertEqual(self.w.signals, [])

    def test_release_drops_only_that_jobs_hold_and_leaves_the_server_up(self):
        self.held()
        out = self.h.release_job("someone-else")
        self.assertIsNone(out["released"])
        self.assertEqual(out["hold"]["job"], "pilot-job")
        out = self.h.release_job("pilot-job")
        self.assertEqual((out["released"], out["model"]), ("pilot-job", "pilot-8b"))
        self.assertTrue(out["server"]["up"])
        self.assertIsNone(self.h.status()["hold"])
        self.assertTrue(self.h.stop(only_if_not_busy=True)["stopped"])  # stop-done may stop it now

    def test_held_start_refuses_under_4_gb_free(self):
        self.w.free = 4095
        out = self.h.start("pilot-8b", job="pilot-job", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("free -m shows 4095 MiB available; a held start needs 4096", out["error"])
        self.assertEqual(self.w.spawned, [])
        self.assertIsNone(self.h.status()["hold"])
        self.w.free = 4096
        self.assertTrue(self.h.start("pilot-8b", job="pilot-job", until=self.w.t + 600)["up"])

    def test_bad_job_or_past_until_is_refused(self):
        self.assertIn("bad job", self.h.start("pilot-8b", job="../x", until=self.w.t + 60)["error"])
        self.assertIn("future", self.h.start("pilot-8b", job="p", until=self.w.t - 1)["error"])
        self.assertEqual(self.w.spawned, [])

    def test_swap_never_stops_a_reused_pid_running_someone_elses_server(self):
        self.held(until_in=600)
        pid = self.w.server["pid"]
        self.w.t += 601  # hold lapsed; our state still names pid as our pilot
        self.w.procs[pid] = ["/x", "1", "/other/llama-server", "-m", "/home/x/other.gguf", "--port", "8091",
                             "--alias", "pilot-8b"]  # pid reused by a foreign server on the port
        self.assertFalse(self.h.owned())
        out = self.h.start("workhorse-12b", job="reviews", until=self.w.t + 600)
        self.assertFalse(out["up"])
        self.assertIn("did not start", out["error"])
        self.assertEqual(self.w.signals, [])

    def test_a_reused_pid_with_an_identical_command_line_is_not_ours(self):
        self.h.start("workhorse-12b")
        pid = self.w.server["pid"]
        self.w.starts[pid] += 1  # same pid and argv, but a different process (it started later)
        self.assertFalse(self.h.owned())
        self.assertEqual(self.h.stop()["reason"], "not_owned")
        self.assertFalse(self.h.start("pilot-8b", job="p", until=self.w.t + 600)["up"])
        self.assertEqual(self.w.signals, [])

    def test_terminate_rechecks_the_full_identity_before_each_signal(self):
        self.h.start("workhorse-12b")
        pid = self.w.server["pid"]
        real_kill = self.w.kill

        def reused_after_sigterm(p, sig):  # our server exits on SIGTERM-ignore; the pid comes back foreign
            self.w.signals.append((p, sig))
            if sig == signal.SIGTERM:
                self.w.starts[p] += 7
        self.w.kill = reused_after_sigterm
        self.h = self.w.host()
        self.h._terminate(pid, "workhorse-12b", 50_000 + pid)
        self.assertEqual(self.w.signals, [(pid, signal.SIGTERM)])  # no SIGKILL to the new process
        self.w.kill = real_kill

    def test_only_the_holding_job_may_use_the_held_server(self):
        self.held()
        out = self.h.hold(model="pilot-8b")
        self.assertFalse(out["held"])
        self.assertIn("held by job pilot-job", out["reason"])
        self.assertFalse(self.h.hold(model="pilot-8b", job="other")["held"])
        self.assertTrue(self.h.hold(model="pilot-8b", job="pilot-job")["held"])
        self.w.t += 3601  # lapsed: anyone may use it again
        self.assertTrue(self.h.hold(model="pilot-8b")["held"])

    def test_memory_is_checked_before_reuse_or_swap(self):
        self.h.start("workhorse-12b")
        pid = self.w.server["pid"]
        self.w.free = 4000
        for model in ("pilot-8b", "workhorse-12b"):  # swap, and reuse of the loaded model
            with self.subTest(model=model):
                out = self.h.start(model, job="pilot-job", until=self.w.t + 600)
                self.assertFalse(out["up"])
                self.assertIn("free -m shows 4000 MiB", out["error"])
        self.assertEqual(self.w.server["pid"], pid)  # the running server was not stopped
        self.assertEqual(self.w.signals, [])
        self.assertIsNone(self.h.status()["hold"])

    def test_free_m_parsing(self):
        text = ("               total        used        free      shared  buff/cache   available\n"
                "Mem:           15613        2358        4849           5        8752       13255\n"
                "Swap:              0           0           0\n")
        self.assertEqual(llama_remote._parse_free(text), 13255)
        self.assertEqual(llama_remote._parse_free("garbage"), 0)


class ChatAndMainTests(Base):
    def test_http_refuses_redirect_to_non_loopback(self):
        with redirect_server() as base_url:
            code, body = llama_remote._http("GET", base_url + "/health", timeout=1)
        self.assertEqual(code, 0)
        self.assertEqual(body, "redirect refused (HTTP 302)")

    def test_chat_forces_non_streaming_and_touches(self):
        self.h.start("workhorse-12b")
        self.w.t += 50
        out = self.h.chat({"messages": [], "stream": True})
        self.assertEqual(out["status"], 200)
        self.assertFalse(self.w.posts[0][0]["stream"])
        self.assertAlmostEqual(self.h.status()["idle_s"], 0.0)
        self.assertEqual(self.h.chat("bad")["status"], 0)

    def test_probe_reports_fit_per_model(self):
        self.w.mem = 5000
        self.assertEqual(self.h.probe()["fits"], {"workhorse-12b": False, "quick-2b": True, "pilot-8b": False,
                                                   "pilot-8b-noreason": False})

    def test_main_version_and_bad_input(self):
        out = io.StringIO()
        sys_stdout = sys.stdout
        try:
            sys.stdout = out
            self.assertEqual(llama_remote.main(["version"]), 0)
            self.assertEqual(llama_remote.main(["status"], stdin=io.StringIO("nope")), 2)
            self.assertEqual(llama_remote.main([]), 2)
        finally:
            sys.stdout = sys_stdout
        self.assertEqual(len(json.loads(out.getvalue().splitlines()[0])["sha256"]), 64)

    def test_helper_is_self_contained(self):
        src = Path(llama_remote.__file__).read_text()
        self.assertNotIn("from .", src)
        self.assertNotIn("import llama_ondemand", src)
        self.assertNotIn("from llama_ondemand", src)


class LaunchArgvTests(Base):
    """Without a launcher or lib_dir the server runs as configured, plus server_args, minus a reasoning flag."""

    def test_plain_launch(self):
        for key in ("launcher", "lib_dir", "reasoning_budget"):
            self.w.cfg.pop(key)
        self.w.cfg["server_args"] = ["--no-webui", "--flash-attn", "on"]
        real = self.w.spawn

        def spawn(argv, env, log):  # the fake world keys "is a server" off argv[2]; mimic a two-word launcher
            return real(["", ""] + argv if "llama-server" in argv[0] else argv, env, log)

        self.w.spawn = spawn
        host = self.w.host()
        self.assertTrue(host.start("quick-2b")["up"])
        argv = self.w.spawned[0][1][2:]
        self.assertEqual(argv[0], "/opt/llama/llama-server")
        self.assertNotIn("--reasoning-budget", argv)
        self.assertEqual(argv[-5:], ["--no-webui", "--flash-attn", "on", "--alias", "quick-2b"])
        self.assertNotEqual(self.w.spawned[0][2].get("LD_LIBRARY_PATH"), "/opt/llama")
        state = json.loads((Path(self.w.cfg["state_dir"]) / "state.json").read_text())
        self.assertEqual(state["server_argv"], argv)
        self.assertEqual(state["owner"], "llama-ondemand")

    def test_until_is_shown_in_the_configured_zone(self):
        self.w.cfg["timezone"] = "UTC"
        st = self.w.host().start("pilot-8b", job="j", until=self.w.t + 60)
        self.assertTrue(st["hold"]["until_local"].endswith("UTC"))
        self.w.cfg["timezone"] = "No/Such_Zone"  # unknown names fall back to UTC rather than failing
        self.assertTrue(self.w.host().status()["hold"]["until_local"].endswith("UTC"))


class BusyTests(Base):
    def test_unreadable_slots_count_as_busy_and_no_answer_as_idle(self):
        cases = ((200, "[]", False), (200, '[{"is_processing": true}]', True), (200, "{}", True),
                 (200, "[1]", True), (200, "not json", True), (500, "", True), (501, "", True), (0, "", False))
        for code, body, busy in cases:
            with self.subTest(code=code, body=body):
                host = Host(self.w.cfg, http=lambda *a, _c=code, _b=body, **k: (_c, _b))
                self.assertIs(host.busy(), busy)


if __name__ == "__main__":
    unittest.main()
