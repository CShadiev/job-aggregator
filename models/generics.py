"""Generic Pydantic response and request data wrappers."""

from pydantic import BaseModel, ConfigDict, Field


class DataResponse[T](BaseModel):
    """Generic single-field container for a list of items."""

    data: list[T]


class PaginatedDataResponse[T](BaseModel):
    """Generic paginated response model containing a list of records and pagination metadata."""

    data: list[T]

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)
    total: int


class PaginatedDataRequest[T](BaseModel):
    """Generic paginated request wrapper containing a query object and pagination parameters."""

    query: T
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)


class FrozenBaseModel(BaseModel):
    """Base Pydantic model configured with immutable instances."""

    model_config = ConfigDict(frozen=True)


class TestModel(FrozenBaseModel):
    """Sample test model for generic response validation."""

    name: str
    age: int


x: PaginatedDataResponse[TestModel] = PaginatedDataResponse(
    data=[TestModel(name="John", age=30)], total=3
)
