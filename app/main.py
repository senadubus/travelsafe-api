from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers.crime import router as crime_router

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

@app.get("/")
def root():
    return {"ok": True, "message": "TravelSafe backend up"}