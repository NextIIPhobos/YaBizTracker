# Release checklist

## Русская версия

1. Обновить `VERSION` и `[project].version` в `pyproject.toml`.
2. Обновить release notes.
3. Выполнить `python -m compileall -q main.py yabiztracker tests`.
4. Выполнить `python -m pytest -q`.
5. Выполнить `ruff check main.py yabiztracker tests`.
6. В Windows запустить `build_windows.bat`.
7. Выполнить smoke-тест `dist\YaBizTracker.exe` в чистом пользовательском профиле Windows.
8. Проверить отсутствие API-ключей, `config.json`, `settings.json`, `organizations.db`, логов и резервных копий в репозитории.
9. Создать Git tag, соответствующий версии, например `v1.0.2`.
10. Создать GitHub Release из этого tag и прикрепить `YaBizTracker.exe`.

Артефактом релиза является собранный EXE. Исходный код остаётся в репозитории под GNU GPL v3. Коммерческое использование разрешено при соблюдении GPL и лицензий сторонних компонентов.

---

## Что нового в 1.0.2

- Добавлена кнопка **«Отображаемые столбцы»** над списком организаций.
- Добавлено управление видимостью каждого столбца через чекбоксы; по умолчанию все столбцы включены.
- Всплывающий список закрывается только при клике вне его области.
- Исправлен Shift-мультивыбор при выборе диапазона вверх от anchor.
- Исправлен crash `QItemSelectionModel has no attribute index`.
- Добавлены регрессионные тесты для отображения столбцов и Shift-мультивыбора.

---

## English version

1. Update `VERSION` and `[project].version` in `pyproject.toml`.
2. Update the release notes.
3. Run `python -m compileall -q main.py yabiztracker tests`.
4. Run `python -m pytest -q`.
5. Run `ruff check main.py yabiztracker tests`.
6. Run `build_windows.bat` on Windows.
7. Smoke-test `dist\YaBizTracker.exe` on a clean Windows user profile.
8. Confirm that API keys, `config.json`, `settings.json`, `organizations.db`, logs and backups are not in the repository.
9. Create a Git tag matching the version, for example `v1.0.2`.
10. Create a GitHub Release from that tag and attach `YaBizTracker.exe`.

### What's new in 1.0.2

- Added the **Displayed columns** button above the organization table.
- Added per-column visibility control using checkboxes; all columns are enabled by default.
- The popup closes only when the user clicks outside its bounds.
- Fixed Shift multi-selection when selecting a range upward from the anchor.
- Fixed the `QItemSelectionModel has no attribute index` crash.
- Added regression tests for column visibility and Shift multi-selection.

The release artifact is the compiled executable. Source code remains in the repository under GNU GPL v3. Commercial use is permitted subject to the GPL and third-party component licenses.
