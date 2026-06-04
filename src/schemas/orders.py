from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from schemas.movies import GenreSchema


class OrderItemMovieSchema(BaseModel):
    id: int
    name: str
    year: int
    price: float
    genres: List[GenreSchema] = []

    model_config = {"from_attributes": True}


class OrderItemSchema(BaseModel):
    id: int
    movie_id: int
    price_at_order: float
    movie: OrderItemMovieSchema

    model_config = {"from_attributes": True}


class OrderSchema(BaseModel):
    id: int
    user_id: int
    status: str
    total_amount: float
    created_at: datetime
    items: List[OrderItemSchema] = []
    payment_url: Optional[str] = None

    model_config = {"from_attributes": True}
