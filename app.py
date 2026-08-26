from __future__ import annotations

import argparse
import asyncio
import json
import math
import mimetypes
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SETTINGS_PATH = APP_DIR / "settings.json"
SESSIONS_DIR = APP_DIR / "data" / "sessions"

HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

HEART_ZONE_DEFS = [
    {
        "label": "Dinlenme",
        "subtitle": "Rahat ritim",
        "range": "<50%",
        "level": 1,
        "min_pct": 0.0,
        "max_pct": 50.0,
        "color": "#7ddaff",
        "soft": "rgba(125, 218, 255, 0.24)",
    },
    {
        "label": "Isınma",
        "subtitle": "Tempo başlıyor",
        "range": "50-60%",
        "level": 2,
        "min_pct": 50.0,
        "max_pct": 60.0,
        "color": "#5eead4",
        "soft": "rgba(94, 234, 212, 0.24)",
    },
    {
        "label": "Yağ Yakımı",
        "subtitle": "Uzun tempo",
        "range": "60-70%",
        "level": 3,
        "min_pct": 60.0,
        "max_pct": 70.0,
        "color": "#f4d35e",
        "soft": "rgba(244, 211, 94, 0.28)",
    },
    {
        "label": "Aerobik",
        "subtitle": "Aerobik tempo",
        "range": "70-80%",
        "level": 4,
        "min_pct": 70.0,
        "max_pct": 80.0,
        "color": "#f59e42",
        "soft": "rgba(245, 158, 66, 0.28)",
    },
    {
        "label": "Anaerobik",
        "subtitle": "Yüksek güç",
        "range": "80-90%",
        "level": 5,
        "min_pct": 80.0,
        "max_pct": 90.0,
        "color": "#e85d04",
        "soft": "rgba(232, 93, 4, 0.3)",
    },
    {
        "label": "Maksimum",
        "subtitle": "Limit bölgesi",
        "range": "90%+",
        "level": 6,
        "min_pct": 90.0,
        "max_pct": 120.0,
        "color": "#8b0000",
        "soft": "rgba(139, 0, 0, 0.32)",
    },
]

WAITING_ZONE = {
    "label": "Bekleniyor",
    "subtitle": "Nabız aranıyor",
    "range": "",
    "pct": 0,
    "level": 0,
    "color": "#7ddaff",
    "soft": "rgba(125, 218, 255, 0.22)",
}


@dataclass
class Settings:
    display_name: str = "Canli Nabiz"
    height_cm: float = 175.0
    weight_kg: float = 75.0
    age: int = 30
    sex: str = "male"
    device_address: str = ""
    device_name: str = ""


@dataclass
class RuntimeState:
    bpm: int | None = None
    sensor_contact: bool | None = None
    rr_ms: list[float] = field(default_factory=list)
    calories: float = 0.0
    kcal_per_hour: float = 0.0
    session_started_at: float = field(default_factory=time.monotonic)
    stopped_elapsed_seconds: float = 0.0
    last_integrated_at: float = field(default_factory=time.monotonic)
    bpm_updated_at: float = 0.0
    connected: bool = False
    connecting: bool = False
    demo: bool = False
    device_name: str = ""
    device_address: str = ""
    status: str = "Hazir"
    error: str = ""


def _coerce_float(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(round(_coerce_float(value, float(default))))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def sanitize_settings(data: dict[str, Any], current: Settings | None = None) -> Settings:
    base = asdict(current or Settings())
    for key in base:
        if key in data:
            base[key] = data[key]

    display_name = str(base.get("display_name") or "Canli Nabiz").strip()[:40]
    if not display_name:
        display_name = "Canli Nabiz"

    sex = str(base.get("sex") or "male").lower()
    sex = "female" if sex.startswith("f") or sex.startswith("k") else "male"

    return Settings(
        display_name=display_name,
        height_cm=round(_clamp(_coerce_float(base.get("height_cm"), 175.0), 90.0, 240.0), 1),
        weight_kg=round(_clamp(_coerce_float(base.get("weight_kg"), 75.0), 25.0, 250.0), 1),
        age=int(_clamp(_coerce_int(base.get("age"), 30), 10, 100)),
        sex=sex,
        device_address=str(base.get("device_address") or "").strip()[:200],
        device_name=str(base.get("device_name") or "").strip()[:80],
    )


def load_settings() -> Settings:
    if not SETTINGS_PATH.exists():
        return Settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return sanitize_settings(data)
    except (OSError, json.JSONDecodeError):
        pass
    return Settings()


def save_settings(settings: Settings) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_heart_rate_measurement(data: bytes | bytearray | memoryview) -> dict[str, Any]:
    raw = bytes(data)
    if len(raw) < 2:
        raise ValueError("Heart Rate Measurement verisi cok kisa.")

    flags = raw[0]
    offset = 1

    if flags & 0x01:
        if len(raw) < offset + 2:
            raise ValueError("16 bit BPM alanı eksik.")
        bpm = int.from_bytes(raw[offset : offset + 2], "little")
        offset += 2
    else:
        bpm = raw[offset]
        offset += 1

    contact_supported = bool(flags & 0x04)
    sensor_contact = bool(flags & 0x02) if contact_supported else None

    energy_expended = None
    if flags & 0x08:
        if len(raw) >= offset + 2:
            energy_expended = int.from_bytes(raw[offset : offset + 2], "little")
            offset += 2

    rr_ms: list[float] = []
    if flags & 0x10:
        while len(raw) >= offset + 2:
            rr_raw = int.from_bytes(raw[offset : offset + 2], "little")
            rr_ms.append(round((rr_raw / 1024.0) * 1000.0, 1))
            offset += 2

    return {
        "bpm": bpm,
        "sensor_contact": sensor_contact,
        "energy_expended": energy_expended,
        "rr_ms": rr_ms,
    }


def bmr_kcal_per_day(settings: Settings) -> float:
    sex_adjustment = -161 if settings.sex == "female" else 5
    return max(
        500.0,
        (10 * settings.weight_kg)
        + (6.25 * settings.height_cm)
        - (5 * settings.age)
        + sex_adjustment,
    )


def keytel_kcal_per_minute(bpm: int, settings: Settings) -> float:
    if settings.sex == "female":
        value = (
            -20.4022
            + (0.4472 * bpm)
            - (0.1263 * settings.weight_kg)
            + (0.074 * settings.age)
        ) / 4.184
    else:
        value = (
            -55.0969
            + (0.6309 * bpm)
            + (0.1988 * settings.weight_kg)
            + (0.2017 * settings.age)
        ) / 4.184
    return max(0.0, value)


def estimate_kcal_per_minute(bpm: int | None, settings: Settings) -> float:
    if bpm is None or bpm < 35:
        return 0.0
    resting_floor = bmr_kcal_per_day(settings) / 1440.0
    return max(resting_floor, keytel_kcal_per_minute(bpm, settings))


def heart_zone(bpm: int | None, age: int) -> dict[str, Any]:
    if bpm is None:
        return dict(WAITING_ZONE)

    max_hr = max(100.0, 208.0 - (0.7 * age))
    pct = _clamp((bpm / max_hr) * 100.0, 0.0, 120.0)
    selected = HEART_ZONE_DEFS[-1]
    for zone in HEART_ZONE_DEFS:
        if pct < zone["max_pct"]:
            selected = zone
            break

    return {
        "label": selected["label"],
        "subtitle": selected["subtitle"],
        "range": selected["range"],
        "pct": round(pct, 1),
        "level": selected["level"],
        "color": selected["color"],
        "soft": selected["soft"],
    }


def recording_settings(settings: Settings) -> dict[str, Any]:
    return {
        "display_name": settings.display_name,
        "height_cm": settings.height_cm,
        "weight_kg": settings.weight_kg,
        "age": settings.age,
        "sex": settings.sex,
    }


def local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def summarize_session(session: dict[str, Any]) -> dict[str, Any]:
    samples = [sample for sample in session.get("samples", []) if sample.get("bpm") is not None]
    zone_seconds = {int(zone["level"]): 0.0 for zone in HEART_ZONE_DEFS}

    bpms: list[int] = []
    for sample in samples:
        bpm = _coerce_int(sample.get("bpm"), 0)
        if bpm > 0:
            bpms.append(bpm)
        zone = sample.get("zone") if isinstance(sample.get("zone"), dict) else {}
        level = int(zone.get("level") or 0)
        if level in zone_seconds:
            zone_seconds[level] += max(0.0, _coerce_float(sample.get("duration_seconds"), 0.0))

    if samples:
        last_sample = samples[-1]
        duration_seconds = int(
            max(
                0.0,
                _coerce_float(last_sample.get("elapsed_seconds"), 0.0)
                + _coerce_float(last_sample.get("duration_seconds"), 0.0),
            )
        )
        calories = _coerce_float(session.get("final_calories"), _coerce_float(last_sample.get("calories"), 0.0))
    else:
        duration_seconds = int(max(0.0, _coerce_float(session.get("final_elapsed_seconds"), 0.0)))
        calories = _coerce_float(session.get("final_calories"), 0.0)

    measured_seconds = sum(zone_seconds.values())
    zones: list[dict[str, Any]] = []
    for zone in HEART_ZONE_DEFS:
        seconds = zone_seconds[int(zone["level"])]
        zones.append(
            {
                "label": zone["label"],
                "subtitle": zone["subtitle"],
                "range": zone["range"],
                "level": zone["level"],
                "color": zone["color"],
                "seconds": round(seconds, 1),
                "minutes": round(seconds / 60.0, 1),
                "percent": round((seconds / measured_seconds) * 100.0, 1) if measured_seconds else 0.0,
            }
        )

    return {
        "id": session.get("id", ""),
        "title": session.get("title", "Yayın Kaydı"),
        "started_at": session.get("started_at", ""),
        "ended_at": session.get("ended_at"),
        "active": not bool(session.get("ended_at")),
        "duration_seconds": duration_seconds,
        "duration": format_seconds(duration_seconds),
        "measured_seconds": int(measured_seconds),
        "measured_duration": format_seconds(measured_seconds),
        "sample_count": len(samples),
        "avg_bpm": round(sum(bpms) / len(bpms), 1) if bpms else None,
        "min_bpm": min(bpms) if bpms else None,
        "max_bpm": max(bpms) if bpms else None,
        "calories": round(calories, 1),
        "zones": zones,
        "settings": session.get("settings", {}),
    }


class SessionRecorder:
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.lock = threading.RLock()
        self.current: dict[str, Any] | None = None
        self.current_path: Path | None = None
        self.last_flush_at = 0.0
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def start_new(self, settings: Settings) -> dict[str, Any]:
        with self.lock:
            if self.current is not None:
                return self.current

            now = datetime.now().astimezone()
            base_id = now.strftime("%Y%m%d-%H%M%S")
            session_id = base_id
            suffix = 1
            current_path = self.sessions_dir / f"{session_id}.json"
            while current_path.exists():
                suffix += 1
                session_id = f"{base_id}-{suffix}"
                current_path = self.sessions_dir / f"{session_id}.json"
            self.current_path = current_path
            self.current = {
                "id": session_id,
                "title": f"Yayın {now.strftime('%d.%m.%Y %H:%M')}",
                "started_at": now.isoformat(timespec="seconds"),
                "ended_at": None,
                "settings": recording_settings(settings),
                "samples": [],
                "final_calories": 0.0,
                "final_elapsed_seconds": 0.0,
            }
            self.flush(force=True)
            return self.current

    def is_active(self) -> bool:
        with self.lock:
            return self.current is not None

    def update_settings(self, settings: Settings) -> None:
        with self.lock:
            if self.current is None:
                return
            self.current["settings"] = recording_settings(settings)
            self.flush(force=True)

    def record_sample(
        self,
        *,
        bpm: int,
        elapsed_seconds: float,
        calories: float,
        kcal_per_hour: float,
        zone: dict[str, Any],
        force_flush: bool = False,
    ) -> None:
        with self.lock:
            if self.current is None:
                return

            samples = self.current.setdefault("samples", [])
            if samples:
                previous = samples[-1]
                previous_elapsed = _coerce_float(previous.get("elapsed_seconds"), elapsed_seconds)
                next_duration = round(_clamp(elapsed_seconds - previous_elapsed, 0.0, 15.0), 2)
                previous["duration_seconds"] = max(
                    _coerce_float(previous.get("duration_seconds"), 0.0),
                    next_duration,
                )

            samples.append(
                {
                    "timestamp": local_iso(),
                    "elapsed_seconds": round(max(0.0, elapsed_seconds), 2),
                    "bpm": int(bpm),
                    "calories": round(max(0.0, calories), 2),
                    "kcal_per_hour": round(max(0.0, kcal_per_hour), 1),
                    "zone": {
                        "label": zone.get("label"),
                        "level": zone.get("level"),
                        "pct": zone.get("pct"),
                        "color": zone.get("color"),
                    },
                    "duration_seconds": 0.0,
                }
            )
            self.current["final_calories"] = round(max(0.0, calories), 2)
            self.current["final_elapsed_seconds"] = round(max(0.0, elapsed_seconds), 2)
            self.flush(force=force_flush)

    def extend_current_sample(
        self,
        *,
        elapsed_seconds: float,
        calories: float,
        kcal_per_hour: float,
        additional_seconds: float,
    ) -> None:
        with self.lock:
            if self.current is None:
                return
            samples = self.current.get("samples", [])
            if not samples:
                return

            last = samples[-1]
            last["duration_seconds"] = round(
                _coerce_float(last.get("duration_seconds"), 0.0)
                + _clamp(additional_seconds, 0.0, 10.0),
                2,
            )
            last["calories"] = round(max(0.0, calories), 2)
            last["kcal_per_hour"] = round(max(0.0, kcal_per_hour), 1)
            self.current["final_calories"] = round(max(0.0, calories), 2)
            self.current["final_elapsed_seconds"] = round(max(0.0, elapsed_seconds), 2)
            self.flush()

    def finish_current(self, *, elapsed_seconds: float, calories: float) -> None:
        with self.lock:
            if self.current is None:
                return

            samples = self.current.get("samples", [])
            if samples:
                last = samples[-1]
                last_elapsed = _coerce_float(last.get("elapsed_seconds"), elapsed_seconds)
                if _coerce_float(last.get("duration_seconds"), 0.0) == 0.0:
                    last["duration_seconds"] = round(_clamp(elapsed_seconds - last_elapsed, 0.0, 15.0), 2)

            self.current["ended_at"] = local_iso()
            self.current["final_calories"] = round(max(0.0, calories), 2)
            self.current["final_elapsed_seconds"] = round(max(0.0, elapsed_seconds), 2)
            self.flush(force=True)
            self.current = None
            self.current_path = None

    def flush(self, force: bool = False) -> None:
        if self.current is None or self.current_path is None:
            return
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        now = time.monotonic()
        if not force and (now - self.last_flush_at) < 5.0:
            return

        tmp_path = self.current_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self.current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.current_path)
        self.last_flush_at = now

    def _load_session_file(self, path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def list_summaries(self) -> list[dict[str, Any]]:
        with self.lock:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            summaries_by_id: dict[str, dict[str, Any]] = {}
            for path in self.sessions_dir.glob("*.json"):
                data = self._load_session_file(path)
                if data:
                    summaries_by_id[str(data.get("id") or path.stem)] = summarize_session(data)

            if self.current is not None:
                summaries_by_id[str(self.current.get("id"))] = summarize_session(self.current)

            return sorted(
                summaries_by_id.values(),
                key=lambda item: str(item.get("started_at", "")),
                reverse=True,
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        safe_id = "".join(ch for ch in session_id if ch.isdigit() or ch == "-")
        if not safe_id:
            return None

        with self.lock:
            if self.current and self.current.get("id") == safe_id:
                session = dict(self.current)
                session["summary"] = summarize_session(self.current)
                return session

            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            path = (self.sessions_dir / f"{safe_id}.json").resolve()
            try:
                path.relative_to(self.sessions_dir.resolve())
            except ValueError:
                return None
            data = self._load_session_file(path)
            if not data:
                return None
            data["summary"] = summarize_session(data)
            return data

    def delete_session(self, session_id: str) -> tuple[bool, str]:
        safe_id = "".join(ch for ch in session_id if ch.isdigit() or ch == "-")
        if not safe_id:
            return False, "Gecersiz kayit"

        with self.lock:
            if self.current and self.current.get("id") == safe_id:
                return False, "Aktif kayit silinemez. Once Durdur ile kaydi bitirin."

            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            path = (self.sessions_dir / f"{safe_id}.json").resolve()
            try:
                path.relative_to(self.sessions_dir.resolve())
            except ValueError:
                return False, "Gecersiz kayit"
            if not path.exists():
                return False, "Kayit bulunamadi"

            path.unlink()
            return True, "Kayit silindi"


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _has_hr_service(service_uuids: list[str]) -> bool:
    for service_uuid in service_uuids:
        compact = service_uuid.lower().replace("-", "")
        if compact == "180d" or compact.startswith("0000180d"):
            return True
    return False


def _looks_like_hrm(name: str, service_uuids: list[str]) -> bool:
    lower_name = name.lower()
    name_match = any(
        token in lower_name
        for token in ("heart", "hrm", "hr ", " hr", "nabiz", "decathlon", "dual", "belt")
    )
    return _has_hr_service(service_uuids) or name_match


def mark_saved_device(devices: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    if not settings.device_address:
        return devices

    saved_address = settings.device_address.lower()
    merged: list[dict[str, Any]] = []
    for device in devices:
        if str(device.get("address", "")).lower() == saved_address:
            merged.append({**device, "is_saved": True})
        else:
            merged.append(device)
    return merged


class HrmApplication:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.settings = load_settings()
        self.state = RuntimeState()
        self.recorder = SessionRecorder(SESSIONS_DIR)
        self.ble = BleController(self)
        self.demo = DemoSource(self)

    def start(self) -> None:
        self.ble.start()

    def shutdown(self) -> None:
        self.demo.stop()
        self.ble.disconnect()
        self.stop_recording("Kayıt kapatıldı")

    def _start_recording_locked(self, status: str = "Kayıt başladı") -> dict[str, Any]:
        self._integrate_locked()
        if not self.recorder.is_active():
            now = time.monotonic()
            self.state.calories = 0.0
            self.state.kcal_per_hour = 0.0
            self.state.session_started_at = now
            self.state.stopped_elapsed_seconds = 0.0
            self.state.last_integrated_at = now
            self.state.status = status
            self.state.error = ""
            self.recorder.start_new(self.settings)
            if self.state.bpm is not None:
                kcal_per_minute = estimate_kcal_per_minute(self.state.bpm, self.settings)
                self.state.kcal_per_hour = kcal_per_minute * 60.0
                self.recorder.record_sample(
                    bpm=self.state.bpm,
                    elapsed_seconds=0.0,
                    calories=self.state.calories,
                    kcal_per_hour=self.state.kcal_per_hour,
                    zone=heart_zone(self.state.bpm, self.settings.age),
                    force_flush=True,
                )
        return summarize_session(self.recorder.current) if self.recorder.current else {}

    def start_recording(self, status: str = "Kayıt başladı") -> dict[str, Any]:
        with self.lock:
            return self._start_recording_locked(status)

    def stop_recording(self, status: str = "Kayıt durduruldu") -> None:
        with self.lock:
            if not self.recorder.is_active():
                self.state.status = status if status != "Kayıt durduruldu" else "Aktif kayıt yok"
                return
            self._integrate_locked()
            elapsed_seconds = time.monotonic() - self.state.session_started_at
            self.recorder.finish_current(
                elapsed_seconds=elapsed_seconds,
                calories=self.state.calories,
            )
            self.state.stopped_elapsed_seconds = elapsed_seconds
            self.state.status = status
            self.state.error = ""

    def _integrate_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self.state.last_integrated_at
        if elapsed <= 0:
            return

        # Cap catch-up after PC sleep or a paused debugger so calories do not jump.
        elapsed = min(elapsed, 10.0)
        self.state.last_integrated_at = now

        bpm_is_fresh = self.state.bpm is not None and (now - self.state.bpm_updated_at) <= 12.0
        bpm_can_drive_estimate = self.state.bpm is not None and (
            bpm_is_fresh or self.recorder.is_active()
        )
        if bpm_can_drive_estimate:
            kcal_per_minute = estimate_kcal_per_minute(self.state.bpm, self.settings)
            self.state.kcal_per_hour = kcal_per_minute * 60.0
            if self.recorder.is_active():
                self.state.calories += kcal_per_minute * (elapsed / 60.0)
                self.recorder.extend_current_sample(
                    elapsed_seconds=now - self.state.session_started_at,
                    calories=self.state.calories,
                    kcal_per_hour=self.state.kcal_per_hour,
                    additional_seconds=elapsed,
                )
        else:
            self.state.kcal_per_hour = 0.0

    def update_settings(self, data: dict[str, Any]) -> Settings:
        with self.lock:
            self._integrate_locked()
            self.settings = sanitize_settings(data, self.settings)
            save_settings(self.settings)
            self.recorder.update_settings(self.settings)
            if self.settings.device_name:
                self.state.device_name = self.settings.device_name
            if self.settings.device_address:
                self.state.device_address = self.settings.device_address
            return self.settings

    def reset_session(self) -> None:
        with self.lock:
            self._integrate_locked()
            now = time.monotonic()
            was_recording = self.recorder.is_active()
            if was_recording:
                elapsed_seconds = now - self.state.session_started_at
                self.recorder.finish_current(
                    elapsed_seconds=elapsed_seconds,
                    calories=self.state.calories,
                )
            self.state.calories = 0.0
            self.state.kcal_per_hour = 0.0
            self.state.session_started_at = now
            self.state.stopped_elapsed_seconds = 0.0
            self.state.last_integrated_at = now
            self.state.status = "Seans sifirlandi"
            self.state.error = ""
            if was_recording:
                self.recorder.start_new(self.settings)

    def set_status(self, status: str, error: str = "") -> None:
        with self.lock:
            self.state.status = status
            self.state.error = error

    def set_ble_connecting(self, connecting: bool, status: str) -> None:
        with self.lock:
            self._integrate_locked()
            self.state.connecting = connecting
            self.state.status = status
            self.state.error = ""
            if connecting:
                self.state.connected = False

    def set_ble_connected(self, connected: bool, status: str, name: str = "", address: str = "") -> None:
        with self.lock:
            self._integrate_locked()
            self.state.connected = connected
            self.state.connecting = False
            self.state.status = status
            if name:
                self.state.device_name = name
            if address:
                self.state.device_address = address
            if not connected and not self.state.demo and not self.recorder.is_active():
                self.state.bpm = None
            self.state.error = ""

    def update_bpm(
        self,
        bpm: int,
        sensor_contact: bool | None = None,
        rr_ms: list[float] | None = None,
        device_name: str = "",
        device_address: str = "",
    ) -> None:
        with self.lock:
            self._integrate_locked()
            self.state.bpm = bpm
            self.state.sensor_contact = sensor_contact
            self.state.rr_ms = rr_ms or []
            self.state.bpm_updated_at = time.monotonic()
            self.state.error = ""
            if device_name:
                self.state.device_name = device_name
            if device_address:
                self.state.device_address = device_address
            if not self.state.status or self.state.status.startswith(
                ("Baglanti", "Baglandi", "Bluetooth", "Nabız verisi")
            ):
                self.state.status = "Nabiz okunuyor"
            elapsed_seconds = time.monotonic() - self.state.session_started_at
            zone = heart_zone(bpm, self.settings.age)
            self.recorder.record_sample(
                bpm=bpm,
                elapsed_seconds=elapsed_seconds,
                calories=self.state.calories,
                kcal_per_hour=self.state.kcal_per_hour,
                zone=zone,
                force_flush=True,
            )

    def set_demo(self, enabled: bool) -> None:
        with self.lock:
            self._integrate_locked()
            self.state.demo = enabled
            self.state.connected = enabled
            self.state.connecting = False
            self.state.device_name = "Demo HRM" if enabled else self.settings.device_name
            self.state.device_address = "" if enabled else self.settings.device_address
            self.state.status = "Demo modu" if enabled else "Demo durduruldu"
            self.state.error = ""
            if not enabled:
                self.state.bpm = None
                self.state.kcal_per_hour = 0.0

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self._integrate_locked()
            now = time.monotonic()
            bpm_fresh = self.state.bpm is not None and (now - self.state.bpm_updated_at) <= 12.0
            recording_active = self.recorder.is_active()
            visible_bpm = self.state.bpm if bpm_fresh or recording_active else None
            bpm_ready = bool(visible_bpm is not None and (self.state.connected or self.state.demo))
            elapsed_seconds = (
                now - self.state.session_started_at
                if recording_active
                else self.state.stopped_elapsed_seconds
            )
            zone = heart_zone(visible_bpm, self.settings.age)
            return {
                "settings": asdict(self.settings),
                "bpm": visible_bpm,
                "last_bpm": self.state.bpm,
                "bpm_ready": bpm_ready,
                "bpm_stale": bool(visible_bpm is not None and not bpm_fresh),
                "bpm_age_seconds": round(now - self.state.bpm_updated_at, 1)
                if self.state.bpm_updated_at
                else None,
                "sensor_contact": self.state.sensor_contact,
                "rr_ms": self.state.rr_ms[-5:],
                "calories": round(self.state.calories, 1),
                "kcal_per_hour": round(self.state.kcal_per_hour, 0),
                "elapsed_seconds": int(elapsed_seconds),
                "elapsed": format_seconds(elapsed_seconds),
                "connected": self.state.connected,
                "connecting": self.state.connecting,
                "demo": self.state.demo,
                "device_name": self.state.device_name or self.settings.device_name,
                "device_address": self.state.device_address or self.settings.device_address,
                "status": self.state.status,
                "error": self.state.error,
                "zone": zone,
                "recording_active": recording_active,
                "active_session": summarize_session(self.recorder.current)
                if self.recorder.current
                else None,
                "updated_at": time.time(),
            }


class DemoSource:
    def __init__(self, app: HrmApplication) -> None:
        self.app = app
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="hrm-demo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        self.app.set_demo(True)
        started = time.monotonic()
        while not self._stop.wait(1.0):
            t = time.monotonic() - started
            bpm = int(round(112 + 28 * math.sin(t / 8.0) + 10 * math.sin(t / 2.5)))
            bpm = int(_clamp(bpm, 68, 172))
            self.app.update_bpm(bpm, sensor_contact=True, device_name="Demo HRM")
        self.app.set_demo(False)


class BleController:
    def __init__(self, app: HrmApplication) -> None:
        self.app = app
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="hrm-ble", daemon=True)
        self.client: Any = None
        self.scan_cache: dict[str, Any] = {}
        self._stop_flag: threading.Event | None = None
        self._connect_future: Any = None

    def start(self) -> None:
        if not self.thread.is_alive():
            self.thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _submit(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def scan_sync(self, timeout: float = 6.0) -> list[dict[str, Any]]:
        future = self._submit(self._scan(timeout))
        return future.result(timeout=timeout + 8.0)

    def connect_background(self, address: str = "", name: str = "") -> None:
        self.disconnect()
        stop_flag = threading.Event()
        self._stop_flag = stop_flag
        self._connect_future = self._submit(self._connect_loop(address, name, stop_flag))

    def disconnect(self) -> None:
        if self._stop_flag:
            self._stop_flag.set()
        try:
            self._submit(self._disconnect_client())
        except RuntimeError:
            pass
        self.app.set_ble_connected(False, "Baglanti kesildi")

    async def _disconnect_client(self) -> None:
        client = self.client
        if client is not None:
            try:
                if getattr(client, "is_connected", False):
                    await client.disconnect()
            except Exception:
                pass

    async def _scan(self, timeout: float) -> list[dict[str, Any]]:
        try:
            from bleak import BleakScanner
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Bleak paketi yuklu degil. run.bat ile veya 'pip install -r requirements.txt' ile kurun."
            ) from exc

        devices: list[dict[str, Any]] = []
        cache: dict[str, Any] = {}

        try:
            discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
            iterator = discovered.values()
            for device, adv in iterator:
                name = getattr(adv, "local_name", None) or getattr(device, "name", None) or "Bilinmeyen"
                address = str(getattr(device, "address", ""))
                service_uuids = list(getattr(adv, "service_uuids", None) or [])
                rssi = getattr(adv, "rssi", None)
                cache[address] = device
                devices.append(
                    {
                        "name": name,
                        "address": address,
                        "rssi": rssi,
                        "service_uuids": service_uuids,
                        "is_hrm": _looks_like_hrm(name, service_uuids),
                        "is_saved": False,
                        "source": "scan",
                    }
                )
        except TypeError:
            discovered = await BleakScanner.discover(timeout=timeout)
            for device in discovered:
                metadata = getattr(device, "metadata", {}) or {}
                service_uuids = list(metadata.get("uuids", []) or [])
                name = getattr(device, "name", None) or "Bilinmeyen"
                address = str(getattr(device, "address", ""))
                cache[address] = device
                devices.append(
                    {
                        "name": name,
                        "address": address,
                        "rssi": getattr(device, "rssi", None),
                        "service_uuids": service_uuids,
                        "is_hrm": _looks_like_hrm(name, service_uuids),
                        "is_saved": False,
                        "source": "scan",
                    }
                )

        self.scan_cache = cache
        devices.sort(key=lambda item: (not item["is_hrm"], item["name"].lower(), item["address"]))
        return devices

    async def _find_hrm_device(self) -> tuple[Any, dict[str, Any]]:
        devices = await self._scan(8.0)
        candidates = [device for device in devices if device.get("is_hrm")]
        if not candidates:
            raise RuntimeError(
                "Nabiz kemeri bulunamadi. Kemeri takin, Bluetooth'u acin ve Windows yakininda uyandirin."
            )
        chosen = candidates[0]
        target = self.scan_cache.get(chosen["address"], chosen["address"])
        return target, chosen

    async def _resolve_known_device(self, address: str, name: str) -> tuple[Any, dict[str, Any]]:
        cached = self.scan_cache.get(address)
        if cached is None:
            saved_address = address.lower()
            cached = next(
                (
                    device
                    for cached_address, device in self.scan_cache.items()
                    if str(cached_address).lower() == saved_address
                ),
                None,
            )
        if cached is not None:
            return cached, {"name": name or getattr(cached, "name", None) or address, "address": address}

        try:
            from bleak import BleakScanner
        except ModuleNotFoundError:
            return address, {"name": name or address, "address": address}

        finder = getattr(BleakScanner, "find_device_by_address", None)
        if finder is not None:
            try:
                device = await finder(address, timeout=4.0)
                if device is not None:
                    self.scan_cache[address] = device
                    return device, {
                        "name": name or getattr(device, "name", None) or address,
                        "address": address,
                    }
            except Exception:
                pass

        return address, {"name": name or address, "address": address}

    async def _connect_loop(self, address: str, name: str, stop_flag: threading.Event) -> None:
        try:
            from bleak import BleakClient
        except ModuleNotFoundError as exc:
            self.app.set_status(
                "Bleak kurulu degil",
                "Terminalde 'pip install -r requirements.txt' calistirin veya run.bat kullanin.",
            )
            raise RuntimeError("Bleak paketi yuklu degil.") from exc

        while not stop_flag.is_set():
            try:
                self.app.set_ble_connecting(
                    True,
                    "Nabiz kemeri araniyor" if not address else "Seçili cihaza bağlanılıyor",
                )
                if address:
                    target, info = await self._resolve_known_device(address, name)
                else:
                    target, info = await self._find_hrm_device()

                async with BleakClient(target, timeout=20.0) as client:
                    self.client = client
                    device_name = str(info.get("name") or name or address or "HRM")
                    device_address = str(info.get("address") or address)
                    self.app.set_ble_connected(True, "Baglandi", device_name, device_address)
                    await client.start_notify(HR_CHAR_UUID, self._handle_hr_notification)

                    while not stop_flag.is_set() and getattr(client, "is_connected", False):
                        await asyncio.sleep(1.0)

                    try:
                        await client.stop_notify(HR_CHAR_UUID)
                    except Exception:
                        pass

                if not stop_flag.is_set():
                    self.app.set_ble_connected(False, "Baglanti koptu, tekrar deneniyor")
                    await asyncio.sleep(4.0)
            except Exception as exc:
                if stop_flag.is_set():
                    break
                hint = (
                    "Kemer Windows'ta bağlı görünse bile takılı/uyanık olmalı. "
                    "Listede çıkmıyorsa Tara ile cihazı yeniden bulun."
                )
                self.app.set_status("Baglanti hatasi", f"{exc} {hint}")
                await asyncio.sleep(5.0)

        self.app.set_ble_connected(False, "Baglanti kesildi")

    def _handle_hr_notification(self, _sender: Any, data: bytearray) -> None:
        try:
            measurement = parse_heart_rate_measurement(data)
            self.app.update_bpm(
                int(measurement["bpm"]),
                sensor_contact=measurement.get("sensor_contact"),
                rr_ms=measurement.get("rr_ms") or [],
            )
        except Exception as exc:
            self.app.set_status("Veri okunamadi", str(exc))


class HrmHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], app: HrmApplication) -> None:
        super().__init__(server_address, HrmRequestHandler)
        self.app = app


class HrmRequestHandler(BaseHTTPRequestHandler):
    server: HrmHttpServer

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("", "/", "/settings"):
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/overlay":
            self._serve_file(STATIC_DIR / "overlay.html", "text/html; charset=utf-8")
            return
        if path == "/events":
            self._serve_events()
            return
        if path == "/api/state":
            self._send_json(self.server.app.snapshot())
            return
        if path == "/api/settings":
            self._send_json(asdict(self.server.app.settings))
            return
        if path == "/api/sessions":
            self._send_json({"sessions": self.server.app.recorder.list_summaries()})
            return
        if path.startswith("/api/sessions/"):
            session_id = path.removeprefix("/api/sessions/").strip("/")
            session = self.server.app.recorder.get_session(session_id)
            if not session:
                self._send_json({"error": "Kayıt bulunamadı"}, code=404)
                return
            self._send_json({"session": session})
            return
        if path == "/api/scan":
            query = parse_qs(parsed.query)
            timeout = _clamp(_coerce_float((query.get("timeout") or [6])[0], 6.0), 2.0, 12.0)
            devices: list[dict[str, Any]] = []
            scan_error = ""
            try:
                devices = self.server.app.ble.scan_sync(timeout)
            except Exception as exc:
                scan_error = str(exc)
            devices = mark_saved_device(devices, self.server.app.settings)
            self._send_json({"devices": devices, "warning": scan_error})
            return
        if path.startswith("/static/"):
            relative = path.removeprefix("/static/").strip("/")
            self._serve_static(relative)
            return

        self._send_json({"error": "Bulunamadi"}, code=404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/sessions/"):
            session_id = path.removeprefix("/api/sessions/").strip("/")
            deleted, message = self.server.app.recorder.delete_session(session_id)
            self._send_json(
                {
                    "ok": deleted,
                    "message": message,
                    "error": "" if deleted else message,
                    "sessions": self.server.app.recorder.list_summaries(),
                },
                code=200 if deleted else 409,
            )
            return

        self._send_json({"error": "Bulunamadi"}, code=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._send_json({"error": "JSON okunamadi"}, code=400)
            return

        if path == "/api/settings":
            settings = self.server.app.update_settings(payload)
            self._send_json({"settings": asdict(settings)})
            return
        if path == "/api/connect":
            self.server.app.demo.stop()
            address = str(payload.get("address") or "").strip()
            name = str(payload.get("name") or "").strip()
            if not address:
                self._send_json({"error": "Once listeden cihaz secin"}, code=400)
                return
            settings_update = {"device_address": address}
            if name:
                settings_update["device_name"] = name
            self.server.app.update_settings(settings_update)
            self.server.app.ble.connect_background(address, name)
            self._send_json(
                {
                    "ok": True,
                    "status": "Bluetooth baglantisi baslatildi",
                    "recording_active": self.server.app.recorder.is_active(),
                }
            )
            return
        if path == "/api/disconnect":
            self.server.app.demo.stop()
            self.server.app.ble.disconnect()
            self.server.app.stop_recording("Durduruldu ve kayit kaydedildi")
            self._send_json(
                {
                    "ok": True,
                    "recording_active": self.server.app.recorder.is_active(),
                    "sessions": self.server.app.recorder.list_summaries(),
                }
            )
            return
        if path == "/api/recording/start":
            with self.server.app.lock:
                bpm_ready = (
                    self.server.app.state.bpm is not None
                    and (time.monotonic() - self.server.app.state.bpm_updated_at) <= 12.0
                )
                source_ready = self.server.app.state.connected or self.server.app.state.demo
            if not (source_ready and bpm_ready):
                self._send_json(
                    {"error": "Nabiz verisi gelmeden kayit baslatilamaz"},
                    code=409,
                )
                return
            active_session = self.server.app.start_recording()
            self._send_json({"ok": True, "active_session": active_session})
            return
        if path == "/api/recording/stop":
            self.server.app.stop_recording()
            self._send_json(
                {
                    "ok": True,
                    "recording_active": self.server.app.recorder.is_active(),
                    "sessions": self.server.app.recorder.list_summaries(),
                }
            )
            return
        if path == "/api/reset":
            self.server.app.reset_session()
            self._send_json({"ok": True})
            return
        if path == "/api/demo":
            enabled = bool(payload.get("enabled"))
            if enabled:
                self.server.app.ble.disconnect()
                self.server.app.demo.start()
            else:
                self.server.app.demo.stop()
            self._send_json({"ok": True, "demo": enabled})
            return

        self._send_json({"error": "Bulunamadi"}, code=404)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _send_json(self, payload: dict[str, Any], code: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _serve_static(self, relative: str) -> None:
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_json({"error": "Gecersiz yol"}, code=400)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or target.suffix in (".js", ".css"):
            content_type += "; charset=utf-8"
        self._serve_file(target, content_type)

    def _serve_file(self, target: Path, content_type: str) -> None:
        try:
            raw = target.read_bytes()
        except OSError:
            self._send_json({"error": "Dosya bulunamadi"}, code=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _serve_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        while True:
            try:
                payload = self.server.app.snapshot()
                frame = f"event: state\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                self.wfile.write(frame.encode("utf-8"))
                self.wfile.flush()
                time.sleep(1.0)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BLE nabiz kemeri icin OBS overlay sunucusu.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--auto-connect", action="store_true")
    args = parser.parse_args(argv)

    app = HrmApplication()
    app.start()
    if args.auto_connect:
        app.ble.connect_background(app.settings.device_address, app.settings.device_name)

    server = HrmHttpServer((args.host, args.port), app)
    print("")
    print(f"Ayar ekrani:   http://{args.host}:{args.port}/")
    print(f"OBS overlay:  http://{args.host}:{args.port}/overlay")
    print("Kapatmak icin Ctrl+C")
    print("")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatiliyor...")
    finally:
        app.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
