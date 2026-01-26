"""
Volume Controller - Windows System Volume Control
Uses pycaw to control Windows Core Audio APIs
"""

import logging
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

logger = logging.getLogger(__name__)


class VolumeController:
    """Controls Windows system volume using Core Audio APIs"""
    
    def __init__(self):
        self.volume_interface = None
        self.current_volume = 0
        self._initialize()
    
    def _initialize(self):
        """Initialize COM audio interface"""
        try:
            # Get default audio device
            devices = AudioUtilities.GetSpeakers()
            
            # Get audio endpoint volume interface
            interface = devices.Activate(
                IAudioEndpointVolume._iid_,
                CLSCTX_ALL,
                None
            )
            
            self.volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
            
            # Get current volume
            self.current_volume = int(self.volume_interface.GetMasterVolumeLevelScalar() * 100)
            
            logger.info(f"Volume controller initialized. Current volume: {self.current_volume}%")
            
        except Exception as e:
            logger.error(f"Failed to initialize volume controller: {e}")
            raise
    
    def set_volume(self, volume_percent):
        """
        Set system volume
        
        Args:
            volume_percent (int): Volume level 0-100
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate input
            if not isinstance(volume_percent, (int, float)):
                logger.error(f"Invalid volume type: {type(volume_percent)}")
                return False
            
            # Clamp to valid range
            volume_percent = max(0, min(100, int(volume_percent)))
            
            # Convert to scalar (0.0 - 1.0)
            volume_scalar = volume_percent / 100.0
            
            # Set volume
            self.volume_interface.SetMasterVolumeLevelScalar(volume_scalar, None)
            
            # Verify
            actual_volume = int(self.volume_interface.GetMasterVolumeLevelScalar() * 100)
            self.current_volume = actual_volume
            
            logger.info(f"Volume set to {actual_volume}% (requested: {volume_percent}%)")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")
            return False
    
    def get_volume(self):
        """
        Get current system volume
        
        Returns:
            int: Current volume level 0-100
        """
        try:
            volume_scalar = self.volume_interface.GetMasterVolumeLevelScalar()
            self.current_volume = int(volume_scalar * 100)
            return self.current_volume
        except Exception as e:
            logger.error(f"Failed to get volume: {e}")
            return self.current_volume
    
    def is_muted(self):
        """
        Check if system is muted
        
        Returns:
            bool: True if muted, False otherwise
        """
        try:
            return self.volume_interface.GetMute()
        except Exception as e:
            logger.error(f"Failed to check mute status: {e}")
            return False
    
    def unmute(self):
        """
        Unmute system audio
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.volume_interface.SetMute(0, None)
            logger.info("System unmuted")
            return True
        except Exception as e:
            logger.error(f"Failed to unmute: {e}")
            return False


# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Volume Controller...")
    vc = VolumeController()
    
    print(f"Current volume: {vc.get_volume()}%")
    print(f"Is muted: {vc.is_muted()}")
    
    print("\nSetting volume to 50%...")
    vc.set_volume(50)
    
    print(f"New volume: {vc.get_volume()}%")