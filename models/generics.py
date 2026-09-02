from pydantic import BaseModel, ConfigDict, Field


class DataResponse[T](BaseModel):
    data: list[T]


class PaginatedDataResponse[T](BaseModel):
    data: list[T]

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)
    total: int


class PaginatedDataRequest[T](BaseModel):
    query: T
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)


class FrozenBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class TestModel(FrozenBaseModel):
    name: str
    age: int


x: PaginatedDataResponse[TestModel] = PaginatedDataResponse(
    data=[TestModel(name="John", age=30)], total=3
)
