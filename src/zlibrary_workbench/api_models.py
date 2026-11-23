from pydantic import BaseModel, Field

from .models import BookMetadata


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=20)
    language: str = ""
    extension: str = ""


class RecommendationRequest(BaseModel):
    interests: list[str] = Field(default_factory=list, max_length=10)


class MetadataRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    author: str = ""
    year: str = ""
    language: str = ""
    format: str = ""
    publisher: str = ""
    isbn: str = ""
    id: str = ""

    def metadata(self) -> BookMetadata:
        return BookMetadata(**self.model_dump())


class DownloadRequest(BaseModel):
    id: str
    hash: str
    metadata: MetadataRequest
    account: str = "auto"
    max_mb: int = Field(default=80, ge=1, le=512)
    confirmed: bool = False
    target_format: str = ""


class ConvertRequest(BaseModel):
    path: str
    metadata: MetadataRequest
    mode: str = Field(default="auto", pattern="^(auto|reflow|visual)$")


class SummarizeRequest(BaseModel):
    path: str
    title: str = ""
    author: str = ""


class AudioCreateRequest(BaseModel):
    path: str
    metadata: MetadataRequest
    voice: str = ""
    model: str = ""


class ZLibraryLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(default="", max_length=1024)
    account: str = Field(default="default", min_length=1, max_length=64)
    remember_password: bool = False


class SettingsRequest(BaseModel):
    library_root: str = Field(min_length=1, max_length=2000)
    downloads: str = "originals"
    converted: str = "converted"
    audiobooks: str = "audiobooks"
    reports: str = "reports"
    naming_template: str = Field(min_length=1, max_length=500)
    collision: str = "suffix"
    ollama_model: str = Field(min_length=1, max_length=200)
    audiosmith_voice: str = ""
    audiosmith_model: str = ""
