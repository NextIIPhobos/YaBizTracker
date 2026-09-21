# Contributing

## Русская версия

Спасибо за интерес к YaBizTracker.

### Требования

- Python 3.10+.
- Не добавляйте API-ключи, пароли, токены, локальные базы данных и пользовательские данные в репозиторий.
- Изменения поведения должны сопровождаться тестами.
- При изменении пользовательского поведения обновляйте README и связанную документацию.

### Проверки перед Pull Request

```bash
python -m pytest -q
python -m compileall -q main.py yabiztracker tests
ruff check main.py yabiztracker tests
```

Для изменений GUI дополнительно рекомендуется проверить приложение на Windows, включая EXE-сборку и WebEngine.

### Pull Request

Опишите:

- что изменено;
- зачем это нужно;
- какие тесты выполнены;
- есть ли изменения схемы SQLite или миграций;
- затронута ли документация.

Не добавляйте реальные API-ключи, базы с пользовательскими данными или другие секреты.

---

## English version

Thank you for your interest in YaBizTracker.

### Requirements

- Python 3.10+.
- Do not add API keys, passwords, tokens, local databases or user data to the repository.
- Behavioral changes should be accompanied by tests.
- Update the README and related documentation when user-facing behavior changes.

### Checks before a Pull Request

```bash
python -m pytest -q
python -m compileall -q main.py yabiztracker tests
ruff check main.py yabiztracker tests
```

For GUI changes, Windows testing is additionally recommended, including the EXE build and WebEngine behavior.

### Pull Request

Describe:

- what changed;
- why the change is needed;
- which tests were run;
- whether SQLite schema or migrations changed;
- whether documentation changed.

Do not add real API keys, databases containing user data or other secrets.
