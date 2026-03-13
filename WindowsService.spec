#WindowsService.spec
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['service\\windows_service.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('utils', 'utils'), 
    ],
    hiddenimports=[
        'win32timezone',
        'win32service',
        'win32serviceutil',
        'servicemanager',
        'pythoncom',
        'pywintypes',
        'utils.logger',      # ← MISSING
        'utils.single_instance',  # ← MISSING
        'logging.handlers',  # ← MISSING
        'subprocess',
        'threading',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AudioAgentService',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=['icon.ico'],
)