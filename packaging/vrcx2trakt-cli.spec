# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

spec_dir = Path(SPECPATH).resolve()
repo_root = spec_dir.parent

hiddenimports = [
    "vrcx2trakt.cli",
    "vrcx2trakt.wizard",
    "vrcx2trakt.extract",
    "vrcx2trakt.match",
    "vrcx2trakt.push",
    "vrcx2trakt.trakt_client",
    "vrcx2trakt.config",
    "requests",
]

a = Analysis(
    [str(spec_dir / "launcher_cli.py")],
    pathex=[str(repo_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="vrcx2trakt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
