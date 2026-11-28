"""Self-hosted map tiles: HTTP Range answers, sign-in and permission."""
import tempfile
from pathlib import Path

from django.test import override_settings

from apps.vehicles.tests.test_vehicles import VehicleBase

TILES = "/api/v1/map/puntland.pmtiles"


class MapTilesTests(VehicleBase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.file = Path(self.dir.name) / "t.pmtiles"
        self.file.write_bytes(bytes(range(256)) * 4)  # 1024 bytes
        self.ov = override_settings(MAP_TILES_FILE=str(self.file))
        self.ov.enable()
        self.addCleanup(self.ov.disable)

    def test_range_reads(self):
        r = self.officer.get(TILES, HTTP_RANGE="bytes=0-9")
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.content, bytes(range(10)))
        self.assertEqual(r["Content-Range"], "bytes 0-9/1024")
        tail = self.officer.get(TILES, HTTP_RANGE="bytes=-4")
        self.assertEqual((tail.status_code, tail.content), (206, bytes([252, 253, 254, 255])))
        open_end = self.officer.get(TILES, HTTP_RANGE="bytes=1020-")
        self.assertEqual(len(open_end.content), 4)
        self.assertEqual(self.officer.get(TILES, HTTP_RANGE="bytes=5000-6000").status_code, 416)
        self.assertEqual(self.officer.get(TILES, HTTP_RANGE="items=0-1").status_code, 416)

    def test_whole_file_and_headers(self):
        r = self.officer.get(TILES)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), self.file.read_bytes())
        self.assertEqual(r["Accept-Ranges"], "bytes")
        self.assertIn("private", r["Cache-Control"])

    def test_needs_sign_in_and_vehicle_permission(self):
        self.assertIn(self.client.get(TILES).status_code, (401, 403))
        self.assertEqual(self.member.get(TILES).status_code, 404)
        self.assertFalse(self.member.get("/api/v1/map/config/").data["available"])

    def test_config_and_missing_file(self):
        c = self.officer.get("/api/v1/map/config/").data
        self.assertTrue(c["available"])
        self.assertEqual(len(c["bounds"]), 4)
        self.file.unlink()
        self.assertFalse(self.officer.get("/api/v1/map/config/").data["available"])
        self.assertEqual(self.officer.get(TILES).status_code, 404)
