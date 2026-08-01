"""Language detection and offline translation.

Everything downstream (spaCy NER, embeddings, clustering) assumes English,
so every article is translated to English here before it reaches those
stages. Detection is pure Python (langdetect); translation runs fully
offline through Argos Translate's locally installed language-pair models.
The first request for a given language pair triggers a one-time model
download, after which it is served from Argos's own package cache.
"""

import argostranslate.package
import argostranslate.translate
from langdetect import DetectorFactory, LangDetectException, detect


# Without a fixed seed, langdetect's detection is non-deterministic
# between runs on short/ambiguous text.
DetectorFactory.seed = 0

TARGET_LANGUAGE = "en"

_installed_pairs: set[tuple[str, str]] = set()


def detect_language(text: str) -> str | None:
    sample = text.strip()

    if not sample:
        return None

    try:
        return detect(sample)
    except LangDetectException:
        return None


def _ensure_package_installed(
    from_code: str,
    to_code: str,
) -> bool:
    pair = (from_code, to_code)

    if pair in _installed_pairs:
        return True

    installed_languages = argostranslate.translate.get_installed_languages()

    already_installed = any(
        language.code == from_code for language in installed_languages
    ) and any(
        language.code == to_code for language in installed_languages
    )

    if already_installed:
        _installed_pairs.add(pair)
        return True

    try:
        argostranslate.package.update_package_index()

        available = argostranslate.package.get_available_packages()

        package = next(
            (
                candidate
                for candidate in available
                if candidate.from_code == from_code
                and candidate.to_code == to_code
            ),
            None,
        )

        if package is None:
            print(
                f"No Argos Translate package for {from_code} -> {to_code}",
                flush=True,
            )
            return False

        argostranslate.package.install_from_path(package.download())

        _installed_pairs.add(pair)
        return True

    except Exception as exc:
        print(
            f"Failed to install Argos Translate package "
            f"{from_code} -> {to_code}: {exc}",
            flush=True,
        )
        return False


def translate_to_english(
    text: str,
    source_language: str,
) -> str:
    """Translate text to English, falling back to the original text on
    any failure so a bad/unavailable language pair never breaks a batch."""
    if not text or source_language == TARGET_LANGUAGE:
        return text

    if not _ensure_package_installed(source_language, TARGET_LANGUAGE):
        return text

    try:
        return argostranslate.translate.translate(
            text,
            source_language,
            TARGET_LANGUAGE,
        )
    except Exception as exc:
        print(
            f"Translation failed ({source_language} -> en): {exc}",
            flush=True,
        )
        return text
