import json
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import heapq

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class Edge:
    segment_id: int
    source: int
    target: int
    length_m: float
    risk_score: float


@dataclass
class RouteResult:
    path_nodes: List[int]
    segment_ids: List[int]
    total_length_m: float
    total_risk: float
    total_cost: float


def get_nearest_node(db: Session, lat: float, lng: float) -> int:
    sql = text("""
        SELECT osmid
        FROM road_nodes
        WHERE osmid IS NOT NULL
        ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
        LIMIT 1
    """)
    row = db.execute(sql, {"lat": lat, "lng": lng}).fetchone()

    if not row:
        raise ValueError("En yakın road node bulunamadı.")

    return row.osmid

def load_graph_edges(db: Session) -> List[Edge]:
    sql = text("""
        SELECT
            rs.id AS segment_id,
            rs.source_node,
            rs.target_node,
            COALESCE(rs.length_m, rs.length, 0) AS length_m,
            COALESCE(rsv.risk_score, 0) AS risk_score
        FROM road_segments rs
        LEFT JOIN road_segment_risk_view rsv
            ON rs.id = rsv.road_segment_id
        WHERE rs.source_node IS NOT NULL
          AND rs.target_node IS NOT NULL
    """)

    rows = db.execute(sql).fetchall() or []
    edges: List[Edge] = []

    for row in rows:
        length_m = float(row.length_m or 0.0)
        risk_score = float(row.risk_score or 0.0)

        # ileri yön
        edges.append(
            Edge(
                segment_id=row.segment_id,
                source=row.source_node,
                target=row.target_node,
                length_m=length_m,
                risk_score=risk_score,
            )
        )

        # şimdilik çift yönlü
        edges.append(
            Edge(
                segment_id=row.segment_id,
                source=row.target_node,
                target=row.source_node,
                length_m=length_m,
                risk_score=risk_score,
            )
        )

    return edges

def load_node_coordinates(db: Session) -> Dict[int, Tuple[float, float]]:
    sql = text("""
        SELECT
            osmid,
            ST_Y(geometry) AS lat,
            ST_X(geometry) AS lng
        FROM road_nodes
        WHERE osmid IS NOT NULL
    """)

    rows = db.execute(sql).fetchall() or []

    return {
        row.osmid: (float(row.lat), float(row.lng))
        for row in rows
        if row.lat is not None and row.lng is not None
    }

def load_segment_geometries(db: Session, segment_ids: List[int]) -> Dict[int, List[List[float]]]:
    if not segment_ids:
        return {}

    sql = text("""
        SELECT
            id,
            ST_AsGeoJSON(geometry) AS geojson
        FROM road_segments
        WHERE id = ANY(:segment_ids)
    """)

    rows = db.execute(sql, {"segment_ids": segment_ids}).fetchall() or []

    result = {}

    for row in rows:
        if not row.geojson:
            result[row.id] = []
            continue

        geojson = json.loads(row.geojson)
        coords = geojson.get("coordinates") or []

        latlngs = []
        for point in coords:
            if not point or len(point) < 2:
                continue
            lng, lat = point[0], point[1]
            latlngs.append([lat, lng])

        result[row.id] = latlngs

    return result

def build_graph(edges: List[Edge]) -> Dict[int, List[Edge]]:
    graph = defaultdict(list)
    for edge in edges or []:
        graph[edge.source].append(edge)
    return graph

def heuristic(node_a: int, node_b: int, node_coords: Dict[int, Tuple[float, float]]) -> float:
    if node_a not in node_coords or node_b not in node_coords:
        return 0.0

    lat1, lng1 = node_coords[node_a]
    lat2, lng2 = node_coords[node_b]

    dx = (lng2 - lng1) * 111320
    dy = (lat2 - lat1) * 110540
    return (dx * dx + dy * dy) ** 0.5

def reconstruct_route(
    start_node: int,
    goal_node: int,
    parent_node: Dict[int, int],
    parent_edge: Dict[int, Edge],
    distance_weight: float,
    risk_weight: float,
    penalized_segments: Dict[int, float],
) -> Optional[RouteResult]:
    if goal_node not in parent_edge and goal_node != start_node:
        return None

    path_nodes = [goal_node]
    segment_ids = []
    total_length_m = 0.0
    total_risk = 0.0
    total_cost = 0.0

    current = goal_node

    while current != start_node:
        edge = parent_edge.get(current)
        prev_node = parent_node.get(current)

        if edge is None or prev_node is None:
            return None

        path_nodes.append(prev_node)
        segment_ids.append(edge.segment_id)

        total_length_m += edge.length_m
        total_risk += edge.risk_score
        total_cost += (
            distance_weight * edge.length_m
            + risk_weight * edge.risk_score
            + penalized_segments.get(edge.segment_id, 0.0)
        )

        current = prev_node

    path_nodes.reverse()
    segment_ids.reverse()

    return RouteResult(
        path_nodes=path_nodes,
        segment_ids=segment_ids,
        total_length_m=total_length_m,
        total_risk=total_risk,
        total_cost=total_cost,
    )

def a_star_with_bans(
    graph: Dict[int, List[Edge]],
    node_coords: Dict[int, Tuple[float, float]],
    start_node: int,
    goal_node: int,
    banned_edges: set[tuple[int, int]],
    banned_nodes: set[int],
    distance_weight: float = 1.0,
    risk_weight: float = 1.0,
) -> Optional[RouteResult]:
    if start_node == goal_node:
        return RouteResult(
            path_nodes=[start_node],
            segment_ids=[],
            total_length_m=0.0,
            total_risk=0.0,
            total_cost=0.0,
        )

    open_heap = []
    heapq.heappush(open_heap, (0.0, start_node))

    g_cost = {start_node: 0.0}
    parent_node: Dict[int, int] = {}
    parent_edge: Dict[int, Edge] = {}
    visited = set()

    while open_heap:
        _, current = heapq.heappop(open_heap)

        if current in visited:
            continue
        visited.add(current)

        if current == goal_node:
            return reconstruct_route(
                start_node=start_node,
                goal_node=goal_node,
                parent_node=parent_node,
                parent_edge=parent_edge,
                distance_weight=distance_weight,
                risk_weight=risk_weight,
                penalized_segments={},
            )

        for edge in graph.get(current, []) or []:
            if (edge.source, edge.target) in banned_edges:
                continue

            if edge.target in banned_nodes:
                continue

            edge_cost = distance_weight * edge.length_m + risk_weight * edge.risk_score
            tentative_g = g_cost[current] + edge_cost

            if edge.target not in g_cost or tentative_g < g_cost[edge.target]:
                g_cost[edge.target] = tentative_g
                parent_node[edge.target] = current
                parent_edge[edge.target] = edge

                h = heuristic(edge.target, goal_node, node_coords)
                f = tentative_g + h
                heapq.heappush(open_heap, (f, edge.target))

    return None

def merge_route_geometry(segment_ids: List[int], segment_geoms: Dict[int, List[List[float]]]) -> List[List[float]]:
    if not segment_ids:
        return []

    full_geometry: List[List[float]] = []

    for i, seg_id in enumerate(segment_ids):
        coords = segment_geoms.get(seg_id) or []
        if not coords:
            continue

        if i == 0:
            full_geometry.extend(coords)
        else:
            full_geometry.extend(coords[1:])

    return full_geometry

def route_overlap_ratio(route_a: RouteResult, route_b: RouteResult) -> float:
    a = set(route_a.segment_ids or [])
    b = set(route_b.segment_ids or [])

    if not a or not b:
        return 0.0

    common = len(a.intersection(b))
    base = min(len(a), len(b))
    if base == 0:
        return 0.0

    return common / base

def build_route_dict(label: str, route: RouteResult, segment_geoms: dict) -> dict:
    return {
        "route_label": label,
        "path_nodes": route.path_nodes or [],
        "segment_ids": route.segment_ids or [],
        "total_length_m": round(route.total_length_m or 0.0, 2),
        "total_risk": round(route.total_risk or 0.0, 4),
        "total_cost": round(route.total_cost or 0.0, 4),
        "geometry": merge_route_geometry(route.segment_ids or [], segment_geoms),
    }


def find_profile_routes(
    graph,
    node_coords,
    start_node: int,
    goal_node: int,
) -> List[tuple[str, RouteResult]]:
    configs = [
        ("Shortest", 1.0, 0.0),
        ("Balanced", 1.0, 1.5),
        ("Safest", 1.0, 4.0),
    ]

    routes: List[tuple[str, RouteResult]] = []

    for label, distance_weight, risk_weight in configs:
        route = a_star(
            graph=graph,
            node_coords=node_coords,
            start_node=start_node,
            goal_node=goal_node,
            distance_weight=distance_weight,
            risk_weight=risk_weight,
            penalized_segments={},
        )

        print(f"{label} ROUTE = {route}")

        if route is not None:
            routes.append((label, route))

    return routes
def edge_cost_for_route(edge: Edge, distance_weight: float, risk_weight: float) -> float:
    return distance_weight * edge.length_m + risk_weight * edge.risk_score

def extract_root_route(full_route: RouteResult, spur_index: int) -> RouteResult:
    return RouteResult(
        path_nodes=full_route.path_nodes[:spur_index + 1],
        segment_ids=full_route.segment_ids[:spur_index],
        total_length_m=0.0,
        total_risk=0.0,
        total_cost=0.0,
    )


def compute_partial_cost(
    graph: Dict[int, List[Edge]],
    path_nodes: List[int],
    distance_weight: float,
    risk_weight: float,
) -> tuple[float, float, float, List[int]]:
    total_length = 0.0
    total_risk = 0.0
    total_cost = 0.0
    segment_ids = []

    for i in range(len(path_nodes) - 1):
        u = path_nodes[i]
        v = path_nodes[i + 1]

        found = None
        for edge in graph.get(u, []):
            if edge.target == v:
                found = edge
                break

        if found is None:
            raise ValueError(f"Edge not found between {u} and {v}")

        segment_ids.append(found.segment_id)
        total_length += found.length_m
        total_risk += found.risk_score
        total_cost += distance_weight * found.length_m + risk_weight * found.risk_score

    return total_length, total_risk, total_cost, segment_ids

def combine_routes(
    root_nodes: List[int],
    spur_route: RouteResult,
    graph: Dict[int, List[Edge]],
    distance_weight: float,
    risk_weight: float,
) -> RouteResult:
    if not root_nodes:
        return spur_route

    combined_nodes = root_nodes[:-1] + (spur_route.path_nodes or [])
    length_1, risk_1, cost_1, segs_1 = compute_partial_cost(
        graph, root_nodes, distance_weight, risk_weight
    )
    length_2 = spur_route.total_length_m or 0.0
    risk_2 = spur_route.total_risk or 0.0
    cost_2 = spur_route.total_cost or 0.0

    combined_seg_ids = segs_1 + (spur_route.segment_ids or [])

    return RouteResult(
        path_nodes=combined_nodes,
        segment_ids=combined_seg_ids,
        total_length_m=length_1 + length_2,
        total_risk=risk_1 + risk_2,
        total_cost=cost_1 + cost_2,
    )

def find_k_shortest_routes(
    graph: Dict[int, List[Edge]],
    node_coords: Dict[int, Tuple[float, float]],
    start_node: int,
    goal_node: int,
    k: int = 3,
    distance_weight: float = 1.0,
    risk_weight: float = 1.0,
    max_overlap: float = 0.85,
) -> List[RouteResult]:
    first_route = a_star(
        graph=graph,
        node_coords=node_coords,
        start_node=start_node,
        goal_node=goal_node,
        distance_weight=distance_weight,
        risk_weight=risk_weight,
        penalized_segments={},
    )

    if first_route is None:
        return []

    A: List[RouteResult] = [first_route]
    B: List[RouteResult] = []

    for kth in range(1, k):
        previous_route = A[-1]

        for spur_index in range(len(previous_route.path_nodes) - 1):
            spur_node = previous_route.path_nodes[spur_index]
            root_path_nodes = previous_route.path_nodes[:spur_index + 1]

            banned_edges = set()
            banned_nodes = set(root_path_nodes[:-1])

            for route in A:
                if route.path_nodes[:spur_index + 1] == root_path_nodes:
                    u = route.path_nodes[spur_index]
                    v = route.path_nodes[spur_index + 1]
                    banned_edges.add((u, v))

            spur_route = a_star_with_bans(
                graph=graph,
                node_coords=node_coords,
                start_node=spur_node,
                goal_node=goal_node,
                banned_edges=banned_edges,
                banned_nodes=banned_nodes,
                distance_weight=distance_weight,
                risk_weight=risk_weight,
            )

            if spur_route is None:
                continue

            total_route = combine_routes(
                root_nodes=root_path_nodes,
                spur_route=spur_route,
                graph=graph,
                distance_weight=distance_weight,
                risk_weight=risk_weight,
            )

            is_duplicate = any(r.path_nodes == total_route.path_nodes for r in A + B)
            if is_duplicate:
                continue

            too_similar = any(route_overlap_ratio(total_route, existing) > max_overlap for existing in A)
            if too_similar:
                continue

            B.append(total_route)

        if not B:
            break

        B.sort(key=lambda r: r.total_cost)
        best_candidate = B.pop(0)
        A.append(best_candidate)

    return A

def find_routes_bundle(
    db: Session,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> dict:
    start_node = get_nearest_node(db, start_lat, start_lng)
    goal_node = get_nearest_node(db, end_lat, end_lng)

    print(f"START NODE = {start_node}")
    print(f"GOAL NODE = {goal_node}")

    edges = load_graph_edges(db)
    graph = build_graph(edges)
    node_coords = load_node_coordinates(db)

    profile_routes = find_profile_routes(
        graph=graph,
        node_coords=node_coords,
        start_node=start_node,
        goal_node=goal_node,
    )

    alternative_routes = find_k_shortest_routes(
        graph=graph,
        node_coords=node_coords,
        start_node=start_node,
        goal_node=goal_node,
        k=3,
        distance_weight=1.0,
        risk_weight=1.0,
        max_overlap=0.85,
    )

    all_segment_ids = list({
        seg_id
        for _, route in profile_routes
        for seg_id in (route.segment_ids or [])
    } | {
        seg_id
        for route in alternative_routes
        for seg_id in (route.segment_ids or [])
    })

    segment_geoms = load_segment_geometries(db, all_segment_ids)

    profile_results = [
        build_route_dict(label, route, segment_geoms)
        for label, route in profile_routes
    ]

    alt_results = [
        build_route_dict(f"Alternative {i+1}", route, segment_geoms)
        for i, route in enumerate(alternative_routes)
    ]

    return {
        "profile_routes": profile_results,
        "alternative_routes": alt_results,
    }

def find_named_routes(
    db: Session,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> List[dict]:
    start_node = get_nearest_node(db, start_lat, start_lng)
    goal_node = get_nearest_node(db, end_lat, end_lng)

    print(f"START NODE = {start_node}")
    print(f"GOAL NODE = {goal_node}")

    edges = load_graph_edges(db)
    graph = build_graph(edges)
    node_coords = load_node_coordinates(db)

    configs = [
        ("Shortest", 1.0, 0.0),
        ("Balanced", 1.0, 1.5),
        ("Safest", 1.0, 4.0),
    ]

    routes: List[tuple[str, RouteResult]] = []

    for label, distance_weight, risk_weight in configs:
        route = a_star(
            graph=graph,
            node_coords=node_coords,
            start_node=start_node,
            goal_node=goal_node,
            distance_weight=distance_weight,
            risk_weight=risk_weight,
            penalized_segments={},
        )

        print(f"{label} ROUTE = {route}")

        if route is not None:
            routes.append((label, route))

    if not routes:
        return []

    all_segment_ids = list({
        seg_id
        for _, route in routes
        for seg_id in (route.segment_ids or [])
    })

    segment_geoms = load_segment_geometries(db, all_segment_ids)

    results = []
    for label, route in routes:
        results.append({
            "route_label": label,
            "path_nodes": route.path_nodes or [],
            "segment_ids": route.segment_ids or [],
            "total_length_m": round(route.total_length_m or 0.0, 2),
            "total_risk": round(route.total_risk or 0.0, 4),
            "total_cost": round(route.total_cost or 0.0, 4),
            "geometry": merge_route_geometry(route.segment_ids or [], segment_geoms),
        })

    return results