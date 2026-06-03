from datetime import datetime
from typing import List
from pydantic import BaseModel

from schemas.movies import GenreSchema


class CartItemMovieSchema(BaseModel):
    id: int
    name: str
    year: int
    price: float
    genres: List[GenreSchema] = []

    model_config = {"from_attributes": True}


class CartItemSchema(BaseModel):
    id: int
    movie_id: int
    added_at: datetime
    movie: CartItemMovieSchema

    model_config = {"from_attributes": True}


class CartSchema(BaseModel):
    id: int
    user_id: int
    items: List[CartItemSchema] = []

    model_config = {"from_attributes": True}


class CartAddItemSchema(BaseModel):
    movie_id: int
