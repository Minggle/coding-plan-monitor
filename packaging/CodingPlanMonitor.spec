# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本：onedir + windowed，供 Inno Setup 安装包使用。

用法：.build-venv\\Scripts\\pyinstaller.exe packaging\\CodingPlanMonitor.spec --noconfirm
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 排除未使用的 Qt / 第三方模块，控制体积
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.Qt3DQuick",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtQuick",
    "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtPdf", "PySide6.QtPdfQuick",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtSensors",
    "PySide6.QtTextToSpeech", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtVirtualKeyboard", "PySide6.QtPdfWidgets",
    "numpy", "pandas", "matplotlib", "tkinter", "pytest",
]

a = Analysis(
    ["../launch.pyw"],
    pathex=[".."],
    binaries=[],
    datas=[("../assets/icon.png", ".")],
    hiddenimports=collect_submodules("app"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
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
    name="CodingPlanMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="../assets/icon.ico",
    version="version_info.txt",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CodingPlanMonitor",
)
