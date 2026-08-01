from urllib.parse import urlsplit

from pydantic import BaseModel, Field, computed_field


def _domain_from_url(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


class EntitySummary(BaseModel):
    entity_id: int
    entity_type: str
    canonical_name: str
    article_count: int | None = None


class ArticleSummary(BaseModel):
    article_id: int
    url: str
    title: str | None
    published: str | None
    excerpt: str | None
    language: str | None = None
    story_id: int | None = None

    @computed_field
    @property
    def domain(self) -> str:
        return _domain_from_url(self.url)


class ArticleDetail(BaseModel):
    article_id: int
    url: str
    title: str | None
    published: str | None
    clean_text: str | None
    language: str | None = None
    story_id: int | None = None
    entities: list[EntitySummary] = Field(default_factory=list)

    @computed_field
    @property
    def domain(self) -> str:
        return _domain_from_url(self.url)


class ArticlePage(BaseModel):
    items: list[ArticleSummary]
    total: int
    limit: int
    offset: int


class EntityPage(BaseModel):
    items: list[EntitySummary]
    total: int
    limit: int
    offset: int


class ArticleStats(BaseModel):
    articles: int
    entities: int
    people: int
    locations: int


class SimilarArticle(BaseModel):
    article_id: int
    url: str
    title: str | None
    published: str | None
    excerpt: str | None
    similarity: float

    @computed_field
    @property
    def domain(self) -> str:
        return _domain_from_url(self.url)


class SimilarArticlesResponse(BaseModel):
    article_id: int
    items: list[SimilarArticle]


class StorySummary(BaseModel):
    story_id: int
    created_at: str
    updated_at: str
    article_count: int
    label: str | None = None


class StoryDetail(StorySummary):
    articles: list[ArticleSummary] = Field(default_factory=list)


class StoryPage(BaseModel):
    items: list[StorySummary]
    total: int
    limit: int
    offset: int


class IngestRequest(BaseModel):
    url: str
    title: str | None = None


class IngestResponse(BaseModel):
    article_id: int
    url: str
    created: bool