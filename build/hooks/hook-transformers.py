from PyInstaller.utils.hooks import (
    copy_metadata,
    get_module_attribute,
    is_module_satisfies,
    logger,
)


datas = []
hiddenimports = []

try:
    dependencies = get_module_attribute(
        'transformers.dependency_versions_table',
        'deps',
    )
except Exception:
    logger.warning(
        'hook-transformers: failed to query the dependency table.',
        exc_info=True,
    )
    dependencies = {}

for dependency_name, dependency_requirement in dependencies.items():
    if not is_module_satisfies(dependency_requirement):
        continue
    try:
        datas += copy_metadata(dependency_name)
    except Exception:
        pass
