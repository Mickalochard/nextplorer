"""Couche d'abstraction plateforme (Linux / Windows) : notifications,
presse-papiers, ouverture de fichiers, intégration système, montage
permanent. `nextplorer/cli.py` et `nextplorer/lockwatch.py` ne doivent
jamais importer `linux`/`windows` directement, seulement ce module."""
from __future__ import annotations

import sys

if sys.platform == "win32":
    from . import windows as _impl
else:
    from . import linux as _impl

MOUNT_NAME = _impl.MOUNT_NAME

notify = _impl.notify
copy_to_clipboard = _impl.copy_to_clipboard
open_path = _impl.open_path
launch_browser = _impl.launch_browser
install_file_manager_integration = _impl.install_file_manager_integration
install_url_handler = _impl.install_url_handler
uninstall_url_handler = _impl.uninstall_url_handler
export_gpo_xml = _impl.export_gpo_xml
setup_permanent_mount = _impl.setup_permanent_mount
mount_control = _impl.mount_control
mount_status_summary = _impl.mount_status_summary
is_office_app_running = _impl.is_office_app_running
