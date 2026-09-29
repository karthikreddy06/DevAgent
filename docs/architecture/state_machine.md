# Task State Machine & Approval Lifecycle

DevAgent governs every task through a deterministic state machine defined in `app/orchestration/state_machine.py`.

## Lifecycle Diagram

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> PLANNING
    PLANNING --> ANALYZING
    ANALYZING --> INVESTIGATING
    INVESTIGATING --> COMPLETED: (If Question)
    INVESTIGATING --> FIX_PROPOSED: (If Changes Needed)
    FIX_PROPOSED --> AWAITING_APPROVAL
    AWAITING_APPROVAL --> APPLYING: (Human Approved)
    AWAITING_APPROVAL --> REJECTED: (Human Rejected)
    APPLYING --> TESTING
    TESTING --> COMPLETED: (Tests Pass)
    TESTING --> INVESTIGATING: (Tests Fail & Attempts Left)
    TESTING --> FAILED: (Attempts Exhausted)
    COMPLETED --> [*]
    FAILED --> [*]
    REJECTED --> [*]
```

## Capability Mapping

Permissions are strictly scoped by state (`permissions_for_status` in `app/tools/permissions.py`):

| Task Status | Granted Permissions | Description |
|---|---|---|
| `CREATED`, `PLANNING`, `ANALYZING` | `READ` | Code search, list files, symbol lookup |
| `INVESTIGATING` | `READ`, `EXECUTE` | Read codebase, run sandboxed tests/diagnostics |
| `AWAITING_APPROVAL` | `READ` | Pipeline paused waiting for human review |
| `APPLYING` | `READ`, `WRITE`, `EXECUTE` | Write files, apply patches to workspace |
| `TESTING` | `READ`, `EXECUTE` | Sandboxed test execution and verification |
| `COMPLETED`, `FAILED` | `READ` | Terminal state audit |
