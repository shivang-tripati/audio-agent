# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = []
hidden_imports += collect_submodules('pystray')
hidden_imports += collect_submodules('PIL')
hidden_imports += collect_submodules('requests')

a = Analysis(
    ['ui/app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('icon.ico','.')
    ],
    hiddenimports=hidden_imports,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AudioAgentUI',
    console=False,
    icon='icon.ico'
)