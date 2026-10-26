<!--
PROVENANCE (mirror of .provenance/ledger.jsonl; ledger wins)
written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
modified-by: codex/gpt-5.6-sol | 2026-10-26 | 4f14980 | provenance block added
END PROVENANCE
-->
# llama-ondemand

Start [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server` when you need it, stop it when it goes idle, and never touch a server you didn't start.

- **On demand.** The first `chat` or `start` launches `llama-server` with the model you asked for. A small watcher stops it after `idle_seconds` without use. Nothing is installed as a service.
- **Local or remote.** Manage a server on this machine, or on another machine over plain `ssh`. The remote side needs only `python3` and the llama.cpp binary. The helper copies itself into the remote state directory and is replaced only when its hash changes.
- **Safe with other users.** A server already answering on the port is reused if it serves a suitable model, but it is never stopped or swapped. Ownership is checked against the recorded PID, the process start time (so a reused PID doesn't count) and the server's own command line.
- **One model at a time, with RAM checks.** A start is refused unless the weights file size plus `headroom_mib` fits in available memory.
- **Stdlib only.** Python 3.10+, Linux (it reads `/proc`), no dependencies.

## Install

```
pip install .
```

## Configure

Copy [`examples/config.json`](examples/config.json) to `~/.config/llama-ondemand/config.json`, or point `--config` or `$LLAMA_ONDEMAND_CONFIG` at it:

```json
{
  "ssh": null,
  "port": 8091,
  "server_bin": "~/llama.cpp/build/bin/llama-server",
  "weights_dir": "~/models",
  "ctx": 8192,
  "threads": 8,
  "server_args": ["--no-webui"],
  "idle_seconds": 300,
  "default_model": "qwen3-8b",
  "models": {
    "qwen3-8b": {"file": "Qwen3-8B-Q4_K_M.gguf", "role": "workhorse"},
    "qwen3-8b-noreason": {"file": "Qwen3-8B-Q4_K_M.gguf", "role": "workhorse", "reasoning_budget": 0},
    "gemma-3-1b": {"file": "gemma-3-1b-it-Q4_K_M.gguf", "role": "quick"}
  },
  "kind_model": {"review": "qwen3-8b", "summarize": "gemma-3-1b"}
}
```

| Key | Meaning |
| --- | --- |
| `ssh` | `null` or `"local"` for this machine; `"user@host"` for ssh with `BatchMode`; or a full argv list such as `["ssh", "-i", "~/.ssh/key", "user@host"]`. |
| `port` | The loopback port `llama-server` listens on, on the model host. |
| `server_bin`, `lib_dir` | The `llama-server` binary (its name must contain `llama-server`), and an optional `LD_LIBRARY_PATH`. |
| `weights_dir`, `models` | Where the GGUF files live on the model host, and the models by name. `file` is a file name under `weights_dir`. |
| `role` | Optional: `workhorse`, `quick` or `pilot`. A `workhorse` model also serves requests for non-workhorse models without a swap; the others are labels. |
| `kind_model` | Optional routing of task kinds to models (`chat --kind review`). |
| `server_args` | Extra `llama-server` flags appended to `-m`, `--host 127.0.0.1`, `--port`, `-t`, `-tb`, `-c`, `-np 1` and `--alias`. Flags that would change the model, address, alias or `/slots` (`-m`, `-hf`, `--host`, `--port`, `--alias`, `--no-slots` and similar) are rejected. |
| `reasoning_budget` | Optional, global or per model. Adds `--reasoning-budget N`. |
| `launcher` | Optional prefix that must `exec` into the server, e.g. `["systemd-run", "--user", "--scope", "-p", "MemoryMax=12G"]`. `{weights_bytes}` is replaced with the weights file size. |
| `headroom_mib`, `min_free_mib` | RAM needed on top of the weights for a start, and for a `--hold` start (checked with `free -m`). |
| `idle_seconds`, `watch_poll_seconds` | When the watcher stops an idle server, and how often it checks. |
| `state_dir` | The helper's state directory on the model host (created with mode 0700). |
| `timezone` | IANA name used for `--until` times and messages (default UTC). |
| `job_hold_window` | Optional `{"weekday_from": "19:30", "weekday_until": "07:00"}`: `--hold` jobs may only run off-hours and on weekends. |
| `python` | Python on the model host (default `python3`). |

Unknown keys are rejected, so a typo fails loudly instead of being ignored.

Environment overrides: `LLAMA_ONDEMAND_SSH` (`user@host` or `local`), `LLAMA_ONDEMAND_PORT`, `LLAMA_ONDEMAND_STATE_DIR`.

## Use

```
llama-ondemand chat "Explain mmap in one paragraph"     # starts the default model if needed
echo "summarize this" | llama-ondemand chat --kind summarize
llama-ondemand chat --model qwen3-8b-noreason --max-tokens 200 --system "Be terse." "..."
llama-ondemand status          # up? which model? did we start it? idle for how long?
llama-ondemand probe           # status plus which models fit in free RAM
llama-ondemand start qwen3-8b  # warm a model; the watcher still stops it when idle
llama-ondemand start qwen3-8b --hold nightly-eval --until 07:00   # pin it for a long job
llama-ondemand release nightly-eval
llama-ondemand stop [--if-idle | --if-not-busy]
```

`chat` prints the answer with `<think>` blocks removed. Use `--show-reasoning` to keep them, `--json` for token counts and speeds, and `--stop-after` to stop the server when nothing else is using it. Exit codes: `0` ok, `1` the server was unavailable or refused, `2` usage or config error.

From Python:

```python
from llama_ondemand import LlamaManager
from llama_ondemand.config import load

m = LlamaManager(load())
m.ensure(None, model="qwen3-8b")      # start or reuse, and hold it until the first chat
try:
    print(m.chat([{"role": "user", "content": "hello"}], max_tokens=64).text)
finally:
    m.release()                       # the idle watcher takes it from here
```

## How idle stop works

When it starts a server, the helper also starts a watcher process next to it. The watcher wakes every `watch_poll_seconds` and stops the server only when all of these hold:

- the server is still the one this tool started (same PID, same start time, same command line);
- no request is in flight (`/slots` reports nothing processing; an unreadable `/slots` answer counts as busy) and no client hold is open;
- nothing has used it for `idle_seconds`;
- no `--hold` job is pinning it.

Every chat stamps the server as in use before it is sent, under a file lock, so the idle stop can't race a request. Client holds expire on their own (`lease_ahead_seconds`), so a client that crashes can't keep a server up forever. When the server goes away for any reason, the watcher exits.

## Guarantee: never touches a server it didn't start

- If something already answers on the port, it is **reused** when it serves a suitable model. Otherwise the request is refused with a clear error.
- `stop`, idle stop and model swaps act only on a server whose recorded owner is `llama-ondemand` and whose live process matches the recorded PID, process start time, port, alias and weights path. Anything else is reported as `not_owned` and left alone.
- Signals are re-checked against that identity before each `SIGTERM` and `SIGKILL`, so a PID reused by another process is never signalled.
- A `--hold` job outranks every stop and swap until it is released or its `--until` passes.

## Tests

```
make test    # or: python3 -m unittest discover -s tests -t tests
```

The suite uses a fake host (fake clock, processes and HTTP). `tests/test_end_to_end.py` also starts a small stand-in `llama-server` as a real process. No GPU, model or network is needed.

## License

MIT. See [LICENSE](LICENSE).
