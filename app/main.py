from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers.crime import router as crime_router
from .routers.tiles import router as tiles_router
from .routers.points import router as points_router
from .routers.route import router as alternative


app = FastAPI(title="TravelSafe API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # prod’da daraltırsın
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#Base.metadata.create_all(bind=engine)

app.include_router(crime_router)
app.include_router(tiles_router)
app.include_router(points_router)
app.include_router(alternative)



@app.get("/")
def root():
    return {"ok": True, "message": "TravelSafe backend up"}
