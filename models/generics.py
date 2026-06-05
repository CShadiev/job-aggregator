from typing import Generic, TypeVar
from pydantic import BaseModel, ConfigDict

T = TypeVar('T')


class DataResponse(BaseModel, Generic[T]):
    data: list[T]


class PaginatedDataResponse(BaseModel, Generic[T]):
    data: list[T]

    page: int
    page_size: int
    total: int


class PaginatedDataRequest(BaseModel, Generic[T]):
    query: T
    page: int = 1
    page_size: int = 10


class FrozenBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True)
