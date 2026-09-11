# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for Neuron AI desktop application (Block 8).

Builds a standalone frozen Windows distribution containing:
- PySide6 transparent overlay and desktop shell
- SoundDevice microphone capture and playback
- Local Whisper STT and Wake-Word engines
- Multimodal Gemini Tutor adapter and deterministic fallback scenarios
- Demo scenario HTML/code fixtures
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

project_root = os.path.abspath(SPECPATH)

# Data files to bundle: demo contexts, templates, and runtime assets
datas = [
    (os.path.join(project_root, 'demo'), 'demo'),
]

# Hidden imports that dynamic loaders or plugins may require
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'sounddevice',
    'numpy',
    'requests',
    'pynput',
    'pynput.keyboard',
    'pynput.keyboard._win32',
    'app.diagnostics',
    'app.diagnostics.metrics',
    'app.diagnostics.readiness',
    'app.config.settings',
    'app.utils.paths',
    'app.tutor.fallback',
    'app.tutor.scenario',
    'app.wake.factory',
    'app.wake.stt_wake',
    'app.wake.energy',
]

# Exclude unnecessary developer/test packages from frozen bundle
excludes = [
    'pytest',
    '_pytest',
    'IPython',
    'jupyter',
    'matplotlib',
    'sphinx',
]

a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NeuronAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Set to True so diagnostic logs and readiness output are visible in console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NeuronAI',
)
