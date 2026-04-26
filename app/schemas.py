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

class RouteOption(BaseModel):
    route_label: str
    path_nodes: List[int]
    segment_ids: List[int]
    total_length_m: float
    total_risk: float
    total_cost: float
    geometry: List[List[float]]


class RouteOut(BaseModel):
    route_id: int
    total_length_m: float
    segments: List[int]
    geometry: List[List[float]]


class RouteResponse(BaseModel):
    message: str
    start_node: int | None
    end_node: int | None
    routes: List[RouteOut]

