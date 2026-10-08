import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class Providers(Model):
    birdweather: Provider = Field(default_factory=Provider)
    open_meteo: Provider = Field(default_factory=Provider)
    ebird: Provider = Field(default_factory=lambda: Provider(enabled=False))


class Site(Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    timezone: str = "America/Denver"
    weather_location: Location
    birdweather_bounds: Bounds
    bird_lookback_hours: int = Field(default=24, ge=1, le=168)
    prepare_local_time: str = "02:30"
    providers: Providers = Field(default_factory=Providers)

    @model_validator(mode="after")
    def validate_site(self):
        ZoneInfo(self.timezone)
        valid_time(self.prepare_local_time)
        if self.providers.ebird.enabled:
            raise ValueError("The optional eBird adapter is not implemented in this release")
        return self


class Panel(Model):
    width: Literal[800] = 800
    height: Literal[480] = 480
    orientation: Literal["landscape"] = "landscape"
    palette: Literal["spectra6"] = "spectra6"
    format: Literal["epdgz"] = "epdgz"


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
    processing_preset: Literal["balanced", "dynamic", "vivid", "soft"] = "balanced"
    dither_algorithm: Literal["floyd-steinberg", "stucki", "burkes", "sierra"] = "stucki"

    @model_validator(mode="after")
    def schedule_matches(self):
        if self.firmware_rotate_cron != cron_for(self.wake_local_time):
            raise ValueError("Wake time and firmware cron disagree")
        return self


class Render(Model):
    concurrency: Literal[1] = 1
    timeout_seconds: int = Field(default=90, ge=5, le=180)
    initial_converter_version: Literal["0.1.21"] = "0.1.21"


class Generation(Model):
    enabled: Literal[False] = False


class Config(Model):
    schema_version: Literal[1] = 1
    public_base_url: Literal["https://eink.majjix.com"] = "https://eink.majjix.com"
    sites: list[Site] = Field(min_length=1)
    frame_defaults: FramePolicy = Field(default_factory=FramePolicy)
    render: Render = Field(default_factory=Render)
    online_image_generation: Generation = Field(default_factory=Generation)

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
            config_path or os.getenv("EINK_CONFIG", "deployment/site.example.json")
        )
        self.data_dir = Path(data_dir or os.getenv("EINK_DATA_DIR", ".state")).resolve()
        self.art_dir = Path(art_dir or os.getenv("EINK_ART_DIR", "art")).resolve()
        self.backup_dir = Path(
            backup_dir or os.getenv("EINK_BACKUP_DIR", str(self.data_dir / "backups"))
        ).resolve()
        self.config = Config.model_validate_json(self.config_path.read_text())
        for path in (self.data_dir, self.data_dir / "cache", self.backup_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "einkartifact.sqlite3"
        self.catalog = json.loads((self.art_dir / "catalog.json").read_text())
        if self.catalog.get("license") != "CC-BY-SA-4.0":
            raise ValueError("Curated catalog must declare its artwork license")
        self.artworks = self.catalog["artworks"]
        if not self.artworks or len({a["id"] for a in self.artworks}) != len(self.artworks):
            raise ValueError("The artwork catalog must have unique entries")
        for artwork in self.artworks:
            if not artwork.get("approved") or not artwork.get("source_url"):
                raise ValueError("Every catalog entry needs approval and source attribution")
            asset = (self.art_dir / artwork["asset"]).resolve()
            if not asset.is_relative_to(self.art_dir) or not asset.is_file():
                raise ValueError("Artwork path must resolve to a file within the art directory")
            if hashlib.sha256(asset.read_bytes()).hexdigest() != artwork.get("asset_sha256"):
                raise ValueError("Artwork does not match its curated source hash")
