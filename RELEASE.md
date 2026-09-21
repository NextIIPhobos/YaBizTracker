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
9. Создать Git tag, соответствующий версии, например `v1.0.0`.
10. Создать GitHub Release из этого tag и прикрепить `YaBizTracker.exe`.

Артефактом релиза является собранный EXE. Исходный код остаётся в репозитории под GNU GPL v3. Коммерческое использование разрешено при соблюдении GPL и лицензий сторонних компонентов.

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
9. Create a Git tag matching the version, for example `v1.0.0`.
10. Create a GitHub Release from that tag and attach `YaBizTracker.exe`.

The release artifact is the compiled executable. Source code remains in the repository under GNU GPL v3. Commercial use is permitted subject to the GPL and third-party component licenses.
