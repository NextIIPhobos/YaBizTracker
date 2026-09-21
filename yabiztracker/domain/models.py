from __future__ import annotations
from dataclasses import dataclass, field, asdict

STATUS_OPTIONS = ("Новый", "В работе", "Связались", "Не дозвонились", "Клиент", "Неинтересно")

@dataclass
class City:
    name: str
    description: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    bbox: str = ""
    uri: str = ""

@dataclass
class Organization:
    id: str
    name: str
    address: str = ""
    category: str = ""
    subcategory: str = ""
    phone: str = ""
    website: str = ""
    email: str = ""
    social_links: str = "{}"
    latitude: float = 0.0
    longitude: float = 0.0
    city_name: str = ""
    first_seen_date: str = ""
    last_updated: str = ""
    status: str = "Новый"
    comment: str = ""
    responsible: str = ""
    next_contact_date: str = ""
    score: int = 0
    age_days: int = 0

    def to_dict(self):
        d = asdict(self)
        d["org_id"] = d.pop("id")
        return d

@dataclass
class ScanStats:
    started_at: str = ""
    finished_at: str = ""
    cities: int = 0
    categories: int = 0
    pages: int = 0
    total_api_results: int = 0
    unique_found: int = 0
    new_count: int = 0
    duplicates: int = 0
    ignored: int = 0
    errors: int = 0
    failed_pages: list[str] = field(default_factory=list)
    categories_failed: list[str] = field(default_factory=list)
    search_requests: int = 0
    geocoder_requests: int = 0
    cancelled: bool = False
    city_stats: dict = field(default_factory=dict)

    @property
    def warnings(self):
        return len(self.failed_pages) + len(self.categories_failed)
