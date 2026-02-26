from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db

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