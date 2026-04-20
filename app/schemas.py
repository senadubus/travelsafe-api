from typing import List
from pydantic import BaseModel

class CrimePoint(BaseModel):
    crime: str | None
    lat: float
    lng: float

class HeatClusterOut(BaseModel):
    lat: float
    lng: float
    count: int
    
class RouteRequest(BaseModel):
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    distance_weight: float = 1.0
    risk_weight: float = 2.0
    penalty_factor: float = 500.0


class RouteOption(BaseModel):
    route_label: str
    path_nodes: List[int]
    segment_ids: List[int]
    total_length_m: float
    total_risk: float
    total_cost: float
    geometry: List[List[float]]


class RouteBundleResponse(BaseModel):
    profile_routes: List[RouteOption]
    alternative_routes: List[RouteOption]

