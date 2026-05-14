"""Orchestrator-Tester Integration Bridge.

This module provides the bridge between the Orchestrator and Tester agents,
enabling the Orchestrator to send testing requests and receive quality results.
"""

import logging
from pathlib import Path
from typing import Any, Optional

try:
    from OrbitronMessageSystem import (
        AgentCommunicator,
        TesterCommunicator,
        Message,
        MessageType,
        AgentRole,
        TestingRequest,
        TestingResponse,
        get_message_bus,
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from OrbitronMessageSystem import (
        AgentCommunicator,
        TesterCommunicator,
        Message,
        MessageType,
        AgentRole,
        TestingRequest,
        TestingResponse,
        get_message_bus,
    )


logger = logging.getLogger("OrchestratorTesterBridge")


class OrchestratorTesterBridge:
    """Bridge class that integrates Orchestrator with Tester via MessageBus.

    This class can be used by the Orchestrator to communicate with the Tester
    without directly instantiating the TesterAgent.
    """

    def __init__(self, orchestrator_name: str = "orchestrator"):
        """Initialize the bridge.

        Args:
            orchestrator_name: Name of the orchestrator instance
        """
        self._communicator = AgentCommunicator(
            agent_name=orchestrator_name,
            agent_role=AgentRole.ORCHESTRATOR,
        )
        self._communicator.connect()

        logger.info("[OrchestratorTesterBridge] Initialized for %s", orchestrator_name)

    def request_testing(
        self,
        task_description: str,
        artifacts: list[str],
        requirements: Optional[dict[str, Any]] = None,
        execution_result: Optional[dict[str, Any]] = None,
        timeout_seconds: int = 900,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        """Request quality testing from the Tester Agent.

        This is a synchronous call that waits for the Tester to complete.
        If the request times out, it will be retried up to max_retries times.

        Args:
            task_description: Description of the original task
            artifacts: List of artifact file paths to test
            requirements: Original requirements for validation
            execution_result: Result from the Executor
            timeout_seconds: Maximum time to wait for testing (default 15 min)
            max_retries: Number of retries after timeout (default 1)

        Returns:
            Dictionary containing the testing results with keys:
            - passed: Whether the product passed quality checks
            - quality_rating: Overall rating (excellent/good/poor)
            - issues: List of issues found
            - summary: Summary of the testing result
        """
        logger.info("[OrchestratorTesterBridge] Requesting testing for %d artifacts", len(artifacts))

        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.warning("[OrchestratorTesterBridge] Retrying testing (attempt %d/%d)", attempt + 1, max_retries + 1)

            response = self._communicator.send_command(
                command="test_quality",
                args={
                    "task_description": task_description,
                    "artifacts": artifacts,
                    "requirements": requirements or {},
                    "execution_result": execution_result or {},
                },
                recipient_role=AgentRole.TESTER,
                wait_for_response=True,
                timeout_ms=timeout_seconds * 1000,
            )

            if response is not None:
                break

            logger.warning("[OrchestratorTesterBridge] Testing timed out (attempt %d/%d)", attempt + 1, max_retries + 1)
            if attempt < max_retries:
                logger.info("[OrchestratorTesterBridge] Retrying testing request...")
            else:
                return {
                    "passed": False,
                    "quality_rating": "poor",
                    "issues": [{"severity": "critical", "description": f"Testing timed out after {max_retries + 1} attempts ({timeout_seconds}s each)"}],
                    "summary": f"Testing failed: timed out after {max_retries + 1} attempts",
                    "error": f"Testing timed out after {max_retries + 1} attempts ({timeout_seconds}s each)",
                }

        payload = response.payload if hasattr(response, "payload") and isinstance(response.payload, dict) else {}
        metadata = response.metadata if hasattr(response, "metadata") and isinstance(response.metadata, dict) else {}

        passed = payload.get("passed", False)
        quality_rating = payload.get("quality_rating", "poor")
        issues = payload.get("issues", [])
        summary = payload.get("summary", "")
        error = metadata.get("error") if isinstance(metadata, dict) else None

        return {
            "passed": passed,
            "quality_rating": quality_rating,
            "issues": issues,
            "summary": summary,
            "error": error,
        }

    def close(self) -> None:
        """Close the bridge and disconnect from message bus."""
        if self._communicator:
            self._communicator.disconnect()
            logger.info("[OrchestratorTesterBridge] Closed")


class TesterMessageHandler:
    """Message handler for the Tester Agent.

    This class handles incoming messages for the Tester Agent,
    processing testing requests and sending results back.
    """

    def __init__(self, tester_agent, agent_name: str = "tester"):
        """Initialize the message handler.

        Args:
            tester_agent: The TesterAgent instance
            agent_name: Name for this tester instance
        """
        self.tester = tester_agent
        self.agent_name = agent_name
        self._communicator = TesterCommunicator(agent_name=agent_name)
        self._communicator.connect(message_handler=self._handle_message)

        logger.info("[TesterMessageHandler] Initialized for %s", agent_name)

    def _handle_message(self, message: Message) -> None:
        """Handle incoming messages for the Tester."""
        try:
            msg_type = message.header.message_type if hasattr(message, 'header') else None

            if msg_type == MessageType.COMMAND:
                payload = message.payload if hasattr(message, 'payload') else {}
                command = payload.get("command")
                args = payload.get("args", {})

                if command == "test_quality":
                    task_description = args.get("task_description", "")
                    artifacts = args.get("artifacts", [])
                    requirements = args.get("requirements", {})
                    execution_result = args.get("execution_result", {})

                    logger.info("[TesterMessageHandler] Testing quality for: %.80s...", task_description)

                    result = self.tester.test_quality(
                        task_description=task_description,
                        artifacts=artifacts,
                        requirements=requirements,
                        execution_result=execution_result,
                    )

                    if hasattr(result, 'to_dict'):
                        result = result.to_dict()

                    self._communicator.send_testing_result(
                        request_id=message.header.message_id if hasattr(message, 'header') else "unknown",
                        quality_rating=result.get("quality_rating", "poor"),
                        issues=result.get("issues", []),
                        summary=result.get("summary", ""),
                        passed=result.get("passed", False),
                        success=True,
                    )

                    logger.info("[TesterMessageHandler] Testing complete: passed=%s, rating=%s",
                                result.get("passed"), result.get("quality_rating"))

                else:
                    self._communicator.send_testing_result(
                        request_id=message.header.message_id if hasattr(message, 'header') else "unknown",
                        quality_rating="poor",
                        issues=[],
                        summary=f"Unknown command: {command}",
                        passed=False,
                        success=False,
                        error_message=f"Unknown command: {command}",
                    )

            elif msg_type == MessageType.TESTING_REQUEST:
                payload = message.payload if hasattr(message, 'payload') else {}
                task_description = payload.get("task_description", "")
                artifacts = payload.get("artifacts", [])
                requirements = payload.get("requirements", {})
                execution_result = payload.get("execution_result", {})

                logger.info("[TesterMessageHandler] Processing testing request: %.80s...", task_description)

                result = self.tester.test_quality(
                    task_description=task_description,
                    artifacts=artifacts,
                    requirements=requirements,
                    execution_result=execution_result,
                )

                if hasattr(result, 'to_dict'):
                    result = result.to_dict()

                self._communicator.send_testing_result(
                    request_id=message.header.message_id if hasattr(message, 'header') else "unknown",
                    quality_rating=result.get("quality_rating", "poor"),
                    issues=result.get("issues", []),
                    summary=result.get("summary", ""),
                    passed=result.get("passed", False),
                    success=True,
                )

            elif msg_type == MessageType.STATUS:
                status = self.tester.get_status() if hasattr(self.tester, 'get_status') else {"status": "idle"}
                self._communicator.send_status(
                    status="idle",
                    details=status,
                )

        except Exception as e:
            logger.exception(f"Error handling message: {e}")
            try:
                self._communicator.send_testing_result(
                    request_id=message.header.message_id if hasattr(message, 'header') else "unknown",
                    quality_rating="poor",
                    issues=[{"severity": "critical", "description": str(e)}],
                    summary=f"Testing failed with error: {e}",
                    passed=False,
                    success=False,
                    error_message=str(e),
                )
            except Exception:
                pass

    def close(self) -> None:
        """Close the message handler."""
        if self._communicator:
            self._communicator.disconnect()
            logger.info("[TesterMessageHandler] Closed")