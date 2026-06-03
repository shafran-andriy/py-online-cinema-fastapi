from pydantic import BaseModel
from typing import List, Optional


class GenreSchema(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class MovieSummarySchema(BaseModel):
    id: int
    uuid: str
    name: str
    year: int
    price: float

    model_config = {"from_attributes": True}


class MovieDetailSchema(MovieSummarySchema):
    time: int
    imdb: float
    votes: int
    meta_score: Optional[float]
    gross: Optional[float]
    description: str
    certification: GenreSchema  # reuse structure for simple cert payload
    genres: List[GenreSchema] = []
    directors: List[GenreSchema] = []
    stars: List[GenreSchema] = []

    model_config = {"from_attributes": True}
