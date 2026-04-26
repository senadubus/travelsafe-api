from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers.crime import router as crime_router
from .routers.tiles import router as tiles_router
from .routers.points import router as points_router
from .routers.route import router as route
from .routers.ui_route import router as ui_route


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
app.include_router(route)
app.include_router(ui_route)




@app.get("/")
def root():
    return { "message": "TravelSafe backend çalısıyor!"}
