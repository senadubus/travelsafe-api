import traceback
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import RouteRequest, RouteBundleResponse 
from ..routing_service import find_routes_bundle

router = APIRouter(prefix="/api")

@router.post("/routes/alternatives", response_model=RouteBundleResponse)
def get_alternative_routes(payload: RouteRequest, db: Session = Depends(get_db)):
    try:
        return find_routes_bundle(
            db=db,
            start_lat=payload.start_lat,
            start_lng=payload.start_lng,
            end_lat=payload.end_lat,
            end_lng=payload.end_lng,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))