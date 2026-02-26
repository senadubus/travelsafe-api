from pydantic import BaseModel

class CrimePoint(BaseModel):
    crime: str | None
    lat: float
    lng: float