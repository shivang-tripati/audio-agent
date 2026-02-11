"""
Volume Controller - Ubuntu (Linux) System Volume Control
Uses pulsectl to control PulseAudio/PipeWire servers
"""

import logging
import pulsectl

logger = logging.getLogger(__name__)

class VolumeController:
    """Controls Ubuntu system volume using PulseAudio APIs"""
    
    def __init__(self):
        self.pulse = pulsectl.Pulse('volume-controller')
        self.current_volume = 0
        self._initialize()
    
    def _initialize(self):
        """Initialize PulseAudio interface"""
        try:
            # Get default sink (output device)
            server_info = self.pulse.server_info()
            sink_name = server_info.default_sink_name
            
            # Find the sink object
            self.sink = self.pulse.get_sink_by_name(sink_name)
            
            # Get current volume (taking the average of all channels)
            self.current_volume = int(self.pulse.volume_get_all_chans(self.sink) * 100)
            
            logger.info(f"Ubuntu Volume controller initialized. Sink: {sink_name}")
            logger.info(f"Current volume: {self.current_volume}%")
            
        except Exception as e:
            logger.error(f"Failed to initialize PulseAudio controller: {e}")
            raise

    def _refresh_sink(self):
        """Update the sink reference to get latest status"""
        self.sink = self.pulse.get_sink_by_name(self.pulse.server_info().default_sink_name)

    def set_volume(self, volume_percent):
        """Set system volume (0-100)"""
        try:
            if not isinstance(volume_percent, (int, float)):
                return False
            
            volume_percent = max(0, min(100, int(volume_percent)))
            volume_scalar = volume_percent / 100.0
            
            # Set volume for all channels
            self.pulse.volume_set_all_chans(self.sink, volume_scalar)
            
            self.current_volume = volume_percent
            logger.info(f"Volume set to {volume_percent}%")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")
            return False
    
    def get_volume(self):
        """Get current system volume"""
        try:
            self._refresh_sink()
            self.current_volume = int(self.pulse.volume_get_all_chans(self.sink) * 100)
            return self.current_volume
        except Exception as e:
            logger.error(f"Failed to get volume: {e}")
            return self.current_volume
    
    def is_muted(self):
        """Check if system is muted (0 = unmuted, 1 = muted in Pulse)"""
        try:
            self._refresh_sink()
            return bool(self.sink.mute)
        except Exception as e:
            logger.error(f"Failed to check mute status: {e}")
            return False
    
    def unmute(self):
        """Unmute system audio"""
        try:
            self.pulse.mute(self.sink, False)
            logger.info("System unmuted")
            return True
        except Exception as e:
            logger.error(f"Failed to unmute: {e}")
            return False

# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Ubuntu Volume Controller...")
    vc = VolumeController()
    
    print(f"Current volume: {vc.get_volume()}%")
    print(f"Is muted: {vc.is_muted()}")
    
    print("\nSetting volume to 50%...")
    vc.set_volume(50)
    
    print(f"New volume: {vc.get_volume()}%")  