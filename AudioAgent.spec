# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Specification File for Audio Agent
Provides advanced build configuration and optimization
"""
# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hidden_imports = []
hidden_imports += collect_submodules('socketio')
hidden_imports += collect_submodules('engineio')
hidden_imports += collect_submodules('websocket')

hidden_imports += collect_submodules('pycaw')
hidden_imports += ['win32timezone']
hidden_imports += collect_submodules('tkinter')
hidden_imports += collect_submodules('tkinter')
hidden_imports += collect_submodules('comtypes')
hidden_imports += ['comtypes.stream']

hidden_imports += ['vlc']

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
    binaries=[],
    datas=[
        ('requirements.txt', '.'),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    name='AudioAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # safer for audio libraries
    console=False,  # no terminal
    icon='icon.ico' if os.path.exists('icon.ico') else None,
)
