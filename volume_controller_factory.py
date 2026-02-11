import platform

def get_volume_controller():
    if platform.system() == "Windows":
        from volume_controller_windows import VolumeController
    else:
        from volume_controller_linux import VolumeController

    return VolumeController()
