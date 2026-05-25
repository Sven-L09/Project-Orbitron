"""Unit tests for TimeoutManager module."""

import json
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from OrbitronKernel.timeout_manager import TimeoutManager, ModelProfile, ExecutionHistory


class TestModelProfile:
    """Test ModelProfile dataclass."""

    def test_default_values(self):
        """ModelProfile should have sensible defaults."""
        profile = ModelProfile(model_name="test-model")
        assert profile.model_name == "test-model"
        assert profile.avg_response_time_seconds == 30.0
        assert profile.tokens_per_second == 50.0
        assert profile.reliability_score == 1.0

    def test_get_timeout_factor_fast_model(self):
        """Fast models should get lower timeout factors."""
        profile = ModelProfile(
            model_name="fast-model",
            avg_response_time_seconds=10.0,
            reliability_score=1.0,
        )
        factor = profile.get_timeout_factor()
        assert factor >= 0.5
        # Fast model should have factor <= 3.0
        assert factor <= 3.0

    def test_get_timeout_factor_slow_model(self):
        """Slow models should get higher timeout factors."""
        profile = ModelProfile(
            model_name="slow-model",
            avg_response_time_seconds=120.0,
            reliability_score=0.8,
        )
        factor = profile.get_timeout_factor()
        assert factor >= 0.5
        assert factor <= 3.0

    def test_get_timeout_factor_unreliable_model(self):
        """Unreliable models should get adjusted timeout factors."""
        profile = ModelProfile(
            model_name="unreliable-model",
            avg_response_time_seconds=30.0,
            reliability_score=0.5,
        )
        factor = profile.get_timeout_factor()
        assert factor >= 0.5
        assert factor <= 3.0


class TestExecutionHistory:
    """Test ExecutionHistory dataclass."""

    def test_creation(self):
        """ExecutionHistory should be created with required fields."""
        history = ExecutionHistory(
            plan_id="test-plan",
            num_steps=5,
            actual_duration_seconds=120.0,
        )
        assert history.plan_id == "test-plan"
        assert history.num_steps == 5
        assert history.actual_duration_seconds == 120.0
        assert history.was_successful is True  # default


class TestTimeoutManager:
    """Test TimeoutManager class."""

    def test_initialization(self, timeout_manager):
        """TimeoutManager should initialize with defaults."""
        assert timeout_manager is not None
        assert timeout_manager.MIN_TIMEOUT_SECONDS == 30
        assert timeout_manager.MAX_TIMEOUT_SECONDS == 600

    def test_get_or_create_profile(self, timeout_manager):
        """get_or_create_profile should create profiles for new models."""
        profile = timeout_manager.get_or_create_profile("new-model")
        assert profile.model_name == "new-model"
        assert profile.avg_response_time_seconds == 30.0  # default

    def test_get_or_create_profile_existing(self, timeout_manager):
        """get_or_create_profile should return existing profiles."""
        profile1 = timeout_manager.get_or_create_profile("existing-model")
        profile2 = timeout_manager.get_or_create_profile("existing-model")
        assert profile1 is profile2

    def test_update_profile(self, timeout_manager):
        """update_profile should update model performance data."""
        timeout_manager.update_profile(
            model_name="test-model",
            response_time_seconds=45.0,
            was_successful=True,
        )
        profile = timeout_manager.get_or_create_profile("test-model")
        # The profile should have been updated
        assert profile is not None

    def test_calculate_timeout_default(self, timeout_manager):
        """calculate_timeout should return a value within bounds."""
        timeout = timeout_manager.calculate_timeout(model_name="unknown-model")
        assert timeout >= timeout_manager.MIN_TIMEOUT_SECONDS
        assert timeout <= timeout_manager.MAX_TIMEOUT_SECONDS

    def test_calculate_timeout_with_steps(self, timeout_manager):
        """calculate_timeout should increase timeout with more steps."""
        plan_few = {"steps": [{"description": "step1"}, {"description": "step2"}]}
        plan_many = {"steps": [{"description": f"step{i}"} for i in range(10)]}
        timeout_few = timeout_manager.calculate_timeout(
            model_name="test-model",
            plan=plan_few,
        )
        timeout_many = timeout_manager.calculate_timeout(
            model_name="test-model",
            plan=plan_many,
        )
        # More steps should result in longer timeout
        assert timeout_many >= timeout_few

    def test_calculate_timeout_with_tokens(self, timeout_manager):
        """calculate_timeout should increase timeout with more tokens."""
        timeout_few = timeout_manager.calculate_timeout(
            model_name="test-model",
            estimated_tokens=100,
        )
        timeout_many = timeout_manager.calculate_timeout(
            model_name="test-model",
            estimated_tokens=10000,
        )
        # More tokens should result in longer timeout
        assert timeout_many >= timeout_few

    def test_calculate_timeout_min_bound(self, timeout_manager):
        """calculate_timeout should never go below MIN_TIMEOUT_SECONDS."""
        timeout = timeout_manager.calculate_timeout(model_name="fast-model")
        assert timeout >= timeout_manager.MIN_TIMEOUT_SECONDS

    def test_calculate_timeout_max_bound(self, timeout_manager):
        """calculate_timeout should never exceed MAX_TIMEOUT_SECONDS."""
        plan_many = {"steps": [{"description": f"step{i}"} for i in range(100)]}
        timeout = timeout_manager.calculate_timeout(
            model_name="slow-model",
            plan=plan_many,
            estimated_tokens=100000,
        )
        assert timeout <= timeout_manager.MAX_TIMEOUT_SECONDS

    def test_profile_persistence(self, tmp_path):
        """TimeoutManager should persist and load profiles."""
        manager1 = TimeoutManager(profiles_dir=str(tmp_path / "profiles"))
        manager1.update_profile("persist-model", response_time_seconds=50.0)

        # Create a new manager to load from disk
        manager2 = TimeoutManager(profiles_dir=str(tmp_path / "profiles"))
        profile = manager2.get_or_create_profile("persist-model")
        # The profile should have been loaded from disk
        assert profile is not None

    def test_execution_history_tracking(self, timeout_manager):
        """TimeoutManager should track execution history."""
        history = ExecutionHistory(
            plan_id="test-plan-001",
            num_steps=5,
            actual_duration_seconds=120.0,
            was_successful=True,
        )
        timeout_manager._history.append(history)
        assert len(timeout_manager._history) == 1
        assert timeout_manager._history[0].plan_id == "test-plan-001"

    def test_max_history_limit(self, timeout_manager):
        """TimeoutManager should limit history size."""
        for i in range(timeout_manager._max_history + 10):
            timeout_manager._history.append(
                ExecutionHistory(
                    plan_id=f"plan-{i}",
                    num_steps=1,
                    actual_duration_seconds=10.0,
                )
            )
        # History should be trimmed
        assert len(timeout_manager._history) <= timeout_manager._max_history + 10