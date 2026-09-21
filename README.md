# YaBizTracker

Local Windows desktop application for discovering organizations in Yandex Maps and turning fresh results into a lightweight lead list.

The project is designed as a **single-user local application**: SQLite stores the local dataset, scheduled scans run in the background, and no application backend is required.

## What the application does

- Searches organizations by settlement and Yandex Maps category.
- Supports multiple settlements and included/excluded categories.
- Excludes an organization when **any** of its Yandex categories matches an excluded category.
- Stores organization contacts, website, social links, coordinates and source status.
- Keeps CRM fields: status, comment, responsible person and next contact date.
- Provides filtering, sorting, Shift multi-selection and bulk CRM updates.
- Contact filters **Телефон, E-mail, Сайт, Соцсети, Ответственный, Следующий контакт** are three-state: first click shows records with a value, second click shows records without a value, third click disables the filter.
- Shows a dedicated **Населённый пункт** column; the corresponding filter is a multi-select checkbox dropdown built only from settlements configured for scanning.
- Copies e-mails or phones of selected organizations to the clipboard.
- Shows organizations on a Yandex Maps view.
- Tracks API usage and configurable local request limits.
- Runs scans manually or through APScheduler.
- Resumes interrupted scans page-by-page using durable SQLite checkpoints.
- Keeps a recoverable Trash with a 30-day retention policy.
- Creates and verifies SQLite backups and can restore a damaged database.
- Exports data to XLSX with an independent fallback writer.
- Provides diagnostics, rotating logs and crash reports.

## Architecture

```text
                    ┌─────────────────────────────┐
                    │          PyQt6 UI            │
                    │ MainWindow / dialogs/widgets │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │          Services            │
                    │ scan / backup / export /     │
                    │ settings / API usage         │
                    └───────┬───────────┬─────────┘
                            │           │
                 ┌──────────▼───┐   ┌──▼───────────┐
                 │ Domain rules │   │ Yandex API   │
                 │ filters      │   │ clients      │
                 │ categories   │   │ retry/errors │
                 │ selection    │   └──────┬───────┘
                 │ scan identity │          │
                 └──────────────┘          │
                            │               │
                       ┌────▼───────────────▼───┐
                       │       SQLite            │
                       │ organizations            │
                       │ CRM history              │
                       │ trash / ignore tombstone │
                       │ scan checkpoints         │
                       │ per-category liveness    │
                       └──────────────────────────┘
```

### Architectural decisions

**Domain logic is independent of Qt.** Filtering, category matching, selection semantics and scan signatures live under `yabiztracker/domain/` and are directly unit-testable.

**The organization table has an explicit column contract.** `domain/table.py` owns stable column indexes, avoiding scattered magic numbers when UI columns evolve.

**UI is split by responsibility.** `main_window.py` owns application orchestration; dialogs, delegates, widgets and workers live in dedicated modules. This prevents the main window from becoming the single dumping ground for every UI concern.

**Liveness is tracked per city and search category.** A global "missing" counter is unsafe because one organization can legitimately belong to several categories. `organization_category_observations` avoids deleting a lead simply because it disappeared from one query while remaining visible in another.

**SQLite writes are transactional.** Organization upserts and category observations for a processed page are committed together. CRM changes, Trash operations, migrations and checkpoints use transactions as well.

**Search reconciliation is conservative.** A missing organization is not removed from the active list after one incomplete result. Reconciliation requires a completed, non-truncated scan and consecutive misses; CRM-active leads are protected.

**Runtime state is not part of the repository.** API keys, settings, SQLite databases, API usage data, backups and logs are created beside the application at runtime and are ignored by Git.

## Project structure

```text
.
├── yabiztracker/
│   ├── api/              # Yandex API clients and typed errors
│   ├── database/         # SQLite schema, migrations and persistence
│   ├── domain/           # Framework-independent business rules
│   ├── services/         # Application services
│   └── ui/               # Qt windows, dialogs, widgets, delegates, workers
├── tests/                # Unit, integration and regression tests
├── main.py               # Thin application entry point
├── YaBizTracker.spec     # PyInstaller build definition
├── build_windows.bat    # Windows build/test bootstrap
├── pyproject.toml        # Project metadata, pytest and Ruff configuration
├── requirements.txt      # Runtime dependencies
├── icon.png / icon.ico   # Application branding
├── LICENSE
└── README.md
```

## Reliability features

### Scan recovery

Every search page is checkpointed. If a request fails or the application is stopped, the next scan with the same normalized configuration resumes from the last durable checkpoint instead of silently pretending the previous run completed.

### API errors and retries

The API layer distinguishes authentication, quota, network, server and invalid-response failures. HTTP 429 honors `Retry-After` when available. Server/network failures use bounded exponential backoff with jitter. Requests are counted at the point they are actually sent.

Each worker thread gets its own HTTP session, avoiding sharing a mutable `requests.Session` between concurrent Qt workers.

### Database protection

- WAL mode and foreign keys are enabled.
- SQLite busy timeout is configured.
- `PRAGMA quick_check` is used for integrity verification.
- Backups use SQLite's online backup API.
- A backup is verified before being considered valid.
- Before schema migration, a pre-migration backup can be created.
- A damaged database is preserved before restore.

### Trash

Manual exclusions are moved to a recoverable Trash and additionally receive an ignore tombstone so a subsequent scan cannot immediately re-import them. Restoration removes the tombstone. Trash entries older than 30 days are permanently removed; manual cleanup is also available.

### Crash handling

Unhandled exceptions produce a timestamped report containing application state, environment information and traceback. API keys are not included in the crash context.

## Configuration

On first launch, the application creates runtime configuration beside the executable. The settings window is used to enter:

- JavaScript API key;
- Geocoder API key;
- Search API key;
- local API limits;
- quota reset period;
- settlements;
- included and excluded categories;
- scan interval;
- backup policy.

API keys should never be committed to Git.

## Development

Python 3.10+ is supported; Python 3.11+ is recommended for development.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m compileall -q main.py yabiztracker tests
ruff check main.py yabiztracker tests
```

The Linux test environment used during development does not need to launch the Qt GUI to validate the domain/database/API layers. GUI and WebEngine smoke testing should be performed on Windows before publishing a release. The CI job therefore treats GUI-only tests as optional where Qt is unavailable.

## Windows build

`build_windows.bat`:

1. creates/updates `.venv`;
2. installs dependencies and PyInstaller;
3. verifies `icon.png` and regenerates `icon.ico`;
4. runs the complete test suite;
5. builds `dist\YaBizTracker.exe` with Qt WebEngine resources;
6. uses the application icon for the executable.

The one-file build stores runtime user data beside the EXE rather than inside PyInstaller's temporary extraction directory.

## Limitations

Yandex Maps Search API is relevance-ranked rather than a guaranteed registry of every organization. Pagination, category coverage and conservative reconciliation improve practical coverage but cannot guarantee completeness.

The JavaScript Maps API runs inside Qt WebEngine, so browser-side network requests cannot be counted as reliably as Python API requests. The application therefore avoids inventing JS request-consumption numbers.

## License

This project is licensed under the **GNU GPL v3**. The license permits commercial use and distribution, but modified/distributed versions must preserve the GPL freedoms and license obligations. See `LICENSE`.

The choice of GPLv3 is intentional because the project uses PyQt6/PyQt6-WebEngine. Riverbank states that PyQt is available under GPLv3 or a commercial license and is not available under LGPL. If you want to distribute a proprietary/non-GPL version, a compatible commercial PyQt license is required.

Third-party libraries remain under their own licenses. Using Yandex Maps APIs also remains subject to the applicable Yandex terms, API rules and quotas; the project license does not grant rights to third-party services.


## Contact-presence filters

The main organization list has six clickable presence filters:

| Filter | 1st click | 2nd click | 3rd click |
|---|---|---|---|
| Телефон | есть телефон | нет телефона | отключён |
| E-mail | есть e-mail | нет e-mail | отключён |
| Сайт | есть сайт | нет сайта | отключён |
| Соцсети | есть соцсети | нет соцсетей | отключён |
| Ответственный | назначен | не назначен | отключён |
| Следующий контакт | дата задана | дата не задана | отключён |

Пустой JSON объекта социальных сетей (`{}`) считается отсутствием соцсетей.

## Quality gates

The repository includes unit, integration and regression tests for API usage boundaries, settings migration, SQLite transactions, category exclusion, scan recovery, scheduling, backups, XLSX export, static import integrity, and the settlement filter.

Run locally with:

```text
python -m pytest -q
python -m compileall -q main.py yabiztracker tests
```

The Windows build script runs the same checks before PyInstaller packaging and verifies that the final `dist\YaBizTracker.exe` exists.

## Сбор e-mail с сайтов организаций

После поиска организаций YaBizTracker может в фоне проверять сайты организаций и дополнять поле `E-mail`. Найденные адреса нормализуются, удаляются дубликаты и сохраняются в одной ячейке через запятую, например `info@example.ru, sales@example.ru`.

Механика рассчитана на большие результаты поиска:

- поиск организаций и сбор e-mail разделены и не блокируют интерфейс;
- сайты группируются по домену: один и тот же сайт не скачивается повторно для каждой организации;
- используется ограниченная параллельность, таймауты, ограничение размера ответа и ограничение числа страниц;
- сначала проверяется главная страница, затем релевантные внутренние страницы (`Контакты`, `Реквизиты`, `О компании` и аналогичные ссылки);
- поддерживаются `mailto:` и e-mail в HTML/видимом тексте;
- результаты имеют отдельный статус (`found`, `not_found`, `error`, `blocked` и др.), поэтому HTTP-ошибка не маскируется под «e-mail не найден»;
- повторная проверка сайта выполняется по настраиваемому интервалу, а не при каждом поиске;
- обработка выполняется с соблюдением `robots.txt` в безопасном режиме. Стандарт Robots Exclusion Protocol описан в RFC 9309.

Сбор e-mail предназначен для исследовательской работы с открытыми корпоративными контактами. Программа не выполняет обход авторизации, CAPTCHA или защитных механизмов и не предназначена для автоматической массовой рассылки.
