<!--
PROVENANCE
written-by: codex (gpt-5.6-sol, codex-cli 0.154.0) | 2026-10-26 | session public8-fix-20261026
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
END PROVENANCE
```

### examples/config.json

```text
PROVENANCE
written-by: unknown (pre-provenance) | 2026-10-09 | 85e8dc6
END PROVENANCE
```
