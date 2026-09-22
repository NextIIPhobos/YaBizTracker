from __future__ import annotations
import copy
import json, os
from datetime import datetime
from zoneinfo import ZoneInfo

from ..domain.filters import normalize_category
SETTINGS_SCHEMA_VERSION = 3

DEFAULTS={"period_days":30,"schedule_hours":6,"api_limits":{"js":1000,"geocoder":1000,"search":1000},
          "api_quota":{"start_date":None,"reset_frequency":"daily"},
          "cities":[],"categories":[],"excluded_categories":[],"profiles":{},"initial_scan_completed":False,
          "email_finder":{"enabled":True,"workers":8,"max_pages":5,"timeout_seconds":12,"max_response_bytes":2097152,"recheck_days":30,"respect_robots":True},
          "backup":{"enabled":True,"retention":14,"path":"backups"},"visible_organization_columns":None,"settings_schema_version":SETTINGS_SCHEMA_VERSION}
def load_json(path, default=None):
    fallback = {} if default is None else copy.deepcopy(default)
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else fallback
    except FileNotFoundError:
        return fallback
    except (OSError, json.JSONDecodeError):
        return fallback


def save_json(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _normalise_category_list(values):
    result=[]
    seen=set()
    for value in values if isinstance(values, list) else []:
        text=str(value or "").strip()
        key=normalize_category(text)
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def migrate_settings(s):
    s=dict(s or {})
    for k,v in DEFAULTS.items():s.setdefault(k,v.copy() if isinstance(v,dict) else list(v) if isinstance(v,list) else v)
    if not s["cities"] and isinstance(s.get("city"),dict):
        s["cities"]=[s["city"]]
    s["categories"] = _normalise_category_list(s.get("categories", []))
    s["excluded_categories"] = _normalise_category_list(s.get("excluded_categories", []))
    included = {normalize_category(value) for value in s["categories"]}
    s["excluded_categories"] = [value for value in s["excluded_categories"] if normalize_category(value) not in included]
    if not s["api_limits"] or not isinstance(s["api_limits"],dict):s["api_limits"]=dict(DEFAULTS["api_limits"])
    for key, default in DEFAULTS["api_limits"].items():
        try:s["api_limits"][key]=max(0,int(s["api_limits"].get(key,default)))
        except (TypeError,ValueError):s["api_limits"][key]=default
    try:s["period_days"] = int(s.get("period_days",30))
    except (TypeError,ValueError):s["period_days"] = 30
    if s["period_days"] not in (7,14,30,60,90):s["period_days"] = 30
    try:s["schedule_hours"] = int(s.get("schedule_hours",6))
    except (TypeError,ValueError):s["schedule_hours"] = 6
    if s["schedule_hours"] not in (1,3,6,12,24):s["schedule_hours"] = 6
    s["initial_scan_completed"] = bool(s.get("initial_scan_completed", False))
    ef = s.get("email_finder") if isinstance(s.get("email_finder"), dict) else {}
    s["email_finder"] = dict(DEFAULTS["email_finder"])
    s["email_finder"].update(ef)
    s["email_finder"]["enabled"] = bool(s["email_finder"].get("enabled", True))
    for key, low, high, default in (("workers",1,32,8),("max_pages",1,20,5),("recheck_days",1,365,30)):
        try: value=int(s["email_finder"].get(key,default))
        except (TypeError,ValueError): value=default
        s["email_finder"][key]=max(low,min(high,value))
    try: value=float(s["email_finder"].get("timeout_seconds",12))
    except (TypeError,ValueError): value=12
    s["email_finder"]["timeout_seconds"]=max(3,min(60,value))
    try: value=int(s["email_finder"].get("max_response_bytes",2097152))
    except (TypeError,ValueError): value=2097152
    s["email_finder"]["max_response_bytes"]=max(65536,min(10*1024*1024,value))
    s["email_finder"]["respect_robots"]=bool(s["email_finder"].get("respect_robots",True))
    if not isinstance(s.get("api_quota"), dict): s["api_quota"]={}
    s["settings_schema_version"] = SETTINGS_SCHEMA_VERSION
    if not isinstance(s.get("backup"), dict): s["backup"]={}
    s["backup"].setdefault("enabled", True)
    try:s["backup"]["retention"]=max(1,min(365,int(s["backup"].get("retention",14))))
    except (TypeError,ValueError):s["backup"]["retention"]=14
    if not str(s["backup"].get("path") or "").strip():s["backup"]["path"]="backups"
    # ``None`` means that this is an older configuration and all columns must
    # be shown.  An empty list is a valid explicit user choice.
    if s.get("visible_organization_columns") is not None:
        if not isinstance(s["visible_organization_columns"], list):
            s["visible_organization_columns"] = None
        else:
            s["visible_organization_columns"] = [
                str(value).strip() for value in s["visible_organization_columns"]
                if str(value).strip()
            ]
    # The first launch date is stored once and becomes the default quota anchor.
    if not s["api_quota"].get("start_date"):
        s["api_quota"]["start_date"]=datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    if s["api_quota"].get("reset_frequency") not in ("daily","weekly","monthly","yearly"):
        s["api_quota"]["reset_frequency"]="daily"
    # Keep legacy fields for compatibility with older external tooling.
    if s["cities"]:
        s["city"]=s["cities"][0];s["city_name"]=s["cities"][0].get("name","")
    return s
