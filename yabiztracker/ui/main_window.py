from __future__ import annotations
import os, sys, sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from enum import Enum
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QDesktopServices
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QComboBox, QCheckBox, QProgressBar, QGroupBox, QMessageBox, QFileDialog, QDialogButtonBox, QPlainTextEdit, QSystemTrayIcon, QDateTimeEdit, QMenu, QInputDialog, QSizePolicy
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineSettings
from apscheduler.schedulers.background import BackgroundScheduler
from ..api import YandexAPI
from ..api.errors import ApiLimitError, ApiAuthError
from ..bridge import MapBridge
from ..database import Database
from ..domain.models import STATUS_OPTIONS
from ..domain.filters import matches_organization_filters
from ..domain.schedule import next_wall_clock_occurrence
from ..domain.table import OrgColumn
from ..services.api_usage import ApiUsageService
from ..services.backup import BackupService
from ..services.export_service import ExportService
from ..services.map_controller import MapController
from ..services.scan_service import ScanWorker
from ..services.settings import load_json, save_json, migrate_settings
from ..logger import AppLogger
from .. import __version__
from .workers import HealthWorker
from .email_worker import EmailFinderWorker
from .widgets import OrganizationTableWidget, CheckableDropdown, PresenceFilterButton
from .messenger_menu import build_messenger_menu
from .dialogs import SettingsDialog, TrashDialog, ExportDialog
from .delegates import NextContactItem, NextContactDelegate, StatusDelegate
class AppState(Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    SCANNING = "scanning"
    ERROR = "error"
    SETTINGS_REQUIRED = "settings_required"
    STOPPING = "stopping"
class MainWindow(QMainWindow):
    scan_requested=pyqtSignal()
    def __init__(self,base_dir):
        super().__init__();self.base_dir=base_dir
        self.config=load_json(os.path.join(base_dir,"config.json"))
        self.settings=migrate_settings(load_json(os.path.join(base_dir,"settings.json")))
        quota_settings=self.settings.get("api_quota",{})
        self.usage=ApiUsageService(os.path.join(base_dir,"api_usage.json"), quota_settings.get("start_date"), quota_settings.get("reset_frequency","daily"))
        self.usage.set_limits(self.settings.get("api_limits",self.usage.snapshot()["limits"]))
        self.settings["api_limits"]=self.usage.snapshot()["limits"]
        self.db=Database(os.path.join(base_dir,"organizations.db"));self.db.purge_trash(days=30);self.api=YandexAPI(self.config.get("search_key",""),self.config.get("geocoder_key",""),self.usage)
        self.logger=AppLogger(base_dir);self.backup_service=self._build_backup_service();self.bridge=MapBridge();self.scan_worker=None;self.email_worker=None;self.health_worker=None;self.scheduler=None;self.map_ready=False;self.state=AppState.INITIALIZING;self._updating_table=False;self.last_run_usage=None
        self._selection_map_timer=QTimer(self);self._selection_map_timer.setSingleShot(True);self._selection_map_timer.timeout.connect(self.update_map_for_selection)
        self.quota_timer=QTimer(self);self.quota_timer.setSingleShot(True);self.trash_cleanup_timer=QTimer(self);self.trash_cleanup_timer.setInterval(60*60*1000);self.trash_cleanup_timer.timeout.connect(self.cleanup_trash);self.trash_cleanup_timer.start()
        self.setWindowTitle("YaBizTracker — мониторинг новых организаций");self.setWindowIcon(QApplication.instance().windowIcon());self.resize(1880,980);self.setMinimumSize(1180,700)
        # ВАЖНО: UI строится до подключения сигналов/инициализации компонентов,
        # которые могут сразу сгенерировать лог. Иначе on_log_message() может
        # обратиться к log_text до его создания и завершить запуск приложения.
        self.build_ui()
        self.logger.log_message.connect(self.on_log_message)
        self.scan_requested.connect(self.on_scheduled_scan)
        self._startup_backup()
        self.init_tray()
        self.schedule_quota_reset_timer()
        self.setup_map();self.refresh_all()
        if self.settings.get("cities") and self.settings.get("categories") and all(self.config.get(k) for k in ("js_api_key","geocoder_key","search_key")):
            self.set_state(AppState.READY);self.start_scheduler();self.run_health()
            if not bool(self.settings.get("initial_scan_completed",False)):
                QTimer.singleShot(500,lambda:self.run_scan(False))
        else:self.set_state(AppState.SETTINGS_REQUIRED);QTimer.singleShot(0,self.open_settings)
    def cleanup_trash(self):
        try:
            removed=self.db.purge_trash(days=30)
            if removed:self.logger.log_general("INFO",f"Автоматически удалено из Корзины записей: {removed}")
        except Exception as exc:
            self.logger.log_general("WARNING",f"Не удалось очистить Корзину: {exc}")
    def _build_backup_service(self):
        cfg=self.settings.get("backup",{}) or {}; raw=str(cfg.get("path") or "backups")
        path=raw if os.path.isabs(raw) else os.path.join(self.base_dir,raw)
        try:ret=int(cfg.get("retention",14))
        except (TypeError,ValueError):ret=14
        return BackupService(self.db,path,max(1,min(365,ret)))
    def _startup_backup(self):
        ok,detail=self.db.integrity_check()
        if not ok:
            self.logger.log_general("ERROR",f"SQLite quick_check не пройден: {detail}")
            QMessageBox.critical(self,"База данных повреждена","База данных повреждена.\n\n"+detail+"\n\nЗапуск отменён для защиты данных.")
            raise sqlite3.DatabaseError(detail)
        if bool((self.settings.get("backup",{}) or {}).get("enabled",True)):
            try:
                path=self.backup_service.create_backup(); self.logger.log_general("INFO",f"Резервная копия при запуске создана: {path}")
            except Exception as exc:
                self.logger.log_general("WARNING",f"Резервная копия при запуске не создана: {exc}")
    def _scheduled_backup(self):
        if not bool((self.settings.get("backup",{}) or {}).get("enabled",True)):return
        try:
            path=self.backup_service.create_backup(); self.logger.log_general("INFO",f"Плановая резервная копия создана: {path}")
        except Exception as exc:
            self.logger.log_general("WARNING",f"Плановая резервная копия не создана: {exc}")
    def on_scheduled_scan(self):
        self.run_scan(False)
    def on_log_message(self,ts,level,msg):
        log_text=getattr(self,"log_text",None)
        if log_text is not None:
            log_text.appendPlainText(f"[{ts}] [{level}] {msg}")
    def set_state(self,state):
        self.state=state
        scanning=state==AppState.SCANNING
        self.refresh_btn.setEnabled(not scanning and state!=AppState.SETTINGS_REQUIRED)
        self.stop_btn.setVisible(scanning)
        self.settings_btn.setEnabled(not scanning)
        self.status_state.setText("Состояние: "+{"ready":"готово","scanning":"сканирование","error":"ошибка","settings_required":"требуются настройки","stopping":"остановка","initializing":"инициализация"}[state.value])
    def build_ui(self):
        root=QWidget();self.setCentralWidget(root);rl=QVBoxLayout(root);rl.setContentsMargins(4,4,4,4)
        sp=QSplitter(Qt.Orientation.Horizontal);sp.setChildrenCollapsible(False);rl.addWidget(sp,1)
        left=QWidget();ll=QVBoxLayout(left)
        self.city_title=QLabel();self.city_title.setFont(QFont("Arial",15,QFont.Weight.Bold));ll.addWidget(self.city_title)
        top=QHBoxLayout();self.refresh_btn=QPushButton("🔄 Обновить сейчас");self.stop_btn=QPushButton("⏹ Остановить");self.settings_btn=QPushButton("⚙ Настройки");self.trash_btn=QPushButton("🗑 Корзина");self.refresh_btn.clicked.connect(lambda:self.run_scan(True));self.stop_btn.clicked.connect(self.stop_scan);self.settings_btn.clicked.connect(self.open_settings);self.trash_btn.clicked.connect(self.open_trash);top.addWidget(self.refresh_btn);top.addWidget(self.stop_btn);top.addWidget(self.settings_btn);top.addWidget(self.trash_btn);ll.addLayout(top)
        filters=QGroupBox("Фильтры");fl=QGridLayout(filters);fl.setHorizontalSpacing(6);fl.setVerticalSpacing(6)
        self.search_edit=QLineEdit();self.search_edit.setPlaceholderText("🔎 Название, адрес или категория")
        self.cat_filter=QComboBox();self.cat_filter.addItem("Все категории","")
        self.status_filter=QComboBox();self.status_filter.addItem("Все статусы","");[self.status_filter.addItem(x,x) for x in STATUS_OPTIONS]
        self.settlement_filter=CheckableDropdown("Населённый пункт")
        self.phone_cb=PresenceFilterButton("Телефон");self.email_cb=PresenceFilterButton("E-mail");self.site_cb=PresenceFilterButton("Сайт");self.social_cb=PresenceFilterButton("Соцсети");self.responsible_cb=PresenceFilterButton("Ответственный");self.next_contact_cb=PresenceFilterButton("Следующий контакт")
        presence_buttons=(self.phone_cb,self.email_cb,self.site_cb,self.social_cb,self.responsible_cb,self.next_contact_cb);[button.setMinimumWidth(128) or button.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed) for button in presence_buttons]
        fl.addWidget(self.search_edit,0,0,1,2);fl.addWidget(self.cat_filter,0,2);fl.addWidget(self.status_filter,1,0);fl.addWidget(self.settlement_filter,1,1,1,2);[(fl.addWidget(button,2+index//3,index%3)) for index,button in enumerate(presence_buttons)]
        fl.setColumnStretch(0,1);fl.setColumnStretch(1,1);fl.setColumnStretch(2,1)
        ll.addWidget(filters)
        self.search_edit.textChanged.connect(self.apply_filters);self.cat_filter.currentIndexChanged.connect(self.apply_filters);self.status_filter.currentIndexChanged.connect(self.apply_filters);self.settlement_filter.changed.connect(self.apply_filters)
        for cb in (self.phone_cb,self.email_cb,self.site_cb,self.social_cb,self.responsible_cb,self.next_contact_cb):cb.clicked.connect(self.apply_filters)
        acts=QHBoxLayout();self.column_visibility=CheckableDropdown("Отображаемые столбцы");self.column_visibility.button.setMinimumWidth(225);self.select_all_btn=QPushButton("☑ Выбрать все");self.copy_email_btn=QPushButton("✉ E-mail");self.copy_phone_btn=QPushButton("☎ Телефоны");self.delete_btn=QPushButton("🗑 Исключить");self.export_btn=QPushButton("📊 Excel");self.history_btn=QPushButton("📜 История")
        for b in (self.column_visibility,self.select_all_btn,self.copy_email_btn,self.copy_phone_btn,self.delete_btn,self.export_btn,self.history_btn):acts.addWidget(b)
        self.select_all_btn.clicked.connect(self.select_visible_all);self.copy_email_btn.clicked.connect(self.copy_emails);self.copy_phone_btn.clicked.connect(self.copy_phones);self.delete_btn.clicked.connect(self.delete_selected);self.export_btn.clicked.connect(self.export_excel);self.history_btn.clicked.connect(self.show_history);ll.addLayout(acts)
        self._selection_action_buttons=(self.copy_email_btn,self.copy_phone_btn,self.delete_btn,self.history_btn)
        for b in self._selection_action_buttons:
            b.setEnabled(False)
            b.setToolTip("Выберите хотя бы одну организацию в списке.")
        self.selection_label=QLabel("Выбрано: 0");ll.addWidget(self.selection_label)
        headers=["Название","Адрес","Населённый пункт","Категория","Дата появления","Возраст","Телефон","E-mail","Сайт","Соцсети","Статус","Комментарий","Ответственный","Следующий контакт","Lead Score"]
        self.org_table=OrganizationTableWidget(0,len(headers));self.org_table.setHorizontalHeaderLabels(headers);self.org_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.org_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection);self.org_table.setSortingEnabled(True);self.org_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.org_table.itemSelectionChanged.connect(self.selection_changed);self.org_table.delete_requested.connect(self.delete_selected);self.org_table.itemChanged.connect(self.crm_changed);self.org_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);self.org_table.customContextMenuRequested.connect(self.show_org_context_menu);self.org_table.setItemDelegateForColumn(OrgColumn.STATUS,StatusDelegate(self.org_table))
        self.org_table.setItemDelegateForColumn(OrgColumn.NEXT_CONTACT,NextContactDelegate(self.org_table))
        widths=[260,300,170,190,105,70,150,210,220,230,110,250,150,145,80]
        for i,w in enumerate(widths):self.org_table.setColumnWidth(i,w)
        visible_columns = self.settings.get("visible_organization_columns")
        if visible_columns is None:
            visible_columns = headers
        self.column_visibility.set_items(headers, visible_columns)
        self.column_visibility.changed.connect(self.set_visible_organization_columns)
        self.set_visible_organization_columns(persist=False)
        ll.addWidget(self.org_table,1)
        left.setMinimumWidth(560)
        left.setMaximumWidth(1170)
        self.last_scan_label=QLabel();self.last_scan_label.setStyleSheet("color:#666");ll.addWidget(self.last_scan_label)
        sp.addWidget(left)
        center=QWidget();center.setMinimumWidth(680);cl=QVBoxLayout(center);self.map_title=QLabel();self.map_title.setAlignment(Qt.AlignmentFlag.AlignCenter);cl.addWidget(self.map_title);self.map=QWebEngineView();self.map_controller=MapController(self.map,self._map_is_ready,self.settings,self.db,OrgColumn);s=self.map.settings();s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,True);s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,True);cl.addWidget(self.map,1);sp.addWidget(center)
        right=QWidget();right.setMinimumWidth(280);right.setMaximumWidth(360);rl2=QVBoxLayout(right);dash=QGroupBox("📊 Dashboard");dl=QVBoxLayout(dash);self.dashboard_label=QLabel();self.dashboard_label.setWordWrap(True);dl.addWidget(self.dashboard_label);rl2.addWidget(dash)
        prog=QGroupBox("Сканирование");pl=QVBoxLayout(prog);self.progress_label=QLabel("Ожидание");self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.quality=QLabel();self.quality.setWordWrap(True);pl.addWidget(self.progress_label);pl.addWidget(self.progress);pl.addWidget(self.quality);rl2.addWidget(prog)
        api=QGroupBox("API / локальное использование");al=QVBoxLayout(api);self.api_status_labels={}
        for key,name in [("js","JavaScript API"),("geocoder","Геокодер API"),("search","Search API")]:
            x=QLabel(name+" — проверка");self.api_status_labels[key]=x;al.addWidget(x)
        self.api_usage_label=QLabel();self.api_usage_label.setWordWrap(True);al.addWidget(self.api_usage_label);rl2.addWidget(api)
        logs=QGroupBox("Журнал событий");lg=QVBoxLayout(logs);self.log_text=QPlainTextEdit();self.log_text.setReadOnly(True);self.log_text.setFont(QFont("Consolas",9));lg.addWidget(self.log_text);clear=QPushButton("Очистить");clear.clicked.connect(self.log_text.clear);lg.addWidget(clear);rl2.addWidget(logs,1);sp.addWidget(right);sp.setStretchFactor(0,0);sp.setStretchFactor(1,1);sp.setStretchFactor(2,0);self._main_splitter=sp;QTimer.singleShot(0,self._optimize_splitter_sizes)
        self.status_state=QLabel();self.statusBar().addPermanentWidget(self.status_state)
        self.brand_footer=QLabel("by NextIIPhobos")
        self.brand_footer.setStyleSheet("color:#777; font-size:9pt; padding-left:12px;")
        self.brand_footer.setToolTip("YaBizTracker")
        self.statusBar().addPermanentWidget(self.brand_footer)
        self.icon_credit=QLabel('<a href="https://www.flaticon.com/">иконка: Flaticon.com</a>')
        self.icon_credit.setOpenExternalLinks(True)
        self.icon_credit.setStyleSheet("color:#777; font-size:8pt; padding-left:6px;")
        self.icon_credit.setToolTip("Источник иконки: Flaticon.com")
        self.statusBar().addPermanentWidget(self.icon_credit)
        self.stop_btn.setVisible(False)
        help_menu=self.menuBar().addMenu("Помощь");email_action=help_menu.addAction("Запустить сбор E-mail");email_action.triggered.connect(self.manual_email_scan);help_menu.addSeparator();diag=help_menu.addAction("Диагностика");diag.triggered.connect(self.show_diagnostics)
    def set_visible_organization_columns(self, _checked=None, *, persist=True):
        """Apply and persist the checked organization-table column names."""
        visible = self.column_visibility.checked_values()
        for column in range(self.org_table.columnCount()):
            header = self.org_table.horizontalHeaderItem(column)
            self.org_table.setColumnHidden(column, not header or header.text() not in visible)
        if persist:
            self.settings["visible_organization_columns"] = [
                self.org_table.horizontalHeaderItem(column).text()
                for column in range(self.org_table.columnCount())
                if not self.org_table.isColumnHidden(column)
            ]
            save_json(os.path.join(self.base_dir, "settings.json"), self.settings)
    def _optimize_splitter_sizes(self):
        sp=getattr(self,"_main_splitter",None)
        if sp is None:return
        w=max(0,sp.width())
        left,right=(960,320) if w>=1750 else ((900,300) if w>=1450 else (840,280))
        center=max(680,w-left-right)
        sp.setSizes([left,center,right])
    def resizeEvent(self,event):
        super().resizeEvent(event)
        QTimer.singleShot(0,self._optimize_splitter_sizes)
    def _map_is_ready(self):
        return bool(getattr(self, "map_ready", False))
    def setup_map(self):
        self.channel=QWebChannel(self.map.page());self.channel.registerObject("bridge",self.bridge);self.map.page().setWebChannel(self.channel);self.map.loadFinished.connect(self.map_loaded)
        self.map.loadStarted.connect(lambda:self.api_status_labels["js"].setText("JavaScript API — загрузка…"))
        self.bridge.mapReady.connect(self.on_map_ready);self.bridge.onOrganizationSelected.connect(self.marker_selected)
        self.load_map_html()
    def load_map_html(self):
        # In a PyInstaller one-file build, data files are extracted to the
        # temporary _MEIPASS directory, while user data intentionally lives
        # beside the executable (base_dir). Looking only in base_dir therefore
        # makes the packaged map invisible to QWebEngine. Try the runtime
        # resource directory first, then the normal source/folder locations.
        candidates=[]
        runtime_dir=getattr(sys,"_MEIPASS","")
        if runtime_dir:
            candidates.append(os.path.join(runtime_dir,"yabiztracker","map.html"))
            candidates.append(os.path.join(runtime_dir,"map.html"))
        candidates.extend([
            os.path.join(self.base_dir,"yabiztracker","map.html"),
            os.path.join(self.base_dir,"map.html"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"map.html"),
        ])
        path=next((p for p in candidates if os.path.isfile(p)),None)
        if not path:
            detail="; ".join(candidates)
            self.api_status_labels["js"].setText("☒ JavaScript API — файл карты не найден")
            self.logger.log_general("ERROR","Карта: map.html не найден. Проверены пути: "+detail)
            return
        try:
            with open(path,encoding="utf-8") as f:html=f.read()
            key=self.config.get("js_api_key","")
            # Explicit callback makes the dependency deterministic: the page no
            # longer relies on window load timing to decide when ymaps exists.
            callback=f"https://api-maps.yandex.ru/2.1/?apikey={key}&lang=ru_RU"
            html=html.replace("</head>",f'<script src="{callback}"></script></head>')
            self.map_ready=False
            self.api_status_labels["js"].setText("JavaScript API — загрузка…")
            self.map.setHtml(html,QUrl.fromLocalFile(path))
            QTimer.singleShot(15000,self.check_map_timeout)
        except Exception as e:
            self.api_status_labels["js"].setText("☒ JavaScript API — ошибка")
            self.logger.log_general("ERROR","Карта: "+str(e))
    def map_loaded(self,ok):
        if not ok:
            self.api_status_labels["js"].setText("☒ JavaScript API — ошибка загрузки страницы")
            self.logger.log_general("ERROR","Карта: QWebEngine не смог загрузить HTML")
            return
        # Capture JS runtime state/errors instead of leaving the UI at “проверка”.
        self.map.page().runJavaScript("typeof ymaps !== 'undefined' ? 'ymaps-present' : 'ymaps-missing'", self._map_js_presence)
    def _map_js_presence(self,value):
        if value == "ymaps-missing":
            self.api_status_labels["js"].setText("☒ JavaScript API — скрипт не загружен")
            self.logger.log_general("ERROR","JavaScript API: объект ymaps не найден")
    def check_map_timeout(self):
        if not self.map_ready:
            self.map.page().runJavaScript("typeof ymaps !== 'undefined' ? 'ymaps-present' : 'ymaps-missing'", lambda v: self._map_timeout_result(v))
    def _map_timeout_result(self,value):
        if self.map_ready:return
        msg="JavaScript API не сообщил о готовности за 15 секунд"
        if value == "ymaps-missing":msg += "; скрипт Яндекс Карт не загрузился (ключ/сеть/доступ QWebEngine)"
        self.api_status_labels["js"].setText("☒ JavaScript API — ошибка")
        self.logger.log_general("ERROR",msg)
    def marker_selected(self,oid):
        for r in range(self.org_table.rowCount()):
            it=self.org_table.item(r,0)
            if it and it.data(Qt.ItemDataRole.UserRole)==oid:
                self.org_table.clearSelection();self.org_table.selectRow(r);self.org_table.scrollToItem(it);return
    def on_map_ready(self):
        self.map_ready=True;self.api_status_labels["js"].setText("☑ JavaScript API — OK");self.map_controller.apply_state()
    def apply_map(self):
        if not self.map_ready:return
        cities=self.settings.get("cities",[]);self.map_title.setText("🗺️ Карта — "+", ".join(c.get("name","") for c in cities));self.map_controller.apply_state()
    def update_map_for_selection(self):
        self.map_controller.fit_after_selection_change(self.org_table)
    def run_health(self):
        cities=self.settings.get("cities",[]);bbox=cities[0].get("bbox","") if cities else "50,53~50.3,53.4";self.health_worker=HealthWorker(self.api,bbox)
        self.health_worker.geocoder.connect(self.on_health_geocoder);self.health_worker.search.connect(self.on_health_search);self.health_worker.start()
    def on_health_geocoder(self,ok,msg): self.health_done("geocoder",ok,msg)
    def on_health_search(self,ok,msg): self.health_done("search",ok,msg)
    def health_done(self,key,ok,msg):
        self.api_status_labels[key].setText(("☑ " if ok else "☒ ")+({"geocoder":"Геокодер API","search":"Search API"}[key])+" — "+("OK" if ok else msg))
        if not ok:self.logger.log_general("ERROR",f"{key}: {msg}")
        else:self.logger.log_general("OK",f"{key}: {msg}")
        self.update_usage_ui()
    @staticmethod
    def _now_msk():
        return datetime.now(ZoneInfo("Europe/Moscow"))
    def _read_next_scan_at(self):
        value=str(self.settings.get("next_scan_at") or "").strip()
        if not value:
            return None
        try:
            dt=datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt=dt.replace(tzinfo=ZoneInfo("Europe/Moscow"))
            return dt.astimezone(ZoneInfo("Europe/Moscow"))
        except ValueError:
            return None
    def _persist_next_scan_at(self, when):
        self.settings["next_scan_at"]=when.astimezone(ZoneInfo("Europe/Moscow")).isoformat(timespec="seconds")
        try:
            save_json(os.path.join(self.base_dir,"settings.json"),self.settings)
        except Exception as exc:
            self.logger.log_general("WARNING",f"Не удалось сохранить время следующего автопоиска: {exc}")
    def _calculate_next_scan_at(self, now=None):
        now=now or self._now_msk()
        h=max(1,int(self.settings.get("schedule_hours",6)))
        last_finished=str((self.settings.get("last_scan_metrics",{}) or {}).get("finished_at") or "").strip()
        if last_finished:
            try:
                last=datetime.fromisoformat(last_finished)
                if last.tzinfo is None:
                    last=last.replace(tzinfo=ZoneInfo("Europe/Moscow"))
                last=last.astimezone(ZoneInfo("Europe/Moscow"))
                candidate=last+timedelta(hours=h)
                if candidate>now:
                    return candidate
                # The application was closed past the scheduled time. Do not
                # execute a backlog of scans; run one catch-up scan now.
                return now
            except ValueError:
                pass
        return now+timedelta(hours=h)
    def start_scheduler(self):
        if self.scheduler:
            try:self.scheduler.shutdown(wait=False)
            except Exception:pass
        self.scheduler=BackgroundScheduler(daemon=True)
        h=max(1,int(self.settings.get("schedule_hours",6)));now=self._now_msk()
        next_scan=self._read_next_scan_at()
        if next_scan is None:next_scan=self._calculate_next_scan_at(now)
        if next_scan<=now:
            due=next_scan;run_at=now+timedelta(seconds=2);self._persist_next_scan_at(due)
            self.logger.log_general("INFO",f"Автопоиск пропущен во время закрытия; выполняется один запуск для срока {due:%d.%m.%Y %H:%M:%S} МСК.");next_scan=run_at
        self.settings["next_scan_interval_hours"]=h;self._persist_next_scan_at(self._read_next_scan_at() or next_scan)
        self.scheduler.add_job(self._scheduler_request,"date",run_date=next_scan,id="scan",max_instances=1,coalesce=True)
        self.scheduler.add_job(self._scheduled_backup,"interval",hours=24,id="backup",max_instances=1,coalesce=True);self.scheduler.start()
        self.logger.log_general("INFO",f"Следующий автоматический поиск: {next_scan:%d.%m.%Y %H:%M:%S} МСК (интервал {h} ч)")
    def _scheduler_request(self):
        now=self._now_msk();h=max(1,int(self.settings.get("schedule_hours",6)))
        next_scan=next_wall_clock_occurrence(self._read_next_scan_at(),now,h)
        self._persist_next_scan_at(next_scan);self.settings["next_scan_interval_hours"]=h;self.scan_requested.emit()
        if self.scheduler and self.scheduler.running:
            try:self.scheduler.add_job(self._scheduler_request,"date",run_date=next_scan,id="scan",max_instances=1,coalesce=True,replace_existing=True)
            except Exception as exc:self.logger.log_general("WARNING",f"Не удалось запланировать следующий автопоиск: {exc}")
    def closeEvent(self,e):
        self.set_state(AppState.STOPPING)
        for timer in (getattr(self,"quota_timer",None),getattr(self,"trash_cleanup_timer",None)):
            if timer is not None:timer.stop()
        if self.scheduler:
            try:self.scheduler.shutdown(wait=True)
            except Exception as exc:self.logger.log_general("WARNING",f"Scheduler не завершился штатно: {exc}")
            self.scheduler=None
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.requestInterruption();self.progress_label.setText("Завершение текущего запроса…");self.scan_worker.wait(75_000)
            if self.scan_worker.isRunning():
                self.logger.log_general("ERROR","Сканирование не завершилось в безопасный срок; база оставлена открытой для защиты данных.");e.ignore();return
        if self.email_worker and self.email_worker.isRunning():
            self.email_worker.stop();self.email_worker.wait(120_000)
            if self.email_worker.isRunning():
                self.logger.log_general("ERROR","Сбор e-mail не завершился в безопасный срок; закрытие отменено для защиты данных.");e.ignore();return
        if self.health_worker and self.health_worker.isRunning():
            self.health_worker.requestInterruption();self.health_worker.wait(15_000)
            if self.health_worker.isRunning():
                self.logger.log_general("ERROR","Проверка API не завершилась в безопасный срок; закрытие отменено.");e.ignore();return
        try:self.usage.flush()
        except Exception as exc:self.logger.log_general("WARNING",f"Не удалось сохранить API usage при закрытии: {exc}")
        if getattr(self,"tray_icon",None):self.tray_icon.hide()
        webview=getattr(self,"map",None)
        if webview is not None:
            for action in (lambda:webview.stop(),lambda:webview.setUrl(QUrl("about:blank")),lambda:webview.close(),lambda:webview.deleteLater()):
                try:action()
                except Exception:pass
        for obj_name in ("channel","bridge"):
            obj=getattr(self,obj_name,None)
            if obj is not None:
                try:obj.deleteLater()
                except Exception:pass
        try:QApplication.processEvents()
        except Exception:pass
        try:self.db.close()
        finally:e.accept()
    def estimate_requests(self):
        base=max(1,len(self.settings.get("cities",[])))*max(1,len(self.settings.get("categories",[])))
        metrics=self.settings.get("last_scan_metrics",{}) or {}
        try:
            last_base=max(1,int(metrics.get("cities",0))*int(metrics.get("categories",0)))
            last_requests=int(metrics.get("search_requests",0))
            factor=last_requests/last_base if last_requests>0 else 1.0
            estimate=max(base,int(round(base*max(1.0,factor))))
            return estimate
        except (TypeError,ValueError,ZeroDivisionError):
            return base
    def estimate_request_range(self):
        estimate=self.estimate_requests(); base=max(1,len(self.settings.get("cities",[])))*max(1,len(self.settings.get("categories",[])))
        metrics=self.settings.get("last_scan_metrics",{}) or {}
        if metrics.get("search_requests"):
            return max(base,int(round(estimate*0.8))), max(base,int(round(estimate*1.5)))
        return base, base*2
    def run_scan(self,manual=True):
        if self.state==AppState.SCANNING:return
        if not self.settings.get("cities") or not self.settings.get("categories"):
            self.open_settings();return
        est_low,est_high=self.estimate_request_range(); rem=self.usage.remaining_today("search")
        if est_low>rem:
            # Never silently discard an automatic run. A local quota warning is
            # a safety gate, not a scheduler failure: the user may explicitly
            # authorize the scan and it will then run normally.
            self.logger.log_general("WARNING",f"Прогноз Search API {est_low}–{est_high} выше локального остатка {rem}; требуется подтверждение пользователя.")
            if QMessageBox.question(self,"Риск лимита",f"Прогноз: ~{est_low}–{est_high} Search API запросов. Остаток по локальному лимиту: {rem}.\n\nРазрешить выполнение поиска несмотря на прогноз превышения?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                self.logger.log_general("INFO","Поиск отменён пользователем после предупреждения о локальном лимите Search API.")
                return
        elif manual:
            if QMessageBox.question(self,"Подтверждение поиска",f"Выбрано населённых пунктов: {len(self.settings['cities'])}\nКатегорий: {len(self.settings['categories'])}\nПрогноз Search API: ~{est_low}–{est_high} запросов. Реальный расход зависит от числа страниц и повторов.\n\nЗапустить полный мониторинг?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        before=self.usage.snapshot();self._usage_before=before
        # The flag is persisted only after a scan really completes. A failed or
        # cancelled first run must remain eligible for the one-time startup scan
        # on the next launch; manual and scheduled runs are always independent.
        self.set_state(AppState.SCANNING);self.progress.setValue(0);self.progress_label.setText("Подготовка сканирования…");self.quality.setText("")
        self.scan_worker=ScanWorker(self.api,self.db,self.settings["cities"],self.settings["categories"],self.settings.get("excluded_categories",[]));self.scan_worker.progress.connect(self.scan_progress);self.scan_worker.completed.connect(self.scan_completed);self.scan_worker.failed.connect(self.scan_failed);self.scan_worker.start()
    def stop_scan(self):
        if self.scan_worker and self.scan_worker.isRunning():self.set_state(AppState.STOPPING);self.scan_worker.requestInterruption();self.progress_label.setText("Остановка…")
    def scan_progress(self,d):
        total=max(1,len(self.settings["cities"])*len(self.settings["categories"]));done=(d["category_index"]-1)/total
        # Current category is deliberately weighted lightly; page progress is informative, not fake precision.
        pct=int(min(99,(done+0.5/total)*100));self.progress.setValue(pct);self.progress_label.setText(f"{d['city']} → {d['category']} | страница {d['page']} | API-результатов: {d['api_results']} | обработано страниц: {d['pages']}")
    def scan_completed(self,st):
        self.usage.flush();after=self.usage.snapshot();before=getattr(self,"_usage_before",after)
        delta={k:max(0,after["total"].get(k,0)-before["total"].get(k,0)) for k in ("js","geocoder","search")};self.usage.set_last_run(delta);self.last_run_usage=delta
        self.settings["api_limits"]=after["limits"]
        self.settings["last_scan_metrics"]={"cities":len(self.settings.get("cities",[])),"categories":len(self.settings.get("categories",[])),"search_requests":int(delta.get("search",0)),"pages":int(st.get("pages",0)),"finished_at":st.get("finished_at","")}
        try:save_json(os.path.join(self.base_dir,"settings.json"),self.settings)
        except Exception as exc:self.logger.log_general("WARNING",f"Не удалось сохранить статистику последнего сканирования: {exc}")
        self._usage_before=after
        if not st.get("cancelled"):
            finished_at=str(st.get("finished_at") or "").strip()
            try:
                finished=datetime.fromisoformat(finished_at) if finished_at else self._now_msk()
                if finished.tzinfo is None:
                    finished=finished.replace(tzinfo=ZoneInfo("Europe/Moscow"))
                finished=finished.astimezone(ZoneInfo("Europe/Moscow"))
            except ValueError:
                finished=self._now_msk()
            next_scan=finished+timedelta(hours=max(1,int(self.settings.get("schedule_hours",6))))
            self._persist_next_scan_at(next_scan)
            self.settings["initial_scan_completed"] = True
            try:
                save_json(os.path.join(self.base_dir, "settings.json"), self.settings)
            except Exception as exc:
                self.logger.log_general("WARNING", f"Не удалось сохранить признак первого успешного поиска: {exc}")
        self.set_state(AppState.READY if not st.get("errors") else AppState.ERROR);self.refresh_all()
        if not st.get("cancelled"):
            self.start_email_finder()
        self.last_scan_label.setText(f"Последний запуск: {datetime.now():%d.%m.%Y %H:%M} | найдено уникальных: {st.get('unique_found',0)} | новых: {st.get('new_count',0)}")
        self.quality.setText(f"Всего результатов API: {st.get('api_results',0)}\nУникальных: {st.get('unique_found',0)}\nНовых: {st.get('new_count',0)}\nИзменено: {st.get('updated',0)}\nДубликатов: {st.get('duplicates',0)}\nИсключено: {st.get('ignored',0)}\nБез телефона: {st.get('without_phone',0)} | без e-mail: {st.get('without_email',0)}\nБез сайта: {st.get('without_website',0)} | без координат: {st.get('without_coordinates',0)}\nОшибок/пропусков: {st.get('errors',0)+st.get('warnings',0)}")
        self.progress.setValue(100 if not st.get("cancelled") else self.progress.value());self.progress_label.setText("Сканирование остановлено" if st.get("cancelled") else ("Завершено с предупреждениями" if st.get("warnings") else "Сканирование завершено"))
        if st.get("warnings"):
            self.logger.log_general("WARNING",f"Сканирование завершено с предупреждениями: пропущено страниц {len(st.get('failed_pages',[]))}; проблемных категорий {len(st.get('categories_failed',[]))}")
            for x in st.get("failed_pages",[])[:20]: self.logger.log_general("WARNING","Пропущена страница: "+x)
            for x in st.get("categories_failed",[])[:20]: self.logger.log_general("WARNING","Проблемная категория: "+x)
        self.logger.log_general("INFO",f"Сканирование: API={st.get('api_results',0)}, уникальных={st.get('unique_found',0)}, новых={st.get('new_count',0)}")
        self.show_notification(st.get("new_count",0),st)
        self.update_usage_ui()
    def start_email_finder(self, organizations=None, force=False):
        cfg=self.settings.get("email_finder",{}) or {}
        if not bool(cfg.get("enabled",True)) and not force:
            self.logger.log_general("INFO","Автоматический сбор e-mail отключён в настройках.")
            return
        if self.email_worker and self.email_worker.isRunning():
            self.logger.log_general("INFO","Сбор e-mail уже выполняется; новый запуск не создан.")
            return
        self.email_worker=EmailFinderWorker(self.db,self.settings,organizations=organizations,force=force)
        self.email_worker.progress.connect(self.email_scan_progress)
        self.email_worker.completed.connect(self.email_scan_completed)
        self.email_worker.failed.connect(self.email_scan_failed)
        self.email_worker.start()
        self.logger.log_general("INFO",("Ручной" if force else "Фоновый")+" сбор e-mail с сайтов запущен.")
    def manual_email_scan(self):
        if self.email_worker and self.email_worker.isRunning():
            QMessageBox.information(self, "Сбор E-mail", "Сбор e-mail уже выполняется."); return
        organizations=[]
        for row in range(self.org_table.rowCount()):
            site=self.org_table.item(row,OrgColumn.WEBSITE); name=self.org_table.item(row,OrgColumn.NAME)
            if site and str(site.text()).strip() and name and name.data(Qt.ItemDataRole.UserRole):
                organizations.append({"org_id":str(name.data(Qt.ItemDataRole.UserRole)),"id":str(name.data(Qt.ItemDataRole.UserRole)),"name":name.text(),"website":site.text()})
        if not organizations:
            QMessageBox.information(self, "Сбор E-mail", "В текущем списке нет организаций с указанным сайтом."); return
        self.start_email_finder(organizations=organizations, force=True); self.progress_label.setText(f"Ручной сбор E-mail: 0/{len(organizations)} организаций")
    def email_scan_progress(self,d):
        processed=int(d.get("processed",0)); queued=int(d.get("queued",0))
        if queued:
            self.progress_label.setText(f"Сбор e-mail: {processed}/{queued} сайтов | найдено адресов: {int(d.get('found',0))}")
        if d.get("status") == "found":
            self.refresh_email_row(str(d.get("org_id") or ""))
    def refresh_email_row(self, oid):
        if not oid:return
        for row in range(self.org_table.rowCount()):
            item=self.org_table.item(row,OrgColumn.NAME)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == oid:
                o=self.db.get_by_id(oid)
                if o:
                    self._updating_table=True
                    try:
                        email_item=self.org_table.item(row,OrgColumn.EMAIL)
                        if email_item is not None:
                            email_item.setText(str(o.get("email") or ""))
                    finally:
                        self._updating_table=False
                break
    def email_scan_completed(self,st):
        self.refresh_all()
        self.logger.log_general("INFO",f"Сбор e-mail завершён: сайтов={st.get('queued',0)}, обработано={st.get('processed',0)}, найдено={st.get('found',0)}, без e-mail={st.get('not_found',0)}, ошибок={st.get('errors',0)}, блокировок={st.get('blocked',0)}")
    def email_scan_failed(self,e):
        self.logger.log_general("ERROR",f"Сбор e-mail завершился ошибкой: {type(e).__name__}: {e}")
    def scan_failed(self,e):
        try:
            self.usage.flush()
            before=getattr(self,"_usage_before",self.usage.snapshot()); after=self.usage.snapshot()
            delta={k:max(0,after["total"].get(k,0)-before["total"].get(k,0)) for k in ("js","geocoder","search")}
            self.usage.set_last_run(delta); self.last_run_usage=delta
        except Exception as flush_exc:
            self.logger.log_general("WARNING",f"Не удалось сохранить API usage после ошибки сканирования: {flush_exc}")
        self.set_state(AppState.ERROR);self.progress_label.setText("Сканирование завершилось ошибкой");self.logger.log_general("ERROR",f"{type(e).__name__}: {e}")
        if isinstance(e,ApiLimitError):QMessageBox.critical(self,"Лимит API",str(e))
        elif isinstance(e,ApiAuthError):QMessageBox.critical(self,"Ошибка ключа API",str(e))
        else:QMessageBox.critical(self,"Ошибка сканирования",str(e))
    def refresh_all(self):
        configured_cities=[c.get("name","").strip() for c in self.settings.get("cities",[]) if c.get("name","").strip()]
        self.city_title.setText("📋 Организации — "+", ".join(configured_cities) if configured_cities else "📋 Организации")
        self.cat_filter.blockSignals(True);cur=self.cat_filter.currentData();self.cat_filter.clear();self.cat_filter.addItem("Все категории","");cats=sorted({o.get("category","") for o in self.db.get_active_organizations(configured_cities,self.settings.get("period_days",30)) if o.get("category")});[self.cat_filter.addItem(c,c) for c in cats];self.cat_filter.setCurrentIndex(max(0,self.cat_filter.findData(cur)));self.cat_filter.blockSignals(False)
        selected_cities=self.settlement_filter.checked_values()
        self.settlement_filter.set_items(configured_cities, selected_cities)
        self.load_table();self.update_dashboard();self.apply_map();self.update_usage_ui()
    def load_table(self):
        cities=[c["name"] for c in self.settings.get("cities",[])]
        orgs=self.db.get_active_organizations(cities,self.settings.get("period_days",30));self._updating_table=True;self.org_table.setSortingEnabled(False);self.org_table.setRowCount(0)
        for o in orgs:self.add_row(o)
        self.org_table.setSortingEnabled(True);self.org_table.sortItems(OrgColumn.APPEARED_DATE, Qt.SortOrder.DescendingOrder);self._updating_table=False;self.apply_filters()
    def add_row(self,o):
        r=self.org_table.rowCount();self.org_table.insertRow(r)
        next_contact=self._normalize_next_contact(o.get("next_contact_date",""))
        display_date=str(o.get("first_seen_date","") or "")[:10]
        vals=[o.get("name",""),o.get("address",""),o.get("city_name",""),o.get("category","")+ (" → "+o.get("subcategory","") if o.get("subcategory") else ""),display_date,f"{o.get('age_days',0)} дн.",o.get("phone",""),o.get("email",""),o.get("website",""),ExportService.social_text(o.get("social_links","{}")),o.get("status","Новый"),o.get("comment",""),o.get("responsible",""),self._display_next_contact(next_contact),str(o.get("score",0))]
        for c,v in enumerate(vals):
            it=(NextContactItem(str(v)) if c==OrgColumn.NEXT_CONTACT else QTableWidgetItem(str(v)))
            it.setData(Qt.ItemDataRole.UserRole,o["id"])
            if c==OrgColumn.NEXT_CONTACT:
                it.setData(Qt.ItemDataRole.UserRole+1,next_contact)
            self.org_table.setItem(r,c,it)
        self.style_status(r);self.org_table.item(r,OrgColumn.NAME).setFont(QFont("Arial",10,QFont.Weight.Bold))
    @staticmethod
    def _normalize_next_contact(value):
        value=str(value or "").strip()
        if not value:return ""
        for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M","%d.%m.%Y %H:%M"):
            try:return datetime.strptime(value,fmt).strftime("%Y-%m-%d %H:%M")
            except ValueError:pass
        return value
    @staticmethod
    def _display_next_contact(value):
        if not value:return ""
        try:return datetime.strptime(value,"%Y-%m-%d %H:%M").strftime("%d.%m.%Y %H:%M")
        except ValueError:return value
    def style_status(self,r):
        it=self.org_table.item(r,OrgColumn.STATUS)
        colors={"Новый":"#e3f2fd","В работе":"#fff3cd","Связались":"#e8f5e9","Не дозвонились":"#fce4ec","Клиент":"#c8e6c9","Неинтересно":"#eeeeee"}
        if it:it.setBackground(QColor(colors.get(it.text(),"#ffffff")))
        age=self.org_table.item(r,OrgColumn.AGE)
        if age:
            n=int(age.text().split()[0]);age.setBackground(QColor("#00C800" if n<=5 else "#FFD700" if n<=15 else "#00BFFF" if n<=25 else "#969696"))
    def apply_filters(self):
        filters = {
            "search": self.search_edit.text(),
            "category": self.cat_filter.currentData(),
            "status": self.status_filter.currentData(),
            "city_names": self.settlement_filter.checked_values(),
            "phone_mode": self.phone_cb.mode,
            "email_mode": self.email_cb.mode,
            "website_mode": self.site_cb.mode,
            "social_mode": self.social_cb.mode,
            "responsible_mode": self.responsible_cb.mode,
            "next_contact_mode": self.next_contact_cb.mode,
        }
        visible = 0
        for row in range(self.org_table.rowCount()):
            org = {
                "name": self.org_table.item(row, 0).text() if self.org_table.item(row, 0) else "",
                "address": self.org_table.item(row, OrgColumn.ADDRESS).text() if self.org_table.item(row, OrgColumn.ADDRESS) else "",
                "city_name": self.org_table.item(row, OrgColumn.SETTLEMENT).text() if self.org_table.item(row, OrgColumn.SETTLEMENT) else "",
                "category": self.org_table.item(row, OrgColumn.CATEGORY).text().split(" → ")[0] if self.org_table.item(row, OrgColumn.CATEGORY) else "",
                "subcategory": self.org_table.item(row, OrgColumn.CATEGORY).text().split(" → ", 1)[1] if self.org_table.item(row, OrgColumn.CATEGORY) and " → " in self.org_table.item(row, OrgColumn.CATEGORY).text() else "",
                "status": self.org_table.item(row, OrgColumn.STATUS).text() if self.org_table.item(row, OrgColumn.STATUS) else "",
                "phone": self.org_table.item(row, OrgColumn.PHONE).text() if self.org_table.item(row, OrgColumn.PHONE) else "",
                "email": self.org_table.item(row, OrgColumn.EMAIL).text() if self.org_table.item(row, OrgColumn.EMAIL) else "",
                "website": self.org_table.item(row, OrgColumn.WEBSITE).text() if self.org_table.item(row, OrgColumn.WEBSITE) else "",
                "social_links": self.org_table.item(row, OrgColumn.SOCIAL).text() if self.org_table.item(row, OrgColumn.SOCIAL) else "",
                "responsible": self.org_table.item(row, OrgColumn.RESPONSIBLE).text() if self.org_table.item(row, OrgColumn.RESPONSIBLE) else "",
                "next_contact_date": str(self.org_table.item(row, OrgColumn.NEXT_CONTACT).data(Qt.ItemDataRole.UserRole + 1) or "") if self.org_table.item(row, OrgColumn.NEXT_CONTACT) else "",
            }
            ok = matches_organization_filters(org, filters)
            self.org_table.setRowHidden(row, not ok)
            visible += int(ok)
        self.org_table.prune_hidden_selection()
        self.selection_changed()
        self.statusBar().showMessage(f"Показано: {visible} из {self.org_table.rowCount()}")
    def selection_changed(self):
        rows=self.org_table.visible_selected_rows();self.selection_label.setText(f"Выбрано: {len(rows)}")
        has_selection=bool(rows)
        for b in getattr(self,"_selection_action_buttons",()):
            b.setEnabled(has_selection)
            b.setToolTip("" if has_selection else "Выберите хотя бы одну организацию в списке.")
        if hasattr(self,"_selection_map_timer"): self._selection_map_timer.start(50);self.map_controller.sync_selection(self.org_table)
    def crm_changed(self,item):
        if self._updating_table or item.column() not in (OrgColumn.STATUS,OrgColumn.COMMENT,OrgColumn.RESPONSIBLE,OrgColumn.NEXT_CONTACT):return
        oid=self.org_table.item(item.row(),0).data(Qt.ItemDataRole.UserRole);fields={OrgColumn.STATUS:"status",OrgColumn.COMMENT:"comment",OrgColumn.RESPONSIBLE:"responsible",OrgColumn.NEXT_CONTACT:"next_contact_date"}
        value=item.text().strip()
        if item.column()==OrgColumn.STATUS:
            # Status is a controlled vocabulary. Reject edits made outside the combo-box/delegate.
            if value not in STATUS_OPTIONS:
                self._updating_table=True
                try:
                    current=self.db.get_by_id(oid)
                    item.setText(current.get("status","Новый") if current else "Новый")
                finally:self._updating_table=False
                self.statusBar().showMessage("Недопустимый статус. Выберите значение из списка.")
                return
        elif item.column()==OrgColumn.NEXT_CONTACT:
            value=str(item.data(Qt.ItemDataRole.UserRole+1) or "").strip() or self._normalize_next_contact(value)
            item.setData(Qt.ItemDataRole.UserRole+1,value)
            item.setText(self._display_next_contact(value))
        self.db.update_crm(oid,**{fields[item.column()]:value});self.style_status(item.row())
    def show_org_context_menu(self,pos):
        item=self.org_table.itemAt(pos)
        if not item:
            return
        if item.column() == OrgColumn.PHONE:
            menu = build_messenger_menu(self, self._split_contact_values(item.text()))
            if menu:
                menu.exec(self.org_table.viewport().mapToGlobal(pos))
            return
        if item.column() == OrgColumn.WEBSITE:
            website=str(item.text() or "").strip()
            if not website:return
            if not website.lower().startswith(("http://","https://")):website="https://"+website
            menu=QMenu(self); action=menu.addAction("Перейти на сайт"); action.triggered.connect(lambda _,url=website:QDesktopServices.openUrl(QUrl(url))); menu.exec(self.org_table.viewport().mapToGlobal(pos)); return
        if item.column() not in (OrgColumn.STATUS,OrgColumn.COMMENT,OrgColumn.RESPONSIBLE,OrgColumn.NEXT_CONTACT):
            return
        selected=self.org_table.visible_selected_rows()
        if not selected:return
        labels={OrgColumn.STATUS:"Статус",OrgColumn.COMMENT:"Комментарий",OrgColumn.RESPONSIBLE:"Ответственный",OrgColumn.NEXT_CONTACT:"Следующий контакт"}
        field=labels[item.column()]
        menu=QMenu(self)
        action=menu.addAction(f"Изменить {field} для выделенных ({len(selected)})")
        action.triggered.connect(lambda _,c=item.column():self.bulk_edit_crm(c))
        menu.exec(self.org_table.viewport().mapToGlobal(pos))
    def bulk_edit_crm(self,column):
        rows=self.org_table.visible_selected_rows()
        if not rows:return
        labels={OrgColumn.STATUS:"Статус",OrgColumn.COMMENT:"Комментарий",OrgColumn.RESPONSIBLE:"Ответственный",OrgColumn.NEXT_CONTACT:"Следующий контакт"}
        field={OrgColumn.STATUS:"status",OrgColumn.COMMENT:"comment",OrgColumn.RESPONSIBLE:"responsible",OrgColumn.NEXT_CONTACT:"next_contact_date"}[column]
        if column==OrgColumn.STATUS:
            dlg=QDialog(self);dlg.setWindowTitle("Изменить Статус")
            lay=QVBoxLayout(dlg);lay.addWidget(QLabel(f"Новый статус для {len(rows)} организаций:"))
            edit=QComboBox();edit.addItems(STATUS_OPTIONS);lay.addWidget(edit)
            bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok);bb.button(QDialogButtonBox.StandardButton.Ok).setText("Применить");lay.addWidget(bb)
            bb.accepted.connect(dlg.accept);bb.rejected.connect(dlg.reject)
            if dlg.exec()!=QDialog.DialogCode.Accepted:return
            value=edit.currentText()
        elif column in (OrgColumn.COMMENT,OrgColumn.RESPONSIBLE):
            value,ok=QInputDialog.getText(self,f"Изменить {labels[column]}",f"Новое значение для {len(rows)} организаций:")
            if not ok:return
            value=value.strip()
        else:
            dlg=QDialog(self);dlg.setWindowTitle("Изменить Следующий контакт")
            lay=QVBoxLayout(dlg);lay.addWidget(QLabel(f"Новое значение для {len(rows)} организаций:"))
            edit=QDateTimeEdit(datetime.now());edit.setCalendarPopup(True);edit.setDisplayFormat("dd.MM.yyyy HH:mm");lay.addWidget(edit)
            clear=QCheckBox("Очистить дату");lay.addWidget(clear)
            bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok);bb.button(QDialogButtonBox.StandardButton.Ok).setText("Применить");lay.addWidget(bb)
            bb.accepted.connect(dlg.accept);bb.rejected.connect(dlg.reject)
            if dlg.exec()!=QDialog.DialogCode.Accepted:return
            value="" if clear.isChecked() else edit.dateTime().toString("yyyy-MM-dd HH:mm")
        ids=[self.org_table.item(x.row(),0).data(Qt.ItemDataRole.UserRole) for x in rows]
        changed=self.db.update_crm_many(ids,**{field:value})
        self._updating_table=True
        try:
            for x in rows:
                r=x.row();it=self.org_table.item(r,column)
                if column==OrgColumn.NEXT_CONTACT:
                    it.setData(Qt.ItemDataRole.UserRole+1,value);it.setText(self._display_next_contact(value))
                else:it.setText(value)
                self.style_status(r)
        finally:self._updating_table=False
        self.statusBar().showMessage(f"Изменено: {changed} из {len(ids)} организаций")
    @staticmethod
    def _split_contact_values(value):
        values=[]
        for part in str(value or "").replace(";",",").split(","):
            part=part.strip()
            if part and part not in values:
                values.append(part)
        return values
    def _copy_selected_contacts(self,column,label):
        vals=[]
        for idx in self.org_table.visible_selected_rows():
            vals.extend(x for x in self._split_contact_values(self.org_table.item(idx.row(),column).text() if self.org_table.item(idx.row(),column) else "") if x not in vals)
        QApplication.clipboard().setText(", ".join(vals))
        self.statusBar().showMessage(f"Скопировано {label}: {len(vals)}")
    def copy_emails(self):
        self._copy_selected_contacts(OrgColumn.EMAIL,"e-mail")
    def copy_phones(self):
        self._copy_selected_contacts(OrgColumn.PHONE,"телефонов")
    def select_visible_all(self):
        self.org_table.select_visible_rows()
    def open_trash(self):
        self.db.purge_trash(days=30)
        dlg=TrashDialog(self,self.db)
        dlg.restored.connect(self.refresh_all)
        dlg.exec()
        self.refresh_all()
    def delete_selected(self):
        ids=[self.org_table.item(x.row(),0).data(Qt.ItemDataRole.UserRole) for x in self.org_table.visible_selected_rows()]
        if not ids:return
        if QMessageBox.question(self,"Исключение",f"Исключить {len(ids)} организаций из будущих поисков?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.db.move_to_trash(ids, reason="manual_exclude", permanently_ignore=True);self.refresh_all()
    def show_history(self):
        rows=self.org_table.visible_selected_rows()
        if len(rows)!=1:return
        oid=self.org_table.item(rows[0].row(),0).data(Qt.ItemDataRole.UserRole);o=self.db.get_by_id(oid);hist=self.db.history(oid)
        text=f"{o['name']}\nПоследнее обновление: {o.get('last_updated','—')}\n\n"
        text+="\n".join(f"{h['changed_at']} — {h['field']}: {h['old_value'] or '∅'} → {h['new_value'] or '∅'}" for h in hist) or "История изменений пока пуста."
        QMessageBox.information(self,"История организации",text)
    def export_excel(self):
        dlg=ExportDialog(self)
        if dlg.exec()!=QDialog.DialogCode.Accepted:return
        mode=dlg.mode();cities=[c["name"] for c in self.settings.get("cities",[])]
        if mode=="selected":
            ids=[self.org_table.item(x.row(),0).data(Qt.ItemDataRole.UserRole) for x in self.org_table.visible_selected_rows()]
            orgs=[self.db.get_by_id(x) for x in ids]
        elif mode=="visible":
            ids=[]
            for r in range(self.org_table.rowCount()):
                if not self.org_table.isRowHidden(r):ids.append(self.org_table.item(r,0).data(Qt.ItemDataRole.UserRole))
            orgs=[self.db.get_by_id(x) for x in ids]
        else:
            orgs=self.db.get_active_organizations(cities,self.settings.get("period_days",30))
            if mode=="email":orgs=[o for o in orgs if o.get("email")]
            elif mode=="phone":orgs=[o for o in orgs if o.get("phone")]
        orgs=[o for o in orgs if o]
        path,_=QFileDialog.getSaveFileName(self,"Сохранить Excel","организации.xlsx","Excel (*.xlsx)")
        if not path:return
        if not path.lower().endswith(".xlsx"):path+=".xlsx"
        try:
            engine=ExportService().export(path,orgs);self.logger.log_general("OK",f"Excel сохранён ({engine}): {path}; записей: {len(orgs)}")
            self.statusBar().showMessage(f"Экспорт завершён: {len(orgs)} организаций")
        except Exception as e:
            self.logger.log_general("ERROR",f"Ошибка Excel: {e}");QMessageBox.critical(self,"Ошибка экспорта",str(e))
    def update_dashboard(self):
        names=[c["name"] for c in self.settings.get("cities",[])];d=self.db.dashboard(names)
        cats="\n".join(f"• {k}: {v}" for k,v in d["categories"][:5]) or "нет данных"
        self.dashboard_label.setText(f"<b>Новые организации</b><br>Сегодня: {d['today']}<br>7 дней: {d['7d']}<br>30 дней: {d['30d']}<br><br>"
                                     f"С телефоном: {d['phone']}<br>С e-mail: {d['email']}<br>С сайтом: {d['website']}<br>С соцсетями: {d['social']}<br><br><b>ТОП категорий</b><br>{cats}")
    def schedule_quota_reset_timer(self):
        try:
            now=datetime.now(ZoneInfo("Europe/Moscow"))
            target=self.usage.next_reset_at()
            delay=max(1000,int((target-now).total_seconds()*1000))
            self.quota_timer.start(delay)
        except Exception as e:
            self.logger.log_general("WARNING",f"Не удалось запланировать сброс лимитов: {e}")
            self.quota_timer.start(60_000)
    def check_quota_reset(self):
        if self.usage.maybe_reset(save=True):
            self.settings["api_quota"]=self.usage.snapshot().get("quota",{})
            save_json(os.path.join(self.base_dir,"settings.json"),self.settings)
            self.logger.log_general("INFO","Лимиты API автоматически сброшены в 00:00 по МСК согласно расписанию.")
            self.update_usage_ui()
        self.schedule_quota_reset_timer()
    def update_usage_ui(self):
        s=self.usage.snapshot();lines=[]
        for k,n in (("search","Search API"),("geocoder","Геокодер"),("js","JS API")):
            lines.append(f"{n}: текущий период {s['period_usage'].get(k,0)} / лимит {s['limits'].get(k,0)}")
        lr=s.get("last_run",{});last=f"Последний запуск: Search {lr.get('search',0)}, Геокодер {lr.get('geocoder',0)}"
        forecast=self.usage.forecast_per_day(lr.get("search",0),int(self.settings.get("schedule_hours",6)))
        if forecast:
            low=max(1,int(round(forecast*0.8))); high=max(low,int(round(forecast*1.5)))
            last+=f"\nПрогноз Search API: ~{low}–{high} / сутки"
        self.api_usage_label.setText("\n".join(lines)+"\n"+last)
    def init_tray(self):
        self.tray_icon=QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.windowIcon())
        self.tray_icon.setToolTip("YaBizTracker")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
            self.logger.log_general("INFO","Windows-уведомления: системный трей доступен")
        else:
            self.logger.log_general("WARNING","Windows-уведомления: системный трей недоступен")
    def show_notification(self,new,st):
        try:
            new_count=int(new or 0)
        except (TypeError,ValueError):
            new_count=0
        if new_count <= 0:
            return
        tray=getattr(self,"tray_icon",None)
        if tray is None or not QSystemTrayIcon.isSystemTrayAvailable():
            self.logger.log_general("WARNING","Windows-уведомление не отправлено: системный трей недоступен")
            return
        items=st.get("new_items",[]) or []
        if len(items) != new_count:
            self.logger.log_general("WARNING",f"Windows-уведомление: несоответствие new_count={new_count} и new_items={len(items)}")
        cities=sorted({str(o.get("city_name") or "").strip() for o in items if o.get("city_name")})
        if not cities:
            cities=[str(c.get("name") or "").strip() for c in self.settings.get("cities",[]) if c.get("name")]
        city_text=", ".join(cities) if cities else "выбранных населённых пунктах"
        with_phone=sum(bool(o.get("phone")) for o in items)
        with_site=sum(bool(o.get("website")) for o in items)
        with_email=sum(bool(o.get("email")) for o in items)
        msg=f"Найдено {new_count} новых организаций в {city_text}.\nС телефоном: {with_phone} | с сайтом: {with_site} | с e-mail: {with_email}"
        try:
            tray.showMessage("YaBizTracker",msg,QSystemTrayIcon.MessageIcon.Information,7000)
            self.logger.log_general("INFO",f"Windows-уведомление отправлено: новых организаций={new_count}")
        except Exception as e:
            self.logger.log_general("WARNING",f"Windows-уведомление недоступно: {e}")
    def diagnostics_text(self):
        import platform
        import sqlite3
        ok,detail=self.db.integrity_check(); snap=self.usage.snapshot()
        bcfg=self.settings.get("backup",{}) or {}
        backups=self.backup_service.list_backups()
        return "\n".join([
            f"Версия приложения: {__version__}", f"Схема БД: {self.db.conn.execute('PRAGMA user_version').fetchone()[0]}", f"Схема настроек: {self.settings.get('settings_schema_version', 1)}", f"Python: {platform.python_version()}", f"Windows/OS: {platform.platform()}",
            f"SQLite: {sqlite3.sqlite_version}", f"DB: {'OK' if ok else 'ERROR'} ({detail})",
            f"JavaScript API status: {self.api_status_labels.get('js').text() if self.api_status_labels.get('js') else 'unknown'}",
            f"Geocoder status: {self.api_status_labels.get('geocoder').text() if self.api_status_labels.get('geocoder') else 'unknown'}",
            f"Search status: {self.api_status_labels.get('search').text() if self.api_status_labels.get('search') else 'unknown'}",
            f"Search API: {'ключ задан' if self.config.get('search_key') else 'не задан'}",
            f"Geocoder: {'ключ задан' if self.config.get('geocoder_key') else 'не задан'}",
            f"JS API: {'ключ задан' if self.config.get('js_api_key') else 'не задан'}",
            f"Scheduler: {'OK' if self.scheduler and self.scheduler.running else 'STOPPED'}",
            f"Состояние: {self.state.value}", f"Последняя резервная копия: {os.path.basename(backups[0]) if backups else 'нет'}",
            f"Автобэкап: {'включён' if bcfg.get('enabled',True) else 'выключен'}", f"Резервных копий: {len(backups)}",
            f"Последний запуск API: {self.last_run_usage or snap.get('last_run',{})}",
            f"Схема API usage: {snap.get('schema_version', 1)}", f"Текущий Search usage: {snap['period_usage'].get('search',0)} / {snap['limits'].get('search',0)}",
        ])
    def save_diagnostics(self):
        path,_=QFileDialog.getSaveFileName(self,"Сохранить диагностический отчёт","diagnostics.txt","Text (*.txt)")
        if not path:return
        if not path.lower().endswith(".txt"):path += ".txt"
        try:
            with open(path,"w",encoding="utf-8") as f:f.write(self.diagnostics_text())
            self.statusBar().showMessage("Диагностический отчёт сохранён")
        except Exception as exc:QMessageBox.warning(self,"Диагностика",str(exc))
    def show_diagnostics(self):
        dlg=QDialog(self);dlg.setWindowTitle("Диагностика");dlg.resize(650,500);lay=QVBoxLayout(dlg);text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(self.diagnostics_text());lay.addWidget(text);bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);save=bb.addButton("Сохранить отчёт",QDialogButtonBox.ButtonRole.ActionRole);save.clicked.connect(self.save_diagnostics);bb.rejected.connect(dlg.reject);lay.addWidget(bb);dlg.exec()
    def open_settings(self):
        dlg=SettingsDialog(self,self.api,self.settings,self.config,self.usage,self.base_dir)
        if dlg.exec()!=QDialog.DialogCode.Accepted:return
        self.settings.update(dlg.result_config);self.config.update(dlg.result_api_keys);self.settings["api_limits"]=self.usage.snapshot()["limits"];self.settings["api_quota"]=self.usage.snapshot().get("quota",{}) | {"start_date":dlg.result_config["api_quota"]["start_date"],"reset_frequency":dlg.result_config["api_quota"]["reset_frequency"]}
        try:
            moved=self.db.move_matching_to_trash(self.settings.get("excluded_categories",[]), None)
            if moved:self.logger.log_general("INFO",f"Исключено по категориям и перемещено в Корзину: {moved}")
        except Exception as exc:
            self.logger.log_general("WARNING",f"Не удалось применить категории-исключения к существующим организациям: {exc}")
        self.settings.pop("next_scan_at",None)
        save_json(os.path.join(self.base_dir,"settings.json"),self.settings);save_json(os.path.join(self.base_dir,"config.json"),self.config)
        self.backup_service=self._build_backup_service();self.api=YandexAPI(self.config["search_key"],self.config["geocoder_key"],self.usage);self.map_ready=False;self.load_map_html()
        self.schedule_quota_reset_timer()
        self.set_state(AppState.READY);self.start_scheduler();self.run_health();self.refresh_all()
        QTimer.singleShot(350,lambda:self.run_scan(False))
