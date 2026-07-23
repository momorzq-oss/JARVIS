from PyInstaller.utils.hooks import collect_dynamic_libs


binaries = collect_dynamic_libs('torch')
datas = []
hiddenimports = []
warn_on_missing_hiddenimports = False
module_collection_mode = 'py'
