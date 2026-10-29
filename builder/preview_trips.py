"""Render the real Qt workspace against an isolated SQLite snapshot."""
import os
import sys
import tempfile
from contextlib import closing
os.environ.setdefault('QT_QPA_PLATFORM', 'windows' if '--native' in sys.argv else 'offscreen')
import sqlite3
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from database import Database, default_data_dir
import app
from theme import STYLESHEET
from ui_common import apply_dark_palette

output = Path(__file__).parent / 'ui_review'
output.mkdir(exist_ok=True)
source = default_data_dir() / 'logist.db'
temporary = tempfile.TemporaryDirectory(prefix='logistdesk_ui_')
target = Path(temporary.name) / 'preview.db'
if source.exists():
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
qt = QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeuib.ttf')
QFontDatabase.addApplicationFont('C:/Windows/Fonts/seguisym.ttf')
qt.setStyle('Fusion')
apply_dark_palette(qt)
qt.setStyleSheet(STYLESHEET)
with patch.object(app, 'Database', lambda: Database(target)), patch.object(app.LogistWindow, 'setup_tray', lambda self: None):
    window = app.LogistWindow()
window.reminder_timer.stop()
window.show()
sizes = [(1093, 566)] if '--native' in sys.argv else [(1920, 1020), (1366, 708), (1093, 566)]
for width, height in sizes:
    window.resize(width, height)
    qt.processEvents()
    suffix = '_windows_125' if '--native' in sys.argv else ''
    window.grab().save(str(output / f'trips_{width}{suffix}.png'))
    print('SIZE', width, height, 'ACTUAL', window.width(), window.height(), 'MIN', window.minimumSizeHint().width(), window.minimumSizeHint().height())
print('ROUTES', window.routes_table.rowCount())
window.db.close()
window.hide()
temporary.cleanup()
