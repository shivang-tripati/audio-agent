"""
System Tray - Optional tray icon for status visibility
Note: This is OPTIONAL and can be disabled for truly headless operation
"""

import logging
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
import threading
import platform

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"

class SystemTray:
    """Optional system tray icon for status visibility"""
    
    def __init__(self, on_exit=None):
        self.icon = None
        self.on_exit = on_exit
        self.status = "IDLE"
        self.enabled = False
        
    def start(self):
        if self.enabled:
            return
        """Start system tray icon"""
        if not IS_WINDOWS:
            logger.info("System tray not supported on this OS.")
            return
        try:
            # Create icon image
            image = self._create_icon()
            
            # Create menu
            menu = (
                item('Audio Agent', lambda: None, enabled=False),
                item('Status: Idle', lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                item('Exit', self._on_exit_clicked)
            )
            
            # Create icon
            self.icon = pystray.Icon(
                "AudioAgent",
                image,
                "Audio Agent",
                menu
            )
            if self.enabled:
                return
            
            self.icon.visible = True
            
            # Run in separate thread
            tray_thread = threading.Thread(target=self.icon.run, daemon=True)
            tray_thread.start()
            
            self.enabled = True
            logger.info("System tray icon started")
            
        except Exception as e:
            logger.warning(f"Failed to start system tray: {e}")
            self.enabled = False
    
    def stop(self):
        """Stop system tray icon"""
        if self.icon and self.enabled:
            self.icon.stop()
            self.enabled = False
            logger.info("System tray icon stopped")
    
    def update_status(self, status, audio_name=None):
        """
        Update tray icon status
        
        Args:
            status (str): Current status (IDLE, PLAYING, OFFLINE)
            audio_name (str, optional): Currently playing audio
        """
        if not self.enabled or not self.icon:
            return
        
        try:
            self.status = status
            
            # Update menu
            if audio_name:
                status_text = f"Status: {status} - {audio_name}"
            else:
                status_text = f"Status: {status}"
            
            menu = (
                item('Audio Agent', lambda: None, enabled=False),
                item(status_text, lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                item('Exit', self._on_exit_clicked)
            )
            
            self.icon.menu = menu
            self.icon.title = f"Audio Agent - {status}"

            
            # Update icon image based on status
            if status == "PLAYING":
                self.icon.icon = self._create_icon(color="green")
            elif status == "OFFLINE":
                self.icon.icon = self._create_icon(color="red")
            else:
                self.icon.icon = self._create_icon(color="blue")
            
        except Exception as e:
            logger.error(f"Failed to update tray status: {e}")
    
    def _create_icon(self, color="blue"):
        """
        Create tray icon image
        
        Args:
            color (str): Icon color
            
        Returns:
            PIL.Image: Icon image
        """
        # Create a simple colored circle icon
        size = 64
        image = Image.new('RGBA', (size, size), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        
        # Color map
        colors = {
            "blue": (52, 152, 219),
            "green": (46, 204, 113),
            "red": (231, 76, 60),
            "gray": (149, 165, 166)
        }
        
        color_rgb = colors.get(color, colors["blue"])
        
        # Draw circle
        padding = 8
        draw.ellipse(
            [padding, padding, size - padding, size - padding],
            fill=color_rgb,
            outline=(255, 255, 255)
        )
        
        return image
    
    def _on_exit_clicked(self):
        """Handle exit menu click"""
        logger.info("Exit requested from system tray")
        
        if self.on_exit:
            self.on_exit()
        
        self.stop()


# Integration example for main.py
"""
To enable system tray in main.py:

1. Import:
from system_tray import SystemTray

2. In AudioAgent.__init__:
self.tray = SystemTray(on_exit=self.stop)

3. In AudioAgent.start():
# Start tray icon (optional)
self.tray.start()

4. Update status in callbacks:
def _on_playback_start(self, audio_name):
    self.current_status = "PLAYING"
    self.current_audio = audio_name
    self.tray.update_status("PLAYING", audio_name)

def _on_playback_end(self, audio_name):
    self.current_status = "IDLE"
    self.current_audio = None
    self.tray.update_status("IDLE")

5. In AudioAgent.stop():
if self.tray:
    self.tray.stop()
"""

# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    def on_exit():
        print("Exit callback triggered")
    
    print("Testing System Tray...")
    tray = SystemTray(on_exit=on_exit)
    tray.start()
    
    import time
    time.sleep(2)
    
    print("Updating to PLAYING status...")
    tray.update_status("PLAYING", "test_audio.mp3")
    
    time.sleep(2)
    
    print("Updating to IDLE status...")
    tray.update_status("IDLE")
    
    time.sleep(2)
    
    print("Stopping tray...")
    tray.stop()