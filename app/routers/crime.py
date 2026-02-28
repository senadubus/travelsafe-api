from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..schemas import HeatClusterOut

router = APIRouter(prefix="/api/crimes", tags=["crimes"])


@router.get("")
def list_crime_points(
    limit: int = Query(5000, ge=1, le=50000),
    db: Session = Depends(get_db),
):
    sql = text("""
        SELECT
            "Primary Type" AS crime,
            "Latitude"     AS lat,
            "Longitude"    AS lng
        FROM crime
        WHERE "Latitude" IS NOT NULL
          AND "Longitude" IS NOT NULL
        LIMIT :limit
    """)

    rows = db.execute(sql, {"limit": limit}).mappings().all()
    # rows: [{"crime": "...", "lat": ..., "lng": ...}, ...]

    return [
        {"crime": r["crime"], "lat": float(r["lat"]), "lng": float(r["lng"])}
        for r in rows
    ]

def cell_size_deg(zoom: int) -> float:
    if zoom <= 10: return 0.03
    if zoom <= 12: return 0.018
    if zoom <= 14: return 0.010
    return 0.006

@router.get("/heat", response_model=list[HeatClusterOut])
def heat(
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    zoom: int = 12,
    days: int = 365,
    crime_type: str | None = None,
    limit: int = 800,
    db: Session = Depends(get_db),
):
    cell = cell_size_deg(zoom)

    q = text("""
    WITH filtered AS (
      SELECT "Latitude" AS lat, "Longitude" AS lng
      FROM crime
      WHERE "Date" >= (NOW() - (:days || ' days')::interval)
        AND (geom::geometry && ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326))
        AND (:crime_type IS NULL OR "Primary Type" = :crime_type)
    ),
    binned AS (
      SELECT
        FLOOR(lat / :cell) AS gx,
        FLOOR(lng / :cell) AS gy,
        COUNT(*)           AS cnt,
        AVG(lat)           AS clat,
        AVG(lng)           AS clng
      FROM filtered
      GROUP BY gx, gy
    )
    SELECT clat AS lat, clng AS lng, cnt AS count
    FROM binned
    ORDER BY cnt DESC
    LIMIT :limit;
    """)

    rows = db.execute(q, {
        "min_lat": min_lat, "min_lng": min_lng,
        "max_lat": max_lat, "max_lng": max_lng,
        "days": days,
        "crime_type": crime_type,
        "cell": cell,
        "limit": limit,
    }).mappings().all()

    return list(rows)