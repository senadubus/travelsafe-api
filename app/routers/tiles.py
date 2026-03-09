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
        return 600.0
    if z <= 15:
        return 250.0
    if z <= 17:
        return 120.0
    return 200.0

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

    # hiç veri yoksa boş tile dön
    if not rows:
        return empty_png()

    counts = [int(row["cnt"]) for row in rows if row["cnt"] is not None]

    # güvenlik amaçlı ikinci kontrol
    if not counts:
        return empty_png()

    max_log = max(math.log1p(c) for c in counts)
    if max_log == 0:
        return empty_png()

    # tile sınırları
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

    for row in rows:
        gx = float(row["gx"])
        gy = float(row["gy"])
        cnt = int(row["cnt"])

        intensity = math.log1p(cnt) / max_log
        if intensity < 0.05:
            continue 

        # grid hücresini tile pikseline çevir
        x1 = int(((gx - minx) / tile_w) * size) + pad
        x2 = int((((gx + cell_m) - minx) / tile_w) * size) + pad

        # y ekseni ters
        y1 = int((1 - ((gy + cell_m - miny) / tile_h)) * size) + pad
        y2 = int((1 - ((gy - miny) / tile_h)) * size) + pad

        x1 = max(0, min(canvas_size - 1, x1))
        x2 = max(0, min(canvas_size, x2))
        y1 = max(0, min(canvas_size - 1, y1))
        y2 = max(0, min(canvas_size, y2))

        if x2 > x1 and y2 > y1:
               
            if intensity < 0.2:
                color = (0, 0, 255, 60)       # mavi
            elif intensity < 0.4:
                color = (0, 255, 255, 90)     # cyan
            elif intensity < 0.6:
                color = (255, 255, 0, 120)    # sarı
            elif intensity < 0.8:
                color = (255, 165, 0, 160)    # turuncu
            else:
                color = (255, 0, 0, 210)
            cx = int(((gx + cell_m / 2 - minx) / tile_w) * size) + pad
            cy = int((1 - ((gy + cell_m / 2 - miny) / tile_h)) * size) + pad
            radius = int(10 + 22 * intensity)
            draw.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                fill=color,
            )
    blur = 10 if z <= 12 else 8 if z <= 14 else 6
    buf = io.BytesIO()
    img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    img = img.crop((pad, pad, pad + size, pad + size))
    img.save(buf, format="PNG")
    print(f"z={z} x={x} y={y} rows={len(rows)}")
    return Response(content=buf.getvalue(), media_type="image/png")
