"""Self-hosted map: serves the Puntland PMTiles file (OpenStreetMap data cut by BBBike with tilemaker, OpenMapTiles layout) from this
server, so the browser never contacts a third party for map tiles. The browser reads the single file with HTTP Range requests, so
this view answers `Range: bytes=a-b` with 206 and only the requested bytes.

Signed-in users with vehicles.view only. The file is public OpenStreetMap data, but keeping it behind the session means the map
cannot be used as an open download from the internet. Missing file: `map/config/` says available=false and the page falls back to
the plain plot."""
import os
import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import scope

# west, south, east, north of the cut (BBBike extract "Puntland"); the map is kept inside this box
BOUNDS = [46.252, 6.548, 51.623, 13.618]
ATTRIBUTION = "© OpenStreetMap contributors · extract by BBBike · tiles by tilemaker"
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def tiles_path():
    return Path(getattr(settings, "MAP_TILES_FILE", "") or (Path(settings.BASE_DIR) / "mapdata" / "puntland.pmtiles"))


def _allowed(user):
    return scope.unit_scope_q(user, "vehicles.view", "org_unit__") is not None


class MapConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        p = tiles_path()
        ok = _allowed(request.user) and p.is_file()
        return Response({"available": bool(ok), "url": "/api/v1/map/puntland.pmtiles", "bounds": BOUNDS, "attribution": ATTRIBUTION,
                        "centre": [48.4845, 8.4054], "zoom": 7, "max_zoom": 14})


class MapTilesView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = []  # a map screen makes dozens of small range reads

    def _file(self, request):
        p = tiles_path()
        if not _allowed(request.user) or not p.is_file():
            return None, HttpResponse(status=404)
        return p, None

    def head(self, request):
        return self.get(request)

    def get(self, request):
        p, err = self._file(request)
        if err:
            return err
        size = os.path.getsize(p)
        etag = f'"{int(os.path.getmtime(p))}-{size}"'
        base = {"Accept-Ranges": "bytes", "ETag": etag, "Cache-Control": "private, max-age=86400", "Content-Type": "application/octet-stream"}
        raw = request.META.get("HTTP_RANGE")
        if not raw:
            r = FileResponse(open(p, "rb"), content_type="application/octet-stream")
            r["Content-Length"] = str(size)
            for k, v in base.items():
                r[k] = v
            return r
        m = _RANGE.match(raw.strip())
        if not m or (m.group(1) == "" and m.group(2) == ""):
            return HttpResponse(status=416, headers={"Content-Range": f"bytes */{size}"})
        if m.group(1) == "":  # the last N bytes
            n = int(m.group(2))
            start, end = max(size - n, 0), size - 1
        else:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            return HttpResponse(status=416, headers={"Content-Range": f"bytes */{size}"})
        length = end - start + 1
        with open(p, "rb") as fh:
            fh.seek(start)
            data = fh.read(length)
        r = HttpResponse(data, status=206, content_type="application/octet-stream")
        for k, v in base.items():
            r[k] = v
        r["Content-Range"] = f"bytes {start}-{end}/{size}"
        r["Content-Length"] = str(len(data))
        return r
