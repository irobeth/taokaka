"""Profanity filter with severity levels.

Loads the dsojevic/profanity-list dataset and checks text against it.
Supports severity overrides and a configurable maximum severity threshold.

Severity scale:
  1 = PG-13   — mild (ass, boob, bloody)
  2 = R       — moderate (bullshit, dick, fuck)
  3 = NC-17   — explicit sexual/fetish
  4 = 4chan    — extreme/shock content
"""

import json
import os
import re

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "profanity_en.json")

# Override severities for specific words.
# Keys are word IDs from the profanity list, values are new severity levels.
SEVERITY_OVERRIDES = {
    "fuck": 2,
    "clusterfuck": 2,
    "motherfucker": 3,
}


SEVERITY_LABELS = {1: "PG-13", 2: "R", 3: "NC-17", 4: "4chan"}
SEVERITY_BY_LABEL = {v.lower(): k for k, v in SEVERITY_LABELS.items()}


class ProfanityFilter:
    def __init__(self, max_severity=2):
        self.max_severity = max_severity
        self._entries = []  # list of (pattern_re, severity, word_id)
        self._load()

    def _load(self):
        with open(_DATA_PATH, "r") as f:
            data = json.load(f)

        for entry in data:
            word_id = entry["id"]
            severity = SEVERITY_OVERRIDES.get(word_id, entry["severity"])
            # Build regex from match patterns (pipe-separated alternatives)
            match_str = entry.get("match", word_id)
            alternatives = [re.escape(alt.strip()) for alt in match_str.split("|") if alt.strip()]
            if not alternatives:
                continue
            pattern = re.compile(
                r"\b(?:" + "|".join(alternatives) + r")\b",
                re.IGNORECASE,
            )
            self._entries.append((pattern, severity, word_id))

    def check(self, text):
        """Check text for profanity above max_severity.

        Returns a list of (word_id, severity, matched_text) for violations,
        or an empty list if clean.
        """
        violations = []
        for pattern, severity, word_id in self._entries:
            if severity <= self.max_severity:
                continue
            match = pattern.search(text)
            if match:
                violations.append((word_id, severity, match.group()))
        return violations

    def worst_violation(self, text):
        """Returns the single worst (highest severity) violation, or None."""
        violations = self.check(text)
        if not violations:
            return None
        return max(violations, key=lambda v: v[1])
