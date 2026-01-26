"""
Configuration Manager - Persistent configuration storage
Handles device config, volume settings, and schedule persistence
"""

import logging
import json
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages persistent configuration"""
    
    def __init__(self, config_dir=None):
        # Configuration directory
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path.home() / "AudioAgent" / "config"
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Config files
        self.config_file = self.config_dir / "agent_config.json"
        self.schedule_file = self.config_dir / "schedule.json"
        self.cache_dir = Path.home() / "AudioAgent" / "audio_cache"
        
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
                # Create default config
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
            "device_id": str(uuid.uuid4()),
            "branch_id": "UNASSIGNED",
            "server_url": "http://127.0.0.1:5000",
            "token": "CHANGE_ME",
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
        """
        Update and persist volume settings
        
        Args:
            master_volume (int): Master volume 0-100
            branch_volume (int): Branch volume 0-100
        """
        self.master_volume = master_volume
        self.branch_volume = branch_volume
        
        self.config['master_volume'] = master_volume
        self.config['branch_volume'] = branch_volume
        
        self._save_config(self.config)
        logger.info(f"Volumes updated: master={master_volume}, branch={branch_volume}")
    
    def update_server_settings(self, server_url=None, token=None, branch_id=None):
        """
        Update server connection settings
        
        Args:
            server_url (str, optional): Server URL
            token (str, optional): Authentication token
            branch_id (str, optional): Branch ID
        """
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
        """
        Save schedule locally for offline operation
        
        Args:
            schedule_data (list): Schedule items
        """
        try:
            with open(self.schedule_file, 'w') as f:
                json.dump(schedule_data, f, indent=2)
            logger.info(f"Schedule saved: {len(schedule_data)} items")
        except Exception as e:
            logger.error(f"Failed to save schedule: {e}")
    
    def load_schedule(self):
        """
        Load schedule from local storage
        
        Returns:
            list: Schedule items, or empty list if not found
        """
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
        """
        Get configuration setting
        
        Args:
            key (str): Setting key
            default: Default value if not found
            
        Returns:
            Setting value or default
        """
        return self.config.get(key, default)
    
    def set_setting(self, key, value):
        """
        Set configuration setting
        
        Args:
            key (str): Setting key
            value: Setting value
        """
        self.config[key] = value
        self._save_config(self.config)
        logger.debug(f"Setting updated: {key} = {value}")
    
    def export_config(self, export_path):
        """
        Export configuration to file
        
        Args:
            export_path (str): Export file path
        """
        try:
            with open(export_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Configuration exported to {export_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export config: {e}")
            return False
    
    def import_config(self, import_path):
        """
        Import configuration from file
        
        Args:
            import_path (str): Import file path
        """
        try:
            with open(import_path, 'r') as f:
                imported_config = json.load(f)
            
            # Validate required fields
            required_fields = ['device_id', 'branch_id', 'server_url', 'token']
            for field in required_fields:
                if field not in imported_config:
                    logger.error(f"Missing required field: {field}")
                    return False
            
            # Update config
            self.config.update(imported_config)
            self._save_config(self.config)
            
            # Reload properties
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


# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Configuration Manager...")
    
    config = ConfigManager()
    
    print(f"Device ID: {config.device_id}")
    print(f"Branch ID: {config.branch_id}")
    print(f"Server URL: {config.server_url}")
    print(f"Master Volume: {config.master_volume}")
    print(f"Branch Volume: {config.branch_volume}")
    
    # Test volume update
    config.update_volumes(80, 90)
    print(f"Updated volumes: {config.master_volume}, {config.branch_volume}")