"""
Read-Only Status Panel with Glass Morphism Design
Features: Real-time data display, minimal logging, clean aesthetics
Positions above taskbar with proper margins
Fixed status display - shows PLAYING, PAUSED, or IDLE correctly
"""

import pystray
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageDraw
import requests
import logging
from datetime import datetime

# Use your existing logger setup
ui_logger = logging.getLogger("StatusPanel")

# Set level if not already configured
if ui_logger.level == logging.NOTSET:
    ui_logger.setLevel(logging.DEBUG)


class ModernStatusPanel:
    """
    Modern Status Panel - Read-Only Version (v3.0)
    - Display-only (no user controls)
    - Glass morphism design
    - Real-time polling from API
    - Positioned above taskbar
    - Fixed status display (shows PLAYING correctly, not IDLE)
    """

    def __init__(self, api_url_getter):
        ui_logger.info("Initializing ModernStatusPanel")
        self.get_api_url = api_url_getter
        self.window = None
        self._poll_thread = None
        self._running = False
        self._last_status = None
        self._api_error_count = 0
        self._max_retries = 3

    def show(self):
        """Show the panel, bring to front if already open"""
        ui_logger.info("show() called")
        if self.window and self.window.winfo_exists():
            ui_logger.debug("Window already exists, lifting to front")
            self.window.lift()
            self.window.focus_force()
            return

        self._build_window()
        self._running = True
        self._api_error_count = 0
        
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="StatusPanel-Poller"
        )
        self._poll_thread.start()
        ui_logger.info("Status panel shown, polling thread started")

    def _build_window(self):
        """Build the tkinter window with modern styling"""
        ui_logger.debug("Building window")
        self.window = tk.Toplevel()
        self.window.title("RedioCast Status")
        self.window.resizable(False, False)
        self.window.overrideredirect(True)  # No title bar
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#F5F5F5")

        # Glass morphism effect
        self.window.attributes("-alpha", 0.98)

        # Position above taskbar with proper margins
        w, h = 380, 440
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        
        # Right side, above taskbar with 16px margin from edges
        x = sw - w - 16
        y = sh - h - 64  # 64px above taskbar (48px + 16px margin)
        
        ui_logger.debug(f"Window geometry: {w}x{h}+{x}+{y} (screen: {sw}x{sh})")
        self.window.geometry(f"{w}x{h}+{x}+{y}")

        # Close on Escape
        self.window.bind("<Escape>", lambda e: self._close())
        self.window.bind("<Button-1>", self._on_window_click)

        self._build_ui()
        self.window.focus_force()
        ui_logger.info("Window built and focused")

    def _build_ui(self):
        """Build the read-only UI with modern design"""
        w = self.window
        
        # Modern color palette - Windows Fluent Design
        BG = "#F5F5F5"
        CARD = "#FFFFFF"
        BORDER = "#E0E0E0"
        TEXT = "#1E1E1E"
        MUTED = "#666666"
        LIGHT_MUTED = "#999999"
        GREEN = "#16A34A"  # Modern green
        AMBER = "#D97706"  # Modern amber
        RED = "#DC2626"    # Modern red
        ACCENT = "#0084FF"  # Windows blue
        
        ui_logger.debug("Building read-only UI with modern color scheme")

        # Fonts
        try:
            title_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
            header_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
            body_font = tkfont.Font(family="Segoe UI", size=10, weight="normal")
            small_font = tkfont.Font(family="Segoe UI", size=9, weight="normal")
        except Exception as e:
            ui_logger.warning(f"Font loading failed: {e}, using defaults")
            title_font = header_font = body_font = small_font = None

        # Main container with padding
        main = tk.Frame(w, bg=BG)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        # === HEADER ===
        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", pady=(0, 12))

        title = tk.Label(
            header,
            text="🎵 RedioCast Player",
            bg=BG,
            fg=TEXT,
            font=title_font,
            anchor="w"
        )
        title.pack(side="left", expand=True)

        close_btn = tk.Label(
            header,
            text="✕",
            bg=BG,
            fg=LIGHT_MUTED,
            font=body_font,
            cursor="hand2",
            padx=8,
            pady=4
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._close())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=TEXT))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=LIGHT_MUTED))

        # Separator
        tk.Frame(main, bg=BORDER, height=1).pack(fill="x", pady=(0, 12))

        # === NOW PLAYING CARD ===
        np_frame = tk.Frame(main, bg=CARD, relief=tk.FLAT, bd=0)
        np_frame.pack(fill="x", pady=(0, 12))
        np_frame.config(highlightbackground=BORDER, highlightthickness=1)

        np_inner = tk.Frame(np_frame, bg=CARD)
        np_inner.pack(fill="both", padx=14, pady=12, expand=True)

        # Track label
        self.track_label = tk.Label(
            np_inner,
            text="Waiting for service...",
            bg=CARD,
            fg=TEXT,
            font=header_font,
            anchor="w",
            wraplength=320
        )
        self.track_label.pack(fill="x", pady=(0, 6))

        # Metadata label
        self.meta_label = tk.Label(
            np_inner,
            text="—",
            bg=CARD,
            fg=MUTED,
            font=small_font,
            anchor="w",
            wraplength=320
        )
        self.meta_label.pack(fill="x", pady=(0, 8))

        # Progress bar
        prog_frame = tk.Frame(np_inner, bg=BORDER, height=4)
        prog_frame.pack(fill="x", pady=(0, 8))
        
        self.prog_fill = tk.Frame(prog_frame, bg=ACCENT, height=4)
        self.prog_fill.place(x=0, y=0, relheight=1, relwidth=0)

        # Status badge
        self.badge_label = tk.Label(
            np_inner,
            text="● CONNECTING",
            bg=CARD,
            fg=LIGHT_MUTED,
            font=small_font,
            anchor="e"
        )
        self.badge_label.pack(anchor="e")

        # === STATISTICS ROW ===
        stats_frame = tk.Frame(main, bg=BG)
        stats_frame.pack(fill="x", pady=(0, 12))

        self.stat_service = self._create_stat_card(
            stats_frame, "Service", "—", BG, CARD, BORDER, TEXT, MUTED, small_font
        )
        self.stat_uptime = self._create_stat_card(
            stats_frame, "Uptime", "—", BG, CARD, BORDER, TEXT, MUTED, small_font
        )
        self.stat_volume = self._create_stat_card(
            stats_frame, "Volume", "—", BG, CARD, BORDER, TEXT, MUTED, small_font
        )

        self.stat_service.pack(side="left", expand=True, fill="both", padx=(0, 6))
        self.stat_uptime.pack(side="left", expand=True, fill="both", padx=(3, 3))
        self.stat_volume.pack(side="left", expand=True, fill="both", padx=(6, 0))

        # === FOOTER ===
        tk.Frame(main, bg=BORDER, height=1).pack(fill="x", pady=(0, 12))

        footer = tk.Frame(main, bg=BG)
        footer.pack(fill="x")

        exit_btn = tk.Label(
            footer,
            text="Exit Tray",
            bg=BG,
            fg=RED,
            font=small_font,
            cursor="hand2",
            padx=4,
            pady=4
        )
        exit_btn.pack(side="left")
        exit_btn.bind("<Button-1>", lambda e: self._exit_tray())
        exit_btn.bind("<Enter>", lambda e: exit_btn.config(fg="#E53E3E"))
        exit_btn.bind("<Leave>", lambda e: exit_btn.config(fg=RED))

        version_label = tk.Label(
            footer,
            text="v3.0 (Read-Only)",
            bg=BG,
            fg=LIGHT_MUTED,
            font=small_font
        )
        version_label.pack(side="right")

        ui_logger.info("UI built successfully")

    def _create_stat_card(self, parent, label, value,
                   BG, CARD, BORDER, TEXT, MUTED, font):
        """Create a stat card component"""
        frame = tk.Frame(parent, bg=CARD, relief=tk.FLAT, bd=0)
        frame.config(highlightbackground=BORDER, highlightthickness=1)

        tk.Label(
            frame,
            text=label,
            bg=CARD,
            fg=MUTED,
            font=font
        ).pack(pady=(8, 4))

        val = tk.Label(
            frame,
            text=value,
            bg=CARD,
            fg=TEXT,
            font=(font.cget("family"), font.cget("size"), "bold") if font else None
        )
        val.pack(pady=(0, 8))
        frame._value_label = val    
        return frame

    def _poll_loop(self):
        """Poll API for status updates"""
        ui_logger.info("Polling thread started")
        
        while self._running:
            try:
                if not self.window or not self.window.winfo_exists():
                    ui_logger.debug("Window closed, exiting poll loop")
                    break

                url = self.get_api_url()
                ui_logger.debug(f"Polling {url}/status")
                
                try:
                    r = requests.get(f"{url}/status", timeout=2)
                    r.raise_for_status()
                    
                    status_data = r.json()
                    current_status = status_data.get('status', 'IDLE')
                    ui_logger.debug(f"Status received: {current_status}")
                    
                    self._api_error_count = 0  # Reset error counter
                    self.window.after(0, lambda d=status_data: self._update_ui(d))
                    
                except requests.RequestException as e:
                    self._api_error_count += 1
                    ui_logger.warning(
                        f"API request failed (attempt {self._api_error_count}): {e}"
                    )
                    
                    if self._api_error_count >= self._max_retries:
                        self.window.after(0, self._update_offline)
                        
            except Exception as e:
                ui_logger.error(f"Poll loop error: {e}", exc_info=True)
                if self.window and self.window.winfo_exists():
                    self.window.after(0, self._update_offline)

            time.sleep(1)  # Poll every 1 second for real-time responsiveness

    def _update_ui(self, status_data):
        """Update UI with new status"""
        if not self.window or not self.window.winfo_exists():
            return

        try:
            # Color definitions
            ACCENT = "#0084FF"
            GREEN = "#16A34A"
            AMBER = "#D97706"
            RED = "#DC2626"
            MUTED = "#666666"
            TEXT = "#1E1E1E"
            LIGHT_MUTED = "#999999"

            # Extract data from server response
            status = status_data.get("status", "IDLE")  # PLAYING, PAUSED, or IDLE
            audio = status_data.get("audio") or "Nothing playing"
            pos_ms = status_data.get("position_ms", 0)
            duration_ms = status_data.get("duration_ms", 0)
            uptime = int(status_data.get("uptime", 0))
            volume = int(status_data.get("volume", 0))
            mode = status_data.get("mode", "IDLE")

            # Log state changes
            if status != self._last_status:
                ui_logger.info(f"Status changed: {self._last_status} -> {status}")
                self._last_status = status

            # === UPDATE TRACK LABEL ===
            self.track_label.config(text=audio[:55] if audio else "Nothing playing")

            # === UPDATE METADATA ===
            pos_s = pos_ms // 1000
            dur_s = duration_ms // 1000
            mins, secs = divmod(pos_s, 60)
            dur_mins, dur_secs = divmod(dur_s, 60)
            uptime_m = uptime // 60
            
            # Format time string
            if dur_s > 0:
                time_str = f"{mins:02d}:{secs:02d} / {dur_mins:02d}:{dur_secs:02d}"
            else:
                time_str = f"{mins:02d}:{secs:02d}"
            
            # Format uptime
            if uptime_m < 60:
                uptime_str = f"{uptime_m}m"
            else:
                hours, minutes = divmod(uptime_m, 60)
                uptime_str = f"{hours}h {minutes}m"

            self.meta_label.config(
                text=f"{mode} · {time_str} · Up {uptime_str}"
            )

            # === UPDATE PROGRESS BAR ===
            if duration_ms and duration_ms > 0:
                prog = min(pos_ms / duration_ms, 1.0)
            else:
                prog = 0.0

            self.prog_fill.place(relwidth=max(0, prog))

            # === UPDATE STATUS BADGE ===
            # FIX: Use actual status from server, not assumption
            badge_map = {
                "PLAYING": (GREEN, "● PLAYING"),
                "PAUSED": (AMBER, "⏸ PAUSED"),
                "IDLE": (LIGHT_MUTED, "○ IDLE"),
            }
            color, badge_text = badge_map.get(status, (LIGHT_MUTED, f"● {status}"))
            self.badge_label.config(text=badge_text, fg=color)

            # === UPDATE STATS ===
            self.stat_service._value_label.config(text="Running", fg=GREEN)
            self.stat_uptime._value_label.config(text=uptime_str, fg=TEXT)
            self.stat_volume._value_label.config(text=f"{volume}%", fg=TEXT)

        except Exception as e:
            ui_logger.error(f"UI update error: {e}", exc_info=True)

    def _update_offline(self):
        """Update UI for offline state"""
        if not self.window or not self.window.winfo_exists():
            return

        ui_logger.warning("Service offline, updating UI")
        
        try:
            RED = "#DC2626"
            LIGHT_MUTED = "#999999"
            
            self.track_label.config(text="Service Offline")
            self.meta_label.config(text="Cannot reach agent service")
            self.badge_label.config(text="● OFFLINE", fg=RED)
            self.stat_service._value_label.config(text="Stopped", fg=RED)
            self.stat_uptime._value_label.config(text="—", fg=LIGHT_MUTED)
            self.stat_volume._value_label.config(text="—", fg=LIGHT_MUTED)
        except Exception as e:
            ui_logger.error(f"Error updating offline state: {e}")

    def _exit_tray(self):
        """Exit the tray application"""
        ui_logger.info("Exit requested from UI")
        self._close()
        if self._on_exit:
            self._on_exit()

    def _close(self):
        """Close the panel"""
        ui_logger.info("Closing status panel")
        self._running = False
        
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        
        self.window = None

    def _on_window_click(self, event):
        """Log window interactions (minimal)"""
        ui_logger.debug(f"Window click at ({event.x}, {event.y})")

    # Callback for exit
    _on_exit = None


# Backward compatibility alias
StatusPanel = ModernStatusPanel