"""Orbitron Tester Agent Package.

The Tester Agent is responsible for critical quality testing of products
created by the Executor. It does NOT modify files — it only reads, inspects,
and evaluates.
"""

from .TesterAgent import TesterAgent, create_tester_agent

__all__ = ["TesterAgent", "create_tester_agent"]