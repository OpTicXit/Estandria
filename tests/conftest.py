import hashlib
from pathlib import Path

import pytest

from app.core.document_analyzer import known_scopes
from app.core.rule_engine import RuleSelection, load_standard
from app.formats.docx_operations import OPERATIONS
from app.paths import standards_dir
from tests import samples


@pytest.fixture(autouse=True)
def isolated_user_data(tmp_path, monkeypatch):
    """Los respaldos y registros de las pruebas van a una carpeta temporal."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


@pytest.fixture
def full_doc(tmp_path) -> Path:
    return samples.build_full(tmp_path / "trabajo.docx")


@pytest.fixture
def plain_doc(tmp_path) -> Path:
    return samples.build_plain(tmp_path / "plano.docx")


@pytest.fixture
def sections_doc(tmp_path) -> Path:
    return samples.build_sections(tmp_path / "secciones.docx")


@pytest.fixture(scope="session")
def apa():
    return load_standard(standards_dir() / "apa7" / "rules.json", OPERATIONS, known_scopes())


@pytest.fixture
def selection(apa) -> RuleSelection:
    return RuleSelection(apa)


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
