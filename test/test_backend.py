"""
Simple test backend for local testing
Run this before starting the audio agent
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sock import Sock
import datetime


app = Flask(__name__)
CORS(app)
sock = Sock(app)

@app.route('/api/auth/device', methods=['POST'])
def auth_device():
    device_id = request.json.get('deviceId')
    print(f"Auth request received for {device_id}")
    return jsonify({
        "success": True,
        "message": "Test authentication successful"
    })

@app.route('/api/device/<device_id>/config', methods=['GET'])
def get_config(device_id):
    print(f"Config requested for {device_id}")

    now = datetime.datetime.now() 
    test_time = (now + datetime.timedelta(minutes=2)).strftime("%H:%M")
    print(f"Test time: {test_time}")
    return jsonify({
        "deviceId": device_id,
        "branchId": "test-branch",
        "masterVolume": 80,
        "branchVolume": 70,
        "schedule": [
            {
                "id": "test-schedule-1",
                "audio_name": "test_audio",
                "audio_url": "https://cdn.freesound.org/previews/842/842709_7395592-lq.mp3",
                "schedule_type": "daily",
                "time": test_time,
                "enabled": True
            }
        ]
    })

@app.route('/api/device/<device_id>/heartbeat', methods=['POST'])
def heartbeat(device_id):
    data = request.json
    print(f"Heartbeat from {device_id}: {data.get('status')}")
    return jsonify({"success": True})

# --- NEW: WebSocket route ---
@sock.route('/ws/device/<device_id>')
def ws_device(ws, device_id):
    print(f"WebSocket connected for device {device_id}")
    while True:
        data = ws.receive()
        if data is None:
            print(f"WebSocket closed for {device_id}")
            break
        print(f"Received from {device_id}: {data}")
        ws.send(f"Echo: {data}")


if __name__ == '__main__':
    print("Test backend running on http://localhost:5000")
    app.run(port=5000, debug=True)