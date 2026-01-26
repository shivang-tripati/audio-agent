# Windows Audio Agent

A production-ready Windows background service for centralized audio playback and volume control across branch laptops.

## 🎯 Overview

The Windows Audio Agent is a lightweight, reliable background application that:

- ✅ Runs silently after Windows startup
- ✅ Connects to cloud backend for centralized control
- ✅ Plays scheduled announcements automatically
- ✅ Controls Windows system volume remotely
- ✅ Works offline with cached audio and schedules
- ✅ Sends real-time status updates to backend
- ✅ Auto-recovers from errors and network issues

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│           Windows Audio Agent (Agent)           │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐    ┌──────────────┐          │
│  │   Volume     │    │    Audio     │          │
│  │  Controller  │    │  Controller  │          │
│  │  (pycaw)     │    │    (VLC)     │          │
│  └──────────────┘    └──────────────┘          │
│                                                 │
│  ┌──────────────┐    ┌──────────────┐          │
│  │   Server     │    │  Scheduler   │          │
│  │   Client     │    │  (Offline)   │          │
│  │ (REST + WS)  │    │              │          │
│  └──────────────┘    └──────────────┘          │
│                                                 │
│  ┌──────────────────────────────────┐          │
│  │     Configuration Manager         │          │
│  │    (Persistent Storage)          │          │
│  └──────────────────────────────────┘          │
│                                                 │
└─────────────────────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │   Backend API Server   │
         │  (REST + WebSocket)    │
         └───────────────────────┘
```

## 📋 Features

### Core Capabilities

1. **Background Operation**
   - Runs continuously without UI
   - No browser dependency
   - Auto-start with Windows boot
   - Auto-restart on failure

2. **Volume Control**
   - Two-tier volume system (Master × Branch)
   - Applied at Windows OS level
   - Persists across restarts
   - Formula: `finalVolume = (master × branch) / 100`

3. **Audio Playback**
   - MP3 and WAV support
   - VLC-based reliable playback
   - Local audio caching
   - Priority-based interruption (emergency > scheduled)

4. **Scheduling**
   - Daily, weekly, and one-time schedules
   - Offline-capable (uses cached schedule)
   - Automatic execution
   - Timezone-aware

5. **Server Communication**
   - HTTPS REST API for config/auth
   - WebSocket for real-time commands
   - Heartbeat every 45 seconds
   - Auto-reconnect on disconnect

6. **Resilience**
   - Works offline with cached data
   - Auto-recovery from errors
   - Graceful degradation
   - Comprehensive error logging

## 🚀 Quick Start

### For Deployment

1. **Install VLC Media Player**
   ```
   Download from: https://www.videolan.org/vlc/
   ```

2. **Copy files to target machine**
   ```
   C:\AudioAgent\AudioAgent.exe
   ```

3. **Configure the agent**
   
   Create: `C:\Users\[YourUsername]\AudioAgent\config\agent_config.json`
   
   ```json
   {
     "device_id": "branch-001-laptop-01",
     "branch_id": "branch-001",
     "server_url": "https://api.yourdomain.com",
     "token": "your-secure-token",
     "master_volume": 100,
     "branch_volume": 100
   }
   ```

4. **Set up auto-start** (Task Scheduler recommended)
   
   See [Setup Guide](SETUP.md) for detailed instructions.

### For Development

1. **Install Python 3.9+**

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the agent**
   ```bash
   python main.py
   ```

4. **Build executable**
   ```bash
   build.bat
   ```

## 📁 Project Structure

```
AudioAgent/
├── main.py                 # Main application entry point
├── audio_controller.py     # Audio playback management
├── volume_controller.py    # Windows volume control
├── server_client.py        # Backend communication
├── scheduler.py            # Schedule management
├── config_manager.py       # Configuration persistence
├── requirements.txt        # Python dependencies
├── build.bat              # Build script
├── README.md              # This file
└── SETUP.md               # Detailed setup guide
```

## 🎛️ Volume Control Logic

The agent implements a two-tier volume system:

```python
finalVolume = (masterVolume × branchVolume) / 100
```

**Example:**
- Master Volume: 80% (global control)
- Branch Volume: 90% (branch-specific)
- Final Output: 72% (applied to Windows system)

This allows:
- **Master Volume:** Global volume cap across all branches
- **Branch Volume:** Individual branch adjustments
- **Final Volume:** Automatically calculated and applied

## 📡 Communication Protocol

### REST API

- **Authentication:** `POST /api/auth/device`
- **Configuration:** `GET /api/device/{id}/config`
- **Heartbeat:** `POST /api/device/{id}/heartbeat`

### WebSocket Commands

From server to agent:

- `VOLUME_UPDATE` - Change volume settings
- `PLAY` - Play audio (manual/emergency)
- `STOP` - Stop current playback
- `SCHEDULE_UPDATE` - Update schedule
- `DOWNLOAD_AUDIO` - Pre-download audio

See [API Documentation](API.md) for details.

## 🔧 Configuration

### Required Settings

| Key | Description | Example |
|-----|-------------|---------|
| `device_id` | Unique device identifier | `"branch-001-laptop-01"` |
| `branch_id` | Branch identifier | `"branch-001"` |
| `server_url` | Backend API URL | `"https://api.domain.com"` |
| `token` | Authentication token | `"eyJhbGc..."` |

### Optional Settings

| Key | Description | Default |
|-----|-------------|---------|
| `master_volume` | Master volume (0-100) | `100` |
| `branch_volume` | Branch volume (0-100) | `100` |
| `heartbeat_interval` | Seconds between heartbeats | `45` |

## 📊 Monitoring

### Heartbeat Payload

Every 45 seconds, the agent sends:

```json
{
  "deviceId": "branch-001-laptop-01",
  "branchId": "branch-001",
  "status": "PLAYING",
  "currentAudio": "morning_announcement",
  "finalVolume": 72
}
```

**Status Values:**
- `IDLE` - Not playing
- `PLAYING` - Currently playing
- `OFFLINE` - Disconnected

### Log Files

Location: `C:\Users\[Username]\AudioAgent\logs\`

Format: `agent_YYYYMMDD.log`

Example:
```
2026-01-20 09:00:00 - INFO - Audio Agent started
2026-01-20 09:00:05 - INFO - Connected to server
2026-01-20 09:00:10 - INFO - Volume set to 72%
2026-01-20 09:00:15 - INFO - Playing: morning_announcement
```

## 🛠️ Building from Source

### Requirements

- Windows 10/11
- Python 3.9+
- VLC Media Player

### Build Steps

```bash
# Install dependencies
pip install -r requirements.txt

# Run build script
build.bat
```

Output: `dist\AudioAgent.exe`

### Manual Build

```bash
pyinstaller --onefile --noconsole --name AudioAgent main.py
```

## 🔒 Security

1. **Authentication**
   - Bearer token authentication
   - Tokens stored securely in config
   - Per-device unique tokens

2. **Communication**
   - HTTPS for REST API
   - WSS for WebSocket
   - No plain HTTP/WS

3. **File Security**
   - Config files in user directory
   - Restricted file permissions
   - No sensitive data in logs

## ⚠️ Known Limitations

These are **OS-level restrictions** that cannot be overcome:

1. **Task Manager Kill** - Users with admin rights can force close
2. **System Mute** - Users can mute via hardware/Windows
3. **Headphone Insertion** - Audio routing follows Windows defaults
4. **Logout** - May stop when user logs out (use Task Scheduler "Run whether user is logged on or not")

## 🐛 Troubleshooting

### Agent Won't Start

1. Check VLC is installed
2. Review logs in `AudioAgent\logs\`
3. Run as administrator
4. Verify config file exists and is valid

### No Audio

1. Check audio cache folder
2. Test VLC separately
3. Verify Windows audio settings
4. Check file format (MP3/WAV)

### Volume Not Changing

1. Check volume controller logs
2. Run with elevated privileges
3. Test Windows Sound settings

### Connection Issues

1. Test network: `ping api.yourdomain.com`
2. Check firewall settings
3. Verify credentials in config
4. Review authentication logs

See [Setup Guide](SETUP.md) for detailed troubleshooting.

## 📈 Performance

- **CPU Usage:** <1% idle, 2-5% during playback
- **Memory:** 30-50 MB
- **Disk:** ~100MB for cache (varies with audio library)
- **Network:** Minimal (heartbeat only when idle)

## 🤝 Contributing

This is a production system. Changes should be:

1. Tested on multiple Windows versions
2. Backward compatible
3. Well documented
4. Logged appropriately

## 📄 License

Proprietary - Internal use only

## 📞 Support

For issues:

1. Check logs first
2. Review [Setup Guide](SETUP.md)
3. Check [API Documentation](API.md)
4. Contact IT support with logs attached

## 🔄 Version History

### v1.0.0 (2026-01-20)
- Initial release
- Core audio playback
- Volume control
- Scheduling system
- Server communication
- Offline operation

---

**Developed with reliability and production deployment in mind.**