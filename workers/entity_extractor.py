import spacy

nlp = spacy.load("en_core_web_sm")

def extract_entities(text):
    doc = nlp(text)

    entities = []

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            entities.append(("PERSON", ent.text.strip()))

        elif ent.label_ in ("GPE", "LOC"):
            entities.append(("LOCATION", ent.text.strip()))

    return set(entities)