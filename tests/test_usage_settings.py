import tempfile, unittest, unittest.mock, json
from pathlib import Path
from yabiztracker.services.api_usage import ApiUsageService
from yabiztracker.services.settings import migrate_settings

class UsageSettingsTests(unittest.TestCase):
    def test_periods_and_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p=str(Path(d)/'usage.json'); u=ApiUsageService(p,'2026-09-01','daily'); u.record('search'); u.flush(); self.assertEqual(u.snapshot()['period_usage']['search'],1); u.reset_now(); self.assertEqual(u.snapshot()['period_usage']['search'],0)
    def test_malformed_usage_json_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'usage.json'; p.write_text('{"quota":{"usage":"bad"},"limits":{"search":"bad"}}',encoding='utf8'); u=ApiUsageService(str(p)); s=u.snapshot(); self.assertEqual(s['limits']['search'],1000); self.assertEqual(s['period_usage']['search'],0)
    def test_settings_backup_defaults(self):
        s=migrate_settings({}); self.assertTrue(s['backup']['enabled']); self.assertEqual(s['backup']['retention'],14); self.assertEqual(s['backup']['path'],'backups')

    def test_column_visibility_defaults_to_all_and_keeps_explicit_empty_choice(self):
        self.assertIsNone(migrate_settings({})["visible_organization_columns"])
        self.assertEqual(migrate_settings({"visible_organization_columns": []})["visible_organization_columns"], [])
        self.assertEqual(
            migrate_settings({"visible_organization_columns": ["Название", "  ", 42]})["visible_organization_columns"],
            ["Название", "42"],
        )

if __name__=='__main__': unittest.main()

class SettingsHardeningTests(unittest.TestCase):
    def test_settings_normalise_categories_and_remove_case_insensitive_overlap(self):
        s=migrate_settings({
            "categories": [" Квесты ", "квесты", "Банк"],
            "excluded_categories": ["БАНК", " Спорт ", "спорт"],
            "period_days": "999",
            "schedule_hours": "bad",
            "api_limits": {"search": "bad", "js": -10},
        })
        self.assertEqual(s["categories"], ["Квесты", "Банк"])
        self.assertEqual(s["excluded_categories"], ["Спорт"])
        self.assertEqual(s["period_days"],30)
        self.assertEqual(s["schedule_hours"],6)
        self.assertEqual(s["api_limits"]["search"],1000)
        self.assertEqual(s["api_limits"]["js"],0)

    def test_settings_missing_api_limit_keys_are_repaired(self):
        s=migrate_settings({"api_limits":{"search":42}})
        self.assertEqual(s["api_limits"], {"search":42,"js":1000,"geocoder":1000})

class SettingsPersistenceTests(unittest.TestCase):
    def test_missing_and_malformed_json_have_explicit_fallback(self):
        from yabiztracker.services.settings import load_json
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            self.assertEqual(load_json(str(path), {"x": 1}), {"x": 1})
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_json(str(path), {"x": 2}), {"x": 2})

    def test_save_json_creates_parent_and_replaces_atomically(self):
        from yabiztracker.services.settings import save_json
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nested" / "settings.json"
            save_json(str(path), {"answer": 42})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["answer"], 42)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


class UsageBoundaryTests(unittest.TestCase):
    def test_daily_usage_resets_after_restart_and_keeps_historical_total(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"usage.json"
            p.write_text(json.dumps({
                "schema_version": 2,
                "limits": {"js":1000,"geocoder":1000,"search":1000},
                "total": {"js":0,"geocoder":0,"search":17},
                "daily": {"2026-09-16": {"js":0,"geocoder":0,"search":17}},
                "last_run": {"js":0,"geocoder":0,"search":17},
                "quota": {"start_date":"2026-09-01","frequency":"daily","period_started":"2026-09-16","usage":{"js":0,"geocoder":0,"search":17},"last_reset_at":None}
            }),encoding="utf8")
            with unittest.mock.patch.object(ApiUsageService, "_today_msk", staticmethod(lambda: __import__('datetime').date(2026,9,17))):
                u=ApiUsageService(str(p),"2026-09-01","daily")
                s=u.snapshot()
            self.assertEqual(s["period_usage"]["search"],0)
            self.assertEqual(s["total"]["search"],17)
            self.assertEqual(s["last_run"]["search"],17)

    def test_daily_reset_is_calendar_based_not_process_uptime_based(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"usage.json"
            with unittest.mock.patch.object(ApiUsageService, "_today_msk", staticmethod(lambda: __import__("datetime").date(2026,9,17))):
                u=ApiUsageService(str(p),"2026-09-01","daily")
                u.record("search");u.flush()
            with unittest.mock.patch.object(ApiUsageService, "_today_msk", staticmethod(lambda: __import__("datetime").date(2026,9,18))):
                self.assertTrue(u.maybe_reset(save=True))
                self.assertEqual(u.snapshot()["period_usage"]["search"],0)


class SchedulerPersistenceTests(unittest.TestCase):
    def test_scheduler_uses_persisted_next_scan_at(self):
        from pathlib import Path
        text=Path(__file__).resolve().parents[1].joinpath("yabiztracker","ui","main_window.py").read_text(encoding="utf8")
        assert 'self._read_next_scan_at()' in text
        assert 'self._calculate_next_scan_at(now)' in text
        assert 'self.scheduler.add_job(self._scheduler_request,"date",run_date=next_scan' in text
        assert 'self._persist_next_scan_at(next_scan)' in text

if __name__=='__main__': unittest.main()


class ApiUsageRestartBoundaryRegressionTests(unittest.TestCase):
    def test_usage_from_yesterday_is_zero_on_first_operation_today_after_process_was_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"usage.json"
            p.write_text(json.dumps({
                "schema_version": 2,
                "limits": {"js":1000,"geocoder":1000,"search":1000},
                "total": {"js":0,"geocoder":0,"search":438},
                "daily": {"2026-09-16": {"js":0,"geocoder":17,"search":438}},
                "last_run": {"js":0,"geocoder":17,"search":438},
                "quota": {
                    "start_date":"2026-09-01",
                    "frequency":"daily",
                    "period_started":"2026-09-16",
                    "usage":{"js":0,"geocoder":17,"search":438},
                    "last_reset_at":"2026-09-16T20:00:00+03:00"
                }
            }),encoding="utf8")
            with unittest.mock.patch.object(
                ApiUsageService, "_today_msk",
                staticmethod(lambda: __import__("datetime").date(2026,9,17))
            ):
                u=ApiUsageService(str(p),"2026-09-01","daily")
                self.assertEqual(u.snapshot()["period_usage"], {"js":0,"geocoder":0,"search":0})
                u.record("search")
                self.assertEqual(u.snapshot()["period_usage"]["search"],1)
                u.flush()

            # Reopening on the same day must retain today's one request.
            with unittest.mock.patch.object(
                ApiUsageService, "_today_msk",
                staticmethod(lambda: __import__("datetime").date(2026,9,17))
            ):
                reopened=ApiUsageService(str(p),"2026-09-01","daily")
                self.assertEqual(reopened.snapshot()["period_usage"]["search"],1)

    def test_two_calendar_days_closed_do_not_accumulate_stale_current_period(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"usage.json"
            with unittest.mock.patch.object(ApiUsageService, "_today_msk", staticmethod(lambda: __import__("datetime").date(2026,9,17))):
                u=ApiUsageService(str(p),"2026-09-01","daily")
                u.record("search"); u.flush()
            with unittest.mock.patch.object(ApiUsageService, "_today_msk", staticmethod(lambda: __import__("datetime").date(2026,9,18))):
                u2=ApiUsageService(str(p),"2026-09-01","daily")
                self.assertEqual(u2.snapshot()["period_usage"]["search"],0)
                u2.record("search")
                u2.flush()
            with unittest.mock.patch.object(ApiUsageService, "_today_msk", staticmethod(lambda: __import__("datetime").date(2026,9,19))):
                u3=ApiUsageService(str(p),"2026-09-01","daily")
                self.assertEqual(u3.snapshot()["period_usage"]["search"],0)
                self.assertEqual(u3.snapshot()["total"]["search"],2)


class WallClockSchedulerTests(unittest.TestCase):
    def test_closed_program_does_not_restart_six_hour_countdown_from_launch_time(self):
        from yabiztracker.domain.schedule import next_wall_clock_occurrence
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz=ZoneInfo("Europe/Moscow")
        previous=datetime(2026,9,17,8,0,tzinfo=tz)
        now=datetime(2026,9,18,8,0,tzinfo=tz)
        # 08:00 is an overdue occurrence; the next future occurrence is 14:00.
        self.assertEqual(next_wall_clock_occurrence(previous,now,6),datetime(2026,9,18,14,0,tzinfo=tz))

    def test_scheduler_collapses_multiple_missed_runs_to_one_future_occurrence(self):
        from yabiztracker.domain.schedule import next_wall_clock_occurrence
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz=ZoneInfo("Europe/Moscow")
        previous=datetime(2026,9,16,8,0,tzinfo=tz)
        now=datetime(2026,9,18,8,0,tzinfo=tz)
        self.assertEqual(next_wall_clock_occurrence(previous,now,6),datetime(2026,9,18,14,0,tzinfo=tz))

    def test_new_schedule_without_history_starts_from_now(self):
        from yabiztracker.domain.schedule import next_wall_clock_occurrence
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz=ZoneInfo("Europe/Moscow")
        now=datetime(2026,9,18,8,0,tzinfo=tz)
        self.assertEqual(next_wall_clock_occurrence(None,now,6),datetime(2026,9,18,14,0,tzinfo=tz))
