import subprocess
import uuid
import hashlib
import winreg
import logging
import socket


logger = logging.getLogger(__name__)


def get_registry_machine_guid():
    """Get Windows Machine GUID from registry"""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography"
        )
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return value
    except Exception as e:
        logger.warning(f"Registry MachineGuid failed: {e}")
        return None


def get_powershell_uuid():
    """Get hardware UUID via PowerShell (modern Windows)"""
    try:
        result = subprocess.check_output(
            ["powershell", "-Command", "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
            text=True
        ).strip()

        if result:
            return result
    except Exception as e:
        logger.warning(f"PowerShell UUID failed: {e}")

    return None


def get_wmic_uuid():
    try:
        output = subprocess.check_output(
            ["wmic", "csproduct", "get", "uuid"],
            text=True
        )

        lines = [l.strip() for l in output.splitlines() if l.strip()]

        if len(lines) >= 2:
            return lines[1]

    except Exception as e:
        logger.warning(f"WMIC UUID failed: {e}")

    return None


def get_mac():
    try:
        mac = uuid.getnode()
        return ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
    except Exception as e:
        logger.warning(f"MAC fetch failed: {e}")
        return None

def get_os_machine_id():
    """
    Try multiple methods to get stable machine ID
    """
    for method in [
        get_registry_machine_guid,
        get_powershell_uuid,
        get_wmic_uuid
    ]:
        value = method()
        if value:
            return value

    # last fallback
    return str(uuid.getnode())


def get_device_fingerprint():
    """
    Create stable fingerprint for device
    """
    os_id = get_os_machine_id()
    mac = get_mac()

    raw = f"{os_id}-{mac}"

    fingerprint = hashlib.sha256(raw.encode()).hexdigest()

    return fingerprint


def get_device_identity():
    """
    Return device identity used for activation
    """
    machine_id = get_os_machine_id()
    mac = get_mac()
    host_name = socket.gethostname()

    fingerprint_raw = f"{machine_id}-{mac}-{host_name}"
    fingerprint = hashlib.sha256(fingerprint_raw.encode()).hexdigest()

    return {
        "device_uuid": machine_id,
        "device_fingerprint": fingerprint,
        "host_name": host_name
    }