from pycaw.pycaw import AudioUtilities
import psutil
import logging
import time

logger = logging.getLogger(__name__)


class VolumeController:

    def __init__(self):
        self.pid = psutil.Process().pid
        self.volume = None
        self.last_volume = 100

    def _find_session(self):
        sessions = AudioUtilities.GetAllSessions()

        for session in sessions:
            if session.Process and session.Process.pid == self.pid:
                self.volume = session.SimpleAudioVolume
                logger.info("AudioAgent session attached")
                return True

        return False

    def _ensure_session(self):
        if self.volume:
            return True

        # retry a few times because session appears only after playback starts
        for _ in range(5):
            if self._find_session():
                return True
            time.sleep(0.5)

        logger.warning("Audio session still not available")
        return False

    def set_volume(self, volume_percent):

        volume_percent = max(0, min(100, int(volume_percent)))
        self.last_volume = volume_percent

        try:
            if hasattr(self, "audio_controller"):
                self.audio_controller.player.audio_set_volume(volume_percent)
        except:
            pass

        if not self._ensure_session():
            return

        try:
            scalar = volume_percent / 100.0
            self.volume.SetMasterVolume(scalar, None)
        except Exception:
            self.volume = None

    def get_volume(self) -> int:
        try:

            if not self._ensure_session():
                return self.last_volume if hasattr(self, "last_volume") else 100

            scalar = self.volume.GetMasterVolume()
            volume = int(scalar * 100)
            self.last_volume = volume
            return volume

        except Exception as e:
            logger.error(f"Failed to get agent volume: {e}")
            self.volume = None
            return self.last_volume if hasattr(self, "last_volume") else 100
