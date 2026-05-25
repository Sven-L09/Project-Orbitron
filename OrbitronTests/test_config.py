"""Unit tests for Config module."""

import json
import os
from pathlib import Path

import pytest

from OrbitronKernel.config import Config


class TestConfigInit:
    """Test Config initialization."""

    def test_default_config(self, tmp_path):
        """Config should create default configuration."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        assert config.config is not None
        assert "ollama" in config.config
        assert "kernel" in config.config

    def test_load_existing_config(self, tmp_path):
        """Config should load existing configuration file."""
        config_path = str(tmp_path / "test_config.json")
        config_data = {
            "ollama": {
                "base_url": "https://custom.api.com",
                "model": "custom-model",
                "api_key": "custom-key",
            },
            "kernel": {
                "workspace": "/custom/workspace",
            },
        }
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        config = Config(config_path=config_path)
        assert config.get("ollama.base_url") == "https://custom.api.com"
        assert config.get("ollama.model") == "custom-model"

    def test_save_config(self, tmp_path):
        """Config should save configuration to file."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        config.set("ollama.model", "new-model")
        config.save()

        # Load again
        config2 = Config(config_path=config_path)
        assert config2.get("ollama.model") == "new-model"


class TestConfigGet:
    """Test Config.get method."""

    def test_get_nested_key(self, tmp_path):
        """Config.get should support nested keys with dot notation."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        assert config.get("ollama.base_url") is not None
        assert config.get("ollama.model") is not None

    def test_get_with_default(self, tmp_path):
        """Config.get should return default for missing keys."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        result = config.get("nonexistent.key", default="default_value")
        assert result == "default_value"

    def test_get_nonexistent_key_no_default(self, tmp_path):
        """Config.get should return None for missing keys without default."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        result = config.get("nonexistent.key")
        assert result is None


class TestConfigSet:
    """Test Config.set method."""

    def test_set_new_key(self, tmp_path):
        """Config.set should create new keys."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        config.set("custom.key", "custom_value")
        assert config.get("custom.key") == "custom_value"

    def test_set_overwrite_key(self, tmp_path):
        """Config.set should overwrite existing keys."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        config.set("ollama.model", "overwritten-model")
        assert config.get("ollama.model") == "overwritten-model"

    def test_set_deep_nested_key(self, tmp_path):
        """Config.set should create deeply nested keys."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        config.set("deep.nested.key", "deep_value")
        assert config.get("deep.nested.key") == "deep_value"


class TestConfigDefaults:
    """Test Config default values."""

    def test_default_ollama_config(self, tmp_path):
        """Config should have default Ollama configuration."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        assert config.get("ollama.base_url") == "https://ollama.com/api"
        assert config.get("ollama.model") == "glm-5.1:cloud"
        assert config.get("ollama.api_key") == ""

    def test_default_kernel_config(self, tmp_path):
        """Config should have default kernel configuration."""
        config_path = str(tmp_path / "test_config.json")
        config = Config(config_path=config_path)
        assert config.get("kernel.workspace") is not None
        assert config.get("kernel.skills_dir") is not None