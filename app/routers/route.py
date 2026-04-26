from fastapi import APIRouter, Depends, HTTPException
from ..schemas import RouteRequest

router = APIRouter(prefix="/api")

@router.post("/ui-route")
def calculate_route(req: RouteRequest):
    print("Başlangıç:", req.start_lat, req.start_lng)
    print("Bitiş:", req.end_lat, req.end_lng)

    return {
        "status": "ok",
        "start": {
            "lat": req.start_lat,
            "lng": req.start_lng
        },
        "end": {
            "lat": req.end_lat,
            "lng": req.end_lng
        },
        "message": "Koordinatlar backend'e ulaştı"
    }
