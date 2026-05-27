# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules

datas = [('industry_keywords_reference.xlsx', '.'), ('SETUP.md', '.')]
binaries = []
hiddenimports = ['openpyxl', 'openpyxl.cell._writer', 'pdfminer', 'pdfminer.high_level', 'cv_match', 'scraper']
datas += collect_data_files('sentence_transformers')
datas += collect_data_files('tokenizers')
datas += collect_data_files('transformers')
datas += collect_data_files('curl_cffi')
datas += collect_data_files('torch')
binaries += collect_dynamic_libs('torch')
hiddenimports += collect_submodules('sentence_transformers')


a = Analysis(
    ['gui.pyw'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JobsDBScraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JobsDBScraper',
)
