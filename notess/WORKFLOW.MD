What already works

What must change

Why we are changing it

How Windows agent, backend and web UI connect

What to implement next

No code yet — just architecture clarity.

🧠 The 3 Actors in your system

There are only three things:

Actor	What it does
Admin Web App	Creates devices, uploads audio, schedules playback
Backend Server	The brain — validates, stores, pushes commands
Windows Audio Agent	The muscle — plays audio at branches

Everything we are fixing is only to make these three talk safely.

🎯 The One Core Problem We Are Solving

You said:

What if someone copies the device code and installs it on another PC?

That is the entire reason for everything we changed.

We are building DRM for physical machines.

🧩 How a Device is supposed to exist

A device must be:

Property	Who owns it
device_code	Human (admin types it)
device_uuid	Windows PC
device_token	Server
device_id	Database

The agent must NEVER claim who it is.
Only the server decides.

🧭 The Correct Life Cycle

Let’s walk it.

🧑‍💼 Step 1 — Admin creates device (Web App)

Admin clicks Add Device → selects branch.

Backend creates:

{
  id: 12,
  branch_id: 3,
  device_code: "DEV-000003-012",
  device_uuid: null,
  device_token: null,
  status: "PENDING"
}


This device is now locked to a branch but not yet activated.

Admin gives the code to branch staff.

💻 Step 2 — Windows agent is installed

When agent runs first time:

It shows:

Enter Device Code

User types:

DEV-000003-012


Agent also has a machine fingerprint:

device_uuid = hashed(mac + disk + bios)


Agent sends:

POST /api/devices/activate
{
  device_code: "DEV-000003-012",
  device_uuid: "ABC123",
  host_name: "SHOP-PC"
}

🔐 Step 3 — Server verifies & locks device

Server looks up:

DEV-000003-012


Case 1 – first activation:

device_uuid == null


→ server stores:

device_uuid = ABC123
device_token = random(64 chars)
status = OFFLINE


Returns:

{
  token: "SECRET_TOKEN",
  branch_id: 3
}


Agent saves:

token
branch_id
server_url


Device is now permanently bound to that PC.

🔌 Step 4 — Agent connects (WebSocket)

Agent connects to:

Socket.IO handshake:
Authorization: Bearer SECRET_TOKEN


Server checks:

SELECT * FROM devices WHERE device_token = SECRET_TOKEN


If found → connection allowed.

Now this socket = this physical device.

❤️ Step 5 — Heartbeat

Every 45s agent sends:

{
  "status": "PLAYING",
  "current_audio": "morning.mp3",
  "volume": 67
}


Server already knows:

which device

which branch

No spoofing possible.

🎵 Step 6 — Schedules

Admin creates schedules in web app.

Server builds schedule list for each device.

Server pushes via socket:

{
  type: "SCHEDULE_UPDATE",
  schedule: [
    {
      id: 5,
      audio_name: "prayer.mp3",
      audio_url: "...",
      schedule_type: "daily",
      time: "09:00",
      play_count: 2
    }
  ]
}


Agent:

saves it offline

executes locally

Even if internet drops, it still plays.

🔁 Step 7 — Reinstall on same PC

Agent again sends:

device_code
device_uuid


Server sees:

same uuid → allow → rotate token


Works.

🚫 Step 8 — Someone steals the code

Another PC sends:

DEV-000003-012
UUID=XYZ


Server sees:

stored UUID != XYZ → BLOCK


Device theft impossible.

🧨 Step 9 — Admin presses “Reset Device”

Backend does:

device_uuid = null
device_token = null
status = PENDING


Now any PC can re-activate.

Old token is instantly invalid.

🔧 Why we changed things

We removed:

❌ device_id from agent
❌ branch_id from agent
❌ REST authentication
❌ WebSocket without auth
❌ trusting client identity

Because all of these allow impersonation.

🧠 What remains to implement

You already have:

✔ Device model
✔ Activate endpoint
✔ Reset endpoint
✔ Socket.IO server
✔ Scheduler
✔ Windows agent

You only needed to:

Remove raw WebSocket

Use token-based socket auth

Use play_count logic

Stop agent sending deviceId/branchId

Which we did.