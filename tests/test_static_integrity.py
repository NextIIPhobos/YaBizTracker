"""Static integrity checks that must pass before building a Windows EXE.

These checks intentionally do not import the application or PyQt6. They are
therefore suitable for CI and for the Linux build/audit environment as well.
"""

from __future__ import annotations

import ast
import builtins
import pathlib
import symtable


ROOT = pathlib.Path(__file__).resolve().parents[1] / "yabiztracker"
PACKAGE = "yabiztracker"
BUILTINS = set(dir(builtins)) | {"__file__", "__version__"}


def _py_files():
    return sorted(ROOT.rglob("*.py"))


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = rel.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return PACKAGE + ("." + ".".join(parts) if parts else "")


def _module_symbols(table: symtable.SymbolTable) -> set[str]:
    return {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_local() or symbol.is_imported() or symbol.is_parameter()
    }


def _undefined_global_names(table: symtable.SymbolTable, module_symbols: set[str]):
    result = []

    def walk(scope):
        for symbol in scope.get_symbols():
            if not symbol.is_referenced():
                continue
            name = symbol.get_name()
            if name in BUILTINS:
                continue
            if scope.get_type() == "module":
                if not (symbol.is_local() or symbol.is_imported() or symbol.is_parameter()):
                    result.append((scope.get_name(), name))
            elif symbol.is_global() and name not in module_symbols:
                result.append((scope.get_name(), name))
        for child in scope.get_children():
            walk(child)

    walk(table)
    return sorted(set(result))


def test_all_python_files_parse():
    for path in _py_files():
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_undefined_global_names():
    """Catch NameError-class defects such as a forgotten Qt/class import."""
    failures = []
    for path in _py_files():
        source = path.read_text(encoding="utf-8")
        table = symtable.symtable(source, str(path), "exec")
        undefined = _undefined_global_names(table, _module_symbols(table))
        if undefined:
            failures.append(f"{path.relative_to(ROOT.parent)}: {undefined}")
    assert not failures, "Undefined names found:\n" + "\n".join(failures)


def _internal_import_graph():
    paths = { _module_name(path): path for path in _py_files() }
    graph = {module: set() for module in paths}

    for module, path in paths.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = alias.name
                    if target in paths:
                        graph[module].add(target)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = module
                    for _ in range(node.level):
                        base = base.rsplit(".", 1)[0]
                    target = base + (("." + node.module) if node.module else "")
                else:
                    target = node.module or ""
                if target in paths:
                    graph[module].add(target)
                for alias in node.names:
                    candidate = target + "." + alias.name
                    if candidate in paths:
                        graph[module].add(candidate)
    for module in graph:
        graph[module].discard(module)
    return graph


def test_no_internal_import_cycles():
    graph = _internal_import_graph()
    cycles = []
    visiting = set()
    visited = set()
    stack = []

    def dfs(node):
        if node in visiting:
            try:
                start = stack.index(node)
            except ValueError:
                start = 0
            cycles.append(stack[start:] + [node])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for child in graph[node]:
            dfs(child)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        dfs(node)

    assert not cycles, "Circular imports found:\n" + "\n".join(" -> ".join(cycle) for cycle in cycles)


def test_no_top_level_use_before_local_class_definition():
    """Detect executable module/class-body references to a class declared later.

    Function bodies are deliberately excluded because functions execute after
    module import in normal application flow and may legally refer to classes
    declared later in the same module.
    """
    failures = []

    def local_classes_before(tree):
        classes = {node.name: node.lineno for node in tree.body if isinstance(node, ast.ClassDef)}
        if not classes:
            return []
        result = []

        def scan_executable(node, owner):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if isinstance(child, ast.ClassDef):
                    # A class body executes immediately; inspect it recursively.
                    scan_executable(child, child.name)
                    continue
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    defined_at = classes.get(child.id)
                    if defined_at is not None and child.lineno < defined_at:
                        result.append((owner, child.id, child.lineno, defined_at))
                scan_executable(child, owner)

        scan_executable(tree, "<module>")
        return result

    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        issues = local_classes_before(tree)
        if issues:
            failures.append(f"{path.relative_to(ROOT.parent)}: {issues}")

    assert not failures, "Local classes used before declaration:\n" + "\n".join(failures)


def test_qt_signal_users_import_pyqt_signal_explicitly():
    """Keep the earlier regression guard for a common EXE-only NameError."""
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        uses_signal = any(
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == "pyqtSignal"
            for node in ast.walk(tree)
        )
        if not uses_signal:
            continue
        imported = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "PyQt6.QtCore"
            and any(alias.name == "pyqtSignal" for alias in node.names)
            for node in tree.body
        )
        assert imported, f"{path} uses pyqtSignal without an explicit QtCore import"


def test_main_window_uses_persistent_wall_clock_scheduler_helper():
    source=(ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "next_wall_clock_occurrence" in source
    assert 'self._read_next_scan_at()' in source
    assert 'self.scheduler.add_job(' in source
    assert 'id="scan"' in source


def test_main_window_shutdown_stops_timers_and_closes_webengine_before_db():
    source=(ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "self.quota_timer" in source and "timer.stop()" in source
    assert 'webview.stop()' in source
    assert 'webview.setUrl(QUrl("about:blank"))' in source
    assert 'webview.deleteLater()' in source
    assert 'QApplication.processEvents()' in source
    # DB must remain open until workers and WebEngine have been handled.
    assert source.index("webview.stop()") < source.index("self.db.close()")


def test_organization_table_exposes_settlement_column_and_filter():
    source=(ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert '"Населённый пункт"' in source
    assert "CheckableDropdown" in source
    assert '"city_names": self.settlement_filter.checked_values()' in source


def test_export_contains_settlement_column():
    source=(ROOT.parent / "yabiztracker" / "services" / "export_service.py").read_text(encoding="utf-8")
    assert '"Населённый пункт"' in source
    assert 'o.get("city_name", "")' in source
