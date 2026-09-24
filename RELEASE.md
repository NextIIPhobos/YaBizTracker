## Что нового в 1.1.2

- Добавлен фоновый поиск социальных сетей для найденных организаций.
- Социальные ссылки извлекаются из публичной карточки организации Яндекс Карт и официального сайта организации; поддерживаются VK, Telegram, Max, Instagram, Одноклассники, Дзен, Rutube, YouTube, TikTok, Facebook, X/Twitter, Threads, Pinterest, LinkedIn, Viber, WhatsApp и Discord.
- Найденные ссылки нормализуются и проверяются доступностью HTTP; ссылки с 404/5xx не сохраняются.
- Добавлена команда «Помощь → Ручной поиск соц. сетей» для повторного поиска по всем организациям в базе.
- ПКМ по столбцу «Соцсети» открывает отдельное меню ссылок по платформам.
- Добавлена миграция SQLite до схемы 10 с состоянием поиска соцсетей; старые БД продолжают работать.
- Добавлены регрессионные тесты парсинга, нормализации, проверки ссылок, БД и UI-контракта.

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
9. Создать Git tag, соответствующий версии, например `v1.1.1`.
10. Создать GitHub Release из этого tag и прикрепить `YaBizTracker.exe`.

Артефактом релиза является собранный EXE. Исходный код остаётся в репозитории под GNU GPL v3. Коммерческое использование разрешено при соблюдении GPL и лицензий сторонних компонентов.

---

## Что нового в 1.1.1

- Маркеры карты теперь всегда соответствуют полному набору фильтров списка организаций: текстовому поиску, категориям, статусам, населённым пунктам и фильтрам наличия контактов/CRM-полей.
- Маркеры стали кликабельными: клик выделяет соответствующую организацию в таблице, а выбор организации в таблице выделяет её маркер красным цветом, увеличивает его и выводит на передний план.
- Фильтр «Статусы» переведён на многовыбор с чекбоксами.
- Фильтры «Категории», «Статусы» и «Населённый пункт» применяются после закрытия окна выбора, поэтому можно спокойно сформировать набор условий без промежуточных обновлений.
- «Отображаемые столбцы» применяются как единая операция после закрытия окна; поиск по отображаемым столбцам и карта обновляются после подтверждения выбора.
- После поиска выполняется проверка категорий всех существующих организаций. Новые категории добавляются в `categories.txt` с нормализацией `ё/е`, регистра и пробелов; добавление отражается в журнале событий.
- В меню «Помощь» добавлена команда «Проверка доступных категорий».
- Сокращено число повторных чтений SQLite при обновлении таблицы и карты; текущий набор организаций кэшируется в памяти для ускорения работы с большими списками.
- Добавлены регрессионные тесты для фильтрации карты, кликов по маркерам, отложенного применения чекбоксов, каталога категорий и версии 1.1.1.

## What's new in 1.1.1

- Map markers now always match the complete set of organization-list filters: text search, categories, statuses, settlements, and contact/CRM presence filters.
- Map markers are clickable: clicking a marker selects the corresponding organization in the table; selecting an organization in the table highlights its marker in red, enlarges it, and brings it to the front.
- The **Status** filter is now a multi-select checkbox filter.
- **Categories**, **Status**, and **Settlement** filters are applied after the selection popup is closed, allowing users to choose several values without intermediate refreshes.
- **Displayed columns** are applied as one operation after the popup closes; text search and map synchronization follow the committed selection.
- After a search, the application checks all existing organizations for previously unknown categories. New categories are appended to `categories.txt` using normalized `ё/е`, case, and whitespace comparison; additions are logged.
- Added **Check available categories** to the **Help** menu.
- Reduced repeated SQLite reads during table/map refreshes; the active organization set is cached in memory for large datasets.
- Added regression tests for map filtering, marker clicks, deferred checkbox application, category catalog synchronization, and version 1.1.1.

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
9. Create a Git tag matching the version, for example `v1.1.1`.
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
