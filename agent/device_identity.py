import uuid
import socket
import hashlib
import subprocess
import platform
import json
from pathlib import Path
import machineid

# -------------------------
# Persistent storage
# -------------------------
CONFIG_DIR = Path.home() / "AudioAgent" / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
IDENTITY_FILE = CONFIG_DIR / "identity.json"


def _load_identity():
    if IDENTITY_FILE.exists():
        with open(IDENTITY_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_identity(data):
    with open(IDENTITY_FILE, "w") as f:
        json.dump(data, f, indent=2)


# -------------------------
# Device UUID (once per install)
# -------------------------
def get_or_create_device_uuid():
    data = _load_identity()

    if "device_uuid" not in data:
        data["device_uuid"] = str(uuid.uuid4())
        _save_identity(data)

    return data["device_uuid"]


# -------------------------
# MAC address
# -------------------------
def get_mac():
    mac = uuid.getnode()
    return ':'.join(f'{(mac >> ele) & 0xff:02x}' for ele in range(40, -1, -8))


# -------------------------
# Disk Serial
# -------------------------
def get_disk_serial():
    try:
        if platform.system() == "Windows":
            import wmi
            c = wmi.WMI()
            for disk in c.Win32_DiskDrive():
                if disk.SerialNumber:
                    return disk.SerialNumber.strip()

        else:  # Linux / Ubuntu
            out = subprocess.check_output("lsblk -ndo SERIAL", shell=True).decode().strip()
            if out:
                return out.split("\n")[0]

    except:
        pass

    return None


# -------------------------
# OS Machine ID (fallback)
# -------------------------
def get_os_machine_id():
    try:
        return machineid.id()
    except Exception as e:
        logger.error(f"Failed to get OS machine ID: {e}")
        return None


# -------------------------
# Hostname
# -------------------------
def get_hostname():
    return socket.gethostname()


# -------------------------
# Final Device Fingerprint
# -------------------------
def get_device_fingerprint():
    mac = get_mac()
    disk = get_disk_serial()
    os_id = get_os_machine_id()
    hostname = get_hostname()

    base = f"{hostname}|{mac}|{disk or os_id}"

    return hashlib.sha256(base.encode()).hexdigest()


# -------------------------
# Collect everything
# -------------------------
def get_device_identity():
    return {
        "device_uuid": get_or_create_device_uuid(),
        "device_fingerprint": get_device_fingerprint(),
        "host_name": get_hostname()
    }
