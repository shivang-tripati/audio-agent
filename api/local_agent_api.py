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

logger = logging.getLogger(__name__)

DEFAULT_PORT = 57821
FALLBACK_PORTS = [57822, 57823, 57824]  # try these if default is busy


# --------------------------------------------------
# FIX #7: Custom server that handles port reuse on Windows
# --------------------------------------------------

class ReusableHTTPServer(ThreadingHTTPServer):
    # Standard reuse — helps on Linux/Mac
    allow_reuse_address = True

    def server_bind(self):
        """
        FIX #7: On Windows, SO_REUSEADDR alone is not enough.
        We explicitly disable SO_EXCLUSIVEADDRUSE which Windows
        sets by default and which blocks port reuse even when
        allow_reuse_address = True.

        Without this, a fast service restart fails with:
        'Only one usage of each socket address is normally permitted'
        """
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            # Disable exclusive address use so we can rebind quickly
            self.socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                0
            )
        super().server_bind()


# --------------------------------------------------
# API Server
# --------------------------------------------------

class LocalAgentAPI:

    def __init__(self, agent, port=DEFAULT_PORT):
        self.agent = agent
        self.port = port
        self.actual_port = port  # may differ if fallback used
        self.server = None

    def start(self):
        """
        Start the HTTP server.
        FIX #7: Retries on fallback ports if default is still in use.
        Logs clearly which port was bound so tray UI can know.
        """
        agent = self.agent

        class Handler(BaseHTTPRequestHandler):

            def _json(self, data, status=200):
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                try:
                    if self.path == "/status":
                        position = 0
                        if agent._mode == "PLAYLIST" and getattr(agent, "playlist_engine", None):
                            state = agent.playlist_engine.get_current_state()
                            position = state.get("position_ms", 0)

                        uptime = int(time.time() - agent.start_time)

                        self._json({
                            "status": agent.current_status,
                            "mode": agent._mode,
                            "audio": agent.current_audio,
                            "volume": agent.volume_controller.get_volume() if agent.volume_controller else 40,
                            "position_ms": position,
                            "uptime": uptime
                        })
                        return

                    if self.path == "/ping":
                        self._json({"ok": True})
                        return

                    self._json({"error": "not found"}, 404)

                except Exception:
                    logger.exception("Local API GET error")
                    self._json({"error": "internal error"}, 500)

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)

                    try:
                        data = json.loads(body or "{}")
                    except Exception:
                        data = {}

                    if self.path == "/volume":
                        v = int(data.get("volume", 100))
                        if agent.volume_controller:
                            agent.volume_controller.set_volume(v)
                        self._json({"ok": True})
                        return

                    if self.path == "/stop":
                        if agent.playback_controller:
                            agent.playback_controller.stop()
                        self._json({"ok": True})
                        return

                    self._json({"error": "not found"}, 404)

                except Exception:
                    logger.exception("Local API POST error")
                    self._json({"error": "internal error"}, 500)

            def log_message(self, *args):
                return  # suppress default request logging

        # FIX #7: Try default port first, then fallbacks
        ports_to_try = [self.port] + FALLBACK_PORTS

        for port in ports_to_try:
            try:
                self.server = ReusableHTTPServer(("127.0.0.1", port), Handler)
                self.actual_port = port

                if port != self.port:
                    logger.warning(
                        f"Default port {self.port} was busy — "
                        f"bound to fallback port {port}"
                    )
                else:
                    logger.info(f"LocalAgentAPI started on 127.0.0.1:{port}")

                # Start server in background thread
                threading.Thread(
                    target=self.server.serve_forever,
                    daemon=True
                ).start()

                return  # success — stop trying ports

            except OSError as e:
                logger.warning(f"Port {port} unavailable: {e}")
                continue

        # All ports failed — log clearly but don't crash the agent
        logger.error(
            f"LocalAgentAPI failed to bind on any port {ports_to_try}. "
            f"Tray UI will not work but agent continues running."
        )

    def stop(self):
        if self.server:
            self.server.shutdown()
            logger.info("LocalAgentAPI stopped")

    def get_api_url(self):
        """Returns the actual URL the API is running on"""
        return f"http://127.0.0.1:{self.actual_port}"