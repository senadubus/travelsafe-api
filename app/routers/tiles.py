from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from PIL import Image, ImageDraw, ImageFilter
import io
import math

from ..database import get_db

router = APIRouter(prefix="/tiles", tags=["tiles"])


def grid_meters_for_zoom(z: int) -> float:
    if z <= 9:
        return 2000.0
    if z <= 11:
        return 1200.0
    if z <= 13:
        return 500.0
    if z < 15:
        return 200.0
    return None


def zoom_blur(z: int) -> int | None:
    if z <= 9:
        return 6
    if z == 10:
        return 6
    if z == 11:
        return 6   # artırdık
    if z == 12:
        return 5
    if z == 13:
        return 4
    if z == 14:
        return 3
    return None


def zoom_radius_multiplier(z: int) -> float:
    if z <= 9:
        return 0.35
    if z == 10:
        return 0.35
    if z == 11:
        return 0.48
    if z == 12:
        return 0.58
    if z == 13:
        return 0.68
    if z == 14:
        return 0.78
    return 0.35


def zoom_alpha_multiplier(z: int) -> float:
    if z <= 9:
        return 1.5
    if z == 10:
        return 1.5
    if z == 11:
        return 1.6
    if z == 12:
        return 1.3
    if z == 13:
        return 1.4
    if z == 14:
        return 1.4
    return 1.3


def empty_png(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/heat/{z}/{x}/{y}.png")
def heat_tile(
    z: int,
    x: int,
    y: int,
    days: int = Query(365, ge=1, le=3650),
    crime_type: str | None = None,
    db: Session = Depends(get_db),
):
    cell_m = grid_meters_for_zoom(z)
    if cell_m is None:
        return empty_png()

    sql = text("""
    WITH tile AS (
        SELECT ST_TileEnvelope(:z, :x, :y) AS geom_3857
    ),
    crimes_in_tile AS (
        SELECT
            ST_Transform(c.geom::geometry, 3857) AS geom_3857
        FROM crime c, tile t
        WHERE c."Date" >= NOW() - (:days || ' days')::interval
          AND ST_Intersects(ST_Transform(c.geom::geometry, 3857), t.geom_3857)
          AND (:crime_type IS NULL OR c."Primary Type" = :crime_type)
    ),
    gridded AS (
        SELECT
            FLOOR(ST_X(geom_3857) / :cell_m) * :cell_m AS gx,
            FLOOR(ST_Y(geom_3857) / :cell_m) * :cell_m AS gy,
            COUNT(*) AS cnt
        FROM crimes_in_tile
        GROUP BY 1, 2
    )
    SELECT gx, gy, cnt
    FROM gridded
    """)

    rows = db.execute(sql, {
        "z": z,
        "x": x,
        "y": y,
        "days": days,
        "crime_type": crime_type,
        "cell_m": cell_m,
    }).mappings().all()

    if not rows:
        return empty_png()

    counts = [int(row["cnt"]) for row in rows if row["cnt"] is not None]
    if not counts:
        return empty_png()

    max_log = max(math.log1p(c) for c in counts)
    if max_log == 0:
        return empty_png()

    sql_bounds = text("""
        SELECT
            ST_XMin(ST_TileEnvelope(:z, :x, :y)) AS minx,
            ST_YMin(ST_TileEnvelope(:z, :x, :y)) AS miny,
            ST_XMax(ST_TileEnvelope(:z, :x, :y)) AS maxx,
            ST_YMax(ST_TileEnvelope(:z, :x, :y)) AS maxy
    """)
    bounds = db.execute(sql_bounds, {"z": z, "x": x, "y": y}).mappings().first()

    minx, miny, maxx, maxy = bounds["minx"], bounds["miny"], bounds["maxx"], bounds["maxy"]
    tile_w = maxx - minx
    tile_h = maxy - miny

    size = 256
    pad = 32
    canvas_size = size + 2 * pad

    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    alpha_mul = zoom_alpha_multiplier(z)
    radius_mul = zoom_radius_multiplier(z)

    for row in rows:
        gx = float(row["gx"])
        gy = float(row["gy"])
        cnt = int(row["cnt"])

        intensity = math.log1p(cnt) / max_log
        if intensity < 0.05:
            continue

        # z 9-10 görünümünü koruyup 11-14'ü biraz parlatıyoruz
        if intensity < 0.20:
            base_color = (90, 140, 255, 45)     # yumuşak mavi
        elif intensity < 0.40:
            base_color = (80, 210, 255, 65)     # sakin cyan
        elif intensity < 0.60:
            base_color = (255, 220, 110, 90)    # yumuşak sarı
        elif intensity < 0.80:
            base_color = (255, 170, 80, 120)    # pastel turuncu
        else:
            base_color = (255, 95, 95, 150)     # yumuşak kırmızı

        r0, g0, b0, a0 = base_color
        a = min(255, int(a0 * zoom_alpha_multiplier(z)))
        color = (r0, g0, b0, a)

        cx = int(((gx + cell_m / 2 - minx) / tile_w) * size) + pad
        cy = int((1 - ((gy + cell_m / 2 - miny) / tile_h)) * size) + pad

        pixel_cell = max(1.0, (cell_m / tile_w) * size)

        # 11-14 için daha büyük radius
        r = max(4, int(pixel_cell * radius_mul))

        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        
    print(f"🔍🔍🔍 MAP ZOOM LEVEL >>>>>>>> {z} 🔍🔍🔍")
    print(f"🔍🔍🔍 MAP ZOOM LEVEL >>>>>>>> {z} 🔍🔍🔍")
    print(f"🔍🔍🔍 MAP ZOOM LEVEL >>>>>>>> {z} 🔍🔍🔍")
    print(f"🔍🔍🔍 MAP ZOOM LEVEL >>>>>>>> {z} 🔍🔍🔍")
    print(f"🔍🔍🔍 MAP ZOOM LEVEL >>>>>>>> {z} 🔍🔍🔍")
    print(f"🔍🔍🔍 MAP ZOOM LEVEL >>>>>>>> {z} 🔍🔍🔍")

    buf = io.BytesIO()
    radius = zoom_blur(z)
    if radius is not None:
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))

    img = img.crop((pad, pad, pad + size, pad + size))
    img.save(buf, format="PNG")

    print(f"heat tile => z={z} x={x} y={y} rows={len(rows)}")
    return Response(content=buf.getvalue(), media_type="image/png")
#zoom level 15'ten sonra markerları göster

