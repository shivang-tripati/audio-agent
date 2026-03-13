"""
Configuration Manager - Persistent configuration storage
Handles device config, volume settings, and schedule persistence
"""

import logging
import json
import os
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


def get_app_data_dir() -> Path:
    """
    Returns the shared application data directory.

    CRITICAL: Must be consistent across ALL processes:
      - Windows Service (runs as SYSTEM)
      - Worker subprocess (child of service)
      - UI process (runs as logged-in user)

    Path.home() gives DIFFERENT results for service vs UI:
      - UI:      C:\\Users\\Username\\
      - Service: C:\\Windows\\System32\\config\\systemprofile\\

    Using PROGRAMDATA (C:\\ProgramData) gives the SAME path
    for all processes regardless of who runs them.
    This is also where the Inno installer creates the directories.
    """
    program_data = os.environ.get('PROGRAMDATA', 'C:\\ProgramData')
    return Path(program_data) / "AudioAgent"


class ConfigManager:
    """Manages persistent configuration"""

    def __init__(self, config_dir=None):
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = get_app_data_dir() / "config"

        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Config files
        self.config_file = self.config_dir / "agent_config.json"
        self.schedule_file = self.config_dir / "schedule.json"
        self.playlist_state_file = self.config_dir / "playlist_state.json"

        # Cache dir — also under ProgramData so service can write to it
        self.cache_dir = get_app_data_dir() / "audio_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Load or create config
        self.config = self._load_config()

        # Expose common settings
        self.device_id = self.config.get('device_id')
        self.branch_id = self.config.get('branch_id')
        self.server_url = self.config.get('server_url')
        self.token = self.config.get('token')
        self.master_volume = self.config.get('master_volume', 100)
        self.branch_volume = self.config.get('branch_volume', 100)

        logger.info(f"Configuration loaded from {self.config_file}")

    def _load_config(self):
        """Load configuration from file or create default"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                logger.info("Configuration loaded from file")
                return config
            else:
                config = self._create_default_config()
                self._save_config(config)
                logger.info("Default configuration created")
                return config

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return self._create_default_config()

    def _create_default_config(self):
        """Create default configuration"""
        return {
            "branch_id": None,
            "device_id": None,
            "server_url": "http://127.0.0.1:3000",
            "token": None,
            "master_volume": 100,
            "branch_volume": 100,
            "heartbeat_interval": 45,
            "auto_start": True
        }

    def _save_config(self, config):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            logger.debug("Configuration saved")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def update_volumes(self, master_volume, branch_volume):
        self.master_volume = master_volume
        self.branch_volume = branch_volume
        self.config['master_volume'] = master_volume
        self.config['branch_volume'] = branch_volume
        self._save_config(self.config)
        logger.info(f"Volumes updated: master={master_volume}, branch={branch_volume}")

    def update_server_settings(self, server_url=None, token=None, branch_id=None):
        if server_url:
            self.server_url = server_url
            self.config['server_url'] = server_url
        if token:
            self.token = token
            self.config['token'] = token
        if branch_id:
            self.branch_id = branch_id
            self.config['branch_id'] = branch_id
        self._save_config(self.config)
        logger.info("Server settings updated")

    def save_schedule(self, schedule_data):
        try:
            with open(self.schedule_file, 'w') as f:
                json.dump(schedule_data, f, indent=2)
            logger.info(f"Schedule saved: {len(schedule_data)} items")
        except Exception as e:
            logger.error(f"Failed to save schedule: {e}")

    def load_schedule(self):
        try:
            if self.schedule_file.exists():
                with open(self.schedule_file, 'r') as f:
                    schedule = json.load(f)
                logger.info(f"Schedule loaded: {len(schedule)} items")
                return schedule
            else:
                logger.info("No saved schedule found")
                return []
        except Exception as e:
            logger.error(f"Failed to load schedule: {e}")
            return []

    def get_setting(self, key, default=None):
        return self.config.get(key, default)

    def set_setting(self, key, value):
        self.config[key] = value
        self._save_config(self.config)
        logger.debug(f"Setting updated: {key} = {value}")

    def export_config(self, export_path):
        try:
            with open(export_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Configuration exported to {export_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export config: {e}")
            return False

    def import_config(self, import_path):
        try:
            with open(import_path, 'r') as f:
                imported_config = json.load(f)

            required_fields = ['device_id', 'branch_id', 'server_url', 'token']
            for field in required_fields:
                if field not in imported_config:
                    logger.error(f"Missing required field: {field}")
                    return False

            self.config.update(imported_config)
            self._save_config(self.config)

            self.device_id = self.config['device_id']
            self.branch_id = self.config['branch_id']
            self.server_url = self.config['server_url']
            self.token = self.config['token']
            self.master_volume = self.config.get('master_volume', 100)
            self.branch_volume = self.config.get('branch_volume', 100)

            logger.info(f"Configuration imported from {import_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to import config: {e}")
            return False