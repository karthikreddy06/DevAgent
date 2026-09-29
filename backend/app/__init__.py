"""DevAgent backend - an AI software engineering agent.

Layering (enforced by tests/unit/test_architecture.py):
    api -> orchestration -> agents -> tools -> core
    services sits beside agents and is used by both.

Nothing in a lower layer imports from a higher one, and nothing in ``tools``
imports from ``agents``.
"""

__version__ = "0.1.0"
