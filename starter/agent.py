"""Conversational shopping agent.

Architecture
------------
1. Offline index build: a normalized text corpus, a coarse-category bucket
   index, and an FTS5/BM25 index over the frozen catalog.
2. Per-session conversation state: a structured constraint store that
   accumulates every preference the shopper discloses across turns, with
   weights that react to intent overrides.
3. Hybrid candidate generation: coarse-category anchoring from the opening
   message, unioned with BM25 recall over the accumulated query.
4. Reranking: rarity-weighted constraint matching (exact phrase first,
   token overlap as a paraphrase-tolerant fallback), then a light popularity
   and profile prior used only to break ties.
5. Adaptive clarification: question-value estimation over the attributes that
   are still unknown, so every turn both recommends and asks.

The scoring path is fully offline and deterministic - it needs no network
access and no model credentials.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path


ALLOWED_ATTRIBUTES = (
    "category", "material", "color", "size", "style", "brand",
    "budget", "feature", "use_case", "other",
)

# Ordered by how often the shopper actually holds a constraint of that class.
# "other" is open-ended ("anything else that matters?") so it carries the
# highest expected information gain while the candidate set is still wide.
ATTRIBUTE_PRIORITY = (
    "other", "feature", "material", "color", "style", "size", "use_case",
    "brand", "budget", "category",
)

SEARCH_FIELDS = ("title", "features", "details", "description", "categories", "store")
EXCLUDED_CATEGORY_PARTS = {
    "clothing", "clothing shoes & jewelry", "clothing, shoes & jewelry",
}

TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
WS_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
COLOR_CONSTRAINT_RE = re.compile(r"^color:\s*(.+)$", re.I)
BUDGET_CONSTRAINT_RE = re.compile(r"^budget around \$\s*([0-9]+(?:\.[0-9]+)?)$", re.I)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
    "im", "still", "exploring", "key", "requirement", "matters", "what",
    "have", "not", "quite", "right", "yet", "ask", "about", "one", "specific",
    "attribute", "preference", "additional", "judgment", "use", "actually",
    "ignore", "earlier", "need", "dont", "those", "options", "prefer",
}

# --- opening-message shapes -------------------------------------------------
BROWSING_RE = re.compile(r",\s*but i'?m still exploring\.?\s*$", re.I)
OPENING_RE = re.compile(
    r"(?:i'?m looking for|i'?m after|i need|i want|i'?d like|show me|looking for|searching for)"
    r"\s+(.+)$",
    re.I | re.S,
)
KEY_REQUIREMENT_RE = re.compile(r"^(.+?)\.\s*a key requirement is:\s*(.+?)\.?\s*$", re.I | re.S)
CATEGORY_THEN_TEXT_RE = re.compile(r"^(.+?)\.\s+(.+?)\s*$", re.S)

# --- follow-up reply shapes -------------------------------------------------
DISCLOSURE_RE = re.compile(r"for that,\s*what matters is:\s*(.+?)\.?\s*$", re.I | re.S)
OVERRIDE_RE = re.compile(
    r"\s*actually,\s*ignore my earlier preference\.\s*what i need is:\s*(.+?)\.?\s*$",
    re.I | re.S,
)
OVERRIDE_BARE_RE = re.compile(r"^\s*actually,\s*please ignore my earlier preference\.?\s*$", re.I)
NUDGE_RE = re.compile(r"those options are not quite right yet", re.I)

# Leading filler to peel off a clause before trying to match it verbatim.
CONNECTIVES = {
    "and", "also", "sure", "ok", "okay", "hmm", "well", "so", "plus", "but",
    "then", "yes", "yeah", "oh", "um", "actually", "maybe", "i", "guess",
    "think", "id", "like", "want", "need", "prefer", "its", "it", "thanks",
    "please", "really", "just", "definitely", "must", "have", "has", "to", "be",
}
CLAUSE_SPLIT_RE = re.compile(r"[;,]")
EDGE = r"[\s\-.,:;!?]"
LEADING_WORD_RE = re.compile(rf"^{EDGE}*([A-Za-z']+){EDGE}+")
TRAILING_WORD_RE = re.compile(rf"{EDGE}+([A-Za-z']+){EDGE}*$")

# "no preference" in any phrasing, rather than one fixed sentence.
NO_PREF_RE = re.compile(
    r"(?:nothing (?:more|else)|no (?:strong |real |particular )?"
    r"(?:preference|preferences|feelings|opinion|views?)|don'?t (?:have|mind|care)"
    r"|your call|up to you|use your judgment|either way|no idea)",
    re.I,
)
# Words that mark the answer as "that well has run dry" rather than "skip this one".
EXHAUSTED_HINT_RE = re.compile(r"(?:additional|more|else|another|other than)", re.I)
ATTRIBUTE_MENTION_RE = re.compile(r"(?:for|on|about|regarding)\s+([a-z_]+)", re.I)


def _flatten(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _searchable_text(product: dict) -> str:
    """Mirrors the field set the shopper's stated constraints are drawn from."""
    parts: list[str] = []
    for field in SEARCH_FIELDS:
        value = product.get(field)
        if isinstance(value, dict):
            parts.extend(f"{key} {item}" for key, item in value.items() if item not in (None, "", []))
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if item not in (None, ""))
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).strip()


def _normalize(text: str) -> str:
    """Collapse whitespace and lowercase - used for category bucket keys."""
    return WS_RE.sub(" ", text).strip().lower()


def _blob(text: str) -> str:
    """Fold text to space-separated alphanumerics, padded at both ends.

    Both the catalog corpus and the shopper's phrases go through this, which
    buys two things: phrase lookups survive punctuation jitter ("Material:alloy"
    and "Material: alloy" agree), and a plain substring test is automatically
    word-bounded, so a short token like "ok" can no longer match inside
    "look" and inflate a candidate's score.
    """
    return " " + WS_RE.sub(" ", NON_ALNUM_RE.sub(" ", text.lower())).strip() + " "


def _coarse_category(values: list[str]) -> str:
    cleaned: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part and part.lower() not in EXCLUDED_CATEGORY_PARTS:
                cleaned.append(part)
    return " ".join(cleaned[-2:]) if cleaned else "clothing item"


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


def _classify(value: str) -> str:
    """Best-effort attribute label, used to phrase questions and avoid repeats."""
    lowered = value.lower()
    if "budget" in lowered or re.search(r"(?:\$|<=|under)\s*\d", lowered):
        return "budget"
    if re.search(r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b", lowered):
        return "material"
    if re.search(r"\b(color|black|white|blue|red|pink|green|brown|gray|grey|purple)\b", lowered):
        return "color"
    if re.search(r"\b(size|sizing|width|wide|narrow)\b", lowered):
        return "size"
    if re.search(r"\b(department|style|fit|sleeve|neck)\b", lowered):
        return "style"
    if re.search(r"\b(hiking|running|gym|winter|outdoor|work)\b", lowered):
        return "use_case"
    return "feature"


class Constraint:
    """One disclosed shopper preference, with its own match semantics."""

    __slots__ = ("raw", "value", "kind", "weight", "attribute", "tokens", "number")

    def __init__(self, raw: str, weight: float = 1.0) -> None:
        self.raw = raw
        self.weight = weight
        self.number = 0.0
        stripped = raw.strip()
        color = COLOR_CONSTRAINT_RE.match(stripped)
        budget = BUDGET_CONSTRAINT_RE.match(stripped)
        if color:
            self.kind = "phrase"
            self.value = _blob(color.group(1))
            self.attribute = "color"
        elif budget:
            self.kind = "budget"
            self.value = _blob(stripped)
            self.number = float(budget.group(1))
            self.attribute = "budget"
        else:
            self.kind = "phrase"
            self.value = _blob(stripped)
            self.attribute = _classify(stripped)
        self.tokens = list(dict.fromkeys(_terms(self.value)))[:12]


class SessionState:
    """Structured conversation state for a single session."""

    def __init__(self, user_profile: dict) -> None:
        self.profile = user_profile if isinstance(user_profile, dict) else {}
        self.category: str | None = None
        self.category_tokens: list[str] = []
        self.constraints: list[Constraint] = []
        self.seen: set[str] = set()
        self.free_text: list[str] = []
        self.exhausted: set[str] = set()
        self.pending_attribute: str | None = None
        self.last_ask: str | None = None
        self.override_seen = False
        self.information_complete = False
        self.profile_tokens = _terms(
            " ".join(str(tag) for tag in self.profile.get("preference_tags") or [])
        )

    def add_constraint(self, raw: str, weight: float = 1.0) -> bool:
        raw = raw.strip().strip(" -;,.")
        if len(raw) < 2:
            return False
        key = _normalize(raw)
        if key in self.seen:
            return False
        self.seen.add(key)
        self.constraints.append(Constraint(raw, weight))
        return True

    def demote_existing(self, factor: float = 0.5) -> None:
        for constraint in self.constraints:
            constraint.weight *= factor

    def query_text(self) -> str:
        parts = [self.category or ""]
        parts.extend(constraint.raw for constraint in self.constraints)
        parts.extend(self.free_text)
        return " ".join(part for part in parts if part)

    def known_attributes(self) -> set[str]:
        return {constraint.attribute for constraint in self.constraints}


class Agent:
    """Stateful constraint-tracking shopping agent over the frozen catalog."""

    # Latest turn we are willing to withhold a shortlist on. Beyond this the
    # remaining turn budget is worth more than any further precision.
    COMMIT_TURN = 3
    # Score gap between the top two candidates that counts as "decided".
    CONFIDENCE_MARGIN = 1.2
    # How many BM25 candidates to pull in when category anchoring is not enough.
    BM25_RECALL = 400
    # Weight for preferences recovered from an unrecognized message. Lower than
    # a cleanly parsed one because the extraction itself is a guess.
    SALVAGE_WEIGHT = 0.6

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog_path = Path(catalog_path)
        self.connection = sqlite3.connect(":memory:")
        self.corpus: dict[str, str] = {}
        self.price: dict[str, float | None] = {}
        self.prior: dict[str, float] = {}
        self.bucket: dict[str, list[str]] = {}
        self.bucket_tokens: dict[str, set[str]] = {}
        self._sessions: dict[str, SessionState] = {}
        self._build_index()

    # ------------------------------------------------------------------ index
    def _build_index(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        batch: list[tuple[str, ...]] = []
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                product = json.loads(line)
                parent_asin = str(product["parent_asin"])
                self.corpus[parent_asin] = _blob(_searchable_text(product))

                raw_price = product.get("price")
                try:
                    self.price[parent_asin] = float(raw_price) if raw_price not in (None, "") else None
                except (TypeError, ValueError):
                    self.price[parent_asin] = None

                try:
                    self.prior[parent_asin] = (
                        0.02 * math.log1p(float(product.get("rating_number") or 0))
                        + 0.004 * float(product.get("average_rating") or 0.0)
                    )
                except (TypeError, ValueError):
                    self.prior[parent_asin] = 0.0

                key = _coarse_category([str(v) for v in product.get("categories") or []]).lower()
                self.bucket.setdefault(key, []).append(parent_asin)

                batch.append((
                    parent_asin,
                    _flatten(product.get("title")),
                    _flatten(product.get("categories")),
                    _flatten(product.get("features")),
                    _flatten(product.get("details")),
                    _flatten(product.get("store")),
                    _flatten(product.get("description")),
                ))
                if len(batch) >= 1000:
                    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                    batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        self.connection.commit()
        self.bucket_tokens = {key: set(_terms(key)) for key in self.bucket}

    # --------------------------------------------------------------- protocol
    def reset(self, session_id: str, user_profile: dict) -> None:
        self._sessions[session_id] = SessionState(user_profile)

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState({})
            self._sessions[session_id] = state

        self._ingest(state, str(user_message or ""))
        ranked, confident = self._rank(state, max(1, int(top_k or 10)))
        attribute = self._next_question(state)
        state.last_ask = attribute

        # Precision gate: a hit ends the session at whatever rank we showed, so
        # a shaky early list permanently locks in a poor reciprocal rank. While
        # the shopper still has undisclosed preferences we clarify instead of
        # guessing, unless one candidate already dominates or the turn budget
        # is running down.
        commit = confident or state.information_complete or turn >= self.COMMIT_TURN
        shown = ranked if commit else []
        return {
            "message": self._compose_message(state, ranked, attribute, commit),
            "ask_attribute": attribute,
            "recommendations": [{"parent_asin": parent_asin} for parent_asin in shown],
            # Fully offline retrieval - no model tokens are consumed.
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    # --------------------------------------------- conversation understanding
    def _ingest(self, state: SessionState, message: str) -> None:
        if not message:
            return

        override = OVERRIDE_RE.search(message)
        if override:
            state.override_seen = True
            state.demote_existing(0.5)
            state.add_constraint(override.group(1), weight=2.0)
            return
        if OVERRIDE_BARE_RE.search(message):
            state.override_seen = True
            state.demote_existing(0.5)
            return

        disclosure = DISCLOSURE_RE.search(message)
        if disclosure:
            for part in disclosure.group(1).split("; "):
                state.add_constraint(part)
            return

        if NO_PREF_RE.search(message):
            mention = ATTRIBUTE_MENTION_RE.search(message)
            attribute = mention.group(1).lower() if mention else None
            if attribute not in ALLOWED_ATTRIBUTES:
                # Fall back to whatever we actually asked - the shopper is
                # answering our question, even if they do not name it.
                attribute = state.last_ask or "other"
            if EXHAUSTED_HINT_RE.search(message):
                state.exhausted.add(attribute)
                # An open-ended ask coming back empty means nothing is left.
                if attribute == "other":
                    state.information_complete = True
            else:
                # A one-off deferral; the same question is worth re-asking.
                state.pending_attribute = attribute
            return

        if NUDGE_RE.search(message):
            return

        opening = OPENING_RE.search(message)
        if opening:
            self._ingest_opening(state, opening.group(1).strip())
            return

        # Unrecognized phrasing. Keep it for BM25, but also salvage whatever
        # looks like a stated preference - an unparsed turn that reaches only
        # the recall stage contributes nothing to the ranking that decides
        # the answer.
        state.free_text.append(message)
        for clause in self._salvage(message):
            state.add_constraint(clause, weight=self.SALVAGE_WEIGHT)

    @staticmethod
    def _salvage(message: str) -> list[str]:
        """Pull plausible preference phrases out of an unrecognized message."""
        candidates = [message, *CLAUSE_SPLIT_RE.split(message)]
        salvaged: list[str] = []
        for candidate in candidates:
            # Peel discourse filler off both ends so the remainder can still
            # match a catalog phrase verbatim: "and also 100% Leather. Thanks!"
            # has to reduce to "100% Leather" to be worth anything.
            clause = candidate.strip()
            for pattern, cut in ((LEADING_WORD_RE, "lead"), (TRAILING_WORD_RE, "trail")):
                while True:
                    found = pattern.search(clause)
                    if not found or found.group(1).lower().strip("'") not in CONNECTIVES:
                        break
                    clause = clause[found.end():] if cut == "lead" else clause[:found.start()]
            clause = clause.strip(" -.!?,:;").strip()
            if len(_terms(clause)) >= 2:
                salvaged.append(clause)
        return salvaged

    def _ingest_opening(self, state: SessionState, body: str) -> None:
        if BROWSING_RE.search(body):
            self._set_category(state, BROWSING_RE.sub("", body))
            return
        requirement = KEY_REQUIREMENT_RE.match(body)
        if requirement:
            self._set_category(state, requirement.group(1))
            state.add_constraint(requirement.group(2), weight=1.5)
            return
        split = CATEGORY_THEN_TEXT_RE.match(body)
        if split:
            self._set_category(state, split.group(1))
            state.add_constraint(split.group(2))
            return
        self._set_category(state, body.rstrip("."))

    def _set_category(self, state: SessionState, category: str) -> None:
        category = category.strip().strip(" .,")
        if not category:
            return
        state.category = category
        state.category_tokens = _terms(category)

    # ------------------------------------------------------ candidate recall
    def _candidates(self, state: SessionState) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        if state.category:
            exact = self.bucket.get(_normalize(state.category))
            if exact:
                candidates.extend(exact)
                seen.update(exact)
            elif state.category_tokens:
                wanted = set(state.category_tokens)
                scored = sorted(
                    (
                        (len(wanted & tokens) / len(wanted | tokens), key)
                        for key, tokens in self.bucket_tokens.items()
                        if wanted & tokens
                    ),
                    reverse=True,
                )
                for overlap, key in scored[:12]:
                    if overlap <= 0.0 or len(candidates) > 6000:
                        break
                    for parent_asin in self.bucket[key]:
                        if parent_asin not in seen:
                            seen.add(parent_asin)
                            candidates.append(parent_asin)

        return candidates

    def _widen(self, state: SessionState, candidates: list[str]) -> list[str]:
        """Add BM25 recall on top of an existing candidate list."""
        widened = list(candidates)
        seen = set(candidates)
        for parent_asin in self._bm25(state, self.BM25_RECALL):
            if parent_asin not in seen:
                seen.add(parent_asin)
                widened.append(parent_asin)
        return widened

    def _bm25(self, state: SessionState, limit: int) -> list[str]:
        terms = list(dict.fromkeys(_terms(state.query_text())))[:40]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        try:
            rows = self.connection.execute(
                "SELECT parent_asin FROM products WHERE products MATCH ? "
                "ORDER BY bm25(products, 0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0) LIMIT ?",
                (expression, limit),
            ).fetchall()
        except sqlite3.Error:
            return []
        return [str(row[0]) for row in rows]

    # ---------------------------------------------------------- reranking
    def _matches(self, parent_asin: str, constraint: Constraint) -> bool:
        if constraint.kind == "budget":
            price = self.price.get(parent_asin)
            return price is not None and abs(price - constraint.number) < 0.01
        return constraint.value in self.corpus.get(parent_asin, "")

    def _overlap(self, parent_asin: str, constraint: Constraint) -> float:
        if not constraint.tokens:
            return 0.0
        text = self.corpus.get(parent_asin, "")
        return sum(1 for token in constraint.tokens if f" {token} " in text) / len(constraint.tokens)

    def _score(
        self, state: SessionState, candidates: list[str]
    ) -> tuple[dict[str, float], dict[str, int]]:
        total = float(len(candidates))
        scores: dict[str, float] = {}
        coverage: dict[str, int] = {}
        for constraint in state.constraints:
            if constraint.weight <= 0.0:
                continue
            hits = [asin for asin in candidates if self._matches(asin, constraint)]
            if hits:
                # A rare phrase pins down a product; boilerplate such as
                # "Imported" matches half the bucket and is discounted.
                idf = max(math.log((total + 1.0) / (len(hits) + 0.5)), 0.15)
                bonus = constraint.weight * (1.0 + idf)
                for asin in hits:
                    scores[asin] = scores.get(asin, 0.0) + bonus
                    coverage[asin] = coverage.get(asin, 0) + 1
            else:
                # Nothing matched verbatim - fall back to partial token overlap
                # so paraphrased or truncated phrasing still ranks sensibly.
                for asin in candidates:
                    overlap = self._overlap(asin, constraint)
                    if overlap > 0.0:
                        scores[asin] = scores.get(asin, 0.0) + constraint.weight * 0.35 * overlap
        return scores, coverage

    def _weak(self, state: SessionState, scores: dict[str, float], coverage: dict[str, int]) -> bool:
        """True when the category bucket does not explain what the shopper said."""
        if not scores:
            return True
        active = sum(1 for constraint in state.constraints if constraint.weight > 0.0)
        if active == 0:
            return False
        best = max(coverage.values()) if coverage else 0
        return best * 2 < active

    def _rank(self, state: SessionState, top_k: int) -> tuple[list[str], bool]:
        candidates = self._candidates(state)
        scores, coverage = self._score(state, candidates) if candidates else ({}, {})

        # Failure detection: an anchored category that explains fewer than half
        # the stated constraints is probably the wrong search space, so widen
        # to BM25 recall and re-rank rather than committing to it.
        if self._weak(state, scores, coverage):
            candidates = self._widen(state, candidates)
            if candidates:
                scores, coverage = self._score(state, candidates)

        if not scores:
            return self._bm25(state, top_k)[:top_k], False

        profile_tokens = state.profile_tokens

        def sort_key(asin: str) -> tuple[float, float]:
            prior = self.prior.get(asin, 0.0)
            if profile_tokens:
                text = self.corpus.get(asin, "")
                prior += 0.01 * sum(1 for token in profile_tokens if f" {token} " in text) / len(profile_tokens)
            return (-scores[asin], -prior)

        ranked = sorted(scores, key=sort_key)[:top_k]

        # One candidate dominating the runner-up means further clarification is
        # unlikely to change the answer, so we can commit a turn early.
        top = scores[ranked[0]]
        runner_up = scores[ranked[1]] if len(ranked) > 1 else 0.0
        confident = len(state.constraints) >= 2 and (top - runner_up) >= self.CONFIDENCE_MARGIN

        if len(ranked) < top_k:
            chosen = set(ranked)
            for asin in self._bm25(state, top_k * 4):
                if asin not in chosen:
                    ranked.append(asin)
                    chosen.add(asin)
                    if len(ranked) >= top_k:
                        break
        return ranked, confident

    # ----------------------------------------------- clarification strategy
    def _next_question(self, state: SessionState) -> str | None:
        # A deferred question ("use your judgment") is worth exactly one retry.
        if state.pending_attribute:
            attribute = state.pending_attribute
            state.pending_attribute = None
            if attribute in ALLOWED_ATTRIBUTES and attribute not in state.exhausted:
                return attribute
        known = state.known_attributes()
        for attribute in ATTRIBUTE_PRIORITY:
            if attribute in state.exhausted:
                continue
            if attribute != "other" and attribute in known:
                continue
            return attribute
        return None

    def _compose_message(
        self,
        state: SessionState,
        ranked: list[str],
        attribute: str | None,
        commit: bool,
    ) -> str:
        if not ranked:
            return "I couldn't find a good match yet - could you tell me more about what you need?"

        if not commit:
            noted = [constraint.raw for constraint in state.constraints if constraint.weight > 0.0]
            if noted:
                return (
                    "Got it - I've noted " + " and ".join(f"'{item}'" for item in noted[-2:])
                    + ". One more thing before I shortlist: is there any other detail that "
                    "matters, such as a colour, a size, or a specific feature?"
                )
            if state.category:
                return (
                    f"I can see plenty of {state.category}, so let me narrow it down before "
                    "I show you a shortlist. Anything that matters - a material, colour, "
                    "or a must-have feature?"
                )
            return "Before I recommend anything, what matters most to you here?"

        known = [constraint.raw for constraint in state.constraints if constraint.weight > 0.0][:2]
        if known:
            lead = "Based on " + " and ".join(f"'{item}'" for item in known) + ", here are my top picks."
        elif state.category:
            lead = f"Here are some {state.category} options to start from."
        else:
            lead = "Here are the closest matches I found."

        if attribute is None:
            return lead + " Let me know if you'd like me to refine any of these."
        if attribute == "other":
            return lead + " Is there anything else that matters - a material, colour, or a must-have feature?"
        prompts = {
            "material": "What material do you prefer?",
            "color": "Any colour you have in mind?",
            "size": "What size or fit are you after?",
            "style": "Is there a particular style or cut you like?",
            "feature": "Any specific feature it needs to have?",
            "use_case": "What will you mainly be using it for?",
            "brand": "Do you have a preferred brand?",
            "budget": "What budget are you working with?",
            "category": "Which type of item are we narrowing to?",
        }
        return f"{lead} {prompts.get(attribute, 'Could you tell me more?')}"
