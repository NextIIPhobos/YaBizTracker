from __future__ import annotations
import sqlite3, threading, json, os
from datetime import datetime, timedelta
from typing import Iterable

from ..domain.models import STATUS_OPTIONS
from ..domain.filters import excluded_category_match, organization_categories, normalize_category
from ..domain.email import merge_emails

SCHEMA_VERSION = 9

class Database:
    def __init__(self, db_path="organizations.db"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self):
        with self._lock:
            v = int(self.conn.execute("PRAGMA user_version").fetchone()[0])
            if v < 1:
                self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS organizations(
                  org_id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT,
                  category TEXT, subcategory TEXT, phone TEXT, website TEXT,
                  email TEXT, social_links TEXT, latitude REAL, longitude REAL,
                  first_seen_date TEXT NOT NULL, last_updated TEXT,
                  city_name TEXT DEFAULT '',
                  status TEXT DEFAULT 'Новый', comment TEXT DEFAULT '',
                  responsible TEXT DEFAULT '', next_contact_date TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS ignored_organizations(
                  org_id TEXT PRIMARY KEY, name TEXT, ignored_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS organization_history(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL,
                  changed_at TEXT NOT NULL, field TEXT NOT NULL,
                  old_value TEXT, new_value TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_org_city_seen ON organizations(city_name, first_seen_date);
                CREATE INDEX IF NOT EXISTS idx_hist_org_time ON organization_history(org_id, changed_at);
                """)
            if v < 2:
                # Legacy databases may have city_name absent.
                cols = {r[1] for r in self.conn.execute("PRAGMA table_info(organizations)")}
                if "city_name" not in cols:
                    self.conn.execute("ALTER TABLE organizations ADD COLUMN city_name TEXT DEFAULT ''")
                for col, typ in [
                    ("status","TEXT DEFAULT 'Новый'"), ("comment","TEXT DEFAULT ''"),
                    ("responsible","TEXT DEFAULT ''"), ("next_contact_date","TEXT DEFAULT ''")
                ]:
                    if col not in cols:
                        self.conn.execute(f"ALTER TABLE organizations ADD COLUMN {col} {typ}")
            if v < 3:
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_org_status ON organizations(status)")
            if v < 4:
                self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS scan_runs(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  signature TEXT NOT NULL, started_at TEXT NOT NULL,
                  finished_at TEXT, status TEXT NOT NULL DEFAULT 'running',
                  last_error TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_scan_runs_signature_time ON scan_runs(signature, started_at DESC);
                CREATE TABLE IF NOT EXISTS scan_checkpoints(
                  run_id INTEGER NOT NULL, city_name TEXT NOT NULL, category TEXT NOT NULL,
                  next_skip INTEGER NOT NULL DEFAULT 0, pages_completed INTEGER NOT NULL DEFAULT 0,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(run_id, city_name, category),
                  FOREIGN KEY(run_id) REFERENCES scan_runs(id) ON DELETE CASCADE
                );
                """)
            if v < 5:
                cols = {r[1] for r in self.conn.execute("PRAGMA table_info(organizations)")}
                for col, typ in [
                    ("last_seen_at", "TEXT DEFAULT ''"),
                    ("missing_scan_count", "INTEGER DEFAULT 0"),
                    ("source_status", "TEXT DEFAULT 'unknown'"),
                ]:
                    if col not in cols:
                        self.conn.execute(f"ALTER TABLE organizations ADD COLUMN {col} {typ}")
                self.conn.execute("UPDATE organizations SET last_seen_at=COALESCE(NULLIF(last_seen_at,''), last_updated, first_seen_date)")
                self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS deleted_organizations(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  org_id TEXT NOT NULL, name TEXT NOT NULL,
                  deleted_at TEXT NOT NULL, reason TEXT NOT NULL,
                  snapshot_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_deleted_org_id_time ON deleted_organizations(org_id, deleted_at DESC);
                CREATE INDEX IF NOT EXISTS idx_org_last_seen ON organizations(city_name, last_seen_at);
                """)
            if v < 6:
                cols = {r[1] for r in self.conn.execute("PRAGMA table_info(organizations)")}
                if "categories_json" not in cols:
                    self.conn.execute("ALTER TABLE organizations ADD COLUMN categories_json TEXT DEFAULT '[]'")
                rows = self.conn.execute("SELECT org_id, category, subcategory FROM organizations").fetchall()
                for row in rows:
                    values = [x for x in (row[1], row[2]) if str(x or "").strip()]
                    self.conn.execute("UPDATE organizations SET categories_json=? WHERE org_id=?",
                                      (json.dumps(values, ensure_ascii=False), row[0]))
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_org_source_status ON organizations(source_status)")
            if v < 8:
                cols = {r[1] for r in self.conn.execute("PRAGMA table_info(organizations)")}
                for col, typ in [
                    ("email_scan_status", "TEXT DEFAULT 'not_scanned'"),
                    ("email_scanned_at", "TEXT DEFAULT ''"),
                    ("email_scan_error", "TEXT DEFAULT ''"),
                    ("email_scan_pages", "INTEGER DEFAULT 0"),
                ]:
                    if col not in cols:
                        self.conn.execute(f"ALTER TABLE organizations ADD COLUMN {col} {typ}")
                self.conn.execute("CREATE INDEX IF NOT EXISTS idx_org_email_scan_status ON organizations(email_scan_status)")

            if v < 9:
                # Clean e-mail values produced by older crawler versions. Those
                # versions searched raw HTML and could persist URL/asset fragments
                # such as /image@2x.png or /policy/info@example.ru. Keep only
                # normalized, syntactically valid e-mail addresses.
                rows = self.conn.execute("SELECT org_id, email FROM organizations WHERE TRIM(COALESCE(email,'')) <> ''").fetchall()
                for row in rows:
                    cleaned = merge_emails(row[1])
                    if cleaned != str(row[1] or ''):
                        self.conn.execute("UPDATE organizations SET email=? WHERE org_id=?", (cleaned, row[0]))

            if v < 7:
                # Liveness is tracked per search category, not globally per organization.
                # An organization can belong to multiple categories; a global miss counter
                # could otherwise delete a lead that was found by another category query.
                self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS organization_category_observations(
                  org_id TEXT NOT NULL,
                  city_name TEXT NOT NULL,
                  search_category TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  missing_scan_count INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY(org_id, city_name, search_category),
                  FOREIGN KEY(org_id) REFERENCES organizations(org_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_org_cat_obs_lookup
                  ON organization_category_observations(city_name, search_category, org_id);
                """)
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.conn.commit()

    @staticmethod
    def _age(first_seen):
        try: return max(0, (datetime.now() - datetime.fromisoformat(first_seen)).days)
        except Exception: return 0

    @staticmethod
    def _score(row):
        score = 0
        if row.get("phone"): score += 10
        if row.get("email"): score += 10
        if row.get("website"): score += 10
        social = str(row.get("social_links") or "").lower()
        if "vk.com" in social: score += 5
        if "t.me" in social or "telegram" in social: score += 5
        age = int(row.get("age_days",0))
        if age <= 7: score += 10
        return score

    @classmethod
    def _row(cls, r):
        if not r: return None
        d = dict(r)
        d["id"] = d.pop("org_id")
        d["age_days"] = cls._age(d.get("first_seen_date",""))
        d["score"] = cls._score(d)
        return d

    @staticmethod
    def _categories_json(organization: dict) -> str:
        """Serialize categories deterministically to avoid false change history."""
        raw = organization.get("categories")
        if not isinstance(raw, (list, tuple, set)):
            raw = [organization.get("category"), organization.get("subcategory")]
        categories = []
        seen = set()
        for value in raw:
            text = str(value or "").strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                categories.append(text)
        categories.sort(key=str.casefold)
        return json.dumps(categories, ensure_ascii=False)

    def upsert_organizations(self, organizations: Iterable[dict], city_name: str, search_category: str | None = None):
        """One transaction per scan batch. Returns (new, updated, ignored, duplicates)."""
        now = datetime.now().isoformat(timespec="seconds")
        new_count = updated_count = ignored = duplicates = 0
        new_items = []
        observed_ids = set()
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("BEGIN")
            try:
                for o in organizations:
                    oid = str(o.get("id","")).strip()
                    if not oid: continue
                    if cur.execute("SELECT 1 FROM ignored_organizations WHERE org_id=?", (oid,)).fetchone():
                        ignored += 1; continue
                    existing = cur.execute("SELECT * FROM organizations WHERE org_id=?", (oid,)).fetchone()
                    if not existing:
                        observed_ids.add(oid)
                        cur.execute("""INSERT INTO organizations
                        (org_id,name,address,category,subcategory,phone,website,email,social_links,
                         latitude,longitude,first_seen_date,last_updated,city_name,status,comment,responsible,next_contact_date,
                         last_seen_at,missing_scan_count,source_status,categories_json,email_scan_status,email_scanned_at,email_scan_error,email_scan_pages)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                            oid,o.get("name",""),o.get("address",""),o.get("category",""),o.get("subcategory",""),
                            o.get("phone",""),o.get("website",""),o.get("email",""),o.get("social_links","{}"),
                            o.get("latitude",0),o.get("longitude",0),now,now,o.get("city_name") or city_name,"Новый","","","",
                            now,0,o.get("source_status") or "unknown",self._categories_json(o),
                            "found" if str(o.get("email") or "").strip() else ("no_website" if not str(o.get("website") or "").strip() else "not_scanned"), "", "", 0))
                        new_count += 1; new_items.append(o)
                    else:
                        observed_ids.add(oid)
                        # Preserve CRM fields; refresh Yandex fields and record actual changes.
                        fields = ["name","address","category","subcategory","phone","website","social_links","latitude","longitude","city_name","source_status","categories_json"]
                        changes = []
                        for f in fields:
                            old = existing[f]
                            if f == "categories_json":
                                new = self._categories_json(o)
                            else:
                                new = o.get(f, old)
                            if new is None: new = old
                            try:
                                same = abs(float(old) - float(new)) < 1e-9 if f in ("latitude","longitude") else str(old or "") == str(new or "")
                            except (TypeError, ValueError):
                                same = str(old or "") == str(new or "")
                            if not same:
                                changes.append((f, str(old or ""), str(new or "")))
                        merged_email = merge_emails(existing["email"], o.get("email", ""))
                        if merged_email != str(existing["email"] or ""):
                            changes.append(("email", str(existing["email"] or ""), merged_email))
                        # Every successful observation is a positive liveness signal.
                        vals = []
                        for f in fields:
                            if f == "categories_json":
                                vals.append(self._categories_json(o))
                            else:
                                vals.append(o.get(f, existing[f]) if o.get(f) is not None else existing[f])
                        if changes:
                            update_fields = fields + ["email"]
                            sets = ", ".join(f"{f}=?" for f in update_fields)
                            vals.append(merged_email)
                            vals += [now, now, oid]
                            cur.execute(f"UPDATE organizations SET {sets}, last_updated=?, last_seen_at=?, missing_scan_count=0 WHERE org_id=?", vals)
                            for f, old, new in changes:
                                cur.execute("INSERT INTO organization_history(org_id,changed_at,field,old_value,new_value) VALUES(?,?,?,?,?)",
                                            (oid,now,f,old,new))
                            updated_count += 1
                        else:
                            cur.execute("UPDATE organizations SET last_seen_at=?, missing_scan_count=0, source_status=? WHERE org_id=?",
                                        (now, o.get("source_status") or existing["source_status"] or "unknown", oid))
                            duplicates += 1
                if search_category:
                    observed_at = now
                    cur.executemany(
                        """INSERT INTO organization_category_observations
                           (org_id,city_name,search_category,last_seen_at,missing_scan_count)
                           VALUES(?,?,?,?,0)
                           ON CONFLICT(org_id,city_name,search_category) DO UPDATE SET
                             last_seen_at=excluded.last_seen_at, missing_scan_count=0""",
                        [(oid, city_name, str(search_category).strip(), observed_at) for oid in observed_ids],
                    )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return new_count, updated_count, ignored, duplicates, new_items

    def get_active_organizations(self, city_names, days=30, filters=None):
        if isinstance(city_names, str): city_names=[city_names]
        city_names=[x for x in city_names if x]
        if not city_names: return []
        filters=filters or {}
        cutoff=(datetime.now()-timedelta(days=int(days))).isoformat(timespec="seconds")
        placeholders=",".join("?" for _ in city_names)
        sql=f"SELECT * FROM organizations WHERE city_name IN ({placeholders}) AND first_seen_date>=?"
        params=list(city_names)+[cutoff]
        if filters.get("category"):
            sql += " AND category=?"; params.append(filters["category"])
        if filters.get("status"):
            sql += " AND status=?"; params.append(filters["status"])
        search=(filters.get("search") or "").strip()
        if search:
            sql += " AND (name LIKE ? OR address LIKE ?)"; q=f"%{search}%"; params += [q,q]
        sql += " ORDER BY first_seen_date DESC, name COLLATE NOCASE"
        with self._lock:
            return [self._row(r) for r in self.conn.execute(sql,params).fetchall()]

    def get_all_organizations(self, city_names=None):
        with self._lock:
            if city_names:
                ph=",".join("?" for _ in city_names)
                rows=self.conn.execute(f"SELECT * FROM organizations WHERE city_name IN ({ph}) ORDER BY first_seen_date DESC",list(city_names)).fetchall()
            else:
                rows=self.conn.execute("SELECT * FROM organizations ORDER BY first_seen_date DESC").fetchall()
            return [self._row(r) for r in rows]

    def get_by_id(self, oid):
        with self._lock: return self._row(self.conn.execute("SELECT * FROM organizations WHERE org_id=?", (oid,)).fetchone())

    def update_crm(self, oid, **fields):
        return self.update_crm_many([oid], **fields) == 1

    def update_crm_many(self, oids, **fields):
        """Массовое изменение CRM-полей одной транзакцией с записью истории."""
        allowed={"status","comment","responsible","next_contact_date"}
        data={k:v for k,v in fields.items() if k in allowed}
        if "status" in data and str(data["status"] or "") not in STATUS_OPTIONS:
            raise ValueError("Недопустимый статус. Выберите значение из списка.")
        ids=[str(x) for x in oids if x]
        if not data or not ids:return 0
        now=datetime.now().isoformat(timespec="seconds")
        changed=0
        with self._lock:
            cur=self.conn.cursor();cur.execute("BEGIN")
            try:
                for oid in ids:
                    row=cur.execute("SELECT * FROM organizations WHERE org_id=?",(oid,)).fetchone()
                    if not row:continue
                    changes=[]
                    for field,value in data.items():
                        old=str(row[field] or "")
                        new=str(value or "")
                        if old != new: changes.append((field,old,new))
                    if not changes:continue
                    cur.execute("UPDATE organizations SET "+",".join(f"{k}=?" for k in data)+", last_updated=? WHERE org_id=?",
                                list(data.values())+[now,oid])
                    for field,old,new in changes:
                        cur.execute("INSERT INTO organization_history(org_id,changed_at,field,old_value,new_value) VALUES(?,?,?,?,?)",
                                    (oid,now,field,old,new))
                    changed += 1
                self.conn.commit()
            except Exception:
                self.conn.rollback();raise
        return changed

    def move_matching_to_trash(self, excluded_categories, city_names=None):
        """Move organizations matching excluded categories to the trash atomically."""
        excluded = [str(x).strip() for x in (excluded_categories or []) if str(x).strip()]
        cities = [str(x).strip() for x in (city_names or []) if str(x).strip()]
        if not excluded:
            return 0

        with self._lock:
            cur = self.conn.cursor()
            cur.execute("BEGIN")
            moved = 0
            try:
                if cities:
                    placeholders = ",".join("?" for _ in cities)
                    rows = cur.execute(
                        f"SELECT * FROM organizations WHERE city_name IN ({placeholders})",
                        cities,
                    ).fetchall()
                else:
                    rows = cur.execute("SELECT * FROM organizations").fetchall()

                now = datetime.now().isoformat(timespec="seconds")
                for row in rows:
                    if not excluded_category_match(dict(row), excluded):
                        continue
                    snapshot = json.dumps(dict(row), ensure_ascii=False, default=str)
                    cur.execute(
                        "INSERT INTO deleted_organizations(org_id,name,deleted_at,reason,snapshot_json) VALUES(?,?,?,?,?)",
                        (row["org_id"], row["name"], now, "excluded_category", snapshot),
                    )
                    cur.execute("DELETE FROM organizations WHERE org_id=?", (row["org_id"],))
                    moved += 1
                self.conn.commit()
                return moved
            except Exception:
                self.conn.rollback()
                raise

    def move_to_trash(self, oids, reason="manual_exclude", permanently_ignore=True):
        """Move active organizations to the recoverable trash.

        Manual exclusions additionally remain in ignored_organizations so the next
        scan does not immediately re-import them. Restoring a trash item removes
        that exclusion marker and puts the full snapshot back into organizations.
        """
        oids=[str(x) for x in oids if x]
        now=datetime.now().isoformat(timespec="seconds")
        with self._lock:
            cur=self.conn.cursor(); cur.execute("BEGIN"); count=0
            try:
                for oid in oids:
                    row=cur.execute("SELECT * FROM organizations WHERE org_id=?", (oid,)).fetchone()
                    if not row: continue
                    snapshot=json.dumps(dict(row), ensure_ascii=False, default=str)
                    cur.execute("INSERT INTO deleted_organizations(org_id,name,deleted_at,reason,snapshot_json) VALUES(?,?,?,?,?)",
                                (oid,row["name"],now,reason,snapshot))
                    if permanently_ignore:
                        cur.execute("INSERT OR REPLACE INTO ignored_organizations VALUES(?,?,?)",(oid,row["name"],now))
                    cur.execute("DELETE FROM organizations WHERE org_id=?",(oid,)); count+=1
                self.conn.commit()
            except Exception:
                self.conn.rollback(); raise
        return count

    @staticmethod
    def _trash_snapshot(row):
        try: d=json.loads(row["snapshot_json"] or "{}")
        except (TypeError,ValueError): d={}
        if not isinstance(d,dict): d={}
        d["trash_id"]=int(row["id"])
        d["deleted_at"]=row["deleted_at"]
        d["reason"]=row["reason"]
        d["name"]=d.get("name") or row["name"]
        return d

    def get_email_scan_candidates(self, recheck_days=30):
        """Return websites that should be scanned, without loading the whole DB into memory."""
        cutoff = (datetime.now() - timedelta(days=max(0, int(recheck_days)))).isoformat(timespec="seconds")
        sql = """SELECT org_id, name, website, email, email_scan_status, email_scanned_at
                 FROM organizations
                 WHERE TRIM(COALESCE(website,'')) <> ''
                   AND (COALESCE(email_scan_status,'not_scanned') IN ('not_scanned','error','blocked')
                        OR COALESCE(email_scanned_at,'') = ''
                        OR email_scanned_at < ?)
                 ORDER BY first_seen_date DESC"""
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, (cutoff,)).fetchall()]

    def mark_email_scan_queued(self, org_ids):
        ids=[str(x) for x in org_ids if x]
        if not ids:return 0
        with self._lock:
            ph=",".join("?" for _ in ids)
            cur=self.conn.execute(f"UPDATE organizations SET email_scan_status='queued', email_scan_error='' WHERE org_id IN ({ph})",ids)
            self.conn.commit(); return cur.rowcount

    def update_organization_emails(self, org_id, discovered_emails, status, error="", pages=0):
        now=datetime.now().isoformat(timespec="seconds")
        with self._lock:
            cur=self.conn.cursor(); cur.execute("BEGIN")
            try:
                row=cur.execute("SELECT email FROM organizations WHERE org_id=?",(org_id,)).fetchone()
                if not row:
                    self.conn.rollback(); return False
                merged=merge_emails(row[0], discovered_emails)
                old=str(row[0] or "")
                if old != merged:
                    cur.execute("UPDATE organizations SET email=?, last_updated=?, email_scan_status=?, email_scanned_at=?, email_scan_error=?, email_scan_pages=? WHERE org_id=?",
                                (merged,now,status,now,error,pages,org_id))
                    cur.execute("INSERT INTO organization_history(org_id,changed_at,field,old_value,new_value) VALUES(?,?,?,?,?)",
                                (org_id,now,"email",old,merged))
                else:
                    cur.execute("UPDATE organizations SET email_scan_status=?, email_scanned_at=?, email_scan_error=?, email_scan_pages=? WHERE org_id=?",
                                (status,now,error,pages,org_id))
                self.conn.commit(); return True
            except Exception:
                self.conn.rollback(); raise

    def get_trash(self, filters=None):
        filters=filters or {}
        search=str(filters.get("search") or "").strip().casefold()
        category=str(filters.get("category") or "")
        status=str(filters.get("status") or "")
        with self._lock:
            rows=self.conn.execute("SELECT * FROM deleted_organizations ORDER BY deleted_at DESC, name COLLATE NOCASE").fetchall()
        result=[]
        for row in rows:
            d=self._trash_snapshot(row)
            cats=[]
            try: cats=json.loads(d.get("categories_json") or "[]")
            except (TypeError,ValueError): pass
            if not isinstance(cats,list): cats=[]
            cats=[str(x) for x in cats if x]
            if not cats:
                cats=[x for x in (d.get("category"),d.get("subcategory")) if x]
            if search and search not in str(d.get("name") or "").casefold() and search not in str(d.get("address") or "").casefold(): continue
            if category and normalize_category(category) not in organization_categories(d): continue
            if status and str(d.get("status") or "") != status: continue
            checks=(("has_phone","phone"),("has_email","email"),("has_website","website"),("has_social","social_links"))
            if any(filters.get(flag) and not str(d.get(field) or "").strip() for flag,field in checks): continue
            responsible=bool(str(d.get("responsible") or "").strip())
            if filters.get("responsible") and not responsible: continue
            if filters.get("no_responsible") and responsible: continue
            if filters.get("next_contact") and not str(d.get("next_contact_date") or "").strip(): continue
            result.append(d)
        return result

    def restore_from_trash(self, trash_ids):
        ids=[int(x) for x in trash_ids if str(x).isdigit()]
        restored=0; conflicts=[]
        with self._lock:
            cur=self.conn.cursor(); cur.execute("BEGIN")
            try:
                for tid in ids:
                    row=cur.execute("SELECT * FROM deleted_organizations WHERE id=?",(tid,)).fetchone()
                    if not row: continue
                    d=self._trash_snapshot(row); oid=str(d.get("org_id") or "").strip()
                    if not oid: continue
                    if cur.execute("SELECT 1 FROM organizations WHERE org_id=?",(oid,)).fetchone():
                        conflicts.append((tid,oid)); continue
                    cols=["org_id","name","address","category","subcategory","phone","website","email","social_links",
                          "latitude","longitude","first_seen_date","last_updated","city_name","status","comment","responsible",
                          "next_contact_date","last_seen_at","missing_scan_count","source_status","categories_json","email_scan_status","email_scanned_at","email_scan_error","email_scan_pages"]
                    defaults = {
                        "name": row["name"],
                        "status": "Новый",
                        "comment": "",
                        "responsible": "",
                        "next_contact_date": "",
                        "social_links": "{}",
                        "latitude": 0,
                        "longitude": 0,
                        "missing_scan_count": 0,
                        "source_status": "unknown",
                        "categories_json": "[]",
                        "email_scan_status": "not_scanned",
                        "email_scanned_at": "",
                        "email_scan_error": "",
                        "email_scan_pages": 0,
                    }
                    vals=[]
                    for col in cols:
                        val=d.get(col)
                        if col=="categories_json" and not val:
                            fallback=[x for x in (d.get("category"),d.get("subcategory")) if x]
                            val=json.dumps(fallback,ensure_ascii=False) if fallback else "[]"
                        if val is None:
                            val=defaults.get(col, "")
                        vals.append(val)
                    cur.execute(f"INSERT INTO organizations({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",vals)
                    cur.execute("DELETE FROM ignored_organizations WHERE org_id=?",(oid,))
                    cur.execute("DELETE FROM deleted_organizations WHERE id=?",(tid,)); restored+=1
                self.conn.commit()
            except Exception:
                self.conn.rollback(); raise
        return restored, conflicts

    def purge_trash(self, days=30):
        cutoff=(datetime.now()-timedelta(days=max(1,int(days)))).isoformat(timespec="seconds")
        with self._lock:
            cur=self.conn.cursor(); cur.execute("BEGIN")
            try:
                old=cur.execute(
                    "SELECT id,org_id,reason FROM deleted_organizations WHERE deleted_at<?",
                    (cutoff,),
                ).fetchall()
                org_ids={str(r[1]) for r in old}
                manual_ignored={str(r[1]) for r in old if str(r[2]) == "manual_exclude"}
                if old:
                    cur.execute("DELETE FROM deleted_organizations WHERE deleted_at<?",(cutoff,))
                    for oid in org_ids:
                        active=cur.execute("SELECT 1 FROM organizations WHERE org_id=?",(oid,)).fetchone()
                        trash=cur.execute("SELECT 1 FROM deleted_organizations WHERE org_id=?",(oid,)).fetchone()
                        if not active and not trash:
                            cur.execute("DELETE FROM organization_history WHERE org_id=?",(oid,))
                            if oid not in manual_ignored:
                                cur.execute("DELETE FROM ignored_organizations WHERE org_id=?",(oid,))
                self.conn.commit()
                return len(old)
            except Exception:
                self.conn.rollback(); raise

    def clear_trash(self):
        with self._lock:
            cur=self.conn.cursor(); cur.execute("BEGIN")
            try:
                rows=cur.execute("SELECT org_id,reason FROM deleted_organizations").fetchall()
                ids={str(r[0]) for r in rows}
                manual_ignored={str(r[0]) for r in rows if str(r[1]) == "manual_exclude"}
                cur.execute("DELETE FROM deleted_organizations")
                for oid in ids:
                    if not cur.execute("SELECT 1 FROM organizations WHERE org_id=?",(oid,)).fetchone():
                        cur.execute("DELETE FROM organization_history WHERE org_id=?",(oid,))
                        if oid not in manual_ignored:
                            cur.execute("DELETE FROM ignored_organizations WHERE org_id=?",(oid,))
                self.conn.commit(); return len(ids)
            except Exception:
                self.conn.rollback(); raise

    def ignore_organizations(self, oids):
        """Backward-compatible alias for moving organizations to the recoverable trash."""
        return self.move_to_trash(oids, reason="manual_exclude", permanently_ignore=True)

    def record_category_observations(self, org_ids, city_name: str, search_category: str, observed_at: str | None = None) -> int:
        """Persist successful observations for one city/category search page."""
        ids = {str(x).strip() for x in (org_ids or []) if str(x).strip()}
        city = str(city_name or "").strip()
        category = str(search_category or "").strip()
        if not ids or not city or not category:
            return 0
        seen_at = observed_at or datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self.conn.executemany(
                """INSERT INTO organization_category_observations
                   (org_id,city_name,search_category,last_seen_at,missing_scan_count)
                   VALUES(?,?,?,?,0)
                   ON CONFLICT(org_id,city_name,search_category) DO UPDATE SET
                     last_seen_at=excluded.last_seen_at, missing_scan_count=0""",
                [(oid, city, category, seen_at) for oid in ids],
            )
            self.conn.commit()
        return len(ids)

    def reconcile_category(self, city_name: str, category: str, seen_ids, *, scan_complete: bool, truncated: bool = False, threshold: int = 3):
        """Reconcile liveness independently for each city/search-category pair.

        Search APIs are ranked and may cap pagination. A lead is therefore archived only
        after a complete, non-truncated scan misses it for ``threshold`` consecutive runs.
        Liveness is stored separately from the organization because one organization may
        legitimately appear under several search categories.
        """
        if not scan_complete or truncated:
            return {"checked": 0, "candidates": 0, "deleted": 0}
        city = str(city_name or "").strip()
        search_category = str(category or "").strip()
        wanted_category = normalize_category(search_category)
        seen = {str(x) for x in (seen_ids or []) if x}
        threshold = max(1, int(threshold))
        now = datetime.now().isoformat(timespec="seconds")
        protected = {"В работе", "Связались", "Не дозвонились", "Клиент", "Неинтересно"}
        checked = candidates = deleted = 0
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("BEGIN")
            try:
                rows = cur.execute("SELECT * FROM organizations WHERE city_name=?", (city,)).fetchall()
                for row in rows:
                    if wanted_category not in organization_categories(dict(row)):
                        continue
                    checked += 1
                    oid = str(row["org_id"])
                    observation = cur.execute(
                        "SELECT missing_scan_count FROM organization_category_observations "
                        "WHERE org_id=? AND city_name=? AND search_category=?",
                        (oid, city, search_category),
                    ).fetchone()
                    if oid in seen:
                        if observation:
                            cur.execute(
                                "UPDATE organization_category_observations SET last_seen_at=?, missing_scan_count=0 "
                                "WHERE org_id=? AND city_name=? AND search_category=?",
                                (now, oid, city, search_category),
                            )
                        else:
                            cur.execute(
                                "INSERT INTO organization_category_observations "
                                "(org_id,city_name,search_category,last_seen_at,missing_scan_count) VALUES(?,?,?,?,0)",
                                (oid, city, search_category, now),
                            )
                        continue
                    if not observation:
                        # The current complete scan is the first consecutive miss.
                        # This preserves the historical three-scan contract while keeping
                        # the counter isolated per search category.
                        count = 1
                        cur.execute(
                            "INSERT INTO organization_category_observations "
                            "(org_id,city_name,search_category,last_seen_at,missing_scan_count) VALUES(?,?,?,?,?)",
                            (oid, city, search_category, row["last_seen_at"] or row["last_updated"] or now, count),
                        )
                        if count < threshold:
                            candidates += 1
                            continue
                        if str(row["status"] or "Новый") in protected:
                            continue
                        snapshot = json.dumps(dict(row), ensure_ascii=False, default=str)
                        cur.execute(
                            "INSERT INTO deleted_organizations(org_id,name,deleted_at,reason,snapshot_json) VALUES(?,?,?,?,?)",
                            (oid, row["name"], now, f"not_seen_in_{count}_complete_scans:{city}:{search_category}", snapshot),
                        )
                        cur.execute("DELETE FROM organizations WHERE org_id=?", (oid,))
                        deleted += 1
                        continue
                    count = int(observation[0] or 0) + 1
                    cur.execute(
                        "UPDATE organization_category_observations SET missing_scan_count=? WHERE org_id=? AND city_name=? AND search_category=?",
                        (count, oid, city, search_category),
                    )
                    if count < threshold:
                        candidates += 1
                        continue
                    if str(row["status"] or "Новый") in protected:
                        continue
                    snapshot = json.dumps(dict(row), ensure_ascii=False, default=str)
                    cur.execute(
                        "INSERT INTO deleted_organizations(org_id,name,deleted_at,reason,snapshot_json) VALUES(?,?,?,?,?)",
                        (oid, row["name"], now, f"not_seen_in_{count}_complete_scans:{city}:{search_category}", snapshot),
                    )
                    cur.execute("DELETE FROM organizations WHERE org_id=?", (oid,))
                    deleted += 1
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return {"checked": checked, "candidates": candidates, "deleted": deleted}

    def archive_deleted(self, oid: str, reason: str) -> bool:
        """Move one organization out of the active table while keeping a recoverable snapshot."""
        oid = str(oid or "").strip()
        if not oid: return False
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            cur = self.conn.cursor(); cur.execute("BEGIN")
            try:
                row = cur.execute("SELECT * FROM organizations WHERE org_id=?", (oid,)).fetchone()
                if not row:
                    self.conn.rollback(); return False
                cur.execute("INSERT INTO deleted_organizations(org_id,name,deleted_at,reason,snapshot_json) VALUES(?,?,?,?,?)",
                            (oid, row["name"], now, reason, json.dumps(dict(row), ensure_ascii=False, default=str)))
                cur.execute("DELETE FROM organizations WHERE org_id=?", (oid,))
                self.conn.commit(); return True
            except Exception:
                self.conn.rollback(); raise

    def deleted_history(self, oid=None):
        with self._lock:
            if oid:
                rows = self.conn.execute("SELECT * FROM deleted_organizations WHERE org_id=? ORDER BY deleted_at DESC", (str(oid),)).fetchall()
            else:
                rows = self.conn.execute("SELECT * FROM deleted_organizations ORDER BY deleted_at DESC").fetchall()
            return [dict(r) for r in rows]

    def history(self, oid):
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT changed_at,field,old_value,new_value FROM organization_history WHERE org_id=? ORDER BY changed_at DESC",(oid,)).fetchall()]

    def dashboard(self, city_names):
        if isinstance(city_names,str): city_names=[city_names]
        ph=",".join("?" for _ in city_names); params=city_names
        with self._lock:
            rows=self.conn.execute(f"SELECT * FROM organizations WHERE city_name IN ({ph})",params).fetchall()
        now=datetime.now()
        result={"today":0,"7d":0,"30d":0,"phone":0,"email":0,"website":0,"social":0,"categories":[]}
        counts={}
        for r in rows:
            d=dict(r)
            try: age=max(0,(now-datetime.fromisoformat(d["first_seen_date"])).days)
            except Exception: age=99999
            if age==0: result["today"]+=1
            if age<=7: result["7d"]+=1
            if age<=30: result["30d"]+=1
            if d.get("phone"): result["phone"]+=1
            if d.get("email"): result["email"]+=1
            if d.get("website"): result["website"]+=1
            if d.get("social_links") and d["social_links"]!="{}": result["social"]+=1
            cat=d.get("category") or "Без категории"; counts[cat]=counts.get(cat,0)+1
        result["categories"]=sorted(counts.items(),key=lambda x:x[1],reverse=True)[:10]
        return result

    def integrity_check(self) -> tuple[bool, str]:
        with self._lock:
            try:
                row = self.conn.execute("PRAGMA quick_check").fetchone()
                result = str(row[0]) if row else ""
                return result.lower() == "ok", result
            except sqlite3.DatabaseError as exc:
                return False, str(exc)

    def backup_to(self, target_path: str) -> None:
        with self._lock:
            if self.conn is None:
                raise sqlite3.ProgrammingError("База данных уже закрыта")
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            dest = sqlite3.connect(target_path)
            try:
                self.conn.backup(dest, pages=100, sleep=0.05)
                dest.execute("PRAGMA foreign_keys=ON")
                dest.commit()
            finally:
                dest.close()

    def restore_from(self, source_path: str) -> None:
        with self._lock:
            if self.conn is None:
                raise sqlite3.ProgrammingError("База данных уже закрыта")
            source = sqlite3.connect(f"file:{os.path.abspath(source_path)}?mode=ro", uri=True, timeout=5)
            tmp = self.db_path + ".restore.tmp"
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
                dest = sqlite3.connect(tmp)
                try:
                    source.backup(dest, pages=100, sleep=0.05)
                    dest.commit()
                finally:
                    dest.close()
            finally:
                source.close()
            self.conn.close()
            self.conn = None
            for suffix in ("-wal", "-shm"):
                sidecar = self.db_path + suffix
                if os.path.exists(sidecar):
                    try: os.remove(sidecar)
                    except OSError: pass
            os.replace(tmp, self.db_path)
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA busy_timeout=10000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            # A restored backup may have an older supported schema. Re-run the
            # normal migration pipeline instead of assuming the backup is current.
            self._migrate()
            row = self.conn.execute("PRAGMA quick_check").fetchone()
            result = str(row[0]) if row else ""
            if result.lower() != "ok":
                raise sqlite3.DatabaseError(f"Восстановленная база не прошла quick_check: {result}")

    def start_or_resume_scan(self, signature: str, cities, categories):
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM scan_runs WHERE signature=? AND status IN ('running','failed','cancelled') ORDER BY started_at DESC LIMIT 1",
                (signature,),
            ).fetchone()
            if row:
                return int(row[0]), True
            cur = self.conn.execute(
                "INSERT INTO scan_runs(signature,started_at,status) VALUES(?,?,?)",
                (signature, now, "running"),
            )
            run_id = int(cur.lastrowid)
            for city in cities:
                for category in categories:
                    self.conn.execute(
                        "INSERT INTO scan_checkpoints(run_id,city_name,category,next_skip,pages_completed,updated_at) VALUES(?,?,?,?,?,?)",
                        (run_id, city.get("name", ""), category, 0, 0, now),
                    )
            self.conn.commit()
            return run_id, False

    def get_checkpoint(self, run_id: int, city_name: str, category: str) -> tuple[int, int]:
        with self._lock:
            row = self.conn.execute(
                "SELECT next_skip,pages_completed FROM scan_checkpoints WHERE run_id=? AND city_name=? AND category=?",
                (run_id, city_name, category),
            ).fetchone()
            return (int(row[0]), int(row[1])) if row else (0, 0)

    def save_checkpoint(self, run_id: int, city_name: str, category: str, next_skip: int, pages_completed: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE scan_checkpoints SET next_skip=?, pages_completed=?, updated_at=? WHERE run_id=? AND city_name=? AND category=?",
                (int(next_skip), int(pages_completed), datetime.now().isoformat(timespec="seconds"), run_id, city_name, category),
            )
            self.conn.commit()

    def finish_scan_run(self, run_id: int, status: str, error: str = "") -> None:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("Недопустимый статус scan run")
        with self._lock:
            self.conn.execute("UPDATE scan_runs SET status=?, finished_at=?, last_error=? WHERE id=?",
                              (status, datetime.now().isoformat(timespec="seconds"), error[:2000], run_id))
            self.conn.commit()

    def latest_scan_run(self, signature: str | None = None):
        with self._lock:
            if signature:
                row = self.conn.execute("SELECT * FROM scan_runs WHERE signature=? ORDER BY started_at DESC LIMIT 1", (signature,)).fetchone()
            else:
                row = self.conn.execute("SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def close(self):
        with self._lock:
            if self.conn: self.conn.close(); self.conn=None
