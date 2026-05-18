from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class Audience(str, Enum):
    SUBSCRIBERS = "subscribers"
    FOLLOWERS_AND_SUBSCRIBERS = "followers-and-subscribers"


class UploadFailure(BaseModel):
    filename: str
    error: str


class CreatePostResponse(BaseModel):
    uuid: str
    createdAt: str
    text: Optional[str] = None
    audience: str
    publishAt: Optional[str] = None
    mediaUuids: List[str] = []
    uploadFailures: List[UploadFailure] = []
