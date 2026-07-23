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


class ArticleDetail(BaseModel):
    article_id: int
    url: str
    title: str | None
    published: str | None
    clean_text: str | None
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