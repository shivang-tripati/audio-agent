2️⃣ Critical gaps you should fix (before production)

These are not cosmetic — they matter in real deployments.

⚠️ 1. Device authentication model is incomplete

Right now:

GET /device/sync?device_code=MUM-001-DEV-01


❌ Problem:

device_code alone is spoofable

No token rotation

No expiry

No device-level authorization

✅ REQUIRED FIX

Add device token authentication:

Authorization: Bearer <DEVICE_JWT>


And return this in /devices/register:

{
  "device_code": "MUM-001-DEV-01",
  "device_token": "device-jwt-token",
  "expires_at": "2026-02-01T00:00:00Z"
}


Your agent already supports this conceptually.

⚠️ 2. Timezone handling is missing (this WILL break)

Schedules use:

"play_time": "10:00:00"


❌ What timezone?

Branch timezone?

Server timezone?

Device timezone?

✅ REQUIRED FIX

Add this to /device/sync response:

"timezone": "Asia/Kolkata"


And define rule:

All play_time values are branch-local time

Your agent scheduler can then safely do:

datetime.now(branch_timezone)

⚠️ 3. No schedule versioning / delta support

Right now devices must:

Download full schedule every time

Re-cache blindly

This is inefficient at scale.

✅ STRONGLY RECOMMENDED

Add:

"schedule_version": 17,
"generated_at": "2026-01-01T00:00:00Z"


And allow:

GET /device/sync?device_code=...&last_version=16


Response:

{
  "unchanged": true
}


This saves bandwidth + CPU.

⚠️ 4. No “missed schedule recovery” policy

If:

Device was OFF at 10:00

Comes online at 10:05

What should happen?

✅ ADD THIS (backend decides)
"recovery_policy": {
  "enabled": true,
  "max_delay_minutes": 10
}


Your agent already supports this logic conceptually.

⚠️ 5. Heartbeat is too weak for monitoring

Current heartbeat:

{
  "device_code": "...",
  "online": true
}


This is not enough for operations.

✅ Upgrade heartbeat payload
{
  "device_code": "MUM-001-DEV-01",
  "online": true,
  "status": "IDLE | PLAYING | ERROR",
  "current_audio": "Morning Prayer - Hindi",
  "agent_version": "1.0.0",
  "uptime_seconds": 86400,
  "last_error": null,
  "disk_free_mb": 2048
}


This enables:

Health dashboard

Alerts

SLA monitoring

3️⃣ Small additions that give BIG power

These are low effort, high value.

🔹 A. Manual Play (Emergency / Test)

Add:

POST /device/command

{
  "device_code": "MUM-001-DEV-01",
  "command": "PLAY",
  "audio_id": 99,
  "priority": "EMERGENCY"
}


You already support this in the agent.

🔹 B. Preload hint (offline optimization)

Add to /device/sync:

"preload_audio_ids": [1, 2, 5]


Agent downloads ahead of time.

🔹 C. Agent self-update hint (future-proof)
"agent_update": {
  "required": false,
  "latest_version": "1.0.3",
  "download_url": "https://cdn.example.com/agent.exe"
}


You don’t have to implement it now — but design for it.
