# Provenance

Generated from `.provenance/ledger.jsonl` by the operator tool; do not edit by hand. The ledger is the record of truth; per-file `PROVENANCE` headers mirror it, and the ledger wins on any disagreement.

Each ledger line is one JSON object with `path`, `blob`, `event` (`written` or `reviewed`), `by` (seat/model, or `unknown (pre-provenance)` for history whose author is not recorded), `date`, and either `commit` (written) or `verdict`, `head` and `record` (reviewed). Verdicts are `APPROVE`, `APPROVE_WITH_NITS` or `REJECT`.

`blob` is the git blob SHA-1 of the file after removing its PROVENANCE header block: the lines from the `PROVENANCE` line through the `END PROVENANCE` line inclusive, plus a directly enclosing `<!--` / `-->` line pair. A review applies only while the file's current `blob` equals the reviewed one; any content change makes it stale. A release needs current reviews from claude-code and grok-build; an author never reviews its own work.

Files tracked: 21 (excluding this summary and `.provenance/`). Inline headers: 19. Ledger-only: 2. Written entries current: 21/21. Current reviews: claude-code 0, grok-build 0. Current REJECTs: 0.

| path | header | written-by (current content) | claude-code | grok-build |
|---|---|---|---|---|
| `.github/workflows/test.yml` | inline | unknown (pre-provenance) | - | - |
| `.gitignore` | inline | unknown (pre-provenance) | - | - |
| `LICENSE` | ledger | unknown (pre-provenance) | - | - |
| `Makefile` | inline | unknown (pre-provenance) | - | - |
| `README.md` | inline | unknown (pre-provenance) | - | - |
| `examples/config.json` | ledger | unknown (pre-provenance) | - | - |
| `llama_ondemand/__init__.py` | inline | unknown (pre-provenance) | - | - |
| `llama_ondemand/__main__.py` | inline | unknown (pre-provenance) | - | - |
| `llama_ondemand/cli.py` | inline | unknown (pre-provenance) | - | - |
| `llama_ondemand/client.py` | inline | codex/gpt-5.6-sol | - | - |
| `llama_ondemand/config.py` | inline | unknown (pre-provenance) | - | - |
| `llama_ondemand/host.py` | inline | codex/gpt-5.6-sol | - | - |
| `llama_ondemand/manager.py` | inline | unknown (pre-provenance) | - | - |
| `pyproject.toml` | inline | unknown (pre-provenance) | - | - |
| `tests/fake_llama_server.py` | inline | unknown (pre-provenance) | - | - |
| `tests/test_cli.py` | inline | unknown (pre-provenance) | - | - |
| `tests/test_client.py` | inline | codex/gpt-5.6-sol | - | - |
| `tests/test_config.py` | inline | unknown (pre-provenance) | - | - |
| `tests/test_end_to_end.py` | inline | unknown (pre-provenance) | - | - |
| `tests/test_host.py` | inline | codex/gpt-5.6-sol | - | - |
| `tests/test_manager.py` | inline | unknown (pre-provenance) | - | - |
