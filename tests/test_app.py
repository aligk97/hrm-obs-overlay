import unittest

from app import (
    Settings,
    estimate_kcal_per_minute,
    heart_zone,
    parse_heart_rate_measurement,
    sanitize_settings,
)


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

    def test_calorie_estimate_uses_height_floor(self):
        short = Settings(height_cm=150, weight_kg=70, age=35, sex="male")
        tall = Settings(height_cm=200, weight_kg=70, age=35, sex="male")
        self.assertGreater(estimate_kcal_per_minute(45, tall), estimate_kcal_per_minute(45, short))

    def test_heart_zones_progress_from_rest_to_maximum(self):
        self.assertEqual(heart_zone(80, 30)["label"], "Dinlenme")
        self.assertEqual(heart_zone(105, 30)["label"], "Isınma")
        self.assertEqual(heart_zone(125, 30)["label"], "Yağ Yakımı")
        self.assertEqual(heart_zone(145, 30)["label"], "Aerobik")
        self.assertEqual(heart_zone(160, 30)["label"], "Anaerobik")
        self.assertEqual(heart_zone(175, 30)["label"], "Maksimum")


if __name__ == "__main__":
    unittest.main()
