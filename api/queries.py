"""Shared SQL fragments for reading articles.

A story row exists as soon as clustering creates a centroid for it, but a
single-article story is just an implementation detail of clustering, not a
"story" a reader should see. These fragments null out story_id (and the
LEFT JOIN needed to know article_count) so every endpoint that returns
articles agrees on when a story is real.
"""

ARTICLE_SUMMARY_COLUMNS = """
    articles.article_id,
    articles.url,
    articles.title,
    articles.published,
    articles.language,
    CASE
        WHEN stories.article_count > 1 THEN articles.story_id
        ELSE NULL
    END AS story_id,
    SUBSTR(
        REPLACE(articles.clean_text, CHAR(10), ' '),
        1,
        300
    ) AS excerpt
"""

ARTICLE_SUMMARY_JOIN = """
    LEFT JOIN stories
        ON stories.story_id = articles.story_id
"""
