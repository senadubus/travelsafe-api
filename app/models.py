from sqlalchemy import Column, Integer, String, Float, TIMESTAMP
from geoalchemy2 import Geography
from .database import Base

class Crime(Base):
    __tablename__ = "crime"

    date = Column("Date", TIMESTAMP, nullable=True)
    primary_type = Column("Primary Type", String, nullable=True)
    description = Column("Description", String, nullable=True)
    latitude = Column("Latitude", Float, nullable=True)
    longitude = Column("Longitude", Float, nullable=True)
    location = Column("Location", String, nullable=True)
    geom = Column("geom", Geography(geometry_type="POINT", srid=4326))
