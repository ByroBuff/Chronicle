from pydantic import BaseModel, Field


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


class ArticleDetail(BaseModel):
    article_id: int
    url: str
    title: str | None
    published: str | None
    clean_text: str | None
    language: str | None = None
    story_id: int | None = None
    entities: list[EntitySummary] = Field(default_factory=list)


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


class SimilarArticlesResponse(BaseModel):
    article_id: int
    items: list[SimilarArticle]


class StorySummary(BaseModel):
    story_id: int
    created_at: str
    updated_at: str
    article_count: int


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