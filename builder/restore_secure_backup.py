"""Restore a .ldbak backup; close LogistDesk first. Never pass passwords as args."""
from __future__ import annotations
import argparse
import getpass
from pathlib import Path
from database import default_data_dir
from security import SecurityVault, VaultError


def main() -> int:
    parser = argparse.ArgumentParser(description='Восстановление защищённой копии LogistDesk')
    parser.add_argument('backup', type=Path, help='Путь к файлу .ldbak')
    parser.add_argument('--data-dir', type=Path, default=default_data_dir())
    args = parser.parse_args()
    vault = SecurityVault(args.data_dir)
    try:
        vault.acquire_lock()
        if vault.pin_configured:
            pin = getpass.getpass('PIN (4 цифры): ')
            vault.unlock_pin(pin, recovery=True)
        else:
            username = input('Логин: ').strip()
            password = getpass.getpass('Старый пароль: ')
            vault.unlock(username, password, recovery=True)
        if input('Напиши RESTORE, чтобы заменить базу резервной копией: ').strip() != 'RESTORE':
            print('Отменено. Данные не изменены.')
            return 1
        vault.restore_from_backup(args.backup)
        print('SUCCESS: зашифрованная база восстановлена и проверена.')
        return 0
    except (VaultError, OSError) as exc:
        print('ОШИБКА:', exc)
        return 1
    finally:
        vault.release_lock()


if __name__ == '__main__':
    raise SystemExit(main())
