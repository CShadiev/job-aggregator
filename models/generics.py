from typing import Generic, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar('T')


class DataResponse(BaseModel, Generic[T]):
    data: list[T]


class PaginatedDataResponse(BaseModel, Generic[T]):
    data: list[T]

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)
    total: int


class PaginatedDataRequest(BaseModel, Generic[T]):
    query: T
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)


class FrozenBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True)
