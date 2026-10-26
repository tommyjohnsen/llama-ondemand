# PROVENANCE (mirror of .provenance/ledger.jsonl; ledger wins)
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex/gpt-5.6-sol | 2026-10-26 | 4f14980 | provenance block added
# reviewed-by: claude-code/claude-opus-5-5 | 2026-10-26 | APPROVE
# reviewed-by: grok-build/grok-4.7 | 2026-10-26 | APPROVE
# END PROVENANCE
"""Client-side manager: one helper install, model choice per kind, reuse and swap rules, chat over ssh."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime

from llama_ondemand import host as llama_remote
from llama_ondemand.client import ClientError
from llama_ondemand.manager import LlamaManager, LlamaRefused, LlamaUnavailable, hold_until, parse_until, remote_path
from test_host import FakeWorld

KIND_MODEL = {"lint": "workhorse-12b", "review": "workhorse-12b", "simple-fix": "workhorse-12b",
              "triage": "quick-2b", "commit-msg": "quick-2b", "search": "quick-2b"}
TZ = datetime.timezone(datetime.timedelta(hours=-5))  # the fixtures' "Etc/GMT+5"


class FakeSsh:
    """Runs helper actions in-process against a FakeWorld, as ssh would on the host."""

    def __init__(self, world):
        self.world = world
        self.commands = []
        self.down = False

    def __call__(self, command, stdin="", timeout=60):
        self.commands.append(command)
        if self.down:
            return 255, "", "ssh: connect to host 192.0.2.10 port 22: timed out"
        if "sha256sum" in command:
            return 0, "helper_ok\n", ""
        action = command.rsplit(" ", 1)[1]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            llama_remote.main([action], stdin=io.StringIO(stdin), host_factory=lambda cfg: self.world.host())
        return 0, out.getvalue(), ""

    def actions(self):
        return [c.rsplit(" ", 1)[1] for c in self.commands if c.startswith("python3 ")]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="llama-ondemand-mgr-")
        self.w = FakeWorld(self.tmp)
        self.ssh = FakeSsh(self.w)
        cfg = dict(self.w.cfg, runner=["ssh", "x"], host="model-host", kind_model=KIND_MODEL,
                   state_dir="~/.local/state/llama-ondemand")
        self.m = LlamaManager(cfg, run=self.ssh)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ManagerTests(Base):
    def test_kind_to_model(self):
        for kind in ("lint", "review", "simple-fix"):
            self.assertEqual(self.m.model_for(kind), "workhorse-12b")
        for kind in ("triage", "commit-msg", "search"):
            self.assertEqual(self.m.model_for(kind), "quick-2b")
        with self.assertRaises(LlamaUnavailable):
            self.m.model_for("hard-code")

    def test_helper_installed_once_and_paths_expand_remote_home(self):
        self.m.status()
        self.m.status()
        installs = [c for c in self.ssh.commands if "sha256sum" in c]
        self.assertEqual(len(installs), 1)
        self.assertIn('"$HOME"/.local/state/llama-ondemand', installs[0])
        self.assertEqual(remote_path("/abs/p q"), "'/abs/p q'")

    def test_override_swaps_our_warm_quick_for_workhorse(self):
        self.m.ensure("triage")  # short triage: quick model
        self.assertEqual(self.m.status()["model"], "quick-2b")
        self.m.release()
        st = self.m.ensure("triage", model="workhorse-12b")  # long triage: must be the workhorse, not the warm quick model
        self.assertEqual(st["model"], "workhorse-12b")
        self.assertIn("stop", self.ssh.actions())

    def test_override_refused_when_foreign_quick_holds_the_port(self):
        self.w.server = {"model_id": "small.gguf"}
        with self.assertRaises(LlamaRefused):
            self.m.ensure("triage", model="workhorse-12b")
        self.assertEqual(self.m.ensure("triage")["model"], "quick-2b")  # short triage reuses it

    def test_ensure_model_override(self):
        st = self.m.ensure("triage", model="workhorse-12b")
        self.assertEqual(st["model"], "workhorse-12b")
        self.assertEqual(self.m.ensure("triage", model="nope")["model"], "workhorse-12b")  # unknown -> covered

    def test_ensure_starts_the_kind_model_on_demand(self):
        st = self.m.ensure("lint")
        self.assertTrue(st["up"])
        self.assertEqual(st["model"], "workhorse-12b")
        self.assertEqual(self.ssh.actions(), ["status", "start", "hold"])

    def test_ensure_reuses_foreign_server_only_when_it_covers_the_kind(self):
        self.w.server = {"model_id": "small.gguf"}  # foreign quick model cannot cover lint
        with self.assertRaises(LlamaRefused):
            self.m.ensure("lint")
        self.assertNotIn("start", self.ssh.actions())
        self.w.server = {"model_id": "big.gguf"}  # foreign workhorse covers quick kinds
        st = self.m.ensure("commit-msg")
        self.assertTrue(st["reused"])
        self.assertFalse(st["owned"])
        self.assertEqual(st["model"], "workhorse-12b")

    def test_workhorse_takes_quick_kinds_without_swapping(self):
        self.m.ensure("review")
        st = self.m.ensure("commit-msg")
        self.assertEqual(st["model"], "workhorse-12b")
        self.assertEqual(self.ssh.actions().count("start"), 1)

    def test_our_quick_server_is_swapped_for_workhorse_kinds(self):
        self.m.ensure("search")
        self.m.chat([{"role": "user", "content": "q"}])
        self.m.release()  # the search job finished; its hold is released
        st = self.m.ensure("lint")
        self.assertEqual(st["model"], "workhorse-12b")
        # ensure holds with touch after every start; swap uses stop(only_if_not_busy)
        self.assertEqual([a for a in self.ssh.actions() if a != "hold"],
                         ["status", "start", "chat", "release", "status", "stop", "start"])

    def test_release_is_reference_counted(self):
        a = LlamaManager(self.m.cfg, run=self.ssh)
        b = LlamaManager(self.m.cfg, run=self.ssh)
        a.ensure("lint")
        b.ensure("review")  # second hold on the same workhorse
        self.assertEqual(a.release()["holds"], 1)
        self.assertEqual(a.stop_when_done()["reason"], "busy")  # B still holds it
        self.assertEqual(b.release()["holds"], 0)
        self.assertTrue(a.stop_when_done()["stopped"])

    def test_one_manager_stacks_its_holds(self):
        self.m.ensure("lint")
        self.m.ensure("review")
        self.assertEqual(self.m.release()["holds"], 1)
        self.assertEqual(self.m.stop_when_done()["reason"], "busy")
        self.assertEqual(self.m.release()["holds"], 0)
        self.assertEqual(self.m.release()["released"], None)  # nothing left to release
        self.assertTrue(self.m.stop_when_done()["stopped"])

    def test_late_release_does_not_drop_another_holders_token(self):
        a = LlamaManager(self.m.cfg, run=self.ssh)
        b = LlamaManager(self.m.cfg, run=self.ssh)
        a.ensure("lint")
        self.w.t += 121  # A's hold expired; A is still chatting under busy()
        b.ensure("review")
        self.assertEqual(a.release()["holds"], 1)  # A's expired id is a no-op; B remains
        self.assertEqual(a.stop_when_done()["reason"], "busy")
        self.assertEqual(b.release()["holds"], 0)

    def test_crashed_holder_expires(self):
        self.m.ensure("lint")  # holder never releases
        self.w.t += 121
        self.assertTrue(self.m.stop_when_done()["stopped"])

    def test_release_after_a_job_without_chat_allows_swap(self):
        self.m.ensure("search")
        self.m.release()  # job escalated before chatting; the hold must not block the next swap
        self.assertEqual(self.m.ensure("lint")["model"], "workhorse-12b")

    def test_hold_refuses_when_server_vanished(self):
        self.m.ensure("lint")
        self.w.server = None
        with self.assertRaises(LlamaUnavailable):
            self.m._hold({"model": "workhorse-12b"}, model="workhorse-12b")

    def test_no_swap_under_an_in_flight_request(self):
        self.m.ensure("search")
        self.w.host().touch(ahead=600)
        with self.assertRaises(LlamaUnavailable):
            self.m.ensure("lint")
        self.assertEqual(self.m.status()["model"], "quick-2b")

    def test_start_refusal_raises(self):
        self.w.mem = 1000
        with self.assertRaises(LlamaUnavailable):
            self.m.ensure("lint")

    def test_available(self):
        self.assertTrue(self.m.available())
        self.w.mem = 1000  # workhorse no longer fits; quick still would, but available requires workhorse
        self.assertFalse(self.m.available())
        self.w.server = {"model_id": "small.gguf"}  # an answering server counts as available
        self.assertTrue(self.m.available())
        self.ssh.down = True
        self.assertFalse(LlamaManager(self.m.cfg, run=self.ssh).available())

    def test_idle_stop_through_manager(self):
        self.m.ensure("lint")
        self.assertEqual(self.m.stop_if_idle()["reason"], "busy")  # the job still holds it
        self.m.release()
        self.assertEqual(self.m.stop_if_idle()["reason"], "active")
        self.w.t += 301
        self.assertTrue(self.m.stop_if_idle()["stopped"])
        self.assertFalse(self.m.status()["up"])

    def test_chat_over_ssh(self):
        self.m.ensure("lint")
        r = self.m.chat([{"role": "user", "content": "hi"}], max_tokens=8)
        self.assertEqual(r.text, "ok")
        self.assertEqual(self.w.posts[0][0]["max_tokens"], 8)
        self.w.server = None
        with self.assertRaises(ClientError):
            self.m.chat([])

    def test_unreachable_host(self):
        self.ssh.down = True
        with self.assertRaises(LlamaUnavailable):
            self.m.status()


def local(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp()


WINDOW = {"job_hold_window": {"weekday_from": "19:30", "weekday_until": "07:00"}, "timezone": "Etc/GMT+5"}


class HoldPolicyTests(unittest.TestCase):
    """The optional sharing window through --until: off-hours only, released by the next weekday 07:00."""

    def test_until_parsing(self):
        now = local(2026, 10, 8, 19, 40)  # Thursday
        self.assertEqual(parse_until("23:00", now, TZ), local(2026, 10, 8, 23))
        self.assertEqual(parse_until("07:45", now, TZ), local(2026, 10, 9, 7, 45))  # the next 07:45
        self.assertEqual(parse_until("2026-10-09T06:30", now, TZ), local(2026, 10, 9, 6, 30))  # no offset: tz
        self.assertEqual(parse_until("2026-10-09T11:30:00Z", now, TZ), local(2026, 10, 9, 6, 30))
        self.assertEqual(parse_until("2026-10-09T11:30", now), local(2026, 10, 9, 6, 30))  # default tz: UTC
        with self.assertRaises(ValueError):
            parse_until("tomorrow", now)

    def test_weekday_night_defaults_to_and_caps_at_7am(self):
        now = local(2026, 10, 8, 19, 40)
        self.assertEqual(hold_until(WINDOW, None, now), local(2026, 10, 9, 7))
        self.assertEqual(hold_until(WINDOW, "07:00", now), local(2026, 10, 9, 7))
        with self.assertRaisesRegex(ValueError, "past the sharing window"):
            hold_until(WINDOW, "07:01", now)
        self.assertEqual(hold_until(WINDOW, None, local(2026, 10, 9, 6)), local(2026, 10, 9, 7))  # Fri early

    def test_weekends_run_to_monday_7am(self):
        for now in (local(2026, 10, 9, 20), local(2026, 10, 10, 12), local(2026, 10, 11, 23)):  # Fri night, Sat, Sun
            with self.subTest(now=now):
                self.assertEqual(hold_until(WINDOW, None, now), local(2026, 10, 12, 7))

    def test_weekday_hours_are_refused(self):
        for now in (local(2026, 10, 8, 8), local(2026, 10, 8, 12), local(2026, 10, 8, 19, 29)):
            with self.subTest(now=now), self.assertRaisesRegex(ValueError, "reserved for shared use"):
                hold_until(WINDOW, "23:00", now)

    def test_past_until_is_refused_and_no_window_means_no_cap(self):
        now = local(2026, 10, 8, 21)
        with self.assertRaisesRegex(ValueError, "not in the future"):
            hold_until(WINDOW, "2026-10-08T20:00", now)
        self.assertIsNone(hold_until({}, None, local(2026, 10, 8, 12)))


class JobHoldManagerTests(Base):
    def setUp(self):
        super().setUp()
        self.m.cfg = dict(self.m.cfg, **WINDOW)
        self.night = local(2026, 10, 8, 19, 45)

    def test_start_holds_until_the_window_end_and_release_frees_it(self):
        st = self.m.start_job("pilot-8b", "pilot-job", now=self.night)
        self.assertEqual(st["model"], "pilot-8b")
        self.assertEqual(self.m.status()["hold"]["until"], local(2026, 10, 9, 7))
        self.assertEqual(self.m.release_job("pilot-job")["released"], "pilot-job")
        self.assertIsNone(self.m.status()["hold"])

    def test_reviews_wait_while_pilot_is_held(self):
        self.w.t = self.night
        self.m.start_job("pilot-8b", "pilot-job", now=self.night)
        with self.assertRaisesRegex(LlamaUnavailable, "held by job pilot-job") as ctx:
            self.m.ensure("review")
        self.assertNotIsInstance(ctx.exception, LlamaRefused)  # waits; is not sent elsewhere
        self.assertFalse(self.m.available())  # so a scheduler leaves jobs waiting, not failing
        self.m.release_job("pilot-job")
        self.assertTrue(self.m.available())
        self.m.release()
        self.assertEqual(self.m.ensure("review")["model"], "workhorse-12b")  # released: the workhorse swaps back in

    def test_pilot_calls_need_the_holding_job(self):
        self.w.t = self.night
        self.m.start_job("pilot-8b", "pilot-job", now=self.night)
        with self.assertRaisesRegex(LlamaUnavailable, "held by job pilot-job"):
            self.m.ensure("smoke", model="pilot-8b")
        self.assertEqual(self.m.ensure("smoke", model="pilot-8b", job="pilot-job")["model"],
                         "pilot-8b")

    def test_refusals_call_nothing_on_the_host(self):
        for args, msg in (((["pilot-8b", "p"]), "reserved for shared use"), ((["nope", "p"]), "unknown model"),
                          ((["pilot-8b", "a b"]), "--hold")):
            with self.subTest(args=args), self.assertRaisesRegex(LlamaRefused, msg):
                self.m.start_job(*args, now=local(2026, 10, 8, 12) if msg == "reserved for shared use" else self.night)
        self.assertNotIn("start", self.ssh.actions())

    def test_host_refusal_is_raised_with_its_message(self):
        self.w.free = 100
        with self.assertRaisesRegex(LlamaRefused, "free -m shows 100 MiB"):
            self.m.start_job("pilot-8b", "pilot-job", now=self.night)


if __name__ == "__main__":
    unittest.main()
