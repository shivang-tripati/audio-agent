"""
Server Client - Backend Communication
Handles HTTPS REST API and WebSocket connections
"""

import logging
import json
import time
import threading
import requests
from websocket import WebSocketApp

logger = logging.getLogger(__name__)


class ServerClient:
    """Manages communication with backend server"""
    
    def __init__(self, base_url, device_id, branch_id, token,
                 on_volume_update=None,
                 on_play_command=None,
                 on_stop_command=None,
                 on_schedule_update=None,
                 on_audio_download=None):
        
        self.base_url = base_url.rstrip('/')
        self.device_id = device_id
        self.branch_id = branch_id
        self.token = token
        
        # Callbacks
        self.on_volume_update = on_volume_update
        self.on_play_command = on_play_command
        self.on_stop_command = on_stop_command
        self.on_schedule_update = on_schedule_update
        self.on_audio_download = on_audio_download
        
        # WebSocket
        self.ws = None
        self.ws_connected = False
        self.ws_url = self._get_ws_url()
        
        # Connection state
        self.authenticated = False
        
        logger.info(f"Server client initialized for {base_url}")
    
    def _get_ws_url(self):
        """Convert HTTP(S) URL to WS(S) URL"""
        ws_url = self.base_url.replace('https://', 'wss://').replace('http://', 'ws://')
        return f"{ws_url}/ws/device/{self.device_id}"
    
    def connect(self):
        """Connect to server (authenticate + WebSocket)"""
        try:
            # Authenticate first
            if not self._authenticate():
                return False
            
            # Connect WebSocket
            return self._connect_websocket()
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from server"""
        if self.ws:
            self.ws.close()
        self.ws_connected = False
        self.authenticated = False
    
    def is_connected(self):
        """Check if connected to server"""
        return self.ws_connected and self.authenticated
    
    def _authenticate(self):
        """Authenticate with backend"""
        try:
            logger.info("Authenticating with server...")
            
            auth_url = f"{self.base_url}/api/auth/device"
            
            payload = {
                "deviceId": self.device_id,
                "branchId": self.branch_id,
                "token": self.token
            }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}"
            }
            
            response = requests.post(auth_url, json=payload, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Authentication successful: {data.get('message', 'OK')}")
                self.authenticated = True
                
                # Get initial configuration
                self._fetch_initial_config()
                
                return True
            else:
                logger.error(f"Authentication failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
    
    def _fetch_initial_config(self):
        """Fetch initial configuration (volume, schedule)"""
        try:
            logger.info("Fetching initial configuration...")
            
            config_url = f"{self.base_url}/api/device/{self.device_id}/config"
            headers = {"Authorization": f"Bearer {self.token}"}
            
            response = requests.get(config_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                config = response.json()
                
                # Apply volume
                if 'masterVolume' in config and 'branchVolume' in config:
                    if self.on_volume_update:
                        self.on_volume_update(
                            config['masterVolume'],
                            config['branchVolume']
                        )
                
                # Apply schedule
                if 'schedule' in config and self.on_schedule_update:
                    self.on_schedule_update(config['schedule'])
                
                logger.info("Initial configuration applied")
            else:
                logger.warning(f"Failed to fetch config: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to fetch initial config: {e}")
    
    def _connect_websocket(self):
        """Connect WebSocket for real-time commands"""
        try:
            logger.info(f"Connecting WebSocket to {self.ws_url}")
            
            self.ws = WebSocketApp(
                self.ws_url,
                header={
                    "Authorization": f"Bearer {self.token}"
                },
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close
            )
            
            # Run in separate thread
            ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
            ws_thread.start()
            
            # Wait for connection (max 5 seconds)
            for _ in range(50):
                if self.ws_connected:
                    return True
                time.sleep(0.1)
            
            logger.error("WebSocket connection timeout")
            return False
            
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            return False
    
    def _on_ws_open(self, ws):
        """WebSocket connection opened"""
        logger.info("WebSocket connected")
        self.ws_connected = True
    
    def _on_ws_close(self, ws, close_status_code, close_msg):
        """WebSocket connection closed"""
        logger.warning(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.ws_connected = False
    
    def _on_ws_error(self, ws, error):
        """WebSocket error"""
        logger.error(f"WebSocket error: {error}")
    
    def _on_ws_message(self, ws, message):
        """Handle WebSocket message"""
        try:
            data = json.loads(message)
            command_type = data.get('type')
            
            logger.info(f"Received command: {command_type}")
            
            if command_type == 'VOLUME_UPDATE':
                self._handle_volume_update(data)
            
            elif command_type == 'PLAY':
                self._handle_play_command(data)
            
            elif command_type == 'STOP':
                self._handle_stop_command(data)
            
            elif command_type == 'SCHEDULE_UPDATE':
                self._handle_schedule_update(data)
            
            elif command_type == 'DOWNLOAD_AUDIO':
                self._handle_audio_download(data)
            
            else:
                logger.warning(f"Unknown command type: {command_type}")
                
        except Exception as e:
            logger.error(f"Failed to process message: {e}")
    
    def _handle_volume_update(self, data):
        """Handle volume update command"""
        master_volume = data.get('masterVolume')
        branch_volume = data.get('branchVolume')
        
        if master_volume is not None and branch_volume is not None:
            if self.on_volume_update:
                self.on_volume_update(master_volume, branch_volume)
    
    def _handle_play_command(self, data):
        """Handle play command"""
        audio_info = data.get('audio', {})
        if self.on_play_command:
            self.on_play_command(audio_info)
    
    def _handle_stop_command(self, data):
        """Handle stop command"""
        if self.on_stop_command:
            self.on_stop_command()
    
    def _handle_schedule_update(self, data):
        """Handle schedule update"""
        schedule = data.get('schedule', [])
        if self.on_schedule_update:
            self.on_schedule_update(schedule)
    
    def _handle_audio_download(self, data):
        """Handle audio download request"""
        audio_info = data.get('audio', {})
        if self.on_audio_download:
            self.on_audio_download(audio_info)
    
    def send_heartbeat(self, heartbeat_data):
        """Send heartbeat to server"""
        try:
            if not self.authenticated:
                logger.warning("Not authenticated, skipping heartbeat")
                return False
            
            heartbeat_url = f"{self.base_url}/api/device/{self.device_id}/heartbeat"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}"
            }
            
            response = requests.post(
                heartbeat_url,
                json=heartbeat_data,
                headers=headers,
                timeout=5
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")
            return False
    
    def send_status_update(self, status_data):
        """Send status update to server"""
        try:
            if self.ws_connected and self.ws:
                message = {
                    "type": "STATUS_UPDATE",
                    "data": status_data
                }
                self.ws.send(json.dumps(message))
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to send status: {e}")
            return False


# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Server Client...")
    
    client = ServerClient(
        base_url="https://api.example.com",
        device_id="test-device-001",
        branch_id="branch-001",
        token="test-token-123"
    )
    
    print("Client initialized")