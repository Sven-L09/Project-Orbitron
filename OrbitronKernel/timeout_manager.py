"""Adaptive Timeout Management for Orbitron.

Calculates dynamic timeouts based on plan complexity, model performance,
and historical execution times.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("OrbitronKernel.TimeoutManager")


@dataclass
class ModelProfile:
    """Performance profile for a specific model."""
    model_name: str
    avg_response_time_seconds: float = 30.0
    tokens_per_second: float = 50.0
    reliability_score: float = 1.0  # 0.0 to 1.0
    last_updated: datetime = field(default_factory=datetime.now)

    def get_timeout_factor(self) -> float:
        """Calculate timeout multiplier based on model performance."""
        # Slower models get higher factors
        base_factor = 30.0 / max(self.avg_response_time_seconds, 1.0)
        reliability_factor = self.reliability_score
        return max(0.5, min(3.0, base_factor * reliability_factor))


@dataclass
class ExecutionHistory:
    """Historical data for timeout calculations."""
    plan_id: str
    num_steps: int
    actual_duration_seconds: float
    completed_at: datetime = field(default_factory=datetime.now)
    was_successful: bool = True


class TimeoutManager:
    """Manages adaptive timeouts for LLM operations.

    Features:
    - Model-specific profiles (slow models get longer timeouts)
    - Plan complexity analysis (more steps = longer timeout)
    - Historical learning (tracks actual execution times)
    - Configurable limits (min/max timeout bounds)
    """

    # Default timeout bounds
    MIN_TIMEOUT_SECONDS = 30    # 30 seconds minimum
    MAX_TIMEOUT_SECONDS = 600   # 10 minutes maximum

    # Base calculations
    BASE_TIMEOUT_SECONDS = 180  # 3 minutes base
    PER_STEP_SECONDS = 60  # 1 minute per plan step
    PER_TOKEN_ESTIMATE_SECONDS = 0.02  # 20ms per expected token

    def __init__(
        self,
        profiles_dir: Optional[str] = None,
    ):
        self.profiles_dir = Path(profiles_dir) if profiles_dir else Path.home() / ".orbitron" / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Model profiles
        self._profiles: dict[str, ModelProfile] = {}

        # Execution history (limited)
        self._history: list[ExecutionHistory] = []
        self._max_history = 100

        # Load persisted profiles
        self._load_profiles()

        logger.info("[TimeoutManager] Initialized with profiles_dir=%s", self.profiles_dir)

    # ========== Model Profiles ==========

    def get_or_create_profile(self, model_name: str) -> ModelProfile:
        """Get or create a profile for a model."""
        if model_name not in self._profiles:
            self._profiles[model_name] = ModelProfile(model_name=model_name)
        return self._profiles[model_name]

    def update_profile(
        self,
        model_name: str,
        response_time_seconds: float,
        tokens_per_second: Optional[float] = None,
        was_successful: bool = True,
    ) -> None:
        """Update a model's performance profile."""
        profile = self.get_or_create_profile(model_name)

        # Exponential moving average for response time
        alpha = 0.3  # Weight for new measurements
        profile.avg_response_time_seconds = (
            alpha * response_time_seconds +
            (1 - alpha) * profile.avg_response_time_seconds
        )

        if tokens_per_second is not None:
            profile.tokens_per_second = (
                alpha * tokens_per_second +
                (1 - alpha) * profile.tokens_per_second
            )

        # Update reliability score
        reliability_target = 1.0 if was_successful else 0.0
        profile.reliability_score = (
            alpha * reliability_target +
            (1 - alpha) * profile.reliability_score
        )

        profile.last_updated = datetime.now()

        # Persist profiles
        self._save_profiles()

        logger.debug(
            "[TimeoutManager] Updated profile for %s: avg_time=%.1fs, reliability=%.2f",
            model_name,
            profile.avg_response_time_seconds,
            profile.reliability_score,
        )

    def get_model_factor(self, model_name: str) -> float:
        """Get timeout multiplier for a specific model."""
        profile = self.get_or_create_profile(model_name)
        return profile.get_timeout_factor()

    # ========== Timeout Calculation ==========

    def calculate_timeout(
        self,
        plan: Optional[dict[str, Any]] = None,
        model_name: Optional[str] = None,
        estimated_tokens: int = 0,
        override_factor: float = 1.0,
    ) -> int:
        """Calculate adaptive timeout in seconds.

        Args:
            plan: Plan dictionary (for step count)
            model_name: Model identifier (for profile lookup)
            estimated_tokens: Expected output tokens
            override_factor: Manual multiplier for special cases

        Returns:
            Timeout in seconds (clamped to MIN/MAX bounds)
        """
        # Start with base timeout
        timeout = self.BASE_TIMEOUT_SECONDS

        # Add per-step time
        if plan:
            steps = plan.get("steps", [])
            if isinstance(steps, list):
                timeout += len(steps) * self.PER_STEP_SECONDS

        # Add per-token time
        if estimated_tokens > 0:
            timeout += estimated_tokens * self.PER_TOKEN_ESTIMATE_SECONDS

        # Apply model factor
        if model_name:
            model_factor = self.get_model_factor(model_name)
            timeout *= model_factor
            logger.debug(
                "[TimeoutManager] Model factor for %s: %.2f",
                model_name,
                model_factor,
            )

        # Apply override factor
        if override_factor != 1.0:
            timeout *= override_factor
            logger.debug("[TimeoutManager] Override factor applied: %.2f", override_factor)

        # Clamp to bounds
        final_timeout = int(max(self.MIN_TIMEOUT_SECONDS, min(self.MAX_TIMEOUT_SECONDS, timeout)))

        logger.info(
            "[TimeoutManager] Calculated timeout: %d seconds (base=%.0f, steps=%d, tokens=%d)",
            final_timeout,
            self.BASE_TIMEOUT_SECONDS,
            len(plan.get("steps", [])) if plan else 0,
            estimated_tokens,
        )

        return final_timeout

    def calculate_planning_timeout(
        self,
        task_description: str,
        model_name: Optional[str] = None,
    ) -> int:
        """Calculate timeout specifically for planning operations.

        Planning typically needs more time for complex reasoning.
        """
        # Base planning timeout is higher
        timeout = 300  # 5 minutes base for planning

        # Adjust for description complexity (rough heuristic)
        word_count = len(task_description.split())
        if word_count > 50:
            timeout += (word_count - 50) * 2  # 2 seconds per extra word

        # Apply model factor
        if model_name:
            timeout *= self.get_model_factor(model_name)

        return int(max(self.MIN_TIMEOUT_SECONDS, min(self.MAX_TIMEOUT_SECONDS, timeout)))

    def calculate_execution_timeout(
        self,
        plan: dict[str, Any],
        model_name: Optional[str] = None,
    ) -> int:
        """Calculate timeout for execution operations.

        Execution involves multiple LLM calls (one per step potentially).
        """
        steps = plan.get("steps", []) if isinstance(plan, dict) else []
        num_steps = len(steps)

        # Base + per-step time
        timeout = 300 + (num_steps * 60)  # 5 min base + 60 sec per step

        # Execution typically uses code generation which is slower
        timeout *= 1.5  # 50% overhead for code generation

        # Apply model factor
        if model_name:
            timeout *= self.get_model_factor(model_name)

        return int(max(self.MIN_TIMEOUT_SECONDS, min(self.MAX_TIMEOUT_SECONDS, timeout)))

    def calculate_validation_timeout(
        self,
        num_artifacts: int,
        model_name: Optional[str] = None,
    ) -> int:
        """Calculate timeout for validation operations."""
        # Validation is typically faster (reading and checking)
        timeout = 120 + (num_artifacts * 30)  # 2 min + 30 sec per artifact

        if model_name:
            timeout *= self.get_model_factor(model_name)

        return int(max(self.MIN_TIMEOUT_SECONDS, min(self.MAX_TIMEOUT_SECONDS, timeout)))

    # ========== History Tracking ==========

    def record_execution(
        self,
        plan_id: str,
        num_steps: int,
        duration_seconds: float,
        was_successful: bool = True,
    ) -> None:
        """Record an execution for historical analysis."""
        history = ExecutionHistory(
            plan_id=plan_id,
            num_steps=num_steps,
            actual_duration_seconds=duration_seconds,
            was_successful=was_successful,
        )

        self._history.append(history)

        # Trim history
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        logger.debug(
            "[TimeoutManager] Recorded execution: %s, %d steps, %.1fs, success=%s",
            plan_id,
            num_steps,
            duration_seconds,
            was_successful,
        )

    def get_average_duration_per_step(self) -> float:
        """Calculate average duration per step from history."""
        if not self._history:
            return self.PER_STEP_SECONDS * 0.5  # Default estimate

        total_steps = sum(h.num_steps for h in self._history)
        total_duration = sum(h.actual_duration_seconds for h in self._history)

        if total_steps == 0:
            return self.PER_STEP_SECONDS * 0.5

        return total_duration / total_steps

    # ========== Persistence ==========

    def _load_profiles(self) -> None:
        """Load model profiles from disk."""
        import json

        profiles_file = self.profiles_dir / "model_profiles.json"
        if not profiles_file.exists():
            return

        try:
            with open(profiles_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for name, profile_data in data.items():
                self._profiles[name] = ModelProfile(
                    model_name=name,
                    avg_response_time_seconds=profile_data.get("avg_response_time_seconds", 30.0),
                    tokens_per_second=profile_data.get("tokens_per_second", 50.0),
                    reliability_score=profile_data.get("reliability_score", 1.0),
                    last_updated=datetime.fromisoformat(profile_data.get("last_updated", datetime.now().isoformat())),
                )

            logger.info("[TimeoutManager] Loaded %d model profiles", len(self._profiles))
        except Exception as e:
            logger.warning("[TimeoutManager] Failed to load profiles: %s", e)

    def _save_profiles(self) -> None:
        """Save model profiles to disk."""
        import json

        profiles_file = self.profiles_dir / "model_profiles.json"

        data = {}
        for name, profile in self._profiles.items():
            data[name] = {
                "model_name": profile.model_name,
                "avg_response_time_seconds": profile.avg_response_time_seconds,
                "tokens_per_second": profile.tokens_per_second,
                "reliability_score": profile.reliability_score,
                "last_updated": profile.last_updated.isoformat(),
            }

        try:
            with open(profiles_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("[TimeoutManager] Failed to save profiles: %s", e)

    # ========== Status & Utilities ==========

    def get_status(self) -> dict[str, Any]:
        """Get timeout manager status."""
        return {
            "profiles_count": len(self._profiles),
            "history_count": len(self._history),
            "avg_duration_per_step": self.get_average_duration_per_step(),
            "profiles": {
                name: {
                    "avg_response_time": p.avg_response_time_seconds,
                    "reliability": p.reliability_score,
                }
                for name, p in self._profiles.items()
            },
        }

    def reset_profiles(self) -> None:
        """Reset all model profiles to defaults."""
        self._profiles.clear()
        self._save_profiles()
        logger.info("[TimeoutManager] Reset all model profiles")

    def clear_history(self) -> None:
        """Clear execution history."""
        self._history.clear()
        logger.info("[TimeoutManager] Cleared execution history")
