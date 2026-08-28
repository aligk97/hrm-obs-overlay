import json
import tempfile
import time
import unittest
from pathlib import Path

from app import (
    HrmApplication,
    SessionRecorder,
    Settings,
    estimate_kcal_per_minute,
    format_ble_connection_error,
    heart_zone,
    mark_saved_device,
    parse_heart_rate_measurement,
    profile_validation_errors,
    sanitize_settings,
    summarize_session,
)


def valid_profile(**overrides):
    data = {
        "display_name": "Canlı Nabız",
        "height_cm": 185,
        "weight_kg": 82,
        "age": 24,
        "sex": "male",
        "resting_hr": 60,
        "max_hr": "",
        "activity_type": "mixed",
        "fitness_level": "average",
        "profile_confirmed": True,
    }
    data.update(overrides)
    return data


def valid_settings(**overrides):
    data = valid_profile(**overrides)
    data["max_hr"] = 0 if data["max_hr"] == "" else data["max_hr"]
    return sanitize_settings(data)


class HeartRateMeasurementTests(unittest.TestCase):
    def test_parse_uint8_bpm(self):
        measurement = parse_heart_rate_measurement(bytes([0x00, 0x78]))
        self.assertEqual(measurement["bpm"], 120)
        self.assertIsNone(measurement["sensor_contact"])

    def test_parse_uint16_bpm_with_rr(self):
        measurement = parse_heart_rate_measurement(bytes([0x11, 0x2C, 0x01, 0x00, 0x04]))
        self.assertEqual(measurement["bpm"], 300)
        self.assertEqual(measurement["rr_ms"], [1000.0])

    def test_sanitize_settings_clamps_values(self):
        settings = sanitize_settings(
            {"height_cm": "300", "weight_kg": "10", "age": "3", "sex": "kadin"}
        )
        self.assertEqual(settings.height_cm, 240.0)
        self.assertEqual(settings.weight_kg, 25.0)
        self.assertEqual(settings.age, 10)
        self.assertEqual(settings.sex, "female")

    def test_sanitize_settings_requires_new_profile_fields_until_confirmed(self):
        settings = sanitize_settings({"height_cm": 185, "weight_kg": 82, "age": 24, "sex": "male"})

        self.assertFalse(settings.profile_confirmed)
        self.assertIn("Dinlenik nabız", profile_validation_errors(settings, require_confirmed=False))
        self.assertIn("Aktivite türü", profile_validation_errors(settings, require_confirmed=False))

    def test_sanitize_settings_marks_complete_with_required_profile(self):
        settings = sanitize_settings(valid_profile(activity_type="broadcast"))

        self.assertTrue(settings.profile_confirmed)
        self.assertEqual(profile_validation_errors(settings), [])
        self.assertEqual(settings.resting_hr, 60)
        self.assertEqual(settings.activity_type, "broadcast")

    def test_calorie_estimate_uses_height_in_personalized_model(self):
        short = valid_settings(height_cm=150, weight_kg=70, age=35)
        tall = valid_settings(height_cm=200, weight_kg=70, age=35)

        self.assertGreater(estimate_kcal_per_minute(130, tall), estimate_kcal_per_minute(130, short))

    def test_broadcast_activity_caps_high_heart_rate_calories(self):
        broadcast = valid_settings(activity_type="broadcast")
        running = valid_settings(activity_type="running")

        broadcast_kcal_hour = estimate_kcal_per_minute(190, broadcast) * 60
        running_kcal_hour = estimate_kcal_per_minute(190, running) * 60

        self.assertLess(broadcast_kcal_hour, 430)
        self.assertGreater(running_kcal_hour, broadcast_kcal_hour)

    def test_heart_zones_progress_from_rest_to_maximum(self):
        self.assertEqual(heart_zone(80, 30)["label"], "Dinlenme")
        self.assertEqual(heart_zone(105, 30)["label"], "Isınma")
        self.assertEqual(heart_zone(125, 30)["label"], "Yağ Yakımı")
        self.assertEqual(heart_zone(145, 30)["label"], "Aerobik")
        self.assertEqual(heart_zone(160, 30)["label"], "Anaerobik")
        self.assertEqual(heart_zone(175, 30)["label"], "Maksimum")

    def test_saved_device_is_not_listed_when_scan_is_empty(self):
        settings = Settings(device_address="AA:BB:CC:DD:EE:FF", device_name="Decathlon HRM")
        devices = mark_saved_device([], settings)

        self.assertEqual(devices, [])

    def test_saved_device_marks_matching_scan_result(self):
        settings = Settings(device_address="AA:BB:CC:DD:EE:FF", device_name="Decathlon HRM")
        scanned = [
            {
                "name": "HRM Belt",
                "address": "aa:bb:cc:dd:ee:ff",
                "rssi": -59,
                "service_uuids": [],
                "is_hrm": True,
                "is_saved": False,
                "source": "scan",
            }
        ]

        devices = mark_saved_device(scanned, settings)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["name"], "HRM Belt")
        self.assertTrue(devices[0]["is_saved"])

    def test_windows_ble_error_gets_pairing_hint(self):
        message = format_ble_connection_error(OSError("[WinError -2147467259] Unspecified error"))

        self.assertIn("Windows BLE", message)
        self.assertIn("Bluetooth ayarlarindan kemeri kaldirin", message)

    def test_ble_connection_attempts_use_progressive_fallbacks(self):
        hrm = HrmApplication()
        attempts = hrm.ble._connection_attempts()

        self.assertEqual(len(attempts), 3)
        self.assertNotIn("winrt", attempts[0]["kwargs"])
        self.assertEqual(
            attempts[1]["kwargs"]["winrt"],
            {"use_cached_services": True},
        )
        self.assertTrue(attempts[2]["refresh_device"])
        self.assertNotIn("services", attempts[2]["kwargs"])
        self.assertEqual(attempts[2]["kwargs"]["timeout"], 30.0)

    def test_session_summary_counts_zone_durations(self):
        session = {
            "id": "20260825-120000",
            "title": "Yayın 25.08.2026 12:00",
            "started_at": "2026-08-25T12:00:00+03:00",
            "ended_at": "2026-08-25T12:03:00+03:00",
            "final_calories": 18.5,
            "samples": [
                {
                    "elapsed_seconds": 0,
                    "bpm": 82,
                    "calories": 1.0,
                    "duration_seconds": 60,
                    "zone": {"level": 1},
                },
                {
                    "elapsed_seconds": 60,
                    "bpm": 124,
                    "calories": 8.0,
                    "duration_seconds": 120,
                    "zone": {"level": 3},
                },
            ],
        }

        summary = summarize_session(session)
        zones = {zone["label"]: zone for zone in summary["zones"]}
        self.assertEqual(summary["duration_seconds"], 180)
        self.assertEqual(summary["calories"], 18.5)
        self.assertEqual(summary["avg_bpm"], 103.0)
        self.assertEqual(zones["Dinlenme"]["minutes"], 1.0)
        self.assertEqual(zones["Yağ Yakımı"]["minutes"], 2.0)

    def test_session_recorder_persists_finished_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = SessionRecorder(Path(tmp))
            session = recorder.start_new(Settings())
            zone = heart_zone(126, 30)
            recorder.record_sample(
                bpm=126,
                elapsed_seconds=0,
                calories=0.5,
                kcal_per_hour=300,
                zone=zone,
                force_flush=True,
            )
            recorder.record_sample(
                bpm=132,
                elapsed_seconds=60,
                calories=8.5,
                kcal_per_hour=480,
                zone=heart_zone(132, 30),
                force_flush=True,
            )
            recorder.finish_current(elapsed_seconds=90, calories=11.0)

            self.assertFalse(recorder.is_active())
            saved_path = Path(tmp) / f"{session['id']}.json"
            self.assertTrue(saved_path.exists())
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["ended_at"] is not None, True)
            self.assertEqual(len(saved["samples"]), 2)
            self.assertEqual(recorder.list_summaries()[0]["calories"], 11.0)

    def test_session_recorder_deletes_finished_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = SessionRecorder(Path(tmp))
            session = recorder.start_new(Settings())
            recorder.finish_current(elapsed_seconds=10, calories=1.5)

            deleted, message = recorder.delete_session(session["id"])

            self.assertTrue(deleted)
            self.assertEqual(message, "Kayit silindi")
            self.assertFalse((Path(tmp) / f"{session['id']}.json").exists())
            self.assertEqual(recorder.list_summaries(), [])

    def test_session_recorder_keeps_active_recording_when_delete_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = SessionRecorder(Path(tmp))
            session = recorder.start_new(Settings())

            deleted, message = recorder.delete_session(session["id"])

            self.assertFalse(deleted)
            self.assertIn("Aktif kayit", message)
            self.assertTrue((Path(tmp) / f"{session['id']}.json").exists())
            self.assertTrue(recorder.is_active())

    def test_connection_reads_bpm_before_recording_can_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            hrm = HrmApplication()
            hrm.recorder = SessionRecorder(Path(tmp))
            hrm.update_settings(valid_profile())

            hrm.set_ble_connected(True, "Baglandi", "Decathlon HRM", "AA:BB")
            connected_snapshot = hrm.snapshot()

            self.assertFalse(connected_snapshot["recording_active"])
            self.assertFalse(connected_snapshot["bpm_ready"])
            self.assertEqual(connected_snapshot["device_name"], "Decathlon HRM")

            hrm.update_bpm(128)
            bpm_snapshot = hrm.snapshot()

            self.assertFalse(bpm_snapshot["recording_active"])
            self.assertTrue(bpm_snapshot["bpm_ready"])
            self.assertEqual(bpm_snapshot["bpm"], 128)

            active_session = hrm.start_recording()
            recording_snapshot = hrm.snapshot()

            self.assertTrue(recording_snapshot["recording_active"])
            self.assertEqual(recording_snapshot["bpm"], 128)
            self.assertGreaterEqual(active_session["sample_count"], 1)

    def test_stale_bpm_is_not_ready_for_recording_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            hrm = HrmApplication()
            hrm.recorder = SessionRecorder(Path(tmp))
            hrm.update_settings(valid_profile())

            hrm.set_ble_connected(True, "Baglandi", "Decathlon HRM", "AA:BB")
            hrm.update_bpm(118)
            hrm.state.bpm_updated_at = time.monotonic() - 30

            snapshot = hrm.snapshot()

            self.assertIsNone(snapshot["bpm"])
            self.assertFalse(snapshot["bpm_ready"])

    def test_ble_error_unlocks_connect_flow_before_recording(self):
        hrm = HrmApplication()

        hrm.set_ble_connecting(True, "Secili cihaza baglaniliyor")
        hrm.set_ble_error("Baglanti hatasi", "Windows BLE baglantiyi acamadi")
        snapshot = hrm.snapshot()

        self.assertFalse(snapshot["connecting"])
        self.assertFalse(snapshot["connected"])
        self.assertFalse(snapshot["bpm_ready"])
        self.assertEqual(snapshot["status"], "Baglanti hatasi")

    def test_recording_requires_completed_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            hrm = HrmApplication()
            hrm.recorder = SessionRecorder(Path(tmp))
            hrm.settings = Settings()

            with self.assertRaises(RuntimeError):
                hrm.start_recording()

    def test_active_recording_keeps_stale_bpm_visible_during_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            hrm = HrmApplication()
            hrm.recorder = SessionRecorder(Path(tmp))
            hrm.update_settings(valid_profile())
            hrm.start_recording()
            hrm.update_bpm(132)
            hrm.state.bpm_updated_at = time.monotonic() - 30
            hrm.state.last_integrated_at = time.monotonic() - 5

            hrm.set_ble_connected(False, "Baglanti koptu, tekrar deneniyor")
            snapshot = hrm.snapshot()
            active_summary = summarize_session(hrm.recorder.current)

            self.assertEqual(snapshot["bpm"], 132)
            self.assertTrue(snapshot["bpm_stale"])
            self.assertGreater(snapshot["kcal_per_hour"], 0)
            self.assertGreater(active_summary["measured_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
