"""Self-hosted map tiles: HTTP Range answers, sign-in and permission. Synthetic data only."""
import tempfile
from pathlib import Path

from django.test import override_settings

from apps.vehicles.tests.test_vehicles import VehicleBase

TILES = "/api/v1/map/puntland.pmtiles"


def body(r):
    return b"".join(r.streaming_content)


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
        self.assertEqual(body(r), bytes(range(10)))
        self.assertEqual(r["Content-Range"], "bytes 0-9/1024")
        tail = self.officer.get(TILES, HTTP_RANGE="bytes=-4")
        self.assertEqual((tail.status_code, body(tail)), (206, bytes([252, 253, 254, 255])))
        open_end = self.officer.get(TILES, HTTP_RANGE="bytes=1020-")
        self.assertEqual(len(body(open_end)), 4)
        self.assertEqual(self.officer.get(TILES, HTTP_RANGE="bytes=5000-6000").status_code, 416)
        self.assertEqual(self.officer.get(TILES, HTTP_RANGE="items=0-1").status_code, 416)

    def test_large_range_is_streamed_in_pieces(self):
        from apps.vehicles import maptiles
        big = bytes(range(256)) * 2048  # 512 KB, two 256 KB pieces
        self.file.write_bytes(big)
        r = self.officer.get(TILES, HTTP_RANGE="bytes=100-524000")
        self.assertEqual((r.status_code, r["Content-Length"]), (206, str(524000 - 100 + 1)))
        self.assertEqual(body(r), big[100:524001])
        self.assertGreater(len(list(maptiles._stream(self.file, 0, len(big)))), 1)

    def test_shipped_tile_parts_are_a_pmtiles_file(self):
        """The three parts in backend/mapdata join into one PMTiles v3 file (or the joined file is already there)."""
        from django.conf import settings
        d = Path(settings.BASE_DIR) / "mapdata"
        parts = sorted(d.glob("puntland.pmtiles.part*"))
        joined = d / "puntland.pmtiles"
        if not parts and not joined.is_file():
            self.skipTest("map data not present in this checkout")
        first = parts[0] if parts else joined
        head = first.read_bytes()[:8]
        self.assertEqual(head[:7], b"PMTiles")
        self.assertEqual(head[7], 3)

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
