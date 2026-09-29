# DevAgent System Architecture

DevAgent is an autonomous software engineering assistant designed to explore, debug, test, and propose verified code changes within source code repositories.

## High-Level Topology

```
+--------------------+        +---------------------+
|   React Frontend   | <----> |     FastAPI API     |
|   (Vite + Tailwind |  HTTP  | (Stateless Gateway) |
|      / Glassmorphic|   SSE  +----------+----------+
+--------------------+                   |
                                         | Pub/Sub & Tasks
                                         v
                              +---------------------+
                              |   Redis + Postgres  |
                              |  (Job Queue + DB)   |
                              +----------+----------+
                                         ^
                                         | Owns Docker Socket
                                         v
                              +---------------------+
                              |     arq Worker      |
                              | (Orchestrator, Git, |
                              |   Docker Runner)    |
                              +----------+----------+
                                         |
                                         | Ephemeral Executions
                                         v
                              +---------------------+
                              |   Docker Sandboxes  |
                              | (runner-python:3.12)|
                              +---------------------+
```

## Security Posture & Isolation

1. **API Container**: Stateless, runs without root privileges, never touches the docker socket, never executes arbitrary user/repository code.
2. **Worker Container**: Owns the arq queue and docker socket. Repository code is **NEVER** executed on the worker host directly.
3. **Sandbox Container**: Spawns per-execution ephemeral containers with strict resource limits:
   - Network disabled (`--network none`) by default
   - Non-root user (`uid 10001`)
   - CPU and memory quotas
   - Read-only root filesystem with ephemeral workspace mount
4. **Approval Gate**: Write and push actions require explicit `Approval` database records. Agents cannot write silently.
