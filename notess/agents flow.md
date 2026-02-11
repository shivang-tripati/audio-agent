device_code  → only for activation
device_token → permanent
Socket.IO connection
AudioScheduler
AudioController
Watchdog
ConfigManager

1️⃣ Pair once
POST /api/devices/activate
→ get token
→ save token

2️⃣ Connect
sio.connect(server_url, auth={"token": token})
socket.on("command")

3️⃣ Receive commands
socket.on("command")


Send heartbeats
sio.emit("heartbeat", {
  "status": "PLAYING",
  "current_audio": "xyz.mp3",
  "volume": 65
})


5️⃣ Run local scheduler for offline cases


6️⃣ Watchdog detects crashes


7️⃣ ConfigManager handles offline config


8️⃣ AudioController plays audio

🧠 9. What works today

| Module            | Status              |
| ----------------- | ------------------- |
| Device activation | ✅                   |
| Audio playback    | ✅                   |
| Scheduler logic   | ✅                   |
| Offline schedule  | ✅                   |
| Volume control    | ✅                   |
| Watchdog          | ✅                   |
| ServerClient      | ❌ Must be rewritten |
| Heartbeat         | ❌ Wrong protocol    |
| Auth              | ❌ Wrong             |


🟢 10. The good news

You do NOT need to rewrite everything.

You need to rewrite:

ServerClient

_send_heartbeat

Agent connect() logic