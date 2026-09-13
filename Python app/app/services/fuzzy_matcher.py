from difflib import SequenceMatcher
import re
import unicodedata
from typing import List, Dict, Any

try:
    from thefuzz import process, fuzz
except ModuleNotFoundError:
    class _FallbackFuzz:
        @staticmethod
        def token_set_ratio(left: str, right: str) -> int:
            left_tokens = set(left.lower().split())
            right_tokens = set(right.lower().split())
            left_text = " ".join(sorted(left_tokens))
            right_text = " ".join(sorted(right_tokens))
            return round(SequenceMatcher(None, left_text, right_text).ratio() * 100)

    class _FallbackProcess:
        @staticmethod
        def extractOne(query: str, choices: list[str], scorer):
            if not choices:
                return None
            best_match = max(choices, key=lambda choice: scorer(query, choice))
            return best_match, scorer(query, best_match)

    process = _FallbackProcess()
    fuzz = _FallbackFuzz()

class FuzzyMatcher:
    """
    Matches extracted text blocks against the local database of entries 
    to find corresponding references.
    """
    
    def __init__(self, db_entries: List[Dict[str, Any]]):
        """
        :param db_entries: List of dicts, each representing an entry from the DB.
                           Required keys for good matching: id, title, authors, year.
        """
        self.db_entries = db_entries
        self._build_index()
        
    def _build_index(self):
        """
        Creates a dictionary mapping a constructed 'search string' back to the entry ID.
        """
        self.search_strings = {}
        for entry in self.db_entries:
            entry_id = entry.get("id")
            if entry_id is None:
                continue
                
            title = entry.get("title", "")
            authors = entry.get("authors", [])
            year = entry.get("year", "")
            
            if isinstance(authors, list):
                authors_str = " ".join([str(a) for a in authors])
            else:
                authors_str = str(authors)
                
            # Costruiamo una stringa comprensiva per il confronto
            search_str = f"{authors_str} {year} {title}".strip().lower()
            if search_str:
                self.search_strings[search_str] = entry_id
                
        self.choices = list(self.search_strings.keys())

    @staticmethod
    def _normalize_tokens(value: object) -> set[str]:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(char for char in text if not unicodedata.combining(char))
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    def _match_short_citation(self, block: str) -> int | None:
        """Match the common manual form ``Surname + year`` before fuzzy matching."""
        year_match = re.search(r"\b(18|19|20|21)\d{2}\b", block)
        if not year_match:
            return None

        year = year_match.group(0)
        author_tokens = self._normalize_tokens(block[:year_match.start()] + block[year_match.end():])
        author_tokens = {token for token in author_tokens if len(token) > 2}
        if not author_tokens:
            return None

        candidates = []
        for entry in self.db_entries:
            if str(entry.get("year", "")).strip()[:4] != year:
                continue
            entry_authors = entry.get("authors", [])
            if isinstance(entry_authors, list):
                entry_authors = " ".join(str(author) for author in entry_authors)
            entry_author_tokens = self._normalize_tokens(entry_authors)
            overlap = author_tokens & entry_author_tokens
            if overlap:
                candidates.append((len(overlap), entry.get("id")))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]
        
    def match_blocks(self, extracted_blocks: List[str], threshold: int = 85) -> List[int]:
        """
        Matches extracted text blocks against the database index.
        :param extracted_blocks: List of raw text blocks extracted from PDF.
        :param threshold: Fuzzy match threshold (0-100).
        :return: A list of matched entry IDs (no duplicates).
        """
        if not self.choices:
            return []
            
        matched_ids = set()
        
        for block in extracted_blocks:
            block_lower = block.lower()
            short_match = self._match_short_citation(block)
            if short_match is not None:
                matched_ids.add(short_match)
                continue
            # thefuzz process.extractOne returns a tuple (best_match_string, score)
            best_match = process.extractOne(block_lower, self.choices, scorer=fuzz.token_set_ratio)
            
            if best_match:
                match_str, score = best_match[0], best_match[1]
                if score >= threshold:
                    matched_id = self.search_strings.get(match_str)
                    if matched_id is not None:
                        matched_ids.add(matched_id)
                        
        return list(matched_ids)
