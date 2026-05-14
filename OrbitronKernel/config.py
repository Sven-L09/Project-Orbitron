"""Configuration module for Orbitron Kernel."""

import os
import json
from pathlib import Path


class Config:
    """Configuration manager for Orbitron."""
    
    def __init__(self, config_path: str | None = None):
        """Initialize configuration."""
        self.config_path = config_path or self._get_default_config_path()
        self.config = self._load_config()
    
    def _get_default_config_path(self) -> str:
        """Get default config path."""
        home = Path.home()
        return str(home / ".orbitron" / "config.json")
    
    def _load_config(self) -> dict:
        """Load configuration from file."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return self._get_default_config()
    
    def _get_default_config(self) -> dict:
        """Get default configuration."""
        return {
            "ollama": {
                "base_url": "https://ollama.com/api",
                "model": "qwen3.5:cloud",
                "api_key": ""
            },
            "kernel": {
                "workspace": str(Path.home() / ".orbitron" / "workspace"),
                "skills_dir": str(Path.home() / ".orbitron" / "workspace" / "skills")
            }
        }
    
    def save(self) -> None:
        """Save configuration to file."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)
    
    def get(self, key: str, default=None):
        """Get configuration value."""
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value) -> None:
        """Set configuration value."""
        keys = key.split(".")
        config = self.config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self.save()
