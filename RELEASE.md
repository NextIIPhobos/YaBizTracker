# Release checklist

1. Update `VERSION` and `[project].version` in `pyproject.toml`.
2. Update release notes.
3. Run `python -m compileall -q main.py yabiztracker tests`.
4. Run `python -m pytest -q`.
5. Run `ruff check main.py yabiztracker tests`.
6. On Windows run `build_windows.bat`.
7. Smoke-test `dist\YaBizTracker.exe` on a clean Windows user profile.
8. Confirm no API keys, `config.json`, `settings.json`, `organizations.db`, logs or backups are in the repository.
9. Create a Git tag matching the version, for example `v1.0.0`.
10. Create a GitHub Release from that tag and attach `YaBizTracker.exe`.

The release asset is the compiled executable. Source code remains in the repository under the GNU GPL v3. Commercial use is permitted, subject to the GPL and third-party component licenses.
