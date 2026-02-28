"""
Server Client
Enhanced with PLAYLIST_UPDATE socket command support.
"""
import socketio
import logging

logger = logging.getLogger(__name__)


class ServerClient:
    def __init__(self, base_url, token,
                 on_volume_update=None,
                 on_play_command=None,
                 on_stop_command=None,
                 on_schedule_update=None,
                 on_audio_download=None,
                 on_playlist_update=None
                 ):

        self.base_url = base_url
        self.token = token

        self.on_volume_update = on_volume_update
        self.on_play_command = on_play_command
        self.on_stop_command = on_stop_command
        self.on_schedule_update = on_schedule_update
        self.on_audio_download = on_audio_download
        self.on_playlist_update = on_playlist_update

        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=5,
            reconnection_delay_max=30
        )

        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("command", self._on_command)

    def connect(self):
        logger.info(f"Attempting socket connection to {self.base_url}")
        formatted_token = f"Bearer {self.token}"
        try:
            self.sio.connect(
                self.base_url,
                auth={"token": formatted_token},
                transports=["websocket"]
            )
            return True  # This must be INSIDE the try block
        except Exception as e:  # This MUST follow the try block
            logger.error(f"Socket connect failed: {e}")
            return False

    def disconnect(self):
        self.sio.disconnect()

    def is_connected(self):
        return self.sio.connected

    def _on_connect(self):
        logger.info("Connected to backend")

    def _on_disconnect(self):
        logger.warning("Disconnected from backend")

    def _on_command(self, data):
        t = data.get("type")

        if t == "PLAYLIST_UPDATE" and self.on_playlist_update:
            logger.info(
                f"[Socket] PLAYLIST_UPDATE received: {len(data.get('playlist', []))} tracks")
            self.on_playlist_update(data["playlist"])

        if t == "PLAY" and self.on_play_command:
            self.on_play_command(data["audio"])

        elif t == "STOP" and self.on_stop_command:
            self.on_stop_command()

        elif t == "SCHEDULE_UPDATE" and self.on_schedule_update:
            self.on_schedule_update(data["schedule"])

        elif t == "VOLUME" and self.on_volume_update:
            self.on_volume_update(data["masterVolume"], data["branchVolume"])

        elif t == "DOWNLOAD_AUDIO" and self.on_audio_download:
            self.on_audio_download(data["audio"])

    def send_heartbeat(self, status, current_audio, volume, mode="IDLE", audio_id=None, position_ms=0):
        if self.sio.connected:
            self.sio.emit("heartbeat", {
                "status": status,
                "current_audio": current_audio,
                "volume": volume,
                "mode": mode,
                "audio_id": audio_id,
                "position_ms": position_ms
            })
