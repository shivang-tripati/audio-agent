from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from comtypes import CLSCTX_ALL
import logging

logger = logging.getLogger(__name__)

class VolumeController:
    def __init__(self):
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(
            IAudioEndpointVolume._iid_, CLSCTX_ALL, None
        )
        self.volume = interface.QueryInterface(IAudioEndpointVolume)

    def set_volume(self, volume_percent: int):
        try:
            volume_percent = max(0, min(100, int(volume_percent)))
            scalar = volume_percent / 100.0
            self.volume.SetMasterVolumeLevelScalar(scalar, None)
            logger.info(f"Volume set to {volume_percent}%")
        except Exception as e:
            logger.error(f"Failed to set Windows volume: {e}")
