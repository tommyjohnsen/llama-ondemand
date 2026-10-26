<!--
PROVENANCE
written-by: codex (gpt-5.6-sol, codex-cli 0.154.0) | 2026-10-26 | session public8-fix-20261026
reviewed-by: claude-code | 2026-10-26 | APPROVE | sha256:17952d79570002508707fe455492cf738ba0b02ce9e2cef4e6853cb95e779a0a | record public8-fix-20261026/llama-ondemand/r1/claude-code (Claude Code 2.1.287)
END PROVENANCE
-->
# Provenance

Every repository file carries a provenance block in the file or, when comments are unsafe, in the ledger below. `written-by` records the original creation provenance, and `modified-by` records each later change and its purpose. `reviewed-by` records an independent review outcome and the canonical content hash. A review counts only for the file content it reviewed; any later change makes it stale until re-reviewed. A release needs current `reviewed-by` lines from grok-build and claude-code, and the author's own review does not count.

Field lines use these formats:

```text
written-by: <agent/model+version> | <YYYY-MM-DD> | <commit or session>
modified-by: <agent/model+version> | <YYYY-MM-DD> | <commit or session> | <one-line what>
reviewed-by: <grok-build|claude-code|codex|local:<model>> | <YYYY-MM-DD> | <APPROVE|APPROVE WITH NITS|REJECT> | sha256:<canonical hash> | <record ref>
```

The sha256 in a reviewed-by line is the SHA-256 of the file's bytes after removing every line that lies inside a PROVENANCE ... END PROVENANCE block and contains `reviewed-by:`. For a file listed only in the ledger it is the SHA-256 of the file's raw bytes.

## Ledger

### LICENSE

```text
PROVENANCE
written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
reviewed-by: claude-code | 2026-10-26 | APPROVE | sha256:98a55bf66ecfdda162f00c3800299f1829b5f16b7ead5a96f61e40599d7b3ff5 | record public8-fix-20261026/llama-ondemand/r1/claude-code (Claude Code 2.1.287)
END PROVENANCE
```

### examples/config.json

```text
PROVENANCE
written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
reviewed-by: claude-code | 2026-10-26 | APPROVE | sha256:7def310f30686bbafdfec1ef0f3844abb76b6db4d12e944e4ae90e7ebc47c596 | record public8-fix-20261026/llama-ondemand/r1/claude-code (Claude Code 2.1.287)
END PROVENANCE
```
