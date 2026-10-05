# Security Policy

## Reporting Security Issues

We take the security of DevAgent seriously. If you discover a vulnerability, please do NOT file a public issue. Instead, report it privately to the maintainers or via GitHub Security Advisories.

Please include:
- A description of the vulnerability and its potential impact.
- Step-by-step instructions to reproduce the issue.
- Any proof-of-concept scripts or commands.

We will acknowledge receipt within 48 hours and work with you to coordinate a safe disclosure.

## Security Architecture & Invariants

DevAgent is built with a defence-in-depth security model to ensure autonomous code analysis and patch execution cannot harm the host system or unauthorized infrastructure:

1. **Docker Sandbox Execution**:
   - Repository code and test suites are executed **only** inside ephemeral `devagent/runner-python:3.12` containers.
   - Sandboxes run with `network_mode=none` by default, blocking external data exfiltration.
   - Read-only root filesystem; non-root user (`runner` uid 1000); dropped capabilities (`CAP_DROP ALL`); `no-new-privileges: true`.
   - The host Docker socket is **never** mounted into API or sandbox containers (only into the isolated worker).

2. **Human-in-the-Loop Approval Gate**:
   - The agent operates in read-only analysis and proposal mode.
   - Before any patch is applied, the task enters `AWAITING_APPROVAL`.
   - Patches are applied to the workspace **only** after an authenticated human issues an explicit `approve` command.

3. **Workspace Path Containment**:
   - All filesystem operations validate relative paths using `ensure_within` / `safe_join` to prevent directory traversal (`../`) attacks.

4. **Credential Scrubbing & Redaction**:
   - Comprehensive regex and key heuristics redact secrets, tokens, API keys, database URLs, and private keys from logs, task event SSE streams, and database records.

5. **No Automatic Remote Push**:
   - Verified changes are committed to local Git branches (`devagent/task-*`) inside the isolated workspace.
   - DevAgent **never** executes `git push` or modifies remote repositories automatically.
