import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

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
    mode_column = "allowed_walk" if data.mode == "walk" else "allowed_car"

    nearest_node_sql = text(f"""
        WITH nearest_segment AS (
            SELECT
                source_node,
                target_node,
                geometry
            FROM road_segments
            WHERE source_node IS NOT NULL
              AND target_node IS NOT NULL
              AND geometry IS NOT NULL
              AND {mode_column} = TRUE
            ORDER BY geometry <-> ST_SetSRID(
                ST_MakePoint(:lng, :lat),
                4326
            )
            LIMIT 1
        ),
        candidate_nodes AS (
            SELECT
                n.osmid AS node_id,
                n.geometry
            FROM road_nodes n
            JOIN nearest_segment ns
              ON n.osmid = ns.source_node

            UNION ALL

            SELECT
                n.osmid AS node_id,
                n.geometry
            FROM road_nodes n
            JOIN nearest_segment ns
              ON n.osmid = ns.target_node
        )
        SELECT node_id
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

    print("MODE:", data.mode)
    print("MODE COLUMN:", mode_column)
    print("START NODE:", start_node)
    print("END NODE:", end_node)

    if start_node is None or end_node is None:
        return {
            "message": "Başlangıç veya bitiş için en yakın node bulunamadı.",
            "start_node": start_node,
            "end_node": end_node,
            "routes": []
        }

    route_profiles = [
        {
            "route_id": 1,
            "label": "En Kısa Rota",
            "color": "#D21A1A",
            "risk_weight": 0
        },
        {
            "route_id": 2,
            "label": "En Güvenli Rota",
            "color": "#2E7D32",
            "risk_weight": 50
        },
        {
            "route_id": 3,
            "label": "Dengeli Rota",
            "color": "#F57C00",
            "risk_weight": 5
        },
    ]

    routes = []

    for profile in route_profiles:
        route_id = profile["route_id"]
        label = profile["label"]
        color = profile["color"]
        risk_weight = profile["risk_weight"]

        rows = db.execute(
            text(f"""
                WITH segment_risk AS (
                    SELECT
                        rsgm.road_segment_id,
                        AVG(crs.normalized_score) AS avg_risk
                    FROM road_segment_grid_map rsgm
                    JOIN cell_risk_scores crs
                        ON crs.cell_id = rsgm.grid_cell_id
                    GROUP BY rsgm.road_segment_id
                ),
                route AS (
                    SELECT *
                    FROM pgr_dijkstra(
                        '
                        SELECT
                            rs.id,
                            rs.source_node AS source,
                            rs.target_node AS target,
                            (
                                rs.length_m
                                + {risk_weight} * rs.length_m * (COALESCE(sr.avg_risk, 0) / 100.0)
                            )::double precision AS cost,
                            (
                                rs.length_m
                                + {risk_weight} * rs.length_m * (COALESCE(sr.avg_risk, 0) / 100.0)
                            )::double precision AS reverse_cost
                        FROM road_segments rs
                        LEFT JOIN (
                            SELECT
                                rsgm.road_segment_id,
                                AVG(crs.normalized_score) AS avg_risk
                            FROM road_segment_grid_map rsgm
                            JOIN cell_risk_scores crs
                                ON crs.cell_id = rsgm.grid_cell_id
                            GROUP BY rsgm.road_segment_id
                        ) sr
                            ON sr.road_segment_id = rs.id
                        WHERE rs.source_node IS NOT NULL
                          AND rs.target_node IS NOT NULL
                          AND rs.length_m IS NOT NULL
                          AND rs.{mode_column} = TRUE
                        ',
                        :start_node,
                        :end_node,
                        directed := false
                    )
                ),
                ordered AS (
                    SELECT
                        route.seq,
                        route.node,
                        route.edge,
                        route.cost,
                        route.agg_cost,
                        LEAD(route.node) OVER (ORDER BY route.seq) AS next_node,

                        rs.source_node,
                        rs.target_node,
                        rs.length_m,
                        COALESCE(sr.avg_risk, 0) AS cell_risk,

                        rs.length_m * COALESCE(sr.avg_risk, 0) AS safety_cost,
                        rs.length_m + (
                            rs.length_m * COALESCE(sr.avg_risk, 0)
                        ) AS total_cost,

                        rs.geometry
                    FROM route
                    JOIN road_segments rs
                        ON route.edge = rs.id
                    LEFT JOIN segment_risk sr
                        ON sr.road_segment_id = rs.id
                    WHERE route.edge <> -1
                )
                SELECT
                    seq,
                    node,
                    edge,
                    cost,
                    agg_cost,
                    length_m,
                    cell_risk,
                    safety_cost,
                    total_cost,
                    ST_AsGeoJSON(
                        CASE
                            WHEN node = source_node AND next_node = target_node
                                THEN geometry
                            WHEN node = target_node AND next_node = source_node
                                THEN ST_Reverse(geometry)
                            ELSE geometry
                        END
                    ) AS edge_geometry
                FROM ordered
                ORDER BY seq;
            """),
            {
                "start_node": int(start_node),
                "end_node": int(end_node),
            }
        ).mappings().all()

        route = {
            "route_id": route_id,
            "route_label": label,
            "label": label,
            "color": color,
            "total_length_m": 0.0,
            "total_length": 0.0,
            "total_risk": 0.0,
            "risk_percent": 0,
            "total_cost": 0.0,
            "risk_level": "Bilinmiyor",
            "segments": [],
            "geometry": [],
        }

        risk_sum = 0.0
        risk_count = 0

        for row in rows:
            edge = row["edge"]

            if edge is None or int(edge) == -1:
                continue

            length_m = float(row["length_m"] or 0)
            cell_risk = float(row["cell_risk"] or 0)
            total_cost = float(row["total_cost"] or 0)

            route["segments"].append(int(edge))
            route["total_length_m"] += length_m
            route["total_length"] = route["total_length_m"]
            route["total_cost"] += total_cost

            risk_sum += cell_risk
            risk_count += 1

            raw_geom = row["edge_geometry"]

            if raw_geom is None:
                continue

            if isinstance(raw_geom, str):
                geom = json.loads(raw_geom)
            else:
                geom = raw_geom

            if geom.get("type") == "LineString":
                coord_groups = [geom.get("coordinates", [])]
            elif geom.get("type") == "MultiLineString":
                coord_groups = geom.get("coordinates", [])
            else:
                coord_groups = []

            for coords in coord_groups:
                for coord in coords:
                    if len(coord) < 2:
                        continue

                    lng = float(coord[0])
                    lat = float(coord[1])
                    point = [lat, lng]

                    if not route["geometry"] or route["geometry"][-1] != point:
                        route["geometry"].append(point)

        if route["segments"]:
            avg_risk = risk_sum / risk_count if risk_count > 0 else 0.0
            risk_percent = min(100, round(avg_risk))

            route["total_risk"] = risk_percent
            route["risk_percent"] = risk_percent

            if risk_percent < 35:
                route["risk_level"] = "Düşük"
            elif risk_percent < 70:
                route["risk_level"] = "Orta"
            else:
                route["risk_level"] = "Yüksek"

            routes.append(route)

        print(
            f"{label} | segments: {len(route['segments'])} | "
            f"geometry: {len(route['geometry'])} | "
            f"length: {route['total_length_m']} | "
            f"risk_percent: {route['risk_percent']}"
        )

    print("ROUTES COUNT:", len(routes))

    return {
        "message": "Rotalar başarıyla hesaplandı.",
        "mode": data.mode,
        "start_node": int(start_node),
        "end_node": int(end_node),
        "routes": routes,
    }