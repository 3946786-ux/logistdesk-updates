"""Локальные диагностические журналы LogistDesk (без содержимого заказов)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os
import sys
import traceback

LOGGER_NAME = 'logistdesk'


def log_directory() -> Path:
    root = os.environ.get('LOCALAPPDATA')
    base = Path(root) if root else Path.home() / '.local' / 'share'
    return base / 'LogistDesk' / 'logs'


def configure_logging(directory: Path | None = None) -> Path:
    directory = directory or log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'logistdesk.log'
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(target, maxBytes=2_000_000, backupCount=4, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logger.addHandler(handler)
    logger.info('Приложение запускается; Python %s', sys.version.split()[0])
    return target


def log_exception(context: str, error: BaseException) -> None:
    """Пишет тип ошибки и стек; не включает значения полей формы."""
    logging.getLogger(LOGGER_NAME).error('%s: %s', context, type(error).__name__,
                                          exc_info=(type(error), error, error.__traceback__))


def install_exception_hook() -> None:
    previous = sys.excepthook
    def hook(exc_type, exc_value, exc_tb):
        logging.getLogger(LOGGER_NAME).critical('Необработанная ошибка', exc_info=(exc_type, exc_value, exc_tb))
        previous(exc_type, exc_value, exc_tb)
    sys.excepthook = hook
