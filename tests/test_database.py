"""Base SQLite, perfiles, preferencias, selección serializable y límite de copias de seguridad."""
import pytest

from app.core.document_loader import create_working_copy, inspect_file, list_backups, prune_backups
from app.database.database import MIGRATIONS, Database
from app.database.profile_repository import ProfileError, ProfileRepository
from app.database.settings_repository import DEFAULTS, SettingsRepository


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "prueba.db")
    yield database
    database.close()


def test_migrations_bring_schema_to_latest(db):
    assert db.version == len(MIGRATIONS)
    reopened = Database(db.path)
    assert reopened.version == len(MIGRATIONS)
    reopened.close()


def test_damaged_database_is_set_aside(tmp_path):
    path = tmp_path / "estandria.db"
    path.write_bytes(b"esto no es una base de datos SQLite" * 50)
    database = Database(path)
    assert database.recovered_from is not None and database.recovered_from.is_file(), "el archivo dañado se conserva"
    assert database.version == len(MIGRATIONS)
    database.close()


def test_profile_crud(db, selection):
    repo = ProfileRepository(db)
    profile = repo.create("APA 7 Profesor", "apa7", selection.to_dict(), "Sin sangría")
    assert repo.get(profile.id).nombre == "APA 7 Profesor"
    with pytest.raises(ProfileError, match="Ya existe"):
        repo.create("apa 7 profesor", "apa7", {})  # sin distinguir mayúsculas
    with pytest.raises(ProfileError, match="vacío"):
        repo.create("   ", "apa7", {})
    updated = repo.update(profile.id, nombre="APA 7 Universidad", descripcion="Institucional")
    assert updated.nombre == "APA 7 Universidad" and updated.descripcion == "Institucional"
    first, second = repo.duplicate(profile.id), repo.duplicate(profile.id)
    assert first.nombre == "Copia de APA 7 Universidad" and second.nombre == "Copia de APA 7 Universidad (2)"
    assert [p.nombre for p in repo.list("apa7")] == sorted(p.nombre for p in repo.list())
    assert repo.list("otra") == []
    repo.delete(profile.id)
    assert repo.get(profile.id) is None


def test_settings_defaults_and_types(db):
    settings = SettingsRepository(db)
    assert settings.get("conservar_respaldos") == DEFAULTS["conservar_respaldos"]
    settings.set("abrir_al_exportar", True)
    settings.set("recientes", ["C:/a.docx"])
    assert settings.get("abrir_al_exportar") is True and settings.get("recientes") == ["C:/a.docx"]
    db.conn.execute("UPDATE preferencias SET valor = '\"texto\"' WHERE clave = 'abrir_al_exportar'")
    assert settings.get("abrir_al_exportar") is False, "un tipo inesperado vuelve al predeterminado"
    with pytest.raises(KeyError):
        settings.get("clave_inventada")


def test_selection_round_trip(selection, apa):
    from app.core.rule_engine import RuleSelection
    selection.set_active("par_sangria_primera", False)
    selection.set_param("tip_familia", "familia", "Arial")
    restored = RuleSelection(apa)
    assert restored.apply_dict(selection.to_dict()) == []
    assert restored.to_dict() == selection.to_dict()


def test_selection_ignores_what_no_longer_fits(selection):
    data = selection.to_dict()
    data["edicion"] = "6.ª"
    data["activas"]["regla_eliminada"] = True
    data["parametros"]["pag_margenes"]["superior_cm"] = 99  # fuera de rango
    problems = selection.apply_dict(data)
    assert any("edición" in p for p in problems)
    assert any("regla_eliminada" in p for p in problems)
    assert any("Márgenes" in p for p in problems)
    assert selection.params("pag_margenes")["superior_cm"] == 2.54


def test_backup_limit_only_touches_own_copies(full_doc, tmp_path):
    folder = tmp_path / "respaldos"
    folder.mkdir()
    foreign = folder / "notas_del_usuario.docx"
    foreign.write_bytes(b"no es una copia")
    info = inspect_file(full_doc)
    copies = [create_working_copy(info, folder, keep=2) for _ in range(4)]
    remaining = list_backups(folder)
    assert remaining == sorted(copies[-2:], reverse=True)
    assert foreign.is_file()
    prune_backups(folder, 1, protect=(copies[-2],))
    assert copies[-2].is_file(), "la copia protegida (documento abierto) nunca se borra"
    assert prune_backups(folder, 0) == 0, "0 = conservar todas"


def test_missing_backup_folder_is_reported(full_doc, tmp_path):
    from app.core.document_loader import LoadError
    with pytest.raises(LoadError, match="no existe"):
        create_working_copy(inspect_file(full_doc), tmp_path / "no_existe")
