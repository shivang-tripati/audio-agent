"""
Local Agent API
HTTP server for tray UI to communicate with the agent.
Runs on 127.0.0.1:57821
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import socket
import logging
import traceback
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_PORT = 57821
FALLBACK_PORTS = [57822, 57823, 57824]


class ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            try:
                self.socket.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_EXCLUSIVEADDRUSE,
                    0
                )
            except Exception as e:
                logger.warning(f"Could not disable SO_EXCLUSIVEADDRUSE: {e}")
        super().server_bind()


class LocalAgentAPI:

    def __init__(self, agent, port=DEFAULT_PORT):
        self.agent = agent
        self.port = port
        self.actual_port = port
        self.server = None
        self._request_count = 0
        self._error_count = 0

    def start(self):
        agent = self.agent

        class Handler(BaseHTTPRequestHandler):
            api_instance = self

            def _json(self, data, status=200):
                try:
                    body = json.dumps(data).encode()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as e:
                    logger.error(f"Error writing response: {e}")

            def do_GET(self):
                self.api_instance._request_count += 1
                rid = self.api_instance._request_count
                logger.debug(f"[{rid}] GET {self.path}")

                try:
                    # --------------------------------------------------
                    # /status
                    # --------------------------------------------------
                    if self.path == "/status":
                        position = 0
                        duration = 0
                        if agent._mode == "PLAYLIST" and getattr(agent, "playlist_engine", None):
                            try:
                                state = agent.playlist_engine.get_current_state()
                                position = state.get("position_ms", 0)
                            except Exception as e:
                                logger.warning(f"[{rid}] Playlist state error: {e}")
                                
                        # Get actual duration from VLC
                        if agent.audio_controller:
                            try:
                                duration = agent.audio_controller.get_duration_ms()
                            except Exception:
                                pass

                        uptime = int(time.time() - agent.start_time)
                        volume = 0
                        if agent.volume_controller:
                            try:
                                volume = agent.volume_controller.get_volume()
                            except Exception:
                                pass

                        # Report the engine's real state while a playlist is
                        # driving playback - otherwise /status would echo a
                        # stale flag set by whoever last issued a command.
                        status = agent.current_status
                        engine = getattr(agent, "playlist_engine", None)
                        if agent._mode == "PLAYLIST" and engine is not None:
                            status = engine.get_state_name()

                        self._json({
                            "status": status,
                            "mode": agent._mode,
                            "audio": agent.current_audio,
                            "volume": volume,
                            "position_ms": position,
                            "duration_ms": duration,
                            "uptime": uptime,
                            "timestamp": datetime.now().isoformat()
                        })
                        return

                    # --------------------------------------------------
                    # /identity — device info for Tauri activation form
                    # --------------------------------------------------
                    if self.path == "/identity":
                        try:
                            from agent.device_identity import get_device_identity
                            from config_manager import ConfigManager
                            identity = get_device_identity()
                            config = ConfigManager()
                            identity["server_url"] = config.server_url or ""
                            self._json(identity)
                        except Exception as e:
                            logger.error(f"[{rid}] Identity error: {e}")
                            self._json({"error": str(e)}, 500)
                        return

                    # --------------------------------------------------
                    # /config — activation status for Tauri
                    # --------------------------------------------------
                    if self.path == "/config":
                        try:
                            from config_manager import ConfigManager
                            config = ConfigManager()
                            self._json({
                                "activated": bool(config.token),
                                "server_url": config.server_url or "",
                                "branch_id": getattr(config, 'branch_id', None)
                            })
                        except Exception as e:
                            logger.error(f"[{rid}] Config error: {e}")
                            self._json({"error": str(e)}, 500)
                        return

                    # --------------------------------------------------
                    # /ping
                    # --------------------------------------------------
                    if self.path == "/ping":
                        self._json({"ok": True})
                        return

                    logger.warning(f"[{rid}] Unknown GET: {self.path}")
                    self._json({"error": "not found"}, 404)

                except Exception as e:
                    self.api_instance._error_count += 1
                    logger.error(f"[{rid}] GET error: {e}\n{traceback.format_exc()}")
                    self._json({"error": "internal error"}, 500)

            def do_POST(self):
                self.api_instance._request_count += 1
                rid = self.api_instance._request_count
                logger.debug(f"[{rid}] POST {self.path}")

                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)

                    try:
                        data = json.loads(body or "{}")
                    except json.JSONDecodeError:
                        data = {}

                    # --------------------------------------------------
                    # /stop — stop playlist engine + playback
                    # --------------------------------------------------
                    if self.path == "/stop":
                        try:
                            if agent.playlist_engine:
                                agent.playlist_engine.stop()
                            if agent.playback_controller:
                                agent.playback_controller.stop()
                            agent._mode = "IDLE"
                            agent.current_status = "IDLE"
                            self._json({"ok": True, "status": agent.current_status})
                            logger.info(f"[{rid}] Stop completed")
                        except Exception as e:
                            logger.error(f"[{rid}] Stop failed: {e}")
                            raise
                        return

                    # --------------------------------------------------
                    # /pause — pause VLC at current position
                    # --------------------------------------------------
                    if self.path == "/pause":
                        try:
                            if agent.playlist_engine:
                                agent.playlist_engine.pause()
                                agent.current_status = agent.playlist_engine.get_state_name()
                            self._json({
                                "ok": True,
                                "status": agent.current_status,
                            })
                            logger.info(f"[{rid}] Paused -> {agent.current_status}")
                        except Exception as e:
                            logger.error(f"[{rid}] Pause failed: {e}")
                            raise
                        return

                    # --------------------------------------------------
                    # /resume — resume VLC from paused position
                    # --------------------------------------------------
                    if self.path == "/resume":
                        try:
                            if agent.playlist_engine:
                                agent.playlist_engine.resume()
                                agent.current_status = agent.playlist_engine.get_state_name()
                            self._json({
                                "ok": True,
                                "status": agent.current_status,
                            })
                            logger.info(f"[{rid}] Resumed -> {agent.current_status}")
                        except Exception as e:
                            logger.error(f"[{rid}] Resume failed: {e}")
                            raise
                        return

                    # --------------------------------------------------
                    # /playlist/start — start playlist engine
                    # --------------------------------------------------
                    if self.path == "/playlist/start":
                        try:
                            if agent.playlist_engine:
                                agent.playlist_engine.start()
                                agent._mode = "PLAYLIST"
                                agent.current_status = agent.playlist_engine.get_state_name()
                            self._json({
                                "ok": True,
                                "status": agent.current_status,
                            })
                            logger.info(
                                f"[{rid}] Playlist start -> {agent.current_status}")
                        except Exception as e:
                            logger.error(f"[{rid}] Playlist start failed: {e}")
                            raise
                        return

                    # --------------------------------------------------
                    # /volume — set VLC session volume only
                    # --------------------------------------------------
                    if self.path == "/volume":
                        try:
                            v = int(data.get("volume", 100))
                            v = max(0, min(100, v))
                            if agent.volume_controller:
                                agent.volume_controller.set_volume(v)
                            if agent.audio_controller:
                                agent.audio_controller.set_volume(v)
                            logger.info(f"[{rid}] Volume set to {v}%")
                        except Exception as e:
                            logger.error(f"[{rid}] Volume failed: {e}")
                            raise
                        self._json({"ok": True})
                        return

                    # --------------------------------------------------
                    # /config/save — save token after Tauri activation
                    # --------------------------------------------------
                    if self.path == "/config/save":
                        try:
                            from config_manager import ConfigManager
                            config = ConfigManager()
                            config.update_server_settings(
                                server_url=data.get("server_url"),
                                token=data.get("token"),
                                branch_id=data.get("branch_id")
                            )
                            logger.info(f"[{rid}] Config saved")
                            self._json({"ok": True})
                        except Exception as e:
                            logger.error(f"[{rid}] Config save failed: {e}")
                            self._json({"error": str(e)}, 500)
                        return

                    logger.warning(f"[{rid}] Unknown POST: {self.path}")
                    self._json({"error": "not found"}, 404)

                except Exception as e:
                    self.api_instance._error_count += 1
                    logger.error(f"[{rid}] POST error: {e}\n{traceback.format_exc()}")
                    self._json({"error": "internal error"}, 500)

            def log_message(self, *args):
                return  # suppress default request logging

        ports_to_try = [self.port] + FALLBACK_PORTS

        for port in ports_to_try:
            try:
                self.server = ReusableHTTPServer(("127.0.0.1", port), Handler)
                self.actual_port = port

                if port != self.port:
                    logger.warning(
                        f"Default port {self.port} busy — "
                        f"bound to fallback port {port}"
                    )
                else:
                    logger.info(f"LocalAgentAPI started on 127.0.0.1:{port}")

                threading.Thread(
                    target=self.server.serve_forever,
                    daemon=True,
                    name="LocalAPIServer"
                ).start()

                return

            except OSError as e:
                logger.warning(f"Port {port} unavailable: {e}")
                continue

        logger.error(
            f"LocalAgentAPI failed to bind on any port {ports_to_try}. "
            f"Tray UI will not work but agent continues running."
        )

    def stop(self):
        if self.server:
            self.server.shutdown()
            logger.info("LocalAgentAPI stopped")

    def get_api_url(self):
        return f"http://127.0.0.1:{self.actual_port}"

    def get_stats(self):
        return {
            "port": self.actual_port,
            "requests": self._request_count,
            "errors": self._error_count
        }