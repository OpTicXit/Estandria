"""Rutas de la aplicación, válidas tanto en desarrollo como en el ejecutable."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app import APP_NAME


def resource_dir() -> Path:
    """Carpeta de recursos: la del proyecto o la que prepara PyInstaller (_MEIPASS)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def standards_dir() -> Path:
    return resource_dir() / "app" / "standards"


def assets_dir() -> Path:
    return resource_dir() / "assets"


def user_data_dir() -> Path:
    """Datos locales del usuario (%LOCALAPPDATA%\\Estandria). Nada sale del equipo."""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    path = user_data_dir() / "respaldos"
    path.mkdir(exist_ok=True)
    return path
