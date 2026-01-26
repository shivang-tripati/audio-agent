# Backend API Documentation

This document describes the API endpoints that the Audio Agent expects from the backend server.

---

## Base URL

All API requests should be made to:
```
https://api.yourdomain.com
```

---

## Authentication

All requests require authentication using a Bearer token.

**Header:**
```
Authorization: Bearer <token>
```

---

## REST API Endpoints

### 1. Device Authentication

**Endpoint:** `POST /api/auth/device`

**Purpose:** Authenticate device and verify credentials

**Request:**
```json
{
  "deviceId": "device-001",
  "branchId": "branch-001",
  "token": "secure-token-here"
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Authentication successful",
  "deviceId": "device-001",
  "branchId": "branch-001"
}
```

**Response (401 Unauthorized):**
```json
{
  "success": false,
  "error": "Invalid credentials"
}
```

---

### 2. Get Device Configuration

**Endpoint:** `GET /api/device/{deviceId}/config`

**Purpose:** Fetch initial configuration including volume and schedule

**Headers:**
```
Authorization: Bearer <token>
```

**Response (200 OK):**
```json
{
  "deviceId": "device-001",
  "branchId": "branch-001",
  "masterVolume": 80,
  "branchVolume": 90,
  "schedule": [
    {
      "id": "schedule-001",
      "audio_name": "morning_announcement",
      "audio_url": "https://cdn.yourdomain.com/audio/morning.mp3",
      "schedule_type": "daily",
      "time": "09:00",
      "enabled": true
    }
  ]
}
```

---

### 3. Send Heartbeat

**Endpoint:** `POST /api/device/{deviceId}/heartbeat`

**Purpose:** Periodic status update from device

**Request:**
```json
{
  "deviceId": "device-001",
  "branchId": "branch-001",
  "status": "PLAYING",
  "currentAudio": "morning_announcement",
  "finalVolume": 72
}
```

**Status values:**
- `"IDLE"` - Not playing anything
- `"PLAYING"` - Currently playing audio
- `"OFFLINE"` - Disconnected (shouldn't normally send)

**Response (200 OK):**
```json
{
  "success": true,
  "timestamp": "2026-01-20T10:30:00Z"
}
```

---

## WebSocket Connection

### Connection URL

```
wss://api.yourdomain.com/ws/device/{deviceId}
```

**Headers:**
```
Authorization: Bearer <token>
```

---

### WebSocket Messages (Server → Device)

All messages are JSON formatted.

#### 1. Volume Update

```json
{
  "type": "VOLUME_UPDATE",
  "masterVolume": 80,
  "branchVolume": 90
}
```

**Effect:** Device calculates `finalVolume = (80 * 90) / 100 = 72` and applies to system.

---

#### 2. Play Audio

```json
{
  "type": "PLAY",
  "audio": {
    "name": "emergency_announcement",
    "url": "https://cdn.yourdomain.com/audio/emergency.mp3",
    "priority": "emergency"
  }
}
```

**Priority levels:**
- `"normal"` - Regular playback
- `"emergency"` - Interrupts current playback

**Effect:** Device downloads (if needed) and plays audio immediately.

---

#### 3. Stop Playback

```json
{
  "type": "STOP"
}
```

**Effect:** Device stops current audio playback.

---

#### 4. Schedule Update

```json
{
  "type": "SCHEDULE_UPDATE",
  "schedule": [
    {
      "id": "schedule-001",
      "audio_name": "morning_announcement",
      "audio_url": "https://cdn.yourdomain.com/audio/morning.mp3",
      "schedule_type": "daily",
      "time": "09:00",
      "enabled": true
    },
    {
      "id": "schedule-002",
      "audio_name": "lunch_announcement",
      "audio_url": "https://cdn.yourdomain.com/audio/lunch.mp3",
      "schedule_type": "weekly",
      "time": "12:00",
      "days": [0, 1, 2, 3, 4],
      "enabled": true
    },
    {
      "id": "schedule-003",
      "audio_name": "special_event",
      "audio_url": "https://cdn.yourdomain.com/audio/event.mp3",
      "schedule_type": "once",
      "time": "15:00",
      "date": "2026-01-25",
      "enabled": true
    }
  ]
}
```

**Schedule Types:**
- `"daily"` - Plays every day at specified time
- `"weekly"` - Plays on specified days of week (0=Monday, 6=Sunday)
- `"once"` - Plays once on specified date

**Effect:** Device updates local schedule and saves for offline operation.

---

#### 5. Download Audio

```json
{
  "type": "DOWNLOAD_AUDIO",
  "audio": {
    "name": "new_announcement",
    "url": "https://cdn.yourdomain.com/audio/new.mp3"
  }
}
```

**Effect:** Device downloads audio file to local cache for future use.

---

### WebSocket Messages (Device → Server)

#### Status Update

Device can send status updates via WebSocket:

```json
{
  "type": "STATUS_UPDATE",
  "data": {
    "status": "PLAYING",
    "currentAudio": "morning_announcement",
    "finalVolume": 72,
    "timestamp": "2026-01-20T09:00:00Z"
  }
}
```

---

## Data Models

### Schedule Item

```typescript
{
  id: string;              // Unique schedule ID
  audio_name: string;      // Name of audio file
  audio_url: string;       // Download URL
  schedule_type: "daily" | "weekly" | "once";
  time: string;            // HH:MM format (24-hour)
  days?: number[];         // For weekly: [0-6], 0=Monday
  date?: string;           // For once: YYYY-MM-DD
  enabled: boolean;        // Is schedule active
}
```

### Audio Info

```typescript
{
  name: string;            // Audio identifier
  url: string;             // CDN URL
  priority?: "normal" | "emergency";
}
```

---

## Error Handling

### HTTP Status Codes

- `200 OK` - Success
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Authentication failed
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

### WebSocket Errors

If WebSocket encounters an error, device will:
1. Log the error
2. Attempt reconnection after 30 seconds
3. Continue using last known configuration
4. Continue offline schedule execution

---

## Volume Calculation

**Formula:**
```
finalVolume = (masterVolume * branchVolume) / 100
```

**Example:**
- Master Volume: 80%
- Branch Volume: 90%
- Final Volume: (80 × 90) / 100 = **72%**

The agent applies this final volume to the Windows system volume.

---

## Heartbeat Behavior

- **Interval:** Every 45 seconds (configurable)
- **Payload:** Current status, audio, and volume
- **Purpose:** 
  - Server knows which devices are online
  - Dashboard shows real-time status
  - Detect disconnected devices

**Example Dashboard View:**
```
Branch 001 - Device 1
├─ Status: PLAYING
├─ Audio: morning_announcement
├─ Volume: 72%
└─ Last Heartbeat: 5 seconds ago

Branch 001 - Device 2
├─ Status: IDLE
├─ Audio: -
├─ Volume: 80%
└─ Last Heartbeat: 3 seconds ago

Branch 002 - Device 1
├─ Status: OFFLINE
├─ Audio: -
├─ Volume: -
└─ Last Heartbeat: 5 minutes ago
```

---

## Offline Operation

The agent is designed for **offline resilience**:

1. **Cached Audio:** 
   - All audio files are downloaded to local cache
   - Playback continues even if CDN is unreachable

2. **Cached Schedule:**
   - Schedule is saved locally
   - Scheduled playback continues offline

3. **Cached Volume:**
   - Last known volume settings are persisted
   - Applied on restart even without server connection

4. **Auto-Reconnect:**
   - Agent continuously attempts to reconnect
   - Once online, syncs with server automatically

---

## Security Considerations

1. **HTTPS/WSS Only:**
   - All communication must use secure protocols
   - No plain HTTP or WS connections

2. **Token Authentication:**
   - Tokens should be long, random, and unique per device
   - Rotate tokens periodically
   - Revoke tokens for decommissioned devices

3. **Audio URL Security:**
   - Use signed URLs with expiration for sensitive content
   - Implement CDN authentication if needed

4. **Rate Limiting:**
   - Implement rate limits on API endpoints
   - Prevent abuse of heartbeat endpoint

---

## Testing

### Test Authentication

```bash
curl -X POST https://api.yourdomain.com/api/auth/device \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "deviceId": "test-device",
    "branchId": "test-branch",
    "token": "your-token"
  }'
```

### Test Heartbeat

```bash
curl -X POST https://api.yourdomain.com/api/device/test-device/heartbeat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "deviceId": "test-device",
    "branchId": "test-branch",
    "status": "IDLE",
    "currentAudio": null,
    "finalVolume": 80
  }'
```

### Test WebSocket (using wscat)

```bash
npm install -g wscat
wscat -c "wss://api.yourdomain.com/ws/device/test-device" \
  -H "Authorization: Bearer your-token"
```

Then send test message:
```json
{"type": "PLAY", "audio": {"name": "test", "url": "https://cdn.yourdomain.com/test.mp3", "priority": "normal"}}
```

---

## Implementation Checklist

Backend developers should implement:

- [ ] Device authentication endpoint
- [ ] Device configuration endpoint
- [ ] Heartbeat endpoint
- [ ] WebSocket server for real-time commands
- [ ] Volume update command
- [ ] Play/Stop commands
- [ ] Schedule update command
- [ ] Audio download command
- [ ] Dashboard to visualize device status
- [ ] Token management system
- [ ] Audio CDN or storage
- [ ] Schedule management UI

---

## Support

For API questions or issues:
1. Check this documentation
2. Test endpoints individually
3. Review agent logs for detailed error messages
4. Contact backend team with specific error codes