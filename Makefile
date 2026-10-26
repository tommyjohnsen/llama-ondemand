# PROVENANCE
# written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
# modified-by: codex (gpt-5.6-sol, codex-cli 0.154.0) | 2026-10-26 | session public8-fix-20261026 | provenance block added
# reviewed-by: claude-code | 2026-10-26 | APPROVE | sha256:a3e3052c663caf62c7f411894518646e60327f0ca9e57271a209b4ce8bd6a0ed | record public8-fix-20261026/llama-ondemand/r1/claude-code (Claude Code 2.1.287)
# END PROVENANCE
PYTHON ?= python3

.PHONY: test clean

test:
	$(PYTHON) -m unittest discover -s tests -t tests

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
