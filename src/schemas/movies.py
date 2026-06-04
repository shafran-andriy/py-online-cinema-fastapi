from datetime import datetime
from pydantic import BaseModel, field_validator
from typing import List, Optional


class GenreSchema(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class GenreWithCountSchema(BaseModel):
    id: int
    name: str
    movies_count: int

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
    certification: GenreSchema
    genres: List[GenreSchema] = []
    directors: List[GenreSchema] = []
    stars: List[GenreSchema] = []
    avg_rating: Optional[float] = None
    likes_count: int = 0
    dislikes_count: int = 0

    model_config = {"from_attributes": True}


class MovieListResponseSchema(BaseModel):
    total: int
    items: List[MovieSummarySchema]

    model_config = {"from_attributes": True}


class MovieCommentSchema(BaseModel):
    id: int
    movie_id: int
    user_id: int
    parent_id: Optional[int]
    body: str
    created_at: datetime
    replies: List["MovieCommentSchema"] = []

    model_config = {"from_attributes": True}


MovieCommentSchema.model_rebuild()


class MovieCommentCreateSchema(BaseModel):
    body: str


class MovieRatingCreateSchema(BaseModel):
    score: int

    @field_validator("score")
    @classmethod
    def validate_score(cls, v: int) -> int:
        if not (1 <= v <= 10):
            raise ValueError("Score must be between 1 and 10")
        return v


class NotificationSchema(BaseModel):
    id: int
    type: str
    related_id: Optional[int]
    message: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
