import hashlib
import json
import math
import os
import re
from datetime import date
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

ART_LICENSES = {"CC-BY-SA-4.0", "CC-BY-NC-SA-4.0", "MIT", "Public-Domain"}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def valid_time(value: str) -> str:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("Time must be HH:MM in local time")
    return value


def cron_for(value: str) -> list[str]:
    hour, minute = map(int, valid_time(value).split(":"))
    return [f"{minute} {hour} *"]


class Location(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Bounds(Model):
    southwest: Location
    northeast: Location

    @model_validator(mode="after")
    def ordered(self):
        if self.southwest.latitude >= self.northeast.latitude:
            raise ValueError("Southwest latitude must precede northeast latitude")
        if self.southwest.longitude >= self.northeast.longitude:
            raise ValueError("Southwest longitude must precede northeast longitude")
        return self


class Provider(Model):
    enabled: bool = True


class EBirdProvider(Provider):
    lookback_days: int = Field(default=7, ge=1, le=30)
    max_results: int = Field(default=100, ge=1, le=200)


class Providers(Model):
    birdweather: Provider = Field(default_factory=Provider)
    open_meteo: Provider = Field(default_factory=Provider)
    ebird: EBirdProvider = Field(default_factory=lambda: EBirdProvider(enabled=False))


class Site(Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    timezone: str = "America/Denver"
    weather_location: Location
    birdweather_bounds: Bounds | None = None  # Legacy configurations remain readable.
    bird_area: Literal["local", "colorado"] = "local"
    locality_radius_km: int = Field(default=25, ge=1, le=50)
    bird_lookback_hours: int = Field(default=24, ge=1, le=168)
    prepare_local_time: str = "02:30"
    providers: Providers = Field(default_factory=Providers)

    @model_validator(mode="after")
    def validate_site(self):
        ZoneInfo(self.timezone)
        valid_time(self.prepare_local_time)
        if abs(self.weather_location.latitude) > 85:
            raise ValueError("This locality query does not support polar regions")
        return self

    @property
    def locality_bounds(self):
        if self.bird_area == "colorado":
            return Bounds(
                southwest=Location(latitude=37, longitude=-109.0603),
                northeast=Location(latitude=41.0007, longitude=-102.0415),
            )
        center = self.weather_location
        latitude_delta = self.locality_radius_km / 111.195
        longitude_delta = latitude_delta / math.cos(math.radians(center.latitude))
        return Bounds(
            southwest=Location(
                latitude=center.latitude - latitude_delta,
                longitude=center.longitude - longitude_delta,
            ),
            northeast=Location(
                latitude=center.latitude + latitude_delta,
                longitude=center.longitude + longitude_delta,
            ),
        )


class Panel(Model):
    width: Literal[800] = 800
    height: Literal[480] = 480
    orientation: Literal["landscape"] = "landscape"
    palette: Literal["spectra6"] = "spectra6"
    format: Literal["epdgz"] = "epdgz"


class SpecialDay(Model):
    id: str = Field(pattern=r"^[a-z0-9-]{1,48}$")
    date: str
    label: str = Field(min_length=1, max_length=40)
    message: str = Field(default="", max_length=80)
    annual: bool = True
    enabled: bool = True
    theme: Literal["birthday", "anniversary", "celebration", "remembrance"] = "celebration"
    artwork_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_day(self):
        if date.fromisoformat(self.date).isoformat() != self.date:
            raise ValueError("Special-day date must be YYYY-MM-DD")
        for text in (self.label, self.message):
            if any(ord(c) < 32 for c in text):
                raise ValueError("Greetings must be plain single-line text")
        if not self.label.strip():
            raise ValueError("Special day needs a name")
        return self


class FramePolicy(Model):
    site_id: str = "denver-gift"
    wake_local_time: str = "03:15"
    firmware_timezone: Literal["MST7MDT,M3.2.0,M11.1.0"] = "MST7MDT,M3.2.0,M11.1.0"
    firmware_rotate_cron: list[str] = Field(default_factory=lambda: ["15 3 *"])
    panel: Panel = Field(default_factory=Panel)
    art_mode: Literal["approved_library"] = "approved_library"
    repeat_penalty_days: int = Field(default=7, ge=0, le=90)
    show_species_name: bool = True
    show_dated_weather_text: bool = False
    weather_cues: bool = True
    max_birds: Literal[1, 2, 3] = 3
    special_days: list[SpecialDay] = Field(default_factory=list, max_length=32)
    allowed_species: list[str] = Field(default_factory=list, max_length=64)
    seasonal_themes: bool = True
    processing_preset: Literal["balanced", "dynamic", "vivid", "soft"] = "balanced"
    dither_algorithm: Literal["floyd-steinberg", "stucki", "burkes", "sierra"] = "stucki"

    @model_validator(mode="after")
    def schedule_matches(self):
        if self.firmware_rotate_cron != cron_for(self.wake_local_time):
            raise ValueError("Wake time and firmware cron disagree")
        if len({d.id for d in self.special_days}) != len(self.special_days):
            raise ValueError("Special-day entries must have unique identifiers")
        return self


class Render(Model):
    concurrency: Literal[1] = 1
    timeout_seconds: int = Field(default=90, ge=5, le=180)
    initial_converter_version: Literal["0.1.21"] = "0.1.21"


class Generation(Model):
    enabled: Literal[False] = False


class Config(Model):
    schema_version: Literal[1] = 1
    public_base_url: Literal["https://emviary.majjix.com"] = "https://emviary.majjix.com"
    sites: list[Site] = Field(min_length=1)
    frame_defaults: FramePolicy = Field(default_factory=FramePolicy)
    render: Render = Field(default_factory=Render)
    online_image_generation: Generation = Field(default_factory=Generation)
    public_frame_id: str | None = Field(default="gift-e1002", pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")

    @model_validator(mode="after")
    def unique_sites(self):
        ids = [s.id for s in self.sites]
        if len(ids) != len(set(ids)) or self.frame_defaults.site_id not in ids:
            raise ValueError("Sites must be unique and include the default frame site")
        if any(s.timezone != "America/Denver" for s in self.sites):
            raise ValueError("This POC implements Denver firmware timezone rules")
        return self

    def site(self, site_id: str) -> Site:
        for site in self.sites:
            if site.id == site_id:
                return site
        raise ValueError(f"Unknown site: {site_id}")


class Settings:
    def __init__(self, config_path=None, data_dir=None, art_dir=None, backup_dir=None):
        self.config_path = Path(
            config_path or os.getenv("EMVIARY_CONFIG", "deployment/site.example.json")
        )
        self.data_dir = Path(data_dir or os.getenv("EMVIARY_DATA_DIR", ".state")).resolve()
        self.art_dir = Path(art_dir or os.getenv("EMVIARY_ART_DIR", "art")).resolve()
        self.backup_dir = Path(
            backup_dir or os.getenv("EMVIARY_BACKUP_DIR", str(self.data_dir / "backups"))
        ).resolve()
        self.config = Config.model_validate_json(self.config_path.read_text())
        for path in (self.data_dir, self.data_dir / "cache", self.backup_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "emviary.sqlite3"
        self.catalog = json.loads((self.art_dir / "catalog.json").read_text())
        if self.catalog.get("license") not in ART_LICENSES | {"mixed"}:
            raise ValueError("Curated catalog must declare its artwork licenses")
        self.artworks = self.catalog["artworks"]
        if not self.artworks or len({a["id"] for a in self.artworks}) != len(self.artworks):
            raise ValueError("The artwork catalog must have unique entries")
        for artwork in self.artworks:
            if not isinstance(artwork.get("approved"), bool) or not artwork.get("source_url"):
                raise ValueError("Every catalog entry needs a review decision and attribution")
            if artwork.get("license") not in ART_LICENSES:
                raise ValueError("Artwork must have a supported, explicit license")
            if artwork.get("kind", "cutout") not in {"cutout", "plate", "field_study"}:
                raise ValueError("Unsupported artwork layout")
            if artwork.get("kind") == "field_study" and artwork["approved"]:
                raise ValueError("Field-study plates are reference only on this panel")
            bird_count = artwork.get("depicted_birds", 1)
            if type(bird_count) is not int or bird_count not in (1, 2, 3):
                raise ValueError("Artwork may depict at most three birds")
            months = artwork.get("months", [])
            if not months or any(type(m) is not int or not 1 <= m <= 12 for m in months):
                raise ValueError("Artwork needs valid seasonal eligibility")
            asset = (self.art_dir / artwork["asset"]).resolve()
            if not asset.is_relative_to(self.art_dir) or not asset.is_file():
                raise ValueError("Artwork path must resolve to a file within the art directory")
            if hashlib.sha256(asset.read_bytes()).hexdigest() != artwork.get("asset_sha256"):
                raise ValueError("Artwork does not match its curated source hash")
            if artwork.get("license_file"):
                notice = (self.art_dir / artwork["license_file"]).resolve()
                if not notice.is_relative_to(self.art_dir / "licenses") or not notice.is_file():
                    raise ValueError("Artwork license notice is missing or outside the library")
