from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from PIL import Image, ImageDraw, ImageFilter
import io
import math

from ..database import get_db

router = APIRouter(prefix="/tiles", tags=["tiles"])

def grid_meters_for_zoom(z: int) -> float:
    # zoom küçüldükçe daha iri grid (daha az nokta)
    if z <= 9:  return 2000.0
    if z <= 11: return 1200.0
    if z <= 13: return 700.0
    if z <= 15: return 350.0
    return 200.0

@router.get("/heat/{z}/{x}/{y}.png")
def heat_tile(
    z: int, x: int, y: int,
    days: int = Query(90, ge=1, le=3650),
    crime_type: str | None = None,
    db: Session = Depends(get_db),
):
    # Tile envelope: WebMercator (EPSG:3857)
    # PostGIS: ST_TileEnvelope(z, x, y) -> 3857 polygon
    cell = grid_meters_for_zoom(z)

    q = text("""
    WITH tile AS (
      SELECT ST_TileEnvelope(:z, :x, :y) AS env
    ),
    filtered AS (
      SELECT ST_Transform(geom::geometry, 3857) AS g
      FROM crime, tile
      WHERE "Date" >= (NOW() - (:days || ' days')::interval)
        AND geom IS NOT NULL
        AND geom::geometry && ST_Transform(tile.env, 4326)
        AND ST_Transform(geom::geometry, 3857) && tile.env
        AND (:crime_type IS NULL OR "Primary Type" = :crime_type)
    ),
    binned AS (
      SELECT
        ST_SnapToGrid(g, :cell) AS cellgeom,
        COUNT(*) AS cnt
      FROM filtered
      GROUP BY cellgeom
    )
    SELECT
      ST_X(ST_Centroid(cellgeom)) AS mx,
      ST_Y(ST_Centroid(cellgeom)) AS my,
      cnt
    FROM binned
    ORDER BY cnt DESC
    LIMIT 250;
    """)

    rows = db.execute(q, {
        "z": z, "x": x, "y": y,
        "days": days,
        "crime_type": crime_type,
        "cell": cell,
    }).mappings().all()

    # Tile bounds in 3857 to convert meters -> pixel
    bq = text("SELECT ST_XMin(env) AS minx, ST_YMin(env) AS miny, ST_XMax(env) AS maxx, ST_YMax(env) AS maxy FROM (SELECT ST_TileEnvelope(:z,:x,:y) AS env) t;")
    b = db.execute(bq, {"z": z, "x": x, "y": y}).mappings().one()
    minx, miny, maxx, maxy = float(b["minx"]), float(b["miny"]), float(b["maxx"]), float(b["maxy"])

    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    # cnt -> radius/alpha
    for r in rows:
        mx, my, cnt = float(r["mx"]), float(r["my"]), int(r["cnt"])

        px = int((mx - minx) / (maxx - minx) * 256)
        py = int((maxy - my) / (maxy - miny) * 256)

        score = math.log(1 + cnt)

        alpha = int(min(150, 45 + score * 18))
        radius = int(min(55, 10 + score * 7))

        draw.ellipse(
            (px - radius, py - radius, px + radius, py + radius),
            fill=(255, 0, 0, alpha)
        )
    img = img.filter(ImageFilter.GaussianBlur(radius=10))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png = buf.getvalue()

    return Response(
        content=png,
        media_type="image/png",
        headers={
            # debug modda düşük tut; prod’da arttırırsın
            "Cache-Control": "public, max-age=60",
        },
    )
