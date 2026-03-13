# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden_imports = []
hidden_imports += [
    'utils.logger',
    'utils.single_instance', 
    'utils.vlc_checker',
    'utils.startup',
    'config_manager',
    'agent_app',
    'volume_controller_factory',
    'volume_controller_windows',
    'agent.audio_controller',
    'agent.watchdog',
    'agent.server_client',
    'agent.scheduler',
    'agent.device_identity',
    'agent.playback_controller',
    'playlist.playlist_engine',
    'api.local_agent_api',
    'worker_main',
    'supervisor',
    'machineid',
    'wmi',
    'psutil',
]
hidden_imports += collect_submodules('socketio')
hidden_imports += collect_submodules('engineio')
hidden_imports += collect_submodules('websocket')

hidden_imports += collect_submodules('pycaw')
hidden_imports += ['win32timezone']
hidden_imports += collect_submodules('tkinter')
hidden_imports += collect_submodules('comtypes')
hidden_imports += ['comtypes.stream']

hidden_imports += ['vlc']
hidden_imports += ['charset_normalizer.md']
hidden_imports += collect_submodules('win32')

hidden_imports += collect_submodules('requests')
hidden_imports += collect_submodules('charset_normalizer')
hidden_imports += collect_submodules('chardet')
hidden_imports += collect_submodules('urllib3')
hidden_imports += collect_submodules('idna')
hidden_imports += collect_submodules('certifi')
hidden_imports += collect_submodules('ctypes')
hidden_imports += collect_submodules('asyncio')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('vlc/libvlc.dll', 'vlc'),
        ('vlc/libvlccore.dll', 'vlc'),
    ],
    datas=[
        ('requirements.txt', '.'),
        ('vlc/plugins', 'vlc/plugins'),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/vlc_runtime_hook.py'],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PyQt5',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=True,
    name='AudioAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='AudioAgent'
)