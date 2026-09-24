from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from PyQt6.QtCore import Qt, QTimer, QUrl, QDate, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFrame, QMessageBox, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem, QSpinBox, QGroupBox, QFormLayout, QScrollArea,
    QRadioButton, QButtonGroup, QDateEdit, QSizePolicy, QInputDialog,
    QFileDialog, QHeaderView, QTableWidget, QTableWidgetItem, QWidget)

from ..api import YandexAPI
from ..domain.categories import ensure_categories_file, load_categories_file, categories_to_activities
from ..domain.models import STATUS_OPTIONS
from ..services.backup import BackupService
from ..services.export_service import ExportService
from ..services.profiles import ProfileService
from ..services.settings import resolve_backup_path
from ..database import Database
from .workers import SuggestWorker
from .widgets import CityRow


class SettingsDialog(QDialog):
    def __init__(self,parent,api,current,config,usage,base_dir):
        super().__init__(parent)
        self.api=api; self.current=current; self.config=config; self.usage=usage; self.base_dir=base_dir
        self.categories_path=ensure_categories_file(base_dir)
        self.category_catalog=load_categories_file(self.categories_path)
        self.category_file_mtime=self._categories_mtime()
        self.result_config=None; self.result_api_keys=None
        self.profile_service=ProfileService(current); self.active_city=None; self.suggest_worker=None; self.suggest_workers=[]; self.suggest_request_id=0; self.suggest_cache={}; self.timer=None; self._guard=False
        self.setWindowTitle("Настройки YaBizTracker"); self.resize(900,656); self.setMinimumSize(760,500)
        root=QVBoxLayout(self)
        root.setContentsMargins(8,8,8,8)
        root.setSpacing(6)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content=QWidget()
        content_layout=QVBoxLayout(content)
        content_layout.setContentsMargins(2,2,2,2)
        content_layout.setSpacing(8)
        scroll.setWidget(content)
        content_layout.addStretch(0)
        root.addWidget(scroll,1)

        # API credentials are deliberately the FIRST section and are ALWAYS editable.
        # Search parameters below are enabled only after all three keys are present.
        api_box=QGroupBox("1. API-ключи и локальные лимиты")
        api_layout=QVBoxLayout(api_box)
        api_help=QLabel('Получить ключи API: <a href="https://yandex.ru/maps-api/console">https://yandex.ru/maps-api/console</a>')
        api_help.setOpenExternalLinks(True)
        api_help.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        api_help.setStyleSheet("color:#666; font-size:9pt; padding:2px 0 4px 0;")
        api_help.setWordWrap(True)
        api_layout.addWidget(api_help)
        af=QFormLayout(); af.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.js=QLineEdit(str(config.get("js_api_key") or "")); self.js.setEchoMode(QLineEdit.EchoMode.Password); self.js.setPlaceholderText("Введите ключ JavaScript API")
        self.geo=QLineEdit(str(config.get("geocoder_key") or "")); self.geo.setEchoMode(QLineEdit.EchoMode.Password); self.geo.setPlaceholderText("Введите ключ Геокодера API")
        self.search=QLineEdit(str(config.get("search_key") or "")); self.search.setEchoMode(QLineEdit.EchoMode.Password); self.search.setPlaceholderText("Введите ключ Поиск по организациям API")
        self.api_fields=(self.js,self.geo,self.search)
        # API fields are always editable, even when all search controls below are disabled.
        for field in self.api_fields:
            field.setEnabled(True)
            field.setMinimumWidth(280)
            field.setMinimumHeight(32)
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        af.addRow("JavaScript API:",self.js); af.addRow("Геокодер API:",self.geo); af.addRow("Поиск по организациям API:",self.search)
        self.api_hint=QLabel("Заполните все 3 ключа. После этого станут доступны населённые пункты и категории.")
        self.api_hint.setStyleSheet("color:#666")
        af.addRow("",self.api_hint)
        self.limit_edits={}
        self.usage_edits={}
        snap=usage.snapshot()
        usage_now=snap.get("period_usage",{})
        for key,label in [("js","Лимит JS"),("geocoder","Лимит Геокодера"),("search","Лимит Search")]:
            sp=QSpinBox(); sp.setMinimumHeight(30); sp.setRange(0,10_000_000); sp.setValue(int(snap["limits"].get(key,1000))); self.limit_edits[key]=sp; af.addRow(label+":",sp)
        af.addRow("",QLabel("Израсходовано запросов (текущий период):"))
        for key,label in [("js","JS"),("geocoder","Геокодер"),("search","Search")]:
            sp=QSpinBox(); sp.setMinimumHeight(30); sp.setRange(0,2_147_483_647); sp.setValue(max(0,int(usage_now.get(key,0)))); self.usage_edits[key]=sp; af.addRow("  "+label+":",sp)
        api_layout.addLayout(af)
        content_layout.addWidget(api_box)

        quota=QGroupBox("Период действия лимитов")
        qf=QFormLayout(quota); qf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow); qsnap=usage.snapshot().get("quota",{})
        self.quota_start=QDateEdit(); self.quota_start.setMinimumHeight(30); self.quota_start.setCalendarPopup(True); self.quota_start.setDisplayFormat("dd.MM.yyyy")
        qd=QDate.fromString(str(qsnap.get("start_date") or ""),"yyyy-MM-dd")
        self.quota_start.setDate(qd if qd.isValid() else QDate.currentDate())
        today=QDate.fromString(datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat(),"yyyy-MM-dd")
        self.quota_start.setMaximumDate(today)
        qf.addRow("Дата начала действия:",self.quota_start)
        self.quota_frequency=QComboBox(); self.quota_frequency.setMinimumHeight(30)
        for value,label in (("daily","Раз в день"),("weekly","Раз в неделю"),("monthly","Раз в месяц"),("yearly","Раз в год")): self.quota_frequency.addItem(label,value)
        self.quota_frequency.setCurrentIndex(max(0,self.quota_frequency.findData(qsnap.get("frequency","daily"))))
        qf.addRow("Сброс лимитов:",self.quota_frequency); qf.addRow("Время автоматического сброса:",QLabel("00:00 по МСК"))
        self.reset_quota_btn=QPushButton("Сбросить лимиты сейчас"); self.reset_quota_btn.setMinimumHeight(30); self.reset_quota_btn.setToolTip("Сбросить использованные запросы текущего периода. Установленные лимиты не изменятся."); self.reset_quota_btn.clicked.connect(self.manual_reset_quota)
        qf.addRow("Ручной сброс:",self.reset_quota_btn)
        content_layout.addWidget(quota)

        backup=QGroupBox("Резервное копирование")
        bf=QFormLayout(backup)
        self.backup_enabled=QCheckBox("Автоматическое резервное копирование")
        bcfg=current.get("backup",{}) or {}
        self.backup_enabled.setChecked(bool(bcfg.get("enabled",True)))
        bf.addRow("",self.backup_enabled)
        self.backup_retention=QSpinBox(); self.backup_retention.setRange(1,365); self.backup_retention.setValue(max(1,min(365,int(bcfg.get("retention",14)))))
        bf.addRow("Хранить копий:",self.backup_retention)
        backup_path=resolve_backup_path(base_dir, bcfg.get("path"))
        self.backup_path=QLineEdit(backup_path); self.backup_path.setMinimumHeight(30)
        browse=QPushButton("Выбрать…"); browse.clicked.connect(self.choose_backup_folder)
        roww=QWidget(); rowl=QHBoxLayout(roww); rowl.setContentsMargins(0,0,0,0); rowl.addWidget(self.backup_path,1); rowl.addWidget(browse)
        bf.addRow("Папка:",roww)
        backup_actions=QHBoxLayout(); nowb=QPushButton("Создать резервную копию сейчас"); openb=QPushButton("Открыть папку")
        nowb.clicked.connect(self.create_backup_now); openb.clicked.connect(self.open_backup_folder); backup_actions.addWidget(nowb); backup_actions.addWidget(openb); backup_actions.addStretch(); bf.addRow("",backup_actions)
        cleanup_actions=QHBoxLayout()
        delete_backups=QPushButton("Удалить все бэкапы")
        delete_logs=QPushButton("Удалить все логи")
        delete_aux=QPushButton("Удалить вспомогательные файлы")
        delete_backups.clicked.connect(self.delete_all_backups)
        delete_logs.clicked.connect(self.delete_all_logs)
        delete_aux.clicked.connect(self.delete_auxiliary_files)
        for button in (delete_backups,delete_logs,delete_aux): cleanup_actions.addWidget(button)
        cleanup_actions.addStretch(); bf.addRow("Очистка:",cleanup_actions)
        self.backup_status=QLabel("Резервная копия создаётся при запуске и затем ежедневно."); self.backup_status.setWordWrap(True); bf.addRow("Состояние:",self.backup_status)
        content_layout.addWidget(backup)

        ef_box=QGroupBox("Сбор e-mail с сайтов организаций")
        ef=QFormLayout(ef_box)
        efcfg=current.get("email_finder",{}) or {}
        self.email_finder_enabled=QCheckBox("Автоматически искать e-mail на сайтах после поиска")
        self.email_finder_enabled.setChecked(bool(efcfg.get("enabled",True)))
        ef.addRow("",self.email_finder_enabled)
        self.email_finder_workers=QSpinBox(); self.email_finder_workers.setRange(1,32); self.email_finder_workers.setValue(max(1,min(32,int(efcfg.get("workers",8)))))
        ef.addRow("Параллельных сайтов:",self.email_finder_workers)
        self.email_finder_pages=QSpinBox(); self.email_finder_pages.setRange(1,20); self.email_finder_pages.setValue(max(1,min(20,int(efcfg.get("max_pages",5)))))
        ef.addRow("Страниц на сайт:",self.email_finder_pages)
        self.email_finder_timeout=QSpinBox(); self.email_finder_timeout.setRange(3,60); self.email_finder_timeout.setValue(max(3,min(60,int(float(efcfg.get("timeout_seconds",12))))))
        ef.addRow("Таймаут запроса, сек.:",self.email_finder_timeout)
        self.email_finder_recheck=QSpinBox(); self.email_finder_recheck.setRange(1,365); self.email_finder_recheck.setValue(max(1,min(365,int(efcfg.get("recheck_days",30)))))
        ef.addRow("Повторно проверять через, дней:",self.email_finder_recheck)
        self.email_finder_robots=QCheckBox("Соблюдать robots.txt (безопасный режим)")
        self.email_finder_robots.setChecked(bool(efcfg.get("respect_robots",True)))
        ef.addRow("",self.email_finder_robots)
        ef_hint=QLabel("Поиск выполняется в фоне и не блокирует поиск организаций. Один сайт сканируется один раз, даже если он указан у нескольких организаций. Найденные адреса объединяются через запятую.")
        ef_hint.setWordWrap(True); ef_hint.setStyleSheet("color:#666")
        ef.addRow("",ef_hint)
        content_layout.addWidget(ef_box)

        cities_box=QGroupBox("2. Населённые пункты")
        cl=QVBoxLayout(cities_box); self.city_rows=[]; self.city_container=QVBoxLayout(); cl.addLayout(self.city_container)
        self.add_city_btn=QPushButton("＋ Добавить населённый пункт"); self.add_city_btn.setMinimumHeight(30); self.add_city_btn.clicked.connect(lambda:self.add_city_row()); cl.addWidget(self.add_city_btn)
        self.suggestions=QListWidget(); self.suggestions.setMaximumHeight(130); self.suggestions.hide(); cl.addWidget(self.suggestions)
        self.suggestion_hint=QLabel("Подсказки Геокодера используются для однозначного выбора одноимённых населённых пунктов."); self.suggestion_hint.setStyleSheet("color:#777"); cl.addWidget(self.suggestion_hint)
        content_layout.addWidget(cities_box)

        options=QGroupBox("Мониторинг"); of=QFormLayout(options)
        self.period=QComboBox(); [self.period.addItem(f"{d} дней",d) for d in (7,14,30,60,90)]; self.period.setCurrentIndex(max(0,self.period.findData(current.get("period_days",30)))); of.addRow("Показывать новые за:",self.period)
        self.schedule=QComboBox(); [self.schedule.addItem(f"каждые {h} ч",h) for h in (1,3,6,12,24)]; self.schedule.setCurrentIndex(max(0,self.schedule.findData(current.get("schedule_hours",6)))); of.addRow("Автосканирование:",self.schedule); content_layout.addWidget(options)

        profile_box=QGroupBox("Профили поиска"); pl=QHBoxLayout(profile_box); self.profile=QComboBox(); self.profile.addItems(self.profile_service.names()); pl.addWidget(self.profile,1)
        loadp=QPushButton("Загрузить"); loadp.clicked.connect(self.load_profile); pl.addWidget(loadp); savep=QPushButton("Сохранить профиль"); savep.clicked.connect(self.save_profile); pl.addWidget(savep); delp=QPushButton("Удалить"); delp.clicked.connect(self.delete_profile); pl.addWidget(delp); content_layout.addWidget(profile_box)

        content_layout.addWidget(QLabel("3. Категории и подкатегории"))
        category_hint=QLabel("Укажите категории для поиска и, при необходимости, категории-исключения. Если у организации есть хотя бы одна исключённая категория, она не попадёт в результаты, даже если одновременно относится к нужной категории.")
        category_hint.setWordWrap(True); category_hint.setStyleSheet("color:#666; padding:2px 0 4px 0;")
        content_layout.addWidget(category_hint)
        self.category_search=QLineEdit()
        self.category_search.setPlaceholderText("Поиск категории…")
        self.category_search.setClearButtonEnabled(True)
        self.category_search.setMinimumHeight(30)
        self.category_search.textChanged.connect(self.filter_categories)
        content_layout.addWidget(self.category_search)
        category_file_row=QHBoxLayout()
        self.edit_categories_btn=QPushButton("Изменить список категорий")
        self.edit_categories_btn.setToolTip("Открыть categories.txt. После сохранения и закрытия файла список категорий в программе обновится автоматически.")
        self.edit_categories_btn.clicked.connect(self.open_categories_file)
        category_file_row.addWidget(self.edit_categories_btn)
        category_file_row.addStretch()
        content_layout.addLayout(category_file_row)
        category_split=QHBoxLayout()
        include_box=QGroupBox("Искать")
        include_layout=QVBoxLayout(include_box)
        self.tree=QTreeWidget(); self.tree.setHeaderLabels(["Категория / подкатегория"]); self.tree.setMinimumHeight(220)
        include_layout.addWidget(self.tree,1)
        include_controls=QHBoxLayout(); allb=QPushButton("Выделить все"); noneb=QPushButton("Убрать все")
        allb.clicked.connect(lambda:self.set_all(True)); noneb.clicked.connect(lambda:self.set_all(False))
        include_controls.addWidget(allb); include_controls.addWidget(noneb); include_layout.addLayout(include_controls)
        exclude_box=QGroupBox("Исключить из поиска")
        exclude_layout=QVBoxLayout(exclude_box)
        self.excluded_tree=QTreeWidget(); self.excluded_tree.setHeaderLabels(["Категория / подкатегория"]); self.excluded_tree.setMinimumHeight(220)
        exclude_layout.addWidget(self.excluded_tree,1)
        exclude_controls=QHBoxLayout(); ex_all=QPushButton("Выделить все"); ex_none=QPushButton("Убрать все")
        ex_all.clicked.connect(lambda:self.set_excluded_all(True)); ex_none.clicked.connect(lambda:self.set_excluded_all(False))
        exclude_controls.addWidget(ex_all); exclude_controls.addWidget(ex_none); exclude_layout.addLayout(exclude_controls)
        category_split.addWidget(include_box,1); category_split.addWidget(exclude_box,1); content_layout.addLayout(category_split,1)
        test=QPushButton("🔎 Тестовый поиск"); test.clicked.connect(self.test_search); content_layout.addWidget(test)
        self.category_controls=(allb,noneb,ex_all,ex_none,test,self.category_search,self.edit_categories_btn)
        self.test_result=QLabel(""); self.test_result.setStyleSheet("color:#555"); content_layout.addWidget(self.test_result)

        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Save); buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить и искать"); buttons.accepted.connect(self.accept_settings); buttons.rejected.connect(self.reject); root.addWidget(buttons)
        self.city_edit_timer=QTimer(self); self.city_edit_timer.setSingleShot(True); self.city_edit_timer.timeout.connect(self._suggest)
        self.category_file_timer=QTimer(self); self.category_file_timer.setInterval(1000); self.category_file_timer.timeout.connect(self._check_categories_file); self.category_file_timer.start(); self.suggestions.itemClicked.connect(self.select_suggestion); self.tree.itemChanged.connect(lambda item,col:self.on_tree_changed(self.tree,item,col)); self.excluded_tree.itemChanged.connect(lambda item,col:self.on_tree_changed(self.excluded_tree,item,col))
        for e in self.api_fields: e.textChanged.connect(self._api_changed)
        self.build_tree(current.get("categories",[]), current.get("excluded_categories",[]))
        cities=current.get("cities") or ([] if not current.get("city") else [current["city"]])
        for c in cities: self.add_city_row(c)
        if not self.city_rows: self.add_city_row()
        self._update_search_controls()

    def _categories_mtime(self):
        try:
            return os.path.getmtime(self.categories_path)
        except OSError:
            return None

    def open_categories_file(self):
        try:
            ensure_categories_file(self.base_dir)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(self.categories_path)):
                if hasattr(os, "startfile"):
                    os.startfile(self.categories_path)
            self.category_file_mtime=self._categories_mtime()
        except Exception as exc:
            QMessageBox.warning(self, "Категории", f"Не удалось открыть categories.txt: {exc}")

    def _check_categories_file(self):
        mtime=self._categories_mtime()
        if mtime is None or mtime == self.category_file_mtime:
            return
        self.category_file_mtime=mtime
        categories=load_categories_file(self.categories_path)
        if not categories:
            QMessageBox.warning(self, "Категории", "В categories.txt не найдено ни одной категории. Список оставлен без изменений.")
            return
        selected=set(self.categories())
        excluded=set(self.excluded_categories())
        self.category_catalog=categories
        self.build_tree([x for x in selected if x in categories], [x for x in excluded if x in categories])
        self.test_result.setText(f"Список категорий обновлён: {len(categories)} категорий.")

    def closeEvent(self,event):
        # Suggestion requests are best-effort. They are short-lived and their
        # results are guarded by request_id, so closing Settings never blocks
        # the UI for an in-flight HTTP request.
        if hasattr(self, 'category_file_timer'): self.category_file_timer.stop()
        for worker in list(self.suggest_workers):
            if worker.isRunning():
                worker.requestInterruption()
        self.suggestions.hide()
        super().closeEvent(event)

    def choose_backup_folder(self):
        path=QFileDialog.getExistingDirectory(self,"Папка резервных копий",self.backup_path.text().strip() or self.base_dir)
        if path:self.backup_path.setText(path)

    def create_backup_now(self):
        try:
            service=BackupService(self.parent().db if hasattr(self.parent(),"db") else None,self.backup_path.text().strip() or os.path.join(self.base_dir,"backups"),self.backup_retention.value())
            path=service.create_backup()
            self.backup_status.setText("✓ Создано: "+path)
        except Exception as exc:
            self.backup_status.setText("⚠ Ошибка резервного копирования: "+str(exc))
            QMessageBox.warning(self,"Резервное копирование",str(exc))

    def delete_all_backups(self):
        service=BackupService(self.parent().db if hasattr(self.parent(),"db") else None,
                              self.backup_path.text().strip() or os.path.join(self.base_dir,"backups"),
                              self.backup_retention.value())
        count=len(service.list_backups())
        if not count:
            self.backup_status.setText("Бэкапов для удаления нет.")
            return
        if QMessageBox.question(self, "Удаление бэкапов", f"Удалить все {count} резервных копии? Это действие нельзя отменить.",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            removed=service.delete_all_backups()
            self.backup_status.setText(f"✓ Удалено резервных копий: {removed}")
        except Exception as exc:
            QMessageBox.warning(self, "Удаление бэкапов", str(exc))

    def delete_all_logs(self):
        if QMessageBox.question(self, "Удаление логов", "Удалить все журналы приложения? База данных и настройки не будут затронуты.",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            logger=getattr(self.parent(), "logger", None)
            removed=logger.clear_logs(self.base_dir) if logger is not None else 0
            self.backup_status.setText(f"✓ Удалено файлов журналов: {removed}")
        except Exception as exc:
            QMessageBox.warning(self, "Удаление логов", str(exc))

    def delete_auxiliary_files(self):
        if QMessageBox.question(self, "Удаление вспомогательных файлов",
                                "Удалить временные, восстановительные и __pycache__-файлы? База, настройки, категории и бэкапы не будут затронуты.",
                                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        removed=BackupService.delete_auxiliary_files(self.base_dir, (resolve_backup_path(self.base_dir, self.backup_path.text().strip()),))
        self.backup_status.setText(f"✓ Удалено вспомогательных файлов: {removed}")

    def open_backup_folder(self):
        path=os.path.abspath(os.path.expanduser(self.backup_path.text().strip() or os.path.join(self.base_dir,"backups")))
        os.makedirs(path,exist_ok=True)
        try:
            if hasattr(os,"startfile"): os.startfile(path)
            else: QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:
            QMessageBox.warning(self,"Резервное копирование",f"Не удалось открыть папку: {exc}")

    def _keep_on_screen(self):
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        x = min(max(self.x(), area.left()), max(area.left(), area.right() - self.width() + 1))
        y = min(max(self.y(), area.top()), max(area.top(), area.bottom() - self.height() + 1))
        if x != self.x() or y != self.y():
            self.move(x, y)

    def moveEvent(self, event):
        super().moveEvent(event)
        QTimer.singleShot(0, self._keep_on_screen)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._keep_on_screen)

    def _api_changed(self):
        self.api=YandexAPI(self.search.text().strip(),self.geo.text().strip(),self.usage)
        self._update_search_controls()

    def _update_search_controls(self):
        ready=all(e.text().strip() for e in self.api_fields)
        for row in self.city_rows: row.setEnabled(ready)
        self.tree.setEnabled(ready)
        for b in getattr(self,"category_controls",()): b.setEnabled(ready)
        if hasattr(self,"add_city_btn"): self.add_city_btn.setEnabled(ready)
        self.api_hint.setText("✓ Все API-ключи заполнены. Параметры поиска доступны." if ready else "⚠ Заполните все 3 API-ключа. После этого станут доступны населённые пункты и категории.")
        self.api_hint.setStyleSheet("color:#176b2c" if ready else "color:#a15c00")

    def add_city_row(self,data=None):
        row=CityRow(data);self.city_rows.append(row);self.city_container.addWidget(row);row.changed.connect(self.city_changed);row.remove_requested.connect(self.remove_city_row)
        row.remove.setVisible(len(self.city_rows)>1);self._refresh_remove_buttons();self._update_search_controls()

    def remove_city_row(self,row):
        if len(self.city_rows)<=1:return
        self.city_rows.remove(row);row.deleteLater();self._refresh_remove_buttons()
        if self.active_city is row:self.active_city=None;self.suggestions.hide()

    def _refresh_remove_buttons(self):
        for r in self.city_rows:r.remove.setVisible(len(self.city_rows)>1)

    def city_changed(self,row):
        self.active_city=row
        self.suggest_request_id += 1
        text=row.edit.text().strip()
        if len(text)<2:
            self.suggestions.hide()
            return
        # Repaint from the closest cached prefix immediately. The network
        # request then refreshes the list, so typing never leaves the user
        # looking at suggestions for an older prefix.
        self._show_cached_suggestions(text)
        self.city_edit_timer.start(280)

    def _show_cached_suggestions(self,text):
        key=text.casefold()
        candidates=[]
        # Prefer the longest cached prefix contained in the current query.
        for cached_text,items in self.suggest_cache.items():
            if key.startswith(cached_text):
                candidates.extend(items)
        if not candidates:
            return
        unique=[];seen=set()
        for item in candidates:
            name=str(item.get("name") or "")
            if name and name.casefold().startswith(key) and name.casefold() not in seen:
                seen.add(name.casefold());unique.append(item)
        if unique:
            self.show_suggestions(unique)

    def _suggest(self):
        row=self.active_city
        if not row:return
        text=row.edit.text().strip()
        if len(text)<2:return
        request_id=self.suggest_request_id
        worker=SuggestWorker(self.api,text,request_id)
        self.suggest_worker=worker
        self.suggest_workers.append(worker)
        worker.finished.connect(self.show_suggestions_result)
        worker.failed.connect(self.on_suggest_failed_result)
        worker.finished.connect(lambda *_: self._forget_suggest_worker(worker))
        worker.failed.connect(lambda *_: self._forget_suggest_worker(worker))
        worker.start()

    def _forget_suggest_worker(self,worker):
        if worker in self.suggest_workers:
            self.suggest_workers.remove(worker)
        if self.suggest_worker is worker:
            self.suggest_worker=None
        worker.deleteLater()

    def on_suggest_failed_result(self,request_id,text,error):
        if request_id != self.suggest_request_id:return
        self.suggestion_hint.setText("Ошибка подсказок: "+str(error))

    def show_suggestions_result(self,request_id,text,items):
        # Late HTTP responses must never overwrite a newer query or another
        # city row. This is the key fix for stale 'Сама' results after typing
        # 'Самара'.
        if request_id != self.suggest_request_id:return
        if self.active_city is None or self.active_city.edit.text().strip() != text:return
        self.suggest_cache[text.casefold()] = list(items or [])
        self.show_suggestions(items)

    def show_suggestions(self,items):
        self.suggestions.clear()
        for x in items:
            it=QListWidgetItem(x.get("name","")+" — "+x.get("description",""));it.setData(Qt.ItemDataRole.UserRole,x);self.suggestions.addItem(it)
        self.suggestions.setVisible(bool(items))

    def select_suggestion(self,item):
        if self.active_city:self.active_city.set_data(item.data(Qt.ItemDataRole.UserRole))
        self.suggestions.hide()

    def _populate_category_tree(self, tree, selected):
        selected=set(selected or []); tree.clear(); self._guard=True
        try:
            for letter,vals in categories_to_activities(self.category_catalog).items():
                values=vals.split("|"); top=QTreeWidgetItem([letter]); top.setFlags(top.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                states=[v in selected for v in values]
                top.setCheckState(0,Qt.CheckState.Checked if all(states) else Qt.CheckState.PartiallyChecked if any(states) else Qt.CheckState.Unchecked); tree.addTopLevelItem(top)
                for v in values:
                    ch=QTreeWidgetItem([v]); ch.setFlags(ch.flags()|Qt.ItemFlag.ItemIsUserCheckable); ch.setCheckState(0,Qt.CheckState.Checked if v in selected else Qt.CheckState.Unchecked); top.addChild(ch)
        finally:self._guard=False

    def build_tree(self,selected,excluded=None):
        self._populate_category_tree(self.tree,selected)
        self._populate_category_tree(self.excluded_tree,excluded or [])

    def _recalc_parents(self,tree):
        for i in range(tree.topLevelItemCount()):
            p=tree.topLevelItem(i); states=[p.child(j).checkState(0) for j in range(p.childCount())]
            p.setCheckState(0,Qt.CheckState.Checked if states and all(x==Qt.CheckState.Checked for x in states) else Qt.CheckState.Unchecked if all(x==Qt.CheckState.Unchecked for x in states) else Qt.CheckState.PartiallyChecked)

    def filter_categories(self,text):
        query=(text or "").strip().casefold()
        for tree in (self.tree,self.excluded_tree):
            for i in range(tree.topLevelItemCount()):
                parent = tree.topLevelItem(i)
                parent_match = not query or query in parent.text(0).casefold()
                child_match = False
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    match = parent_match or query in child.text(0).casefold()
                    child.setHidden(not match)
                    child_match = child_match or match
                parent.setHidden(not (parent_match or child_match))
                if query and child_match and not parent_match:parent.setExpanded(True)

    def on_tree_changed(self,tree,item,col):
        if self._guard:
            return
        self._guard=True
        try:
            if item.parent() is None:
                # A filtered parent represents only the currently visible
                # children. Never toggle hidden categories as a side effect
                # of clicking the letter. With no filter, the parent toggles
                # the complete group.
                state=item.checkState(0)
                if state not in (Qt.CheckState.Checked, Qt.CheckState.Unchecked):
                    return
                query=self.category_search.text().strip().casefold()
                for i in range(item.childCount()):
                    child=item.child(i)
                    if not query or not child.isHidden():
                        child.setCheckState(0,state)
                self._recalc_parent(tree,item)
            else:
                p=item.parent()
                self._recalc_parent(tree,p)
            self._recalc_visible_parents(tree)
        finally:
            self._guard=False

    def _recalc_parent(self,tree,parent):
        states=[parent.child(i).checkState(0) for i in range(parent.childCount())]
        parent.setCheckState(0, Qt.CheckState.Checked if states and all(x==Qt.CheckState.Checked for x in states)
                             else Qt.CheckState.Unchecked if states and all(x==Qt.CheckState.Unchecked for x in states)
                             else Qt.CheckState.PartiallyChecked)

    def _recalc_visible_parents(self,tree):
        for i in range(tree.topLevelItemCount()):
            self._recalc_parent(tree,tree.topLevelItem(i))

    def set_all(self,on):
        self._set_tree_all(self.tree,on)

    def set_excluded_all(self,on):
        self._set_tree_all(self.excluded_tree,on)

    def _set_tree_all(self,tree,on):
        self._guard=True
        try:
            st=Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
            for i in range(tree.topLevelItemCount()):
                t=tree.topLevelItem(i)
                t.setCheckState(0,st)
                for j in range(t.childCount()):
                    t.child(j).setCheckState(0,st)
        finally:
            self._guard=False

    @staticmethod
    def _tree_categories(tree):
        out=[]
        for i in range(tree.topLevelItemCount()):
            t=tree.topLevelItem(i)
            for j in range(t.childCount()):
                if t.child(j).checkState(0)==Qt.CheckState.Checked:out.append(t.child(j).text(0))
        return out

    def categories(self):return self._tree_categories(self.tree)
    def excluded_categories(self):return self._tree_categories(self.excluded_tree)

    def load_profile(self):
        d=self.profile_service.get(self.profile.currentText())
        if d:self.build_tree(d.get("categories",[]),d.get("excluded_categories",[]))

    def save_profile(self):
        name,ok=QInputDialog.getText(self,"Профиль","Название профиля:")
        if ok and name.strip():
            self.profile_service.save(name.strip(),self.categories(),self.excluded_categories());self.profile.clear();self.profile.addItems(self.profile_service.names());self.profile.setCurrentText(name.strip())

    def delete_profile(self):
        if self.profile.currentText():self.profile_service.delete(self.profile.currentText());self.profile.removeItem(self.profile.currentIndex())

    def _update_usage_edits_after_api_call(self, before, ui_before):
        """Отражает фактически выполненные API-запросы в полях настроек без сохранения.

        Поля в SettingsDialog могут содержать ручную поправку, которая ещё не
        записана в ApiUsageService. Поэтому нельзя просто заменить их значениями
        из snapshot(): к ручному значению нужно прибавить фактическую дельту запросов.
        """
        after=self.usage.snapshot()
        for key, widget in self.usage_edits.items():
            try:
                delta=int(after.get("period_usage",{}).get(key,0))-int(before.get("period_usage",{}).get(key,0))
                widget.setValue(max(0, int(ui_before.get(key, widget.value())) + delta))
            except (TypeError, ValueError):
                pass
        return after

    def test_search(self):
        cities=[r.data for r in self.city_rows if r.data]
        cats=self.categories()
        if not cities or not cats:
            self.test_result.setText("Для теста выберите населённый пункт и категорию.")
            return

        # Сохраняем оба состояния: фактическое состояние счётчика и то, что
        # пользователь сейчас видит/вручную указал в SettingsDialog.
        before=self.usage.snapshot()
        ui_before={k:w.value() for k,w in self.usage_edits.items()}
        try:
            fs,more=self.api.search.search_page(cats[0],cities[0]["bbox"],0)
            self.test_result.setText(f"Тест: API вернул {len(fs)} организаций; уникальных на странице: {len({str((f.get('properties',{}) or {}).get('CompanyMetaData',{}).get('id','')) for f in fs})}; расход Search API отражён в текущем периоде.")
        except Exception as e:
            self.test_result.setText("Тест завершился ошибкой: "+str(e))
        finally:
            # _request() учитывает каждый реально отправленный HTTP-запрос,
            # включая повторные попытки. Поэтому даже при ошибке/429/5xx
            # поле должно показать фактический расход.
            self._update_usage_edits_after_api_call(before,ui_before)

    def manual_reset_quota(self):
        answer=QMessageBox.question(self,"Сброс лимитов","Сбросить использованные запросы текущего периода? Установленные лимиты останутся без изменений.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if answer==QMessageBox.StandardButton.Yes:
            self.usage.reset_now()
            self.refresh_usage_edits()
            self.test_result.setText("Лимиты использования сброшены. Установленные значения лимитов не изменены.")

    def refresh_usage_edits(self):
        """Синхронизирует поля расхода с сохранённым текущим периодом."""
        snap=self.usage.snapshot()
        for key, widget in self.usage_edits.items():
            try: widget.setValue(max(0,int(snap.get("period_usage",{}).get(key,0))))
            except (TypeError, ValueError): pass

    def accept_settings(self):
        self._check_categories_file()
        keys={"js_api_key":self.js.text().strip(),"geocoder_key":self.geo.text().strip(),"search_key":self.search.text().strip()}
        if not all(keys.values()):
            QMessageBox.warning(self,"API-ключи","Заполните все три API-ключа. Пока ключи не заполнены, параметры поиска недоступны.");return
        # Existing text may already represent a previously resolved city. Never
        # require the user to select the same suggestion again.
        cities=[];seen=set()
        for row in self.city_rows:
            city=row.data
            if city and city.get("bbox"):
                key=(str(city.get("uri") or ""), str(city.get("name") or "").strip().lower(), str(city.get("bbox") or ""))
                if key not in seen:
                    seen.add(key);cities.append(dict(city))
        if not cities:QMessageBox.warning(self,"Населённые пункты","Выберите населённый пункт из подсказок хотя бы для одного поля.");return
        cats=self.categories()
        if not cats:QMessageBox.warning(self,"Категории","Выберите хотя бы одну категорию.");return
        limits={k:w.value() for k,w in self.limit_edits.items()}
        consumed={k:w.value() for k,w in self.usage_edits.items()}
        self.usage.set_limits(limits)
        quota_start=self.quota_start.date().toString("yyyy-MM-dd")
        quota_frequency=str(self.quota_frequency.currentData())
        self.usage.configure(start_date=quota_start, reset_frequency=quota_frequency)
        # Configure may intentionally start a new period; apply the manual
        # correction afterwards so the value entered by the user is retained.
        self.usage.set_period_usage(consumed)
        backup_path=self.backup_path.text().strip() or os.path.join(self.base_dir,"backups")
        default_backup=os.path.abspath(os.path.join(self.base_dir,"backups"))
        if os.path.normcase(os.path.abspath(os.path.expanduser(backup_path))) == os.path.normcase(default_backup):
            backup_path="backups"
        self.result_config={"cities":cities,"city":cities[0],"city_name":cities[0]["name"],"categories":cats,"excluded_categories":self.excluded_categories(),"period_days":int(self.period.currentData()),"schedule_hours":int(self.schedule.currentData()),"profiles":self.current.get("profiles",{}),"api_quota":{"start_date":quota_start,"reset_frequency":quota_frequency},"backup":{"enabled":self.backup_enabled.isChecked(),"retention":self.backup_retention.value(),"path":backup_path},"email_finder":{"enabled":self.email_finder_enabled.isChecked(),"workers":self.email_finder_workers.value(),"max_pages":self.email_finder_pages.value(),"timeout_seconds":self.email_finder_timeout.value(),"max_response_bytes":2097152,"recheck_days":self.email_finder_recheck.value(),"respect_robots":self.email_finder_robots.isChecked()}}
        self.result_api_keys=keys;self.accept()

class TrashDialog(QDialog):
    restored=pyqtSignal()

    def __init__(self,parent,db):
        super().__init__(parent); self.db=db; self.setWindowTitle("Корзина"); self.resize(1450,720); self.setMinimumSize(1050,560)
        root=QVBoxLayout(self)
        info=QLabel("Записи хранятся в Корзине 30 дней. После этого они удаляются без возможности восстановления.")
        info.setWordWrap(True); info.setStyleSheet("color:#666"); root.addWidget(info)
        filters=QGroupBox("Фильтры"); fl=QHBoxLayout(filters)
        self.search_edit=QLineEdit(); self.search_edit.setPlaceholderText("🔎 Название, адрес или категория")
        self.cat_filter=QComboBox(); self.cat_filter.addItem("Все категории","")
        self.status_filter=QComboBox(); self.status_filter.addItem("Все статусы",""); [self.status_filter.addItem(x,x) for x in STATUS_OPTIONS]
        self.phone_cb=QCheckBox("Телефон"); self.email_cb=QCheckBox("E-mail"); self.site_cb=QCheckBox("Сайт"); self.social_cb=QCheckBox("Соцсети")
        self.responsible_cb=QCheckBox("Ответственный"); self.next_contact_cb=QCheckBox("Следующий контакт")
        for w in (self.search_edit,self.cat_filter,self.status_filter,self.phone_cb,self.email_cb,self.site_cb,self.social_cb,self.responsible_cb,self.next_contact_cb):fl.addWidget(w)
        root.addWidget(filters)
        self.table=QTableWidget(0,15); self.table.setHorizontalHeaderLabels(["Название","Адрес","Категория","Возраст","Телефон","E-mail","Сайт","Соцсети","Статус","Комментарий","Ответственный","Следующий контакт","Lead Score","Удалено","Причина"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection); self.table.setSortingEnabled(True); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        root.addWidget(self.table,1)
        actions=QHBoxLayout(); self.restore_btn=QPushButton("↩ Восстановить"); self.clear_btn=QPushButton("🗑 Очистить Корзину"); self.close_btn=QPushButton("Закрыть")
        actions.addWidget(self.restore_btn); actions.addWidget(self.clear_btn); actions.addStretch(); actions.addWidget(self.close_btn); root.addLayout(actions)
        self.restore_btn.clicked.connect(self.restore_selected); self.clear_btn.clicked.connect(self.clear_trash); self.close_btn.clicked.connect(self.accept)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        for w in (self.search_edit,self.cat_filter,self.status_filter):w.textChanged.connect(self.load) if isinstance(w,QLineEdit) else w.currentIndexChanged.connect(self.load)
        for cb in (self.phone_cb,self.email_cb,self.site_cb,self.social_cb,self.responsible_cb,self.next_contact_cb):cb.stateChanged.connect(self.load)
        self.db.purge_trash(days=30); self.load()

    def _filters(self):
        return {"search":self.search_edit.text(),"category":self.cat_filter.currentData(),"status":self.status_filter.currentData(),
                "has_phone":self.phone_cb.isChecked(),"has_email":self.email_cb.isChecked(),"has_website":self.site_cb.isChecked(),"has_social":self.social_cb.isChecked(),
                "responsible":self.responsible_cb.isChecked(),"next_contact":self.next_contact_cb.isChecked()}

    def load(self):
        current=self.cat_filter.currentData(); rows=self.db.get_trash(self._filters())
        all_rows=self.db.get_trash({})
        self.cat_filter.blockSignals(True); self.cat_filter.clear(); self.cat_filter.addItem("Все категории","")
        cats=sorted({x for o in all_rows for x in ((o.get("category"),o.get("subcategory")) if not o.get("categories_json") else ()) if x})
        for o in all_rows:
            try: vals=json.loads(o.get("categories_json") or "[]")
            except (TypeError,ValueError): vals=[]
            if isinstance(vals,list):cats.extend(str(x) for x in vals if x)
        for c in sorted(set(cats),key=str.casefold):self.cat_filter.addItem(c,c)
        self.cat_filter.setCurrentIndex(max(0,self.cat_filter.findData(current))); self.cat_filter.blockSignals(False)
        self.table.setSortingEnabled(False); self.table.setRowCount(0)
        for o in rows:self._add_row(o)
        self.table.setSortingEnabled(True); self.selection_changed()
        self.setWindowTitle(f"Корзина — {len(all_rows)} записей")

    def _add_row(self,o):
        r=self.table.rowCount(); self.table.insertRow(r)
        age=Database._age(o.get("first_seen_date","")); social=ExportService.social_text(o.get("social_links","{}"))
        vals=[o.get("name",""),o.get("address",""),o.get("category","")+((" → "+o.get("subcategory","")) if o.get("subcategory") else ""),f"{age} дн.",o.get("phone",""),o.get("email",""),o.get("website",""),social,o.get("status","Новый"),o.get("comment",""),o.get("responsible",""),o.get("next_contact_date",""),str(Database._score({**o,"age_days":age})),o.get("deleted_at",""),o.get("reason","")]
        for c,v in enumerate(vals):
            it=QTableWidgetItem(str(v)); it.setData(Qt.ItemDataRole.UserRole,o.get("trash_id")); self.table.setItem(r,c,it)

    def selection_changed(self):
        self.restore_btn.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def restore_selected(self):
        ids=[self.table.item(x.row(),0).data(Qt.ItemDataRole.UserRole) for x in self.table.selectionModel().selectedRows()]
        if not ids:return
        n,conflicts=self.db.restore_from_trash(ids)
        if conflicts:
            QMessageBox.warning(self,"Восстановление",f"Восстановлено: {n}.\nКонфликтов: {len(conflicts)} — соответствующая организация уже существует в активном списке.")
        self.restored.emit(); self.load()

    def clear_trash(self):
        count=len(self.db.get_trash({}))
        if not count:return
        if QMessageBox.question(self,"Очистить Корзину",f"Удалить навсегда {count} записей из Корзины? Восстановление будет невозможно.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.db.clear_trash(); self.load()

class ExportDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent);self.setWindowTitle("Экспорт в Excel");self.resize(520,620);self.setMinimumSize(440,520)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel("Что экспортировать?"))
        self.group=QButtonGroup(self)
        options=[("Текущий отфильтрованный список","visible"),("Все новые за выбранный период","period"),
                 ("Только выбранные","selected"),("Только с e-mail","email"),("Только с телефоном","phone")]
        self.buttons=[]
        for i,(txt,val) in enumerate(options):
            b=QRadioButton(txt);self.group.addButton(b,i);b.setProperty("mode",val);layout.addWidget(b);self.buttons.append(b)
        self.buttons[0].setChecked(True)

        layout.addWidget(QLabel("Столбцы для экспорта:"))
        columns_box=QWidget();columns_layout=QVBoxLayout(columns_box);columns_layout.setContentsMargins(6,4,6,4);columns_layout.setSpacing(4)
        self.column_checks=[]
        for i,name in enumerate(ExportService.HEADERS):
            check=QCheckBox(name);check.setChecked(True);check.setProperty("column_index",i);columns_layout.addWidget(check);self.column_checks.append(check)
        columns_layout.addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(columns_box);scroll.setMinimumHeight(210);layout.addWidget(scroll,1)

        self.select_all_columns=QPushButton("Выбрать все столбцы")
        self.clear_columns=QPushButton("Снять все")
        column_actions=QHBoxLayout();column_actions.addWidget(self.select_all_columns);column_actions.addWidget(self.clear_columns);layout.addLayout(column_actions)
        self.select_all_columns.clicked.connect(lambda: self._set_all_columns(True))
        self.clear_columns.clicked.connect(lambda: self._set_all_columns(False))

        bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok);bb.button(QDialogButtonBox.StandardButton.Ok).setText("Экспортировать");bb.accepted.connect(self._accept_with_validation);bb.rejected.connect(self.reject);layout.addWidget(bb)
    def _set_all_columns(self, checked):
        for check in self.column_checks: check.setChecked(checked)
    def selected_columns(self):
        return [int(c.property("column_index")) for c in self.column_checks if c.isChecked()]
    def _accept_with_validation(self):
        if not self.selected_columns():
            QMessageBox.warning(self,"Столбцы не выбраны","Выберите хотя бы один столбец для экспорта.")
            return
        self.accept()
    def mode(self):
        for b in self.buttons:
            if b.isChecked():return b.property("mode")
        return "visible"
