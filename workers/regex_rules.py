import os
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from functools import reduce
from pathlib import Path


DEFAULT_RULES_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "entity_rules.toml"
)

RULES_PATH = Path(
    os.getenv(
        "ENTITY_RULES_PATH",
        str(DEFAULT_RULES_PATH),
    )
)


# Only expose a safe, explicit subset of re flags to the config.
_FLAG_NAMES = {
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "VERBOSE": re.VERBOSE,
    "UNICODE": re.UNICODE,
    "ASCII": re.ASCII,
}

_NORMALIZERS = {
    "strip": str.strip,
    "lower": str.lower,
    "upper": str.upper,
}


@dataclass(frozen=True)
class RegexRule:
    id: str
    entity_type: str
    regex: re.Pattern[str]
    group: str | None
    value_template: str | None
    normalizers: tuple[str, ...]
    max_matches: int

    def render(self, match: re.Match[str]) -> str | None:
        """Turn a single regex match into a normalized entity value."""
        if self.value_template is not None:
            fields = {
                name: (value or "")
                for name, value in match.groupdict().items()
            }
            raw = self.value_template.format(**fields)
        elif self.group is not None:
            raw = match.group(self.group)
        else:
            raw = match.group(0)

        if raw is None:
            return None

        value = reduce(
            lambda text, name: _NORMALIZERS[name](text),
            self.normalizers,
            raw,
        )

        return value or None


def _combine_flags(names: Iterable[str]) -> re.RegexFlag:
    flags = re.RegexFlag(0)

    for name in names:
        try:
            flags |= _FLAG_NAMES[name]
        except KeyError as exc:
            raise ValueError(
                f"Unknown regex flag {name!r}; "
                f"allowed flags: {sorted(_FLAG_NAMES)}"
            ) from exc

    return flags


def _build_rule(raw: dict) -> RegexRule:
    rule_id = raw["id"]

    pattern = raw["pattern"]
    flags = _combine_flags(raw.get("flags", []))

    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(
            f"Rule {rule_id!r} has an invalid pattern: {exc}"
        ) from exc

    group = raw.get("group")
    value_template = raw.get("value_template")

    if group is not None and value_template is not None:
        raise ValueError(
            f"Rule {rule_id!r} sets both 'group' and 'value_template'; "
            f"use exactly one"
        )

    # Fail loudly at load time rather than silently emitting nothing.
    if group is not None and group not in regex.groupindex:
        raise ValueError(
            f"Rule {rule_id!r} references group {group!r} "
            f"not present in its pattern"
        )

    for name in raw.get("normalizers", []):
        if name not in _NORMALIZERS:
            raise ValueError(
                f"Rule {rule_id!r} uses unknown normalizer {name!r}; "
                f"allowed: {sorted(_NORMALIZERS)}"
            )

    return RegexRule(
        id=rule_id,
        entity_type=raw["entity_type"],
        regex=regex,
        group=group,
        value_template=value_template,
        normalizers=tuple(raw.get("normalizers", [])),
        max_matches=int(raw.get("max_matches", 100)),
    )


def load_rules(path: Path = RULES_PATH) -> list[RegexRule]:
    if not path.exists():
        return []

    with path.open("rb") as handle:
        data = tomllib.load(handle)

    return [
        _build_rule(raw)
        for raw in data.get("rules", [])
        if raw.get("enabled", True)
    ]


# Compile rules once at import, mirroring how the spaCy model is loaded.
RULES: list[RegexRule] = load_rules()


def extract_regex_entities(
    text: str,
    rules: list[RegexRule] = RULES,
) -> set[tuple[str, str]]:
    entities: set[tuple[str, str]] = set()

    if not text:
        return entities

    for rule in rules:
        seen = 0

        for match in rule.regex.finditer(text):
            value = rule.render(match)

            if value is None:
                continue

            entities.add((rule.entity_type, value))
            seen += 1

            if seen >= rule.max_matches:
                break

    return entities