import os
from collections.abc import Iterable
from workers.regex_rules import extract_regex_entities

import spacy


NLP_PROCESSES = int(
    os.getenv(
        "NLP_PROCESSES",
        "1",
    )
)

nlp = spacy.load(
    "en_core_web_sm",
    enable=["ner"],
    exclude=[
        "tagger",
        "parser",
        "attribute_ruler",
        "lemmatizer",
    ],
)


def entities_from_doc(doc) -> set[tuple[str, str]]:
    entities: set[tuple[str, str]] = set()

    for entity in doc.ents:
        name = entity.text.strip()

        if not name:
            continue

        if entity.label_ == "PERSON":
            entities.add(
                ("PERSON", name)
            )

        elif entity.label_ in {"GPE", "LOC"}:
            entities.add(
                ("LOCATION", name)
            )

    return entities


def extract_entities_batch(
    texts: Iterable[str],
) -> list[set[tuple[str, str]]]:
    text_list = list(texts)

    if not text_list:
        return []

    process_count = min(
        NLP_PROCESSES,
        len(text_list),
    )

    documents = nlp.pipe(
        text_list,
        batch_size=len(text_list),
        n_process=process_count,
    )

    return [
        entities_from_doc(document) | extract_regex_entities(text)
        for document, text in zip(
            documents,
            text_list,
            strict=True,
        )
    ]