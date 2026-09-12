# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for Neuron AI v0.1.0 (Windows onedir).

Builds a standalone frozen Windows distribution containing:
- PySide6 transparent overlay, Siri-like listening orb, and desktop shell
- SoundDevice microphone capture and playback
- Local Whisper STT and Wake-Word engines
- Multimodal Gemini Tutor adapter and deterministic fallback scenarios
- Demo scenario fixtures and application schemas
Guarantees:
- console=False (windowed desktop application without console popup)
- NEVER bundles .env, secrets, logs, recordings, or developer test files.
- Collects required native libraries for PySide6, SoundDevice, faster-whisper, ctranslate2, tokenizers, google-genai.
- Bundles local faster-whisper-base.en model directory if present on build machine.
- Gracefully accepts assets/neuron.ico if present.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

block_cipher = None
project_root = os.path.abspath(SPECPATH)

# 1. Collect package data files for native AI / audio / runtime dependencies
datas = []

# Demo contexts and templates
demo_dir = os.path.join(project_root, 'demo')
if os.path.exists(demo_dir):
    datas.append((demo_dir, 'demo'))

# JSON schemas if present
schemas_dir = os.path.join(project_root, 'schemas')
if os.path.exists(schemas_dir):
    datas.append((schemas_dir, 'schemas'))

# Brand assets if present
assets_dir = os.path.join(project_root, 'assets')
if os.path.exists(assets_dir):
    datas.append((assets_dir, 'assets'))

# Bundled faster-whisper model (if present on build machine)
bundled_whisper_dir = os.path.join(project_root, 'models', 'faster-whisper-base.en')
if os.path.exists(bundled_whisper_dir) and os.path.isdir(bundled_whisper_dir):
    datas.append((bundled_whisper_dir, os.path.join('models', 'faster-whisper-base.en')))

# Package data collections
try:
    datas += collect_data_files('faster_whisper')
except Exception:
    pass

try:
    datas += collect_data_files('ctranslate2')
except Exception:
    pass

try:
    datas += collect_data_files('tokenizers')
except Exception:
    pass

try:
    datas += collect_data_files('google.genai')
except Exception:
    pass

try:
    datas += collect_data_files('certifi')
except Exception:
    pass

# Collect dynamic libraries for ctranslate2 & sounddevice
binaries = []
try:
    binaries += collect_dynamic_libs('ctranslate2')
except Exception:
    pass

try:
    binaries += collect_dynamic_libs('sounddevice')
except Exception:
    pass

# Explicit security guard: ensure .env and secrets are NEVER bundled
sanitized_datas = []
for src, dst in datas:
    src_norm = os.path.normpath(src).lower()
    basename = os.path.basename(src_norm)
    # Never bundle environment files, git repo, or secret files
    if basename == '.env' or basename.startswith('.env.'):
        continue
    if '.git' in src_norm.split(os.sep) or '.venv' in src_norm.split(os.sep):
        continue
    if 'secret' in src_norm:
        continue
    sanitized_datas.append((src, dst))
datas = sanitized_datas

# 2. Hidden imports (strictly necessary; pynput and stale wake imports removed)
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'sounddevice',
    'numpy',
    'requests',
    'certifi',
    'faster_whisper',
    'ctranslate2',
    'tokenizers',
    'google.genai',
    'pydantic',
    'app.version',
    'app.config.settings',
    'app.config.credentials',
    'app.config.user_config',
    'app.utils.paths',
    'app.desktop.setup_dialog',
    'app.desktop.orb',
    'app.session.indicator',
    'app.diagnostics.metrics',
    'app.diagnostics.readiness',
    'app.tutor.fallback',
    'app.tutor.scenario',
    'app.wake.detector',
    'app.wake.factory',
    'app.wake.fake',
    'app.wake.whisper_wake',
    'app.wake.errors',
]

try:
    hiddenimports += collect_submodules('faster_whisper')
except Exception:
    pass

try:
    hiddenimports += collect_submodules('ctranslate2')
except Exception:
    pass

try:
    hiddenimports += collect_submodules('google.genai')
except Exception:
    pass

# 3. Excludes: keep tests, IDE caches, and dev tools out of the bundle
excludes = [
    'pytest',
    '_pytest',
    'IPython',
    'jupyter',
    'matplotlib',
    'sphinx',
    'tests',
]

# 4. Icon resolution: check for assets/neuron.ico, gracefully fall back to None
icon_file = os.path.join(project_root, 'assets', 'neuron.ico')
app_icon = icon_file if os.path.exists(icon_file) else None

a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=binaries,
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
    console=False,  # Windowed GUI application for v0.1.0 release (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=app_icon,
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
