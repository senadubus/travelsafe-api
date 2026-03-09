from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

router = APIRouter(prefix="/api/crimes", tags=["crimes"])


@router.get("/points")
def get_crime_points(
    min_lat: float = Query(...),
    min_lng: float = Query(...),
    max_lat: float = Query(...),
    max_lng: float = Query(...),
    days: int = Query(30, ge=1, le=3650),
    limit: int = Query(300, ge=1, le=2000),
    crime_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    q = text("""
    WITH bounds AS (
      SELECT ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326) AS bbox
    )
    SELECT
      "ID" AS id,
      "Primary Type" AS crime_type,
      "Description" AS description,
      "Date" AS crime_date,
      ST_Y(geom::geometry) AS lat,
      ST_X(geom::geometry) AS lng
    FROM crime, bounds
    WHERE geom IS NOT NULL
      AND "Date" >= (NOW() - (:days || ' days')::interval)
      AND geom::geometry && bounds.bbox
      AND ST_Intersects(geom::geometry, bounds.bbox)
      AND (:crime_type IS NULL OR "Primary Type" = :crime_type)
    ORDER BY "Date" DESC
    LIMIT :limit
    """)

    rows = db.execute(
        q,
        {
            "min_lat": min_lat,
            "min_lng": min_lng,
            "max_lat": max_lat,
            "max_lng": max_lng,
            "days": days,
            "limit": limit,
            "crime_type": crime_type,
        },
    ).mappings().all()

    return {
        "count": len(rows),
        "points": [dict(r) for r in rows],
    }