"""Configuration module for loading settings from config.yaml file.

This module provides functionality to load and access configuration settings
from a config.yaml file located in the project root directory.

"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Dict, Any
import yaml

from core.logger import logger


class Config:
    """Configuration manager for loading settings from YAML file."""

    def __init__(self):
        """Initialize the config manager and load configuration from file."""
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from config.yaml file in project root.
        
        The config file should be located at the project root directory.
        If the file doesn't exist, a warning is logged and an empty config is used.
        """
        # Find the project root (parent of the core directory)
        current_dir = Path(__file__).parent
        config_file = current_dir.parent / "config.yaml"

        if not config_file.exists():
            logger.warning(f"Config file not found at {config_file}. Using empty configuration.")
            self._config = {}
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                loaded_config = yaml.safe_load(f)
                self._config = loaded_config if loaded_config else {}
                logger.info(f"Configuration loaded from {config_file}")
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML config file {config_file}: {e}")
            self._config = {}
        except IOError as e:
            logger.error(f"Error reading config file {config_file}: {e}")
            self._config = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key.
        
        Args:
            key: Configuration key (e.g., 'kalshi', 'polymarket.api_token')
            default: Default value if key is not found
        
        Returns:
            The configuration value or default if not found.
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value if value is not None else default

    def reload(self) -> None:
        """Reload configuration from file.
        
        Useful when the config file has been updated and you want to pick up changes.
        """
        self._load_config()
        logger.info("Configuration reloaded")


# Global config instance
config = Config()


__all__ = ['config', 'Config']
