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
9. Создать Git tag, соответствующий версии, например `v1.1.0`.
10. Создать GitHub Release из этого tag и прикрепить `YaBizTracker.exe`.

Артефактом релиза является собранный EXE. Исходный код остаётся в репозитории под GNU GPL v3. Коммерческое использование разрешено при соблюдении GPL и лицензий сторонних компонентов.

---

## Что нового в 1.1.0

- Поле текстового поиска на главном окне теперь ищет только по столбцам, которые в данный момент отмечены в «Отображаемые столбцы».
- Добавлен пользовательский каталог `categories.txt`: при первом запуске он создаётся из встроенного каталога, далее категории загружаются из файла.
- В настройках добавлена кнопка **«Изменить список категорий»**; после изменения `categories.txt` список в программе обновляется автоматически.
- Добавлена очистка всех резервных копий, логов и безопасно удаляемых временных/вспомогательных файлов.
- Фильтр **«Категория»** на главном окне синхронизирован с картой: при его использовании на карте остаются только соответствующие организации.
- Добавлены регрессионные тесты для области текстового поиска, каталога категорий, очистки файлов и фильтрации маркеров.
- Версия приложения и Python-пакета обновлена до **1.1.0**.

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
9. Create a Git tag matching the version, for example `v1.1.0`.
10. Create a GitHub Release from that tag and attach `YaBizTracker.exe`.

### What's new in 1.1.0

- The main-window text search now searches only the columns currently enabled in **Displayed columns**.
- Added a user-editable `categories.txt` catalog; it is generated from the built-in catalog on first launch and loaded from the file on subsequent launches.
- Added **Edit category list** in Settings; changes to `categories.txt` are detected and applied automatically.
- Added cleanup actions for all backups, logs, and safely regenerable temporary/auxiliary files.
- The main-window **Category** filter is synchronized with the map, so only matching organization markers remain visible.
- Added regression tests for search scope, category catalog loading, cleanup, and map category filtering.
- Updated application and Python package version to **1.1.0**.



The release artifact is the compiled executable. Source code remains in the repository under GNU GPL v3. Commercial use is permitted subject to the GPL and third-party component licenses.
