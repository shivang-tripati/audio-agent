from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import logging

logger = logging.getLogger(__name__)


class ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class LocalAgentAPI:

    def __init__(self, agent, port=57821):
        self.agent = agent
        self.port = port
        self.server = None

    def start(self):

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

                except Exception as e:
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
                return

        self.server = ReusableHTTPServer(("127.0.0.1", self.port), Handler)

        logger.info(f"LocalAgentAPI started on 127.0.0.1:{self.port}")

        threading.Thread(
            target=self.server.serve_forever,
            daemon=True
        ).start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            logger.info("LocalAgentAPI stopped")
