"""
keyword_extractor.py — Extract keywords from bibliography entry fields.

Phase 1: TF-IDF-style extraction using stdlib only (Counter + log weighting).
Phase 2: Hybrid with Ollama LLM extraction (optional).

Applies lemmatization-lite via suffix stripping and stopword removal.
"""
import math
import re
from collections import Counter


# ── Stopwords (English + Italian, compact) ────────────────────────────────────
_STOPWORDS = frozenset(
    # English
    "a an the and or but in on at to for of is it by with from as be "
    "was were been are this that these those not no nor so if do did "
    "has have had may can could will would should shall its also than "
    "about between through during before after above below up down out "
    "into over under again further then once here there when where how "
    "all each every both few more most other some such only own same "
    "very just because until while which what who whom why "
    # Italian
    "il lo la le gli i un uno una del dello della dei degli delle "
    "di da in con su per tra fra al allo alla ai agli alle è sono "
    "che non si come anche più già era stato essere ha ho fatto "
    "ed nel nella nell negli nelle sul sulla sulle suo sua suoi "
    "questo questa questi queste quello quella quelli quelle "
    "ma se perché quando dove chi cosa".split()
)

# Minimum word length to consider
_MIN_WORD_LEN = 3

# Academic terms that are too generic to be useful as graph nodes.
# They are filtered out unless they appear as part of a more specific phrase.
_GENERIC_ACADEMIC_WORDS = frozenset({
    "analysis", "analyses", "analytic", "analytical", "study", "studies",
    "method", "methods", "methodology", "approach", "approaches",
    "data", "datum", "model", "models", "modelling", "modeling",
    "research", "results", "result", "system", "systems", "framework",
    "frameworks", "theory", "theories", "technique", "techniques",
    "information", "application", "applications", "evaluation", "review",
    "article", "articles", "paper", "papers", "topic", "topics",
    "issue", "issues", "case", "cases", "use", "uses", "used", "using",
    "finding", "findings", "problem", "problems", "context", "field",
    "fields", "domain", "domains", "sample", "samples", "guide", "guides",
    "script", "scripts", "perspective", "perspectives", "interpretation",
    "interpretations", "introduction", "chapter", "edition", "publication",
    "publications", "volume", "issue", "date", "access", "summary"
})

# Common translations used in mixed-language bibliographic datasets.
_TOPIC_TRANSLATIONS = {
    "analisi": "analysis",
    "analyses": "analysis",
    "studio": "study",
    "studi": "study",
    "metodo": "method",
    "metodi": "method",
    "dati": "data",
    "dato": "data",
    "modello": "model",
    "modelli": "model",
    "ricerca": "research",
    "risultati": "results",
    "risultato": "result",
    "sistema": "system",
    "tecnica": "technique",
    "tecniche": "technique",
    "informazione": "information",
    "applicazione": "application",
    "valutazione": "evaluation",
    "revisione": "review",
    "articolo": "article",
    "articoli": "article",
    "paper": "paper",
    "tema": "topic",
    "temi": "topic",
    "problema": "problem",
    "problemi": "problem",
    "contesto": "context",
    "dominio": "domain",
    "campione": "sample",
    "archeologia": "archaeology",
    "archeologic": "archaeological",
    "archeologica": "archaeological",
    "archeologico": "archaeological",
    "arte": "art",
    "artistico": "artistic",
    "informatica": "informatics",
    "storico": "historical",
    "storia": "history",
    "culturale": "cultural",
    "antropologia": "anthropology",
    "linguistica": "linguistics",
    "biologia": "biology",
    "chimica": "chemistry",
    "medicina": "medicine",
    "fisica": "physics",
    "matematica": "mathematics",
    "economia": "economics",
    "ecologia": "ecology",
    "pianificazione": "planning",
    "geografia": "geography",
    "architettura": "architecture",
    "classica": "classical",
    "classico": "classical",
}


def normalize_topic_label(text: str) -> str:
    """Normalize topic labels to a compact English form and collapse mixed-language variants."""
    if text is None:
        return ""
    norm = str(text).strip().lower()
    norm = re.sub(r"[\-_]+", " ", norm)
    for it_word, en_word in _TOPIC_TRANSLATIONS.items():
        norm = re.sub(rf"\b{re.escape(it_word)}\b", en_word, norm)
    norm = re.sub(r"[^a-z0-9\s&/()]", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into tokens."""
    text = text.lower()
    text = re.sub(r"[^a-zà-öø-ÿ0-9\s-]", " ", text)
    tokens = text.split()
    return [t for t in tokens if len(t) >= _MIN_WORD_LEN and t not in _STOPWORDS]


def _simple_lemma(word: str) -> str:
    """Very lightweight suffix stripping (English-centric)."""
    for suffix in ("ation", "ment", "ness", "ies", "ing", "ous", "ive",
                   "ity", "ers", "ion", "ed", "ly", "es", "er", "al", "s"):
        if len(word) - len(suffix) >= 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _build_author_blocklist(entries: list[dict]) -> frozenset[str]:
    """Build a set of lowercased author-name tokens to exclude from keywords."""
    tokens: set[str] = set()
    for entry in entries:
        authors = entry.get("authors", "")
        if not authors:
            continue
        # Normalise: lowercase, strip punctuation, split
        cleaned = re.sub(r"[^a-zà-öø-ÿ\s]", " ", authors.lower())
        for tok in cleaned.split():
            if len(tok) >= _MIN_WORD_LEN:
                tokens.add(tok)
                tokens.add(_simple_lemma(tok))
    return frozenset(tokens)


def extract_keywords_tfidf(
    entries: list[dict],
    *,
    top_k: int = 8,
    fields: tuple[str, ...] = ("title", "notes", "journal", "publisher"),
) -> dict[int, list[str]]:
    """
    Extract keywords for each entry using TF-IDF-style scoring.

    Parameters
    ----------
    entries : list[dict]
        Full entry dicts from the database.
    top_k : int
        Maximum keywords per document.
    fields : tuple[str, ...]
        Which fields to concatenate for text.

    Returns
    -------
    dict[int, list[str]]
        Mapping of entry_id → list of keywords (original surface forms).
    """
    # 0. Build author-name blocklist so names never become keyword nodes
    author_blocklist = _build_author_blocklist(entries)

    # 1. Tokenize each document
    doc_tokens: list[list[str]] = []
    doc_ids: list[int] = []
    # Keep mapping from lemma → best surface form (most frequent)
    lemma_to_surface: dict[str, Counter] = {}

    for entry in entries:
        eid = entry.get("id")
        if eid is None:
            continue
        doc_ids.append(eid)
        raw = " ".join(str(entry.get(f, "")) for f in fields)
        tokens = _tokenize(raw)
        lemmas = []
        for t in tokens:
            lem = _simple_lemma(t)
            # Skip tokens that match author names
            if lem in author_blocklist or t in author_blocklist:
                continue
            lemmas.append(lem)
            if lem not in lemma_to_surface:
                lemma_to_surface[lem] = Counter()
            lemma_to_surface[lem][t] += 1
        doc_tokens.append(lemmas)

    if not doc_tokens:
        return {}

    n_docs = len(doc_tokens)

    # 2. Document frequency (DF)
    df: Counter = Counter()
    for lemmas in doc_tokens:
        df.update(set(lemmas))

    # 3. TF-IDF per document
    result: dict[int, list[str]] = {}
    for idx, (eid, lemmas) in enumerate(zip(doc_ids, doc_tokens)):
        tf = Counter(lemmas)
        scores: dict[str, float] = {}
        for lemma, count in tf.items():
            idf = math.log((1 + n_docs) / (1 + df.get(lemma, 0))) + 1.0
            scores[lemma] = count * idf
        top_lemmas = sorted(scores, key=scores.get, reverse=True)[:top_k]
        # Map back to best surface form
        keywords = []
        for lem in top_lemmas:
            surface = lemma_to_surface[lem].most_common(1)[0][0]
            keywords.append(surface)
        result[eid] = filter_academic_keywords(keywords)

    return result


def _infer_discipline_from_text(text: str) -> str:
    """Infer a main academic discipline from common domain terms."""
    norm = normalize_topic_label(text)
    if not norm:
        return ""

    discipline_map = {
        "archaeology": "archaeology",
        "archaeological": "archaeology",
        "art": "art",
        "artistic": "art",
        "history": "history",
        "historical": "history",
        "informatics": "informatics",
        "digital": "informatics",
        "computer": "informatics",
        "linguistics": "linguistics",
        "anthropology": "anthropology",
        "biology": "biology",
        "chemistry": "chemistry",
        "medicine": "medicine",
        "physics": "physics",
        "mathematics": "mathematics",
        "economics": "economics",
        "ecology": "ecology",
        "architecture": "architecture",
        "geography": "geography",
        "planning": "planning",
        "cultural": "cultural studies",
        "heritage": "cultural heritage",
    }

    for token, discipline in discipline_map.items():
        if token in norm:
            return discipline
    return ""


def build_semantic_keyword_profile(entry: dict) -> dict:
    """Return a structured semantic profile for a single bibliographic record.

    The result is a dictionary with:
      - discipline: main academic field
      - subdisciplines: secondary field labels
      - topics: article-specific topical terms
      - keywords: flattened list for immediate graph use
    """
    text_parts = [
        entry.get("title", ""),
        entry.get("journal", ""),
        entry.get("publisher", ""),
        entry.get("notes", ""),
        entry.get("abstract", ""),
    ]
    merged_text = " ".join(str(p) for p in text_parts if str(p).strip())

    author_tokens = set()
    for author_text in (entry.get("authors", "") or "").split(";"):
        for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", author_text):
            low = normalize_topic_label(token)
            if low:
                author_tokens.add(low)
                author_tokens.add(_simple_lemma(low))

    words = [normalize_topic_label(w) for w in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", merged_text)]
    words = [w for w in words if w and len(w) > 1 and w not in {"a", "an", "the", "to", "from", "of", "for", "with", "by", "in", "on", "at", "and", "or"}]

    candidates: list[str] = []
    seen: set[str] = set()
    for i, word in enumerate(words):
        if any(tok in author_tokens for tok in word.split()):
            continue
        if word in _GENERIC_ACADEMIC_WORDS or word in _STOPWORDS:
            continue
        if word.lower() in seen:
            continue
        seen.add(word.lower())
        candidates.append(word)

        if i + 1 < len(words):
            next_word = words[i + 1]
            if any(tok in author_tokens for tok in next_word.split()):
                continue
            if next_word in _GENERIC_ACADEMIC_WORDS or next_word in _STOPWORDS:
                if word.lower() in {"correspondence", "causal", "climate", "digital", "semantic", "network", "archaeological", "cultural", "heritage", "roman", "classical"}:
                    pair = f"{word} {next_word}"
                    if pair.lower() not in seen and next_word.lower() not in {"guide", "script", "use", "results", "perspective", "interpretation"}:
                        seen.add(pair.lower())
                        candidates.append(pair)
                continue
            pair = f"{word} {next_word}"
            if pair.lower() not in seen:
                seen.add(pair.lower())
                candidates.append(pair)

    discipline = _infer_discipline_from_text(merged_text)
    subdisciplines: list[str] = []
    for candidate in candidates:
        if len(candidate.split()) <= 2 and candidate.lower() not in {discipline.lower() if discipline else ""}:
            subdisciplines.append(candidate)

    topics = filter_academic_keywords(candidates)
    if discipline:
        topics = [t for t in topics if t.lower() != discipline.lower()]
    if not topics:
        if discipline:
            topics = [discipline]
        else:
            topics = filter_academic_keywords([entry.get("entry_type", "research")])

    final_keywords = []
    if discipline:
        final_keywords.append(discipline)
    for sd in subdisciplines[:2]:
        if sd.lower() != discipline.lower():
            final_keywords.append(sd)
    for topic in topics[:3]:
        if topic.lower() not in {kw.lower() for kw in final_keywords}:
            final_keywords.append(topic)

    return {
        "discipline": discipline,
        "subdisciplines": subdisciplines[:3],
        "topics": filter_academic_keywords(topics[:3]),
        "keywords": filter_academic_keywords(final_keywords)[:6],
    }


def build_fallback_topic_assignments(entries: list[dict], *, max_topics: int = 3) -> dict[int, list[str]]:
    """Guarantee every entry gets at least one meaningful topic using its semantic profile."""
    assignments: dict[int, list[str]] = {}
    for entry in entries:
        eid = entry.get("id")
        if eid is None:
            continue
        profile = build_semantic_keyword_profile(entry)
        keywords = profile.get("keywords", []) or profile.get("topics", [])
        assignments[int(eid)] = filter_academic_keywords(keywords)[:max_topics]
        if not assignments[int(eid)]:
            discipline = profile.get("discipline") or normalize_topic_label(entry.get("entry_type", "research"))
            if discipline and discipline not in _GENERIC_ACADEMIC_WORDS:
                assignments[int(eid)] = [discipline]
    return assignments


def filter_academic_keywords(items: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Keep only research-relevant concepts and discard generic academic fillers.

    The goal is to preserve labels that carry real academic meaning, such as
    "climate resilience", "causal inference", or "Roman pottery", while removing
    vague placeholders like "analysis", "study", "method", "data", or "model".
    """
    candidates: list[tuple[int, int, str]] = []
    seen: set[str] = set()

    for item in items:
        text = str(item).strip()
        if not text:
            continue
        norm = normalize_topic_label(text)
        if not norm:
            continue

        tokens = norm.split()
        if not tokens:
            continue

        # Remove single-word generic fillers entirely.
        if len(tokens) == 1 and tokens[0] in _GENERIC_ACADEMIC_WORDS:
            continue

        # Reject phrases made only of generic academic terms.
        if all(token in _GENERIC_ACADEMIC_WORDS for token in tokens):
            continue

        # Prefer phrases with at least one content-bearing keyword.
        informative_tokens = sum(1 for token in tokens if token not in _GENERIC_ACADEMIC_WORDS)
        if informative_tokens == 0:
            continue

        if norm.lower() in seen:
            continue
        seen.add(norm.lower())
        candidates.append((informative_tokens, len(tokens), norm))

    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [text for _, _, text in candidates]


def filter_keywords_by_document_frequency(
    keywords_by_entry: dict[int, list[str]],
    *,
    max_doc_fraction: float = 0.5,
) -> dict[int, list[str]]:
    """Drop keywords that are repeated across too many documents.

    This is the key guard against a giant central "discipline" hub: single broad
    labels like archaeology or history are useful as a field, but they should not
    dominate the graph when they appear across most articles.
    """
    if not keywords_by_entry:
        return {}

    total_docs = max(1, len(keywords_by_entry))
    counts: Counter[str] = Counter()
    for kws in keywords_by_entry.values():
        for kw in kws:
            norm = normalize_topic_label(kw)
            if not norm:
                continue
            counts[norm] += 1

    cutoff = max_doc_fraction * total_docs
    filtered: dict[int, list[str]] = {}
    for eid, kws in keywords_by_entry.items():
        kept = []
        for kw in kws:
            norm = normalize_topic_label(kw)
            if not norm:
                continue
            if counts.get(norm, 0) > cutoff:
                continue
            kept.append(norm)
        filtered[eid] = filter_academic_keywords(kept)
    return filtered


def derive_topics_from_key_points(key_points: list[str] | tuple[str, ...] | None) -> list[str]:
    """Convert article key points into compact, concept-oriented topic labels.

    The goal is to keep topics aligned with the actual content of the article: each
    topic should be a short noun phrase derived from the key points, never a vague
    academic placeholder like "analysis", "study", or "method".
    """
    if not key_points:
        return []

    generic_words = _GENERIC_ACADEMIC_WORDS | {
        "analysis", "analyses", "study", "studies", "method", "methods",
        "approach", "approaches", "research", "results", "result", "system",
        "application", "applications", "issue", "issues", "use", "uses",
        "context", "field", "fields", "case", "cases", "guide", "script",
        "perspective", "interpretation", "summary", "consumer", "value",
        "meaning", "data", "information", "theory"
    }

    values: list[str] = []
    for item in key_points:
        text = str(item).strip()
        if not text:
            continue
        norm = normalize_topic_label(text)
        if not norm:
            continue

        segments = re.split(r"[.;:•\-]", norm)
        for segment in segments:
            segment = re.sub(r"\s+", " ", segment).strip()
            if not segment:
                continue

            for delim in (" and ", " or ", " of ", " from ", " in ", " on ", " to ", " with ", " during ", " for ", " by ", " as ", " into ", " between ", " through "):
                if delim in segment:
                    for sub in segment.split(delim):
                        sub = re.sub(r"\s+", " ", sub).strip()
                        if sub:
                            values.append(sub)
                    break
            else:
                values.append(segment)

    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        tokens = [tok for tok in value.split() if tok not in generic_words and tok not in _STOPWORDS]
        if not tokens:
            continue
        if len(tokens) > 4:
            tokens = tokens[-4:]
        label = " ".join(tokens)
        if len(label.split()) == 1 and label in generic_words:
            continue
        if not label:
            continue
        lowered = label.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        selected.append(label)
        if len(selected) >= 5:
            break

    if not selected:
        return []

    grounded: list[str] = []
    for item in selected:
        tokens = item.split()
        if len(tokens) == 1 and tokens[0] in generic_words:
            continue
        grounded.append(item)
    return grounded[:5]


def merge_keywords(
    tfidf_keywords: dict[int, list[str]],
    llm_keywords: dict[int, list[str]] | None = None,
) -> dict[int, list[str]]:
    """
    Merge TF-IDF keywords with optional LLM-extracted keywords.
    LLM keywords get priority (placed first), de-duplicated.
    """
    if llm_keywords is None:
        return {
            eid: filter_academic_keywords(kws)
            for eid, kws in tfidf_keywords.items()
        }

    merged: dict[int, list[str]] = {}
    all_ids = set(tfidf_keywords) | set(llm_keywords)
    for eid in all_ids:
        llm = llm_keywords.get(eid, [])
        tfidf = tfidf_keywords.get(eid, [])
        seen = set()
        combined = []
        for kw in llm + tfidf:
            low = kw.lower()
            if low not in seen:
                seen.add(low)
                combined.append(kw)
        merged[eid] = filter_academic_keywords(combined[:15])
    return merged
