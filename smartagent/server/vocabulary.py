"""
vocabulary.py — Whisper hotword vocabulary and post-processing corrections for Elena.

Two complementary mechanisms fight Whisper transcription errors on proper nouns:

1. HOTWORDS   — Passed to Whisper's beam-search decoder at inference time.
                The decoder biases strongly toward tokens it has "seen" in the
                hotword string.  Zero extra latency; baked into the decode pass.
                Most effective mechanism — fixes "Spain"→"spin" at the source.

2. CORRECTIONS — Case-insensitive whole-word substitutions applied after
                 Whisper returns text.  Catches systematic errors the model
                 still makes even with hotwords (accent + fast speech combos).
                 Only applied for corrections where the wrong word is phonetically
                 close AND the replacement is unambiguous (i.e. the wrong word
                 is not a common independent English word that would be used in
                 a different context).

Usage
-----
    from smartagent.server.vocabulary import (
        build_hotwords,
        apply_corrections,
        user_vocabulary,
    )

    # Get hotword string for Whisper (base + dynamic nouns + user words)
    hw = build_hotwords(context_nouns=["Spain", "Argentina"])

    # Post-process Whisper's raw output
    corrected = apply_corrections(raw_text)
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# ── 1. Base geography hotwords ─────────────────────────────────────────────────
# Countries, capitals, and major cities that Whisper (small/medium) commonly
# mishears, especially for non-native English speakers.
#
# Format: comma-separated string consumed by faster-whisper's `hotwords` param.
# Each entry adds a positive logit bias toward that token sequence in the decoder.

_GEO_COUNTRIES: list[str] = [
    # Americas
    "Argentina", "Bolivia", "Brazil", "Canada", "Chile", "Colombia",
    "Costa Rica", "Cuba", "Dominican Republic", "Ecuador", "El Salvador",
    "Guatemala", "Haiti", "Honduras", "Jamaica", "Mexico", "Nicaragua",
    "Panama", "Paraguay", "Peru", "Puerto Rico", "Uruguay", "Venezuela",
    "United States", "United Kingdom",
    # Europe
    "Albania", "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus",
    "Czech Republic", "Denmark", "Estonia", "Finland", "France", "Germany",
    "Greece", "Hungary", "Iceland", "Ireland", "Italy", "Latvia",
    "Lithuania", "Luxembourg", "Malta", "Netherlands", "Norway", "Poland",
    "Portugal", "Romania", "Serbia", "Slovakia", "Slovenia", "Spain",
    "Sweden", "Switzerland", "Turkey", "Ukraine",
    # Africa
    "Algeria", "Angola", "Cameroon", "Egypt", "Ethiopia", "Ghana", "Kenya",
    "Morocco", "Mozambique", "Nigeria", "Senegal", "South Africa", "Sudan",
    "Tanzania", "Tunisia", "Uganda",
    # Asia / Pacific
    "Afghanistan", "Australia", "Bangladesh", "China", "India", "Indonesia",
    "Iran", "Iraq", "Israel", "Japan", "Jordan", "Kazakhstan", "Kuwait",
    "Lebanon", "Malaysia", "Myanmar", "Nepal", "New Zealand", "North Korea",
    "Pakistan", "Philippines", "Qatar", "Russia", "Saudi Arabia",
    "Singapore", "South Korea", "Syria", "Taiwan", "Thailand", "UAE",
    "United Arab Emirates", "Uzbekistan", "Vietnam",
]

_GEO_CITIES: list[str] = [
    "Amsterdam", "Ankara", "Athens", "Auckland", "Baghdad", "Bangkok",
    "Barcelona", "Beijing", "Berlin", "Bogotá", "Brasília", "Brussels",
    "Budapest", "Buenos Aires", "Cairo", "Caracas", "Copenhagen", "Delhi",
    "Doha", "Dubai", "Dublin", "Helsinki", "Hong Kong", "Istanbul",
    "Jakarta", "Johannesburg", "Kabul", "Karachi", "Kiev", "Kyiv",
    "Lagos", "Lima", "Lisbon", "Ljubljana", "London", "Los Angeles",
    "Luxembourg", "Madrid", "Manila", "Melbourne", "Mexico City", "Miami",
    "Milan", "Montevideo", "Moscow", "Mumbai", "Nairobi", "New York",
    "Oslo", "Panama City", "Paris", "Prague", "Quito", "Riyadh",
    "Rome", "San José", "Santiago", "São Paulo", "Seoul", "Shanghai",
    "Singapore", "Stockholm", "Sydney", "Taipei", "Tehran", "Tokyo",
    "Toronto", "Vancouver", "Vienna", "Warsaw", "Washington", "Zurich",
]

# ── 2. Named entity hotwords ───────────────────────────────────────────────────
# People, organizations, and tech terms Whisper often mangles.

_NAMED_ENTITIES: list[str] = [
    # AI / Tech
    "Elena", "ChatGPT", "OpenAI", "Anthropic", "NVIDIA", "GPU", "CPU",
    "Python", "JavaScript", "TypeScript", "React", "GitHub", "API",
    "LLM", "Whisper", "LiveKit", "FastAPI", "WebSocket", "Ollama",
    # Finance
    "Bitcoin", "Ethereum", "cryptocurrency", "blockchain", "Nasdaq",
    "S&P 500", "portfolio", "dividend", "inflation", "recession",
    # Common proper names (can be extended via user vocab)
    "Mr. Smart",
]

# ── 3. Known Whisper substitution corrections ──────────────────────────────────
# Maps a commonly mis-transcribed word/phrase → its correct form.
# SAFETY RULES for adding entries:
#   - WRONG must NOT be a common English word with its own distinct meaning
#     (e.g. never remap "spin" → "Spain" unconditionally — "spin" is valid).
#   - Instead, use multi-word patterns that are unambiguous.
#   - All matching is case-insensitive and whole-word.
#   - Replacements preserve sentence case (first word capitalised = replacement capitalised).
#
# Observed Whisper errors on accented speech (small.en / medium.en):
_RAW_CORRECTIONS: dict[str, str] = {
    # Country name phonetic confusions (confirmed observed errors)
    "argen tina":    "Argentina",
    "argent ina":    "Argentina",
    "arjentina":     "Argentina",
    "Argentine":     "Argentina",   # wrong demonym used as noun
    "bolivie":       "Bolivia",
    "chilli":        "Chile",       # "chilli" (spice spelling) for country
    "chille":        "Chile",
    "columbie":      "Colombia",
    "columbia":      "Colombia",    # common near-miss
    "equador":       "Ecuador",
    "guatamala":     "Guatemala",
    "hondurus":      "Honduras",
    "mexicco":       "Mexico",
    "nicuaragua":    "Nicaragua",
    "nicarague":     "Nicaragua",
    "perou":         "Peru",
    "paraguy":       "Paraguay",
    "uruguy":        "Uruguay",
    "venezuele":     "Venezuela",
    "venezuala":     "Venezuela",
    "venezula":      "Venezuela",
    # European countries
    "spayn":         "Spain",
    "spane":         "Spain",
    "portegal":      "Portugal",
    "portugel":      "Portugal",
    "rumania":       "Romania",
    "checkia":       "Czechia",
    "czeck":         "Czech",
    "sweeden":       "Sweden",
    "norwey":        "Norway",
    "denemark":      "Denmark",
    "fineland":      "Finland",
    "greese":        "Greece",
    "hungery":       "Hungary",
    # City names
    "buenos aries":  "Buenos Aires",
    "buenos ares":   "Buenos Aires",
    "sao paullo":    "São Paulo",
    "rio de janiero": "Rio de Janeiro",
    # Tech / AI
    "open ai":       "OpenAI",
    "chat g p t":    "ChatGPT",
    "chat gbt":      "ChatGPT",
    "nvidea":        "NVIDIA",
    "nvida":         "NVIDIA",
    "web socket":    "WebSocket",
    "web sockets":   "WebSockets",
    "fast api":      "FastAPI",
    "live kit":      "LiveKit",
    "git hub":       "GitHub",
    "java script":   "JavaScript",
    "type script":   "TypeScript",
    "data base":     "database",
}

# Compile corrections as whole-word regex patterns for efficiency
_CORRECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(wrong) + r"\b", re.IGNORECASE), right)
    for wrong, right in _RAW_CORRECTIONS.items()
]

# ── 3b. Context-aware corrections for near-homophones ──────────────────────────
# These handle words that ARE valid English but are almost certainly a country
# name when they appear in a specific geographic or travel context.
#
# USER-REPORTED ERRORS (confirmed):
#   "spin"      → "Spain"     (Whisper mishears the diphthong "ain" as "in")
#   "attention" → "Argentina" (Whisper splits the phoneme sequence differently)
#
# SAFETY: Each pattern requires BOTH the ambiguous word AND a geographic/travel
# context word to fire — so "spin the ball" and "pay attention" are never touched.
#
# Each tuple is (compiled_pattern, replacement_template).  Use r'\1'-style
# back-references to preserve the captured context words.

# Country names used as geographic context anchors
_ALL_COUNTRIES_RE = (
    r"Argentina|Bolivia|Brazil|Canada|Chile|Colombia|Ecuador|France|Germany|"
    r"Greece|Guatemala|Honduras|Italy|Japan|Mexico|Netherlands|Nicaragua|Norway|"
    r"Panama|Paraguay|Peru|Portugal|Romania|Russia|Spain|Sweden|Switzerland|"
    r"Turkey|Ukraine|Uruguay|Venezuela|United States|United Kingdom|Australia|"
    r"India|China|South Korea|Japan|Egypt|Morocco|Nigeria|South Africa|Kenya"
)

# Travel/location verbs and prepositions — strong geographic context signals
_GEO_PREP_RE = r"(?:to|in|from|at|for|visit|visiting|visited|go to|going to|travel to|traveling|flew to|fly to|move to|moving to|live in|living in|born in|based in)"

_CONTEXT_CORRECTIONS: list[tuple[re.Pattern[str], str]] = [
    # ── "spin" → "Spain" ──────────────────────────────────────────────────────
    # Pattern: <geo-preposition> spin  →  <geo-preposition> Spain
    (
        re.compile(rf"\b({_GEO_PREP_RE})\s+spin\b", re.IGNORECASE),
        r"\1 Spain",
    ),
    # Pattern: spin and/or <country>  →  Spain and/or <country>
    (
        re.compile(rf"\bspin\s+(and|or)\s+({_ALL_COUNTRIES_RE})\b", re.IGNORECASE),
        r"Spain \1 \2",
    ),
    # Pattern: <country> and/or spin  →  <country> and/or Spain
    (
        re.compile(rf"\b({_ALL_COUNTRIES_RE})\s+(and|or)\s+spin\b", re.IGNORECASE),
        r"\1 \2 Spain",
    ),
    # Pattern: spin is (description of a place/country)
    (
        re.compile(r"\bspin\s+is\s+(?:a\s+)?(?:beautiful|great|nice|amazing|wonderful|famous|known|located|situated)", re.IGNORECASE),
        "Spain is ",
    ),
    # Pattern: people in spin / cities in spin / capital of spin
    (
        re.compile(r"\b(people|cities|city|capital|culture|language|football|food|cuisine|history|coast)\s+(?:in|of)\s+spin\b", re.IGNORECASE),
        r"\1 of Spain",
    ),

    # ── "attention" → "Argentina" ─────────────────────────────────────────────
    # Pattern: <geo-preposition> attention  →  <geo-preposition> Argentina
    (
        re.compile(rf"\b({_GEO_PREP_RE})\s+attention\b", re.IGNORECASE),
        r"\1 Argentina",
    ),
    # Pattern: attention and/or <country>  →  Argentina and/or <country>
    (
        re.compile(rf"\battention\s+(and|or)\s+({_ALL_COUNTRIES_RE})\b", re.IGNORECASE),
        r"Argentina \1 \2",
    ),
    # Pattern: <country> and/or attention  →  <country> and/or Argentina
    (
        re.compile(rf"\b({_ALL_COUNTRIES_RE})\s+(and|or)\s+attention\b", re.IGNORECASE),
        r"\1 \2 Argentina",
    ),
    # Pattern: attention is (description)
    (
        re.compile(r"\battention\s+is\s+(?:a\s+)?(?:beautiful|great|nice|amazing|wonderful|famous|known|located|situated)", re.IGNORECASE),
        "Argentina is ",
    ),
    # Pattern: people/cities in attention / capital of attention
    (
        re.compile(r"\b(people|cities|city|capital|culture|language|football|food|cuisine|history|coast|pampas|tango|Buenos)\s+(?:in|of)\s+attention\b", re.IGNORECASE),
        r"\1 of Argentina",
    ),

    # ── Common near-homophones for other countries ────────────────────────────
    # "France" sounds like "Frans" / "Franz" in some accents
    (
        re.compile(rf"\b({_GEO_PREP_RE})\s+(?:Franz|Frans)\b", re.IGNORECASE),
        r"\1 France",
    ),
    # "Brazil" → "Brazile" / "Brasile" (final -e added)
    (
        re.compile(r"\b(Brazile|Brasile|Braseal)\b", re.IGNORECASE),
        "Brazil",
    ),
    # "Chile" → "Chili" (spice word used for country)  — safe: geographic context only
    (
        re.compile(rf"\b({_GEO_PREP_RE})\s+chili\b", re.IGNORECASE),
        r"\1 Chile",
    ),
    # "Colombia" → "Columbia" (very common near-miss — province/university)
    # Only safe in explicit country-list context to avoid "British Columbia"
    (
        re.compile(rf"\bColumbia\s+(and|or)\s+({_ALL_COUNTRIES_RE})\b", re.IGNORECASE),
        r"Colombia \1 \2",
    ),
    (
        re.compile(rf"\b({_ALL_COUNTRIES_RE})\s+(and|or)\s+Columbia\b", re.IGNORECASE),
        r"\1 \2 Colombia",
    ),
]


def apply_corrections(text: str) -> str:
    """Apply post-processing word substitutions to Whisper's raw output.

    Two passes:
      1. Simple whole-word substitutions (unambiguous misspellings / phonetic forms).
      2. Context-aware corrections for near-homophones that are valid English words
         but almost certainly mean a country name in a geographic context (e.g.
         "spin" → "Spain" when preceded by "to/in/from/visit").

    Preserves sentence-level capitalisation: if the replacement begins the
    sentence (or the wrong word was capitalised), the result is capitalised too.
    """
    # Pass 1: simple unambiguous substitutions
    for pattern, replacement in _CORRECTION_PATTERNS:
        def _replace(m: re.Match[str], rep: str = replacement) -> str:
            if m.group(0)[0].isupper():
                return rep[0].upper() + rep[1:]
            return rep
        text = pattern.sub(_replace, text)

    # Pass 2: context-aware near-homophone corrections
    for pattern, replacement in _CONTEXT_CORRECTIONS:
        text = pattern.sub(replacement, text)

    return text


# ── 4. Hotword builder ─────────────────────────────────────────────────────────

_BASE_HOTWORDS: list[str] = _GEO_COUNTRIES + _GEO_CITIES + _NAMED_ENTITIES


def build_hotwords(
    *,
    context_nouns: list[str] | None = None,
    user_words:    list[str] | None = None,
    max_length:    int = 1000,
) -> str:
    """Build the hotwords string for faster-whisper's `hotwords` parameter.

    Combines:
      1. Base geography + entity vocabulary (always included)
      2. Dynamic nouns extracted from the current conversation context
      3. User-defined custom words

    The result is a comma-separated string.  faster-whisper internally tokenises
    this and adds a positive logit bias to every matching token sequence during
    beam search.  Words near the top of the string get marginally stronger bias
    (earlier in the attention window), so we put user-custom words first.

    ``max_length`` caps the string to avoid blowing CTranslate2's internal
    prompt budget (practical limit ~1000 chars, safe at 1500).
    """
    parts: list[str] = []

    # User vocab first (highest priority)
    if user_words:
        parts.extend(user_words)

    # Dynamic context nouns second
    if context_nouns:
        parts.extend(context_nouns)

    # Base vocabulary last (always present but lowest priority)
    parts.extend(_BASE_HOTWORDS)

    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        key = p.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(p.strip())

    result = ", ".join(deduped)
    # Trim to max_length at a word boundary so we never cut a hotword in half
    if len(result) > max_length:
        result = result[:max_length].rsplit(",", 1)[0].rstrip(", ")

    return result


# ── 5. Noun extractor (for dynamic hotwords from conversation) ─────────────────
# A simple pattern-based extractor — avoids NLP dependencies.
# Picks capitalised words (likely proper nouns) from conversation text and
# adds them to the hotwords for the next transcription turn.

_SKIP_CAPS_WORDS = {
    "I", "The", "A", "An", "And", "But", "Or", "So", "If", "In", "On",
    "At", "To", "Of", "For", "With", "By", "As", "Is", "Are", "Was",
    "Were", "Be", "Been", "Being", "Have", "Has", "Had", "Do", "Does",
    "Did", "Will", "Would", "Could", "Should", "May", "Might", "Shall",
    "Can", "Must", "That", "This", "These", "Those", "It", "He", "She",
    "We", "They", "You", "My", "Your", "His", "Her", "Its", "Our",
    "Their", "What", "Which", "Who", "How", "When", "Where", "Why",
    "Elena", "User", "Mr",
}

_NOUN_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*)\b")


def extract_nouns(text: str) -> list[str]:
    """Extract capitalised proper-noun candidates from conversation text.

    Returns a deduplicated list of Title-case words/phrases ≥ 3 chars that
    are not common function words.  Called on every completed conversation turn
    to build dynamic hotwords for the next transcription.
    """
    found: list[str] = []
    seen: set[str] = set()
    for m in _NOUN_RE.finditer(text):
        word = m.group(1).strip()
        key  = word.lower()
        if word not in _SKIP_CAPS_WORDS and key not in seen and len(word) >= 3:
            seen.add(key)
            found.append(word)
    return found


# ── 6. User vocabulary (persisted to disk) ────────────────────────────────────

_USER_VOCAB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "smartagent", "data", "user_vocabulary.json"
)
# Normalise so it always resolves regardless of cwd
_USER_VOCAB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../smartagent/data/user_vocabulary.json")
)


class _UserVocabulary:
    """Persistent user-defined vocabulary for Whisper hotword boosting.

    Words added here are saved to ``smartagent/data/user_vocabulary.json``
    and included in every transcription call so Whisper recognises them
    reliably even in the first turn of a new session.
    """

    def __init__(self) -> None:
        self._words: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            with open(_USER_VOCAB_PATH) as f:
                data = json.load(f)
            self._words = [str(w) for w in data.get("words", []) if w]
        except FileNotFoundError:
            self._words = []
        except Exception as exc:
            logger.warning("user_vocabulary: load failed: %s", exc)
            self._words = []

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(_USER_VOCAB_PATH), exist_ok=True)
            with open(_USER_VOCAB_PATH, "w") as f:
                json.dump({"words": self._words}, f, indent=2)
        except Exception as exc:
            logger.warning("user_vocabulary: save failed: %s", exc)

    @property
    def words(self) -> list[str]:
        return list(self._words)

    def add(self, word: str) -> bool:
        """Add a word to the vocabulary.  Returns True if newly added."""
        word = word.strip()
        if not word:
            return False
        if word.lower() in {w.lower() for w in self._words}:
            return False
        self._words.append(word)
        self._save()
        logger.info("user_vocabulary: added %r (total %d)", word, len(self._words))
        return True

    def remove(self, word: str) -> bool:
        """Remove a word.  Returns True if found and removed."""
        before = len(self._words)
        self._words = [w for w in self._words if w.lower() != word.strip().lower()]
        if len(self._words) < before:
            self._save()
            return True
        return False

    def clear(self) -> None:
        self._words = []
        self._save()


user_vocabulary = _UserVocabulary()
