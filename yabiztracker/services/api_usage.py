from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


MSK = ZoneInfo("Europe/Moscow")
API_USAGE_SCHEMA_VERSION = 2
APIS = ("js", "geocoder", "search")
FREQUENCIES = ("daily", "weekly", "monthly", "yearly")


class ApiUsageService:
    """Persistent local API quota accounting.

    Limits themselves never change on reset; only the usage counters for the
    current quota period are reset. Calendar boundaries are evaluated in MSK
    and always occur at 00:00:00 MSK.
    """

    def __init__(self, path, start_date: str | None = None, reset_frequency: str = "daily"):
        self.path = path
        self.lock = threading.RLock()
        self._pending = 0
        self._data = {
            "schema_version": API_USAGE_SCHEMA_VERSION,
            "limits": {"js": 1000, "geocoder": 1000, "search": 1000},
            "total": {"js": 0, "geocoder": 0, "search": 0},
            "daily": {},
            "last_run": {"js": 0, "geocoder": 0, "search": 0},
            "quota": {
                "start_date": start_date or datetime.now(MSK).date().isoformat(),
                "frequency": reset_frequency if reset_frequency in FREQUENCIES else "daily",
                "period_started": None,
                "usage": {"js": 0, "geocoder": 0, "search": 0},
                "last_reset_at": None,
            },
        }
        self._load()
        self._data["schema_version"] = API_USAGE_SCHEMA_VERSION
        self.configure(start_date=start_date, reset_frequency=reset_frequency, save=False)
        self.maybe_reset(save=True)

    @staticmethod
    def _today_msk() -> date:
        return datetime.now(MSK).date()

    @staticmethod
    def _normalise_date(value: str | date | None) -> str:
        if isinstance(value, date):
            return value.isoformat()
        try:
            return date.fromisoformat(str(value)).isoformat()
        except (TypeError, ValueError):
            return datetime.now(MSK).date().isoformat()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._deep_merge(self._data, loaded)
        except (OSError, ValueError, TypeError):
            pass

        if not isinstance(self._data.get("limits"), dict): self._data["limits"] = {}
        if not isinstance(self._data.get("total"), dict): self._data["total"] = {}
        if not isinstance(self._data.get("daily"), dict): self._data["daily"] = {}
        if not isinstance(self._data.get("last_run"), dict): self._data["last_run"] = {}
        for k in APIS:
            try:self._data["limits"][k] = max(0, int(self._data["limits"].get(k, 1000)))
            except (TypeError,ValueError):self._data["limits"][k] = 1000
            try:self._data["total"][k] = max(0, int(self._data["total"].get(k, 0)))
            except (TypeError,ValueError):self._data["total"][k] = 0
            try:self._data["last_run"][k] = max(0, int(self._data["last_run"].get(k, 0)))
            except (TypeError,ValueError):self._data["last_run"][k] = 0

        q = self._data.setdefault("quota", {})
        if not isinstance(q, dict): q = self._data["quota"] = {}
        q.setdefault("start_date", datetime.now(MSK).date().isoformat())
        if q.get("frequency") not in FREQUENCIES: q["frequency"] = "daily"
        q.setdefault("period_started", None)
        if not isinstance(q.get("usage"), dict): q["usage"] = {}
        q.setdefault("last_reset_at", None)
        for k in APIS:
            try:q["usage"][k] = max(0, int(q["usage"].get(k, 0)))
            except (TypeError,ValueError):q["usage"][k] = 0

        # Migration from 1.0.0: the old daily ledger is historical data.
        # Do not derive the current quota period from process start/restart time.
        # The normal maybe_reset() call below computes the period from the wall
        # clock and the configured quota definition. If legacy data exists for
        # the actual current calendar day, preserve it as the current usage.
        if q.get("period_started") is None:
            today = self._today_msk().isoformat()
            old_today = self._data.get("daily", {}).get(today, {})
            if isinstance(old_today, dict) and any(int(old_today.get(k, 0) or 0) for k in APIS):
                q["usage"] = {k: max(0, int(old_today.get(k, 0) or 0)) for k in APIS}
                q["period_started"] = today
            else:
                q["usage"] = {k: 0 for k in APIS}
                q["period_started"] = None

    @staticmethod
    def _deep_merge(base, incoming):
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                ApiUsageService._deep_merge(base[key], value)
            else:
                base[key] = value

    def _save(self):
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def _period_start(anchor: date, frequency: str, today: date) -> date:
        """Return the start of the current quota period.

        The manually selected start date is the anchor. For the default first
        day of the month this naturally becomes calendar periods. For custom
        anchors, weekly/monthly/yearly periods repeat from that anchor.
        """
        if today < anchor:
            return anchor
        if frequency == "daily":
            return today
        if frequency == "weekly":
            elapsed = (today - anchor).days
            return anchor + timedelta(days=(elapsed // 7) * 7)
        if frequency == "monthly":
            months = (today.year - anchor.year) * 12 + (today.month - anchor.month)
            candidate_month = anchor.month + months
            year = anchor.year + (candidate_month - 1) // 12
            month = (candidate_month - 1) % 12 + 1
            # If the anchor day does not exist in the month, clamp to month end.
            import calendar
            day = min(anchor.day, calendar.monthrange(year, month)[1])
            candidate = date(year, month, day)
            if candidate > today:
                months -= 1
                candidate_month = anchor.month + months
                year = anchor.year + (candidate_month - 1) // 12
                month = (candidate_month - 1) % 12 + 1
                day = min(anchor.day, calendar.monthrange(year, month)[1])
                candidate = date(year, month, day)
            return candidate
        if frequency == "yearly":
            year = today.year
            import calendar
            day = min(anchor.day, calendar.monthrange(year, anchor.month)[1])
            candidate = date(year, anchor.month, day)
            if candidate > today:
                year -= 1
                day = min(anchor.day, calendar.monthrange(year, anchor.month)[1])
                candidate = date(year, anchor.month, day)
            return candidate
        return today

    def configure(self, start_date=None, reset_frequency=None, save=True):
        with self.lock:
            q = self._data["quota"]
            new_start = self._normalise_date(start_date if start_date is not None else q.get("start_date"))
            new_frequency = reset_frequency if reset_frequency in FREQUENCIES else q.get("frequency", "daily")
            changed = (q.get("start_date") != new_start or q.get("frequency") != new_frequency)
            q["start_date"] = new_start
            q["frequency"] = new_frequency
            if changed:
                # Changing the quota definition starts a fresh period under
                # the new definition; historical totals remain untouched.
                q["period_started"] = None
                q["usage"] = {k: 0 for k in APIS}
            if save:
                self._save()
            self.maybe_reset(save=save)

    def maybe_reset(self, save=True) -> bool:
        """Synchronise the current quota period with wall-clock calendar time.

        The decision is based exclusively on the current MSK date and the
        configured quota definition, never on process uptime or application
        launch time. This is important when the application is closed across
        midnight: the first operation after reopening must see a fresh period.
        """
        with self.lock:
            q = self._data["quota"]
            try:
                anchor = date.fromisoformat(q["start_date"])
            except (TypeError, ValueError):
                anchor = self._today_msk()
                q["start_date"] = anchor.isoformat()

            today = self._today_msk()
            frequency = q.get("frequency", "daily")
            if frequency not in FREQUENCIES:
                frequency = "daily"
                q["frequency"] = frequency

            current_iso = self._period_start(anchor, frequency, today).isoformat()
            previous_iso = q.get("period_started")

            if previous_iso != current_iso:
                q["period_started"] = current_iso
                q["usage"] = {k: 0 for k in APIS}
                q["last_reset_at"] = datetime.now(MSK).isoformat(timespec="seconds")
                if save:
                    self._save()
                return True
            return False

    def next_reset_at(self):
        """Return the next quota boundary as an aware MSK datetime."""
        with self.lock:
            q = self._data["quota"]
            anchor = date.fromisoformat(q["start_date"])
            today = self._today_msk()
            current = self._period_start(anchor, q.get("frequency", "daily"), today)
            freq = q.get("frequency", "daily")
            import calendar
            if freq == "daily":
                nxt = current + timedelta(days=1)
            elif freq == "weekly":
                nxt = current + timedelta(days=7)
            elif freq == "monthly":
                month = current.month + 1
                year = current.year + (month - 1) // 12
                month = (month - 1) % 12 + 1
                nxt = date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))
            else:
                year = current.year + 1
                nxt = date(year, anchor.month, min(anchor.day, calendar.monthrange(year, anchor.month)[1]))
            return datetime.combine(nxt, datetime.min.time(), tzinfo=MSK)

    def reset_now(self):
        """Manual reset of current-period usage; limits and totals remain intact."""
        with self.lock:
            q = self._data["quota"]
            q["usage"] = {k: 0 for k in APIS}
            q["period_started"] = self._period_start(
                date.fromisoformat(q["start_date"]), q.get("frequency", "daily"), self._today_msk()
            ).isoformat()
            q["last_reset_at"] = datetime.now(MSK).isoformat(timespec="seconds")
            self._save()

    def record(self, api):
        if api not in APIS or api == "js":
            return
        with self.lock:
            self.maybe_reset(save=False)
            day = self._today_msk().isoformat()
            self._data.setdefault("daily", {})
            if not isinstance(self._data["daily"].get(day), dict):
                self._data["daily"][day] = {k: 0 for k in APIS}
            self._data["daily"][day][api] = int(self._data["daily"][day].get(api, 0) or 0) + 1
            self._data.setdefault("total", {})
            self._data["total"][api] = self._data["total"].get(api, 0) + 1
            self._data["quota"]["usage"][api] = self._data["quota"]["usage"].get(api, 0) + 1
            self._pending += 1
            if self._pending >= 20:
                self._save()
                self._pending = 0

    def flush(self):
        with self.lock:
            self.maybe_reset(save=False)
            self._save()
            self._pending = 0

    def snapshot(self):
        with self.lock:
            self.maybe_reset(save=True)
            q = self._data["quota"]
            return {
                "schema_version": API_USAGE_SCHEMA_VERSION,
                "today": dict(q["usage"]),  # backward-compatible key; now means current quota period
                "period_usage": dict(q["usage"]),
                "total": dict(self._data.get("total", {})),
                "limits": dict(self._data.get("limits", {})),
                "last_run": dict(self._data.get("last_run", {})),
                "quota": {
                    "start_date": q.get("start_date"),
                    "frequency": q.get("frequency"),
                    "period_started": q.get("period_started"),
                    "last_reset_at": q.get("last_reset_at"),
                },
            }

    def set_limits(self, limits):
        with self.lock:
            for k in APIS:
                try:
                    self._data["limits"][k] = max(0, int(limits.get(k, self._data["limits"].get(k, 1000))))
                except (TypeError, ValueError):
                    pass
            self._save()

    def set_period_usage(self, usage):
        """Manually set consumed requests for the current quota period.

        This is intentionally separate from historical daily/total counters: the
        setting represents the current provider quota period and can be corrected
        when the provider dashboard shows a different starting value.
        """
        with self.lock:
            self.maybe_reset(save=False)
            q = self._data["quota"]
            for k in APIS:
                try:
                    q["usage"][k] = max(0, int(usage.get(k, q["usage"].get(k, 0))))
                except (TypeError, ValueError):
                    pass
            self._save()

    def set_last_run(self, counts):
        with self.lock:
            self._data["last_run"] = {k: int(counts.get(k, 0)) for k in APIS}
            self._save()

    def remaining_today(self, api):
        s = self.snapshot()
        return max(0, s["limits"].get(api, 0) - s["period_usage"].get(api, 0))

    def remaining_current_period(self, api):
        return self.remaining_today(api)

    def forecast_per_day(self, last_search_count, interval_hours):
        if not interval_hours:
            return 0
        return int(round(last_search_count * (24 / interval_hours)))
