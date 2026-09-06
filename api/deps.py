from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth_service import Auth0ClientWrapper
from models.users import User
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage
from search.search_service import SearchService


async def get_auth0_client(request: Request) -> Auth0ClientWrapper:
    return request.state.auth0_client


async def get_current_user(
    bearer: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    auth0_client: Auth0ClientWrapper = Depends(get_auth0_client),
) -> User:

    token = bearer.credentials
    user_info = auth0_client.get_user_info(token)
    return User.model_validate({**user_info, "username": user_info["name"]})


async def get_jobs_repository(request: Request) -> MongoJobsRepository:
    return request.state.jobs_repository


async def get_object_storage(request: Request) -> ObjectStorage:
    return request.state.object_storage


async def get_search_service(request: Request) -> SearchService:
    return request.state.search_service


AppAuth0Client = Annotated[Auth0ClientWrapper, Depends(get_auth0_client)]
AppCurrentUser = Annotated[User, Depends(get_current_user)]
AppJobsRepository = Annotated[MongoJobsRepository, Depends(get_jobs_repository)]
AppObjectStorage = Annotated[ObjectStorage, Depends(get_object_storage)]
AppSearchService = Annotated[SearchService, Depends(get_search_service)]
