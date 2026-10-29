"""Аварийная выгрузка всех пользовательских таблиц SQLite в CSV для Excel.
Работает без PySide6 и без запуска основного приложения. База не изменяется.
"""
from __future__ import annotations
import argparse
import csv
import getpass
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def default_db() -> Path:
    custom = os.environ.get('LOGIST_DATA_DIR')
    if custom:
        return Path(custom) / 'logist.db'
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'LogistDesk' / 'logist.db'
    return Path.home() / '.local' / 'share' / 'LogistDesk' / 'logist.db'


def export_database(db_path: Path, output_root: Path, *, vault=None) -> tuple[Path, dict[str, int]]:
    db_path = Path(db_path).expanduser().resolve()
    if vault is None and not db_path.is_file():
        raise FileNotFoundError(f'База не найдена: {db_path}')
    output_root = Path(output_root).expanduser().resolve()
    if vault is not None:
        con = sqlite3.connect(':memory:')
        con.deserialize(vault.load_bytes())
        con.execute('PRAGMA query_only=ON')
    else:
        # SQLite read-only: do not create a new empty database by mistake.
        con = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if not tables:
            raise ValueError('В базе не обнаружены пользовательские таблицы')
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        folder = output_root / f'LogistDesk_export_{stamp}'
        folder.mkdir(parents=True, exist_ok=False)
        counts = {}
        for name in tables:
            # Table names are quoted safely, including future schema additions.
            quoted = '"' + name.replace('"', '""') + '"'
            cursor = con.execute(f'SELECT * FROM {quoted}')
            columns = [d[0] for d in cursor.description]
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
            path = folder / f'{safe_name}.csv'
            count = 0
            with path.open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.writer(stream, delimiter=';', quoting=csv.QUOTE_MINIMAL)
                writer.writerow(columns)
                for row in cursor:
                    writer.writerow([row[col] if row[col] is not None else '' for col in columns])
                    count += 1
            counts[name] = count
        with (folder / 'README_ОТКРЫТЬ.txt').open('w', encoding='utf-8-sig') as f:
            f.write('Аварийная выгрузка LogistDesk.\nCSV открываются в Excel (UTF-8, разделитель ;).\n'
                    'Файлы включают все столбцы SQLite, в том числе ID и даты.\n'
                    'Для полного восстановления сохраните также исходный logist.db и папку backups.\n'
                    'Исходная база при выгрузке не изменялась.\n')
        return folder, counts
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='Аварийная выгрузка базы LogistDesk в CSV для Excel')
    parser.add_argument('--db', type=Path, default=default_db(), help='Путь к logist.db')
    parser.add_argument('--out', type=Path, default=Path.home() / 'Desktop', help='Папка для выгрузки')
    args = parser.parse_args()
    try:
        from security import SecurityVault
        vault = SecurityVault(args.db.parent)
        if vault.configured:
            if args.db.name not in ('logist.db', 'logist.db.enc'):
                raise ValueError('Для защищённой базы укажи каталог LogistDesk')
            print('Внимание: CSV после выгрузки НЕ зашифрованы. Храни их в защищённом месте.')
            if vault.pin_configured:
                pin = getpass.getpass('PIN (4 цифры): ')
                vault.unlock_pin(pin)
            else:
                login = input('Логин: ').strip()
                password = getpass.getpass('Старый пароль: ')
                vault.unlock(login, password)
        else:
            vault = None
        folder, counts = export_database(args.db, args.out, vault=vault)
        print('Выгрузка готова:', folder)
        for table, count in counts.items():
            print(f'  {table}: {count} записей')
        return 0
    except Exception as exc:
        print('Ошибка:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
