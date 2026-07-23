# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from collections import Counter
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

datas = [
    ('data/piper', 'data/piper'),
    ('.env.example', '.'),
    ('jarvis.ico', '.'),
    ('icon_preview.png', '.'),
]
piper_executable = Path(sys.executable).resolve().parent / 'Scripts' / 'piper.exe'
binaries = [(str(piper_executable), '.')] if piper_executable.is_file() else []
import piper
piper_package_dir = Path(piper.__file__).resolve().parent
datas.append((str(piper_package_dir / 'espeak-ng-data'), 'piper/espeak-ng-data'))
datas.append((str(Path('gui/themes')), 'gui/themes'))

hiddenimports = ['webrtcvad', 'pywintypes', 'pythoncom', 'win32timezone', 'win32com.client', 'comtypes', 'comtypes.client', 'pycaw.pycaw', 'pygame', 'feedparser', 'pygetwindow', 'pywinauto', 'pyperclip', 'psutil', 'setuptools', 'pkg_resources', 'pkg_resources.extern']
hiddenimports += ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'gui', 'gui.main_window', 'gui.settings_window', 'gui.workers', 'gui.tray', 'gui.styles', 'gui.core_widget', 'core.settings', 'core.assistant_controller', 'skills.window_control', 'skills.office_close', 'voice.devices', 'voice.capture', 'voice.engine', 'voice.voice_state', 'voice.speech_service', 'voice.audio_log', 'core.desktop_agent', 'skills.office_service', 'skills.news_service']
hiddenimports += [
    'gui.dashboard_page', 'gui.capabilities_page', 'gui.secondary_pages',
    'gui.widgets', 'gui.widgets.hud', 'gui.widgets.ai_core_widget',
    'gui.widgets.dashboard_panels', 'core.action_manager',
    'core.application_registry', 'core.capability_health',
    'core.capability_registry', 'core.command_text', 'core.live_task',
    'core.planner', 'core.registry', 'core.save_workflow',
    'core.windows_controller',
]
hiddenimports += collect_submodules('skills')
# sklearn data for openwakeword (estimator.css etc.)
datas += collect_data_files('sklearn', includes=['**/_repr_html/**', '**/*.css', '**/*.js'])
hiddenimports += collect_submodules(
    'sklearn',
    filter=lambda name: (
        '.tests' not in name
        and not name.endswith(('.tests', '.conftest'))
        and 'array_api_compat.torch' not in name
        and 'array_api_extra._lib._testing' not in name
        and 'utils._test' not in name
    ),
)
hiddenimports += ['sklearn.utils._repr_html', 'sklearn.utils._estimator_html_repr']
hiddenimports += collect_submodules('sounddevice')
datas += copy_metadata('setuptools', recursive=True)

def include_numpy(name):
    return not (
        name.startswith('numpy.tests')
        or name.startswith('numpy.f2py')
    )


def include_scipy(name):
    return not (
        name.startswith('scipy.tests')
        or '.tests' in name
        or name.startswith('scipy.special.tests')
    )


TORCH_EXCLUDED_PREFIXES = (
    'torch._dynamo',
    'torch._inductor',
    'torch.compile',
    'torch.utils.tensorboard',
    'torch.utils.benchmark',
    'torch.utils.bottleneck',
    'torch.onnx',
    'torch.export',
    'torch._export',
    'functorch',
    'triton',
    'caffe2',
)


def include_torch(name):
    return not any(
        name == prefix or name.startswith(prefix + '.')
        for prefix in TORCH_EXCLUDED_PREFIXES
    )


def include_transformers(name):
    if (
        name.startswith('transformers.tests')
        or name.startswith('transformers.benchmark')
        or name.startswith('transformers.onnx')
        or name.startswith('transformers.sagemaker')
        or name.startswith('transformers.commands')
        or name.startswith('transformers.testing_utils')
        or '.convert_' in name
        or name.endswith('.convert')
    ):
        return False
    if name.startswith('transformers.models.'):
        parts = name.split('.')
        return len(parts) > 2 and parts[2] in {'auto', 'qwen2', 'qwen2_moe'}
    return True


def include_piper(name):
    return not name.startswith('piper.train')


def exclude_tests(name):
    return '.tests' not in name and not name.endswith('.tests')


binaries += collect_dynamic_libs('numpy')
binaries += collect_dynamic_libs('scipy')
tmp_ret = collect_all('openwakeword')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# Only bundle torch + transformers when the local router is enabled at build time
_local_router = os.environ.get('LOCAL_ROUTER_ENABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')
if _local_router:
    binaries += collect_dynamic_libs('torch')
    hiddenimports += collect_submodules('torch', filter=include_torch)
    hiddenimports += collect_submodules('transformers', filter=include_transformers)
    datas += collect_data_files('transformers', excludes=['**/tests/**', '**/benchmark/**'])
else:
    print('[spec] LOCAL_ROUTER_ENABLED is false - skipping torch/transformers bundle')
if _local_router:
    datas += collect_data_files(
        'transformers',
        includes=[
            '*.py',
            'generation/*.py',
            'generation/**/*.py',
            'utils/*.py',
            'utils/**/*.py',
            'models/auto/*.py',
            'models/qwen2/*.py',
            'models/qwen2_moe/*.py',
        ],
        include_py_files=True,
    )
if _local_router:
    for package in ('tokenizers', 'huggingface_hub', 'safetensors', 'ctranslate2'):
        binaries += collect_dynamic_libs(package)
        hiddenimports += collect_submodules(package, filter=exclude_tests)
else:
    print('[spec] Skipping HuggingFace ecosystem (tokenizers, huggingface_hub, safetensors, ctranslate2)')
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
for _qt in ('PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'PySide6.QtNetwork'):
    tmp_ret = collect_all(_qt)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
hiddenimports += collect_submodules('piper', filter=include_piper)
hiddenimports = sorted(set(hiddenimports))


excluded_modules = [
    'torch.tests',
    'torch._dynamo',
    'torch._inductor',
    'torch.utils.tensorboard',
    'torch.utils.benchmark',
    'torch.utils.bottleneck',
    'torch.onnx',
    'torch.export',
    'torch._export',
    'caffe2',
    'functorch',
    'triton',
    'sympy',
    'networkx',
    'matplotlib',
    'tkinter',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'edge_tts',
    'pandas',
    'pip',
    'lib2to3',
    'xmlrpc',
    'email.test',
    'curses',
    'dbm',
    'tcl',
    'numpy.tests',
    'numpy.f2py',
    'scipy.tests',
]
if not _local_router:
    # OpenWakeWord and Faster Whisper both use their ONNX/CTranslate2 paths.
    # Scikit-learn exposes optional Torch array-API shims, but JARVIS does not
    # use them; allowing PyInstaller to follow those shims adds 300+ MB and
    # materially delays first paint without adding a runtime capability.
    excluded_modules += ['torch', 'torchvision', 'torchaudio']


a = Analysis(
    ['desktop_main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['build/hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)

def keep_analysis_data(entry):
    destination = str(entry[0]).replace('\\', '/')
    if destination.startswith('sklearn/'):
        # keep runtime HTML/CSS/JS resources openwakeword/sklearn need at
        # runtime; only drop bulky non-essential data
        if destination.endswith(('.css', '.js', '.html', '.json')):
            return True
        return False
    if destination.startswith('torch-') and '/licenses/' in destination:
        return False
    return True


a.datas[:] = [entry for entry in a.datas if keep_analysis_data(entry)]

total = len(a.pure) + len(a.binaries) + len(a.datas)
print(f'TOC_SIZE={total}')

binary_sizes = []
for entry in a.binaries:
    try:
        source = Path(entry[1])
        binary_sizes.append((source.stat().st_size, entry[0], str(source)))
    except (OSError, IndexError, TypeError):
        continue
print('TOP_10_BINARIES_BEGIN')
for size, destination, source in sorted(binary_sizes, reverse=True)[:10]:
    print(f'TOP_BINARY bytes={size} destination={destination} source={source}')
print('TOP_10_BINARIES_END')

data_packages = Counter()
for entry in a.datas:
    try:
        destination = str(entry[0]).replace('\\', '/')
        package = destination.split('/', 1)[0] or '(root)'
        data_packages[package] += 1
    except (IndexError, TypeError):
        continue
print('TOP_10_DATA_PACKAGES_BEGIN')
for package, count in data_packages.most_common(10):
    print(f'TOP_DATA_PACKAGE entries={count} package={package}')
print('TOP_10_DATA_PACKAGES_END')

if total > 9000:
    raise SystemExit(f'TOC too large: {total} entries. Trim before building.')
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JARVIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['jarvis.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='JARVIS',
)
