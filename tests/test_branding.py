from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def classes(path):
    return {node.name for node in parse(path).body if isinstance(node, ast.ClassDef)}


def test_repository_is_clean_and_runtime_files_are_not_committed():
    assert not (ROOT / "config.json").exists()
    assert not (ROOT / "settings.json").exists()
    assert not (ROOT / "test_api_keys.py").exists()


def test_branding_and_version_are_consistent():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.0.2"
    assert (ROOT / "yabiztracker" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__="1.0.2"'
    assert 'version = "1.0.2"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    source_files = list((ROOT / "yabiztracker").rglob("*.py")) + [ROOT / "main.py"]
    for p in source_files:
        text = p.read_text(encoding="utf-8").lower()
        assert "sambizmonitor" not in text
        assert "samara" not in text


def test_ui_is_split_into_cohesive_modules():
    ui = ROOT / "yabiztracker" / "ui"
    assert classes(ui / "main_window.py") == {"AppState", "MainWindow"}
    assert {"CityRow", "OrganizationTableWidget"} <= classes(ui / "widgets.py")
    assert {"SettingsDialog", "TrashDialog", "ExportDialog"} <= classes(ui / "dialogs.py")
    assert {"NextContactItem", "NextContactDelegate", "StatusDelegate"} <= classes(ui / "delegates.py")
    assert {"HealthWorker", "SuggestWorker"} <= classes(ui / "workers.py")
    # The main window coordinates the application UI. Keep a practical cap so
    # that feature additions still trigger a deliberate modularity review.
    assert len((ui / "main_window.py").read_text(encoding="utf-8").splitlines()) < 900


def test_pyinstaller_build_configuration_is_explicit():
    spec = (ROOT / "YaBizTracker.spec").read_text(encoding="utf-8")
    assert "name='YaBizTracker'" in spec
    assert "console=False" in spec
    assert "icon='icon.ico'" in spec
    assert "yabiztracker/map.html" in spec
    assert "collect_all('PyQt6.QtWebEngineCore')" in spec
    assert "collect_all('PyQt6.QtWebEngineWidgets')" in spec


def test_runtime_resources_exist():
    assert (ROOT / "icon.png").is_file()
    assert (ROOT / "icon.ico").is_file()
    assert (ROOT / "yabiztracker" / "map.html").is_file()


def test_build_script_is_reproducible_and_runs_tests_first():
    bat = (ROOT / "build_windows.bat").read_text(encoding="utf-8")
    assert "python -m pip install -r requirements.txt -r requirements-dev.txt" in bat
    assert "python -m pytest -q" in bat
    assert "python -m PyInstaller --clean --noconfirm YaBizTracker.spec" in bat
    assert r"dist\YaBizTracker.exe" in bat


def test_domain_rules_are_independent_of_qt():
    for name in ("filters.py", "selection.py", "scan.py", "models.py"):
        text = (ROOT / "yabiztracker" / "domain" / name).read_text(encoding="utf-8")
        assert "PyQt" not in text


def test_database_schema_contains_per_category_liveness():
    db = (ROOT / "yabiztracker" / "database" / "database.py").read_text(encoding="utf-8")
    assert "SCHEMA_VERSION = 9" in db
    assert "organization_category_observations" in db
    assert "PRIMARY KEY(org_id, city_name, search_category)" in db


def test_settings_persistence_is_atomic_and_tolerates_missing_files():
    text = (ROOT / "yabiztracker" / "services" / "settings.py").read_text(encoding="utf-8")
    assert "except FileNotFoundError" in text
    assert "os.replace(tmp, path)" in text
    assert "os.fsync(f.fileno())" in text


def test_api_retry_does_not_sleep_inside_domain_layer():
    for p in (ROOT / "yabiztracker" / "domain").glob("*.py"):
        assert "time.sleep" not in p.read_text(encoding="utf-8")


def test_initial_scan_is_marked_only_after_completion():
    ui = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
    run_start = ui.index("def run_scan(self,manual=True):")
    run_end = ui.index("    def stop_scan", run_start)
    completed_start = ui.index("def scan_completed(self,st):")
    completed_end = ui.index("    def scan_failed", completed_start)
    run_block = ui[run_start:run_end]
    completed_block = ui[completed_start:completed_end]
    assert 'self.settings["initial_scan_completed"] = True' not in run_block
    assert 'self.settings["initial_scan_completed"] = True' in completed_block


def test_database_observation_write_is_part_of_upsert_transaction():
    db = (ROOT / "yabiztracker" / "database" / "database.py").read_text(encoding="utf-8")
    upsert = db[db.index("def upsert_organizations"):db.index("def get_active_organizations")]
    assert "search_category: str | None = None" in upsert
    assert "organization_category_observations" in upsert
    assert upsert.index("organization_category_observations") < upsert.index("self.conn.commit()")


def test_windows_launchers_cover_packaged_and_source_runs():
    dialogs = (ROOT / "yabiztracker" / "ui" / "dialogs.py").read_text(encoding="utf-8")
    assert "QDate, pyqtSignal" in dialogs
    bat = (ROOT / "run.bat").read_text(encoding="utf-8")
    assert r'dist\YaBizTracker.exe' in bat
    assert r'.venv\Scripts\pythonw.exe' in bat
    assert "pyw.exe -3" in bat
    vbs = (ROOT / "run.vbs").read_text(encoding="utf-8")
    assert 'run.bat' in vbs
    assert 'cmd.exe /c' in vbs


def test_dialog_module_does_not_use_undefined_pyqt_signal():
    tree = ast.parse((ROOT / "yabiztracker" / "ui" / "dialogs.py").read_text(encoding="utf-8"))
    imported = set()
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "PyQt6.QtCore":
            imported.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Name):
            used.add(node.id)
    assert "pyqtSignal" in imported
    assert "pyqtSignal" in used


def test_ui_pyqt_names_are_explicitly_imported():
    """Ловим runtime NameError/ImportError для используемых Qt-классов до сборки EXE."""
    ui = ROOT / "yabiztracker" / "ui"
    for path in ui.glob("*.py"):
        tree = parse(path)
        imported = set()
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    imported.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.Name):
                used.add(node.id)
        qt_names = {name for name in used if name.startswith("Q") and len(name) > 1 and name[1].isupper()}
        missing = sorted(qt_names - imported)
        assert not missing, f"{path}: Qt names used without explicit import: {missing}"


def test_dialog_qdesktopservices_comes_from_qtgui():
    text = (ROOT / "yabiztracker" / "ui" / "dialogs.py").read_text(encoding="utf-8")
    assert "from PyQt6.QtGui import QDesktopServices" in text
    assert "QDesktopServices" not in text.split("from PyQt6.QtWidgets", 1)[1].split("\n\n", 1)[0]
