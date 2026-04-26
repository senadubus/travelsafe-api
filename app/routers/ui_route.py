from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
import json

from ..database import get_db
from ..schemas import RouteRequest

router = APIRouter(
    prefix="/api",
    tags=["UI Route"]
)


@router.post("/uiroute")
def calculate_ui_route(
    data: RouteRequest,
    db: Session = Depends(get_db)
):
    nearest_node_sql = text("""
    WITH nearest_segment AS (
        SELECT
            source_node,
            target_node,
            geometry
        FROM road_segments
        WHERE source_node IS NOT NULL
          AND target_node IS NOT NULL
          AND geometry IS NOT NULL
        ORDER BY geometry <-> ST_SetSRID(
            ST_MakePoint(:lng, :lat),
            4326
        )
        LIMIT 1
    ),
    candidate_nodes AS (
        SELECT
            n.id,
            n.geometry
        FROM road_nodes n
        JOIN nearest_segment ns
          ON n.id = ns.source_node

        UNION ALL

        SELECT
            n.id,
            n.geometry
        FROM road_nodes n
        JOIN nearest_segment ns
          ON n.id = ns.target_node
    )
    SELECT id
    FROM candidate_nodes
    ORDER BY geometry <-> ST_SetSRID(
        ST_MakePoint(:lng, :lat),
        4326
    )
    LIMIT 1;
""")
    start_node = db.execute(
        nearest_node_sql,
        {
            "lat": data.start_lat,
            "lng": data.start_lng,
        }
    ).scalar()

    end_node = db.execute(
        nearest_node_sql,
        {
            "lat": data.end_lat,
            "lng": data.end_lng,
        }
    ).scalar()

    if start_node is None or end_node is None:
        return {
            "message": "Başlangıç veya bitiş için en yakın node bulunamadı.",
            "start_node": start_node,
            "end_node": end_node,
            "routes": []
        }

    rows = db.execute(
        text("""
            WITH ksp AS (
                SELECT *
                FROM pgr_ksp(
                    '
                    SELECT
                        id,
                        source_node AS source,
                        target_node AS target,
                        length_m AS cost,
                        length_m AS reverse_cost
                    FROM road_segments
                    WHERE source_node IS NOT NULL
                    AND target_node IS NOT NULL
                    AND length_m IS NOT NULL
                    ',
                    :start_node,
                    :end_node,
                    3,
                    directed := false
                )
            )
            SELECT
                ksp.path_id,
                ksp.seq,
                ksp.node,
                ksp.edge,
                ksp.cost,
                rs.length_m,
                ST_AsGeoJSON(rs.geometry) AS geometry
            FROM ksp
            JOIN road_segments rs
            ON ksp.edge = rs.id
            WHERE ksp.edge <> -1
            ORDER BY ksp.path_id, ksp.seq;
        """),
        {
            "start_node": start_node,
            "end_node": end_node,
        }
    ).mappings().all()
    
    grouped_routes = {}

    for row in rows:
        path_id = int(row["path_id"])
        edge = row["edge"]

        if edge is None or int(edge) == -1:
            continue

        if path_id not in grouped_routes:
            grouped_routes[path_id] = {
                "route_id": path_id,
                "total_length_m": 0.0,
                "segments": [],
                "geometry": []
            }

        grouped_routes[path_id]["segments"].append(int(edge))
        grouped_routes[path_id]["total_length_m"] += float(row["length_m"] or 0)

        geom = row["geometry"]

        if isinstance(geom, str):
            geom = json.loads(geom)

        if geom and geom.get("type") == "LineString":
            for coord in geom.get("coordinates", []):
                lng = coord[0]
                lat = coord[1]
                grouped_routes[path_id]["geometry"].append([lat, lng])

        elif geom and geom.get("type") == "MultiLineString":
            for line in geom.get("coordinates", []):
                for coord in line:
                    lng = coord[0]
                    lat = coord[1]
                    grouped_routes[path_id]["geometry"].append([lat, lng])

    routes = list(grouped_routes.values())

    
    print("ROUTES COUNT:", len(routes))
    print("START NODE:", start_node)
    print("END NODE:", end_node)
    print("ROUTE ROWS:", len(rows))
    print("ROUTES COUNT:", len(routes))

    return {
        "message": "Rotalar başarıyla hesaplandı.",
        "start_node": int(start_node),
        "end_node": int(end_node),
        "routes": routes,
    }
