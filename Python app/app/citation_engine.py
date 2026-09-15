"""
citation_engine.py — CitationStyleEngine: formats bibliography entries
in multiple academic citation styles (Preistoria Alpina, APA, MLA, Chicago, Harvard)
and supports user-defined custom styles. Uses the Strategy Pattern.
"""
import re
from typing import Protocol, List, Tuple

RunList = List[Tuple[str, bool, bool]]

class CitationStyle(Protocol):
    @property
    def name(self) -> str: ...
    def format_bibliography(self, e: dict) -> RunList: ...
    def cite_inline(self, e: dict) -> str: ...
    def cite_footnote(self, e: dict) -> RunList: ...

class BaseStyle:
    """Provides common formatting utilities for citation styles."""
    def _s(self, val: str) -> str:
        return val.strip() if val else ""

    def _format_authors(self, e: dict, ed_suffix: str = " (ed.)", eds_suffix: str = " (eds)") -> str:
        authors = self._s(e.get("authors", ""))
        is_ed = int(e.get("is_editor", 0))
        if authors and is_ed:
            if any(x in authors for x in ["&", " and ", " e ", ", "]):
                authors += eds_suffix
            else:
                authors += ed_suffix
        return authors

    def _get_inline_author(self, authors: str) -> str:
        """Extracts primary author surname for in-text citation."""
        if not authors:
            return "Unknown"
        # Simplistic extraction for MVP: take first part before comma or just first word
        parts = authors.split(",")
        if len(parts) > 0 and parts[0]:
            return parts[0].strip().split()[0]
        return authors.split()[0]


class ApaStyle(BaseStyle):
    @property
    def name(self) -> str: return "APA 7th"

    def format_bibliography(self, e: dict) -> RunList:
        runs = []
        authors = self._format_authors(e, " (Ed.)", " (Eds.)")
        year    = self._s(e.get("year", ""))
        title   = self._s(e.get("title", ""))
        journal = self._s(e.get("journal", ""))

        if e.get("entry_type") == "tesi":
            if authors: runs.append((authors, False, False))
            if year:    runs.append((f" ({year}). ", False, False))
            elif authors: runs.append((". ", False, False))
            if title:   runs.append((title, False, True))
            if journal: runs.append((f" [{journal}]", False, False))
            runs.append((". ", False, False))
            pub = self._s(e.get("publisher", ""))
            if pub: runs.append((pub + ".", False, False))
            return runs or [("(empty thesis entry)", False, False)]

        if authors: runs.append((authors, False, False))
        if year:    runs.append((f" ({year}). ", False, False))
        elif authors: runs.append((". ", False, False))

        if journal:
            if title: runs.append((title + ". ", False, False))
            runs.append((journal, False, True))
            vol = self._s(e.get("volume", ""))
            iss = self._s(e.get("issue", ""))
            if vol:
                runs.append((f", {vol}", False, True))
                if iss: runs.append((f"({iss})", False, False))
            pages = self._s(e.get("pages", ""))
            if pages: runs.append((f", {pages}", False, False))
            runs.append((". ", False, False))
        elif title:
            runs.append((title, False, True))
            runs.append((". ", False, False))

        pub = self._s(e.get("publisher", ""))
        loc = self._s(e.get("location", ""))
        pub_str = f"{loc}: {pub}" if (loc and pub) else (pub or loc)
        if pub_str and not journal: runs.append((pub_str + ". ", False, False))

        doi = self._s(e.get("doi", ""))
        url = self._s(e.get("url", ""))
        if doi:  runs.append((f"https://doi.org/{doi}", False, False))
        elif url: runs.append((url, False, False))

        return runs or [("(empty entry)", False, False)]

    def cite_inline(self, e: dict) -> str:
        author = self._get_inline_author(self._s(e.get("authors", "")))
        year = self._s(e.get("year", "n.d."))
        return f"({author}, {year})"
    
    def cite_footnote(self, e: dict) -> RunList:
        # APA typically uses in-text, not footnotes, but fallback to bibliography
        return self.format_bibliography(e)


class MlaStyle(BaseStyle):
    @property
    def name(self) -> str: return "MLA 9th"

    def format_bibliography(self, e: dict) -> RunList:
        runs = []
        authors = self._format_authors(e, ", editor", ", editors")
        title   = self._s(e.get("title", ""))
        journal = self._s(e.get("journal", ""))
        year    = self._s(e.get("year", ""))

        if e.get("entry_type") == "tesi":
            if authors: runs.append((authors + ". ", False, False))
            if title:   runs.append((f"\u201c{title}.\u201d ", False, False))
            if journal: runs.append((journal + ", ", False, False))
            pub = self._s(e.get("publisher", ""))
            if pub: runs.append((pub + ", ", False, False))
            if year: runs.append((year + ".", False, False))
            return runs or [("(empty thesis entry)", False, False)]

        if authors: runs.append((authors + ". ", False, False))

        if journal:
            if title: runs.append((f"\u201c{title}.\u201d ", False, False))
            runs.append((journal, False, True))
            vol = self._s(e.get("volume", ""))
            iss = self._s(e.get("issue", ""))
            if vol: runs.append((f", vol. {vol}", False, False))
            if iss: runs.append((f", no. {iss}", False, False))
            if year: runs.append((f", {year}", False, False))
            pages = self._s(e.get("pages", ""))
            if pages: runs.append((f", pp. {pages}", False, False))
            runs.append((". ", False, False))
        elif title:
            runs.append((title, False, True))
            runs.append((". ", False, False))

        pub = self._s(e.get("publisher", ""))
        loc = self._s(e.get("location", ""))
        pub_str = f"{loc}: {pub}" if (loc and pub) else (pub or loc)
        if pub_str and not journal: runs.append((pub_str + ", ", False, False))
        if year and not journal: runs.append((year + ". ", False, False))

        url = self._s(e.get("url", ""))
        if url:
            runs.append((url + ". ", False, False))
            ad = self._s(e.get("access_date", ""))
            if ad: runs.append((f"Accessed {ad}.", False, False))

        return runs or [("(empty entry)", False, False)]

    def cite_inline(self, e: dict) -> str:
        author = self._get_inline_author(self._s(e.get("authors", "")))
        return f"({author})"
    
    def cite_footnote(self, e: dict) -> RunList:
        return self.format_bibliography(e)


class ChicagoStyle(BaseStyle):
    @property
    def name(self) -> str: return "Chicago"

    def format_bibliography(self, e: dict) -> RunList:
        runs = []
        authors = self._format_authors(e, ", ed.", ", eds.")
        title   = self._s(e.get("title", ""))
        journal = self._s(e.get("journal", ""))
        year    = self._s(e.get("year", ""))

        if e.get("entry_type") == "tesi":
            if authors: runs.append((authors + ". ", False, False))
            if title:   runs.append((f"\u201c{title}.\u201d ", False, False))
            if journal: runs.append((journal + ", ", False, False))
            pub = self._s(e.get("publisher", ""))
            if pub: runs.append((pub, False, False))
            if year: runs.append((f", {year}.", False, False))
            return runs or [("(empty thesis entry)", False, False)]

        if authors: runs.append((authors + ". ", False, False))

        if journal:
            if title: runs.append((f"\u201c{title}.\u201d ", False, False))
            runs.append((journal, False, True))
            vol = self._s(e.get("volume", ""))
            iss = self._s(e.get("issue", ""))
            if vol: runs.append((f" {vol}", False, False))
            if iss: runs.append((f", no. {iss}", False, False))
            if year: runs.append((f" ({year})", False, False))
            pages = self._s(e.get("pages", ""))
            if pages: runs.append((f": {pages}", False, False))
            runs.append((". ", False, False))
        elif title:
            runs.append((title, False, True))
            runs.append((". ", False, False))

        pub  = self._s(e.get("publisher", ""))
        loc  = self._s(e.get("location", ""))
        pub_str = f"{loc}: {pub}" if (loc and pub) else (pub or loc)
        if pub_str and not journal:
            runs.append((pub_str, False, False))
            if year: runs.append((f", {year}", False, False))
            runs.append((". ", False, False))
        elif year and not journal:
            runs.append((year + ". ", False, False))

        doi = self._s(e.get("doi", ""))
        url = self._s(e.get("url", ""))
        if doi:   runs.append((f"https://doi.org/{doi}.", False, False))
        elif url: runs.append((url + ".", False, False))

        return runs or [("(empty entry)", False, False)]

    def cite_inline(self, e: dict) -> str:
        author = self._get_inline_author(self._s(e.get("authors", "")))
        year = self._s(e.get("year", "n.d."))
        return f"({author} {year})"
    
    def cite_footnote(self, e: dict) -> RunList:
        # Footnote format: Firstname Lastname, "Title," Journal Vol (Year): Pages.
        # This is a simplified approximation of Chicago footnotes.
        runs = []
        authors = self._format_authors(e, ", ed.", ", eds.")
        title   = self._s(e.get("title", ""))
        journal = self._s(e.get("journal", ""))
        year    = self._s(e.get("year", ""))
        
        # In footnotes, names are not inverted (e.g. Mattia Curto instead of Curto, Mattia)
        # But our DB stores strings, so we just use the string.
        if authors: runs.append((authors + ", ", False, False))
        
        if journal:
            if title: runs.append((f"\u201c{title},\u201d ", False, False))
            runs.append((journal, False, True))
            vol = self._s(e.get("volume", ""))
            if vol: runs.append((f" {vol}", False, False))
            if year: runs.append((f" ({year})", False, False))
            pages = self._s(e.get("pages", ""))
            if pages: runs.append((f": {pages}", False, False))
            runs.append((".", False, False))
        else:
            if title: runs.append((title, False, True))
            pub  = self._s(e.get("publisher", ""))
            loc  = self._s(e.get("location", ""))
            pub_str = f"{loc}: {pub}" if (loc and pub) else (pub or loc)
            if pub_str or year:
                runs.append((" (", False, False))
                if pub_str: runs.append((pub_str, False, False))
                if pub_str and year: runs.append((", ", False, False))
                if year: runs.append((year, False, False))
                runs.append((").", False, False))
            else:
                runs.append((".", False, False))

        return runs or [("(empty footnote)", False, False)]


class HarvardStyle(BaseStyle):
    @property
    def name(self) -> str: return "Harvard"

    def format_bibliography(self, e: dict) -> RunList:
        runs = []
        authors = self._format_authors(e, " (ed.)", " (eds)")
        year    = self._s(e.get("year", ""))
        title   = self._s(e.get("title", ""))
        journal = self._s(e.get("journal", ""))

        if e.get("entry_type") == "tesi":
            if authors: runs.append((authors, False, False))
            if year:    runs.append((f" ({year}) ", False, False))
            elif authors: runs.append((" ", False, False))
            if title:   runs.append((f"\u2018{title}\u2019. ", False, False))
            if journal: runs.append((journal + ", ", False, False))
            pub = self._s(e.get("publisher", ""))
            if pub: runs.append((pub + ".", False, False))
            return runs or [("(empty thesis entry)", False, False)]

        if authors: runs.append((authors, False, False))
        if year:    runs.append((f" ({year}) ", False, False))
        elif authors: runs.append((" ", False, False))

        if journal:
            if title: runs.append((f"\u2018{title}\u2019, ", False, False))
            runs.append((journal, False, True))
            vol = self._s(e.get("volume", ""))
            iss = self._s(e.get("issue", ""))
            if vol: runs.append((f", {vol}", False, False))
            if iss: runs.append((f"({iss})", False, False))
            pages = self._s(e.get("pages", ""))
            if pages: runs.append((f", pp. {pages}", False, False))
            runs.append((". ", False, False))
        elif title:
            runs.append((title, False, True))
            ed = self._s(e.get("edition", ""))
            if ed: runs.append((f". {ed}", False, False))
            runs.append((". ", False, False))

        pub = self._s(e.get("publisher", ""))
        loc = self._s(e.get("location", ""))
        pub_str = f"{loc}: {pub}" if (loc and pub) else (pub or loc)
        if pub_str and not journal: runs.append((pub_str + ". ", False, False))

        url = self._s(e.get("url", ""))
        if url:
            runs.append(("Available at: ", False, False))
            runs.append((url, False, False))
            ad = self._s(e.get("access_date", ""))
            if ad: runs.append((f" (Accessed: {ad})", False, False))
            runs.append((".", False, False))

        return runs or [("(empty entry)", False, False)]

    def cite_inline(self, e: dict) -> str:
        author = self._get_inline_author(self._s(e.get("authors", "")))
        year = self._s(e.get("year", "n.d."))
        return f"({author}, {year})"
    
    def cite_footnote(self, e: dict) -> RunList:
        return self.format_bibliography(e)


class PreistoriaAlpinaStyle(BaseStyle):
    @property
    def name(self) -> str: return "Preistoria Alpina"

    def format_bibliography(self, e: dict) -> RunList:
        runs = []
        authors = self._format_authors(e, " (a cura di)", " (a cura di)")
        year      = self._s(e.get("year", ""))
        title     = self._s(e.get("title", ""))
        journal   = self._s(e.get("journal", ""))
        volume    = self._s(e.get("volume", ""))
        issue     = self._s(e.get("issue", ""))
        pages     = self._s(e.get("pages", ""))
        pub       = self._s(e.get("publisher", ""))
        loc       = self._s(e.get("location", ""))
        publisher = f"{loc}, {pub}" if (loc and pub) else (pub or loc)
        edition   = self._s(e.get("edition", ""))
        doi       = self._s(e.get("doi", ""))
        url       = self._s(e.get("url", ""))
        access    = self._s(e.get("access_date", ""))
        notes     = self._s(e.get("notes", ""))
        pub_type  = self._s(e.get("pub_type", ""))

        if not pub_type:
            if "tesi" in e.get("entry_type", ""):
                pub_type = "tesi"
            elif journal and not title and not publisher:
                pub_type = "article"
            elif publisher and ("In:" in title or "in:" in title or "(ed" in publisher.lower() or "(cur" in publisher.lower() or "*" in publisher):
                pub_type = "chapter"
            elif title and not journal and publisher:
                pub_type = "book"
            elif journal:
                pub_type = "article"
            else:
                pub_type = "book"

        in_stampa  = "in stampa" in year.lower() or "in stampa" in notes.lower()
        clean_year = year.lower().replace("in stampa", "").strip(", ()")

        if e.get("entry_type") == "tesi" or pub_type in ["triennale", "magistrale", "dottorato", "specializzazione", "tesi"]:
            if authors:    runs.append((authors, False, False))
            if clean_year: runs.append((f", {clean_year} - ", False, False))
            elif authors:  runs.append((", s.d. - ", False, False))
            if title:      runs.append((title + ". ", False, True))

            thesis_type_str = ""
            if pub_type in ["triennale", "magistrale", "dottorato", "specializzazione"]:
                thesis_type_str = f"Tesi {pub_type.capitalize()}"
            elif journal:
                thesis_type_str = journal
            if thesis_type_str:
                runs.append((thesis_type_str + ", ", False, False))

            if publisher:  runs.append((publisher + ".", False, False))
            if in_stampa:  runs.append((" (in stampa)", False, False))
            return runs or [("(empty thesis entry)", False, False)]

        if authors:    runs.append((authors, False, False))
        if clean_year: runs.append((f", {clean_year} - ", False, False))
        elif authors:  runs.append((", s.d. - ", False, False))

        if pub_type == "article":
            if title:   runs.append((title + ". ", False, False))
            if journal: runs.append((journal, False, True))
            if volume:
                if issue: runs.append((f", {volume}({issue})", False, False))
                else:     runs.append((f", {volume}", False, False))
            if pages:   runs.append((f": {pages}", False, False))
            runs.append((". ", False, False))
        elif pub_type == "chapter":
            if title: runs.append((title + ". ", False, False))
            if publisher and "*" in publisher and not journal:
                for i, seg in enumerate(publisher.split("*")):
                    runs.append((seg, False, i % 2 == 1))
            else:
                if journal:
                    runs.append(("In: ", False, False))
                    runs.append((journal, False, True))
                    if volume: runs.append((f", vol. {volume}", False, False))
                    runs.append((", ", False, False))
                if publisher: runs.append((publisher + ", ", False, False))
            if pages: runs.append((f": {pages}", False, False))
            runs.append((". ", False, False))
        else:  # book / webpage
            if title:
                runs.append((title, False, True))
                if edition: runs.append((f". {edition}", False, False))
                runs.append((". ", False, False))
            if journal:
                runs.append((journal, False, False))
                if volume: runs.append((f", {volume}", False, False))
                runs.append((". ", False, False))
            if publisher: runs.append((publisher + ". ", False, False))
            if pages:
                if "pp" not in pages.lower():
                    runs.append((f"{pages} pp. ", False, False))
                else:
                    runs.append((pages + ". ", False, False))

        if url:
            runs.append((f"URL: {url}", False, False))
            if access: runs.append((f" [consultato: {access}]", False, False))
            runs.append((". ", False, False))
        if doi: runs.append((f"DOI: {doi}.", False, False))
        if in_stampa: runs.append((" (in stampa)", False, False))

        return runs or [("(empty entry)", False, False)]

    def cite_inline(self, e: dict) -> str:
        author = self._get_inline_author(self._s(e.get("authors", "")))
        year = self._s(e.get("year", "s.d."))
        return f"({author}, {year})"
    
    def cite_footnote(self, e: dict) -> RunList:
        return self.format_bibliography(e)


class CustomStyle(BaseStyle):
    def __init__(self, name: str, template: str):
        self._name = name
        self._template = template

    @property
    def name(self) -> str: return self._name

    def format_bibliography(self, e: dict) -> RunList:
        template = self._template
        for k, v in e.items():
            if isinstance(v, (str, int)):
                template = template.replace(f"{{{k}}}", str(v).strip())

        template = re.sub(r'\{[^}]+\}', '', template)
        tokens = re.split(r'(<i>|</i>|<b>|</b>)', template)
        runs = []
        is_i = is_b = False
        for t in tokens:
            if t == '<i>':    is_i = True
            elif t == '</i>': is_i = False
            elif t == '<b>':  is_b = True
            elif t == '</b>': is_b = False
            elif t:
                runs.append((t, is_b, is_i))
        return runs if runs else [("(empty custom entry)", False, False)]

    def cite_inline(self, e: dict) -> str:
        author = self._get_inline_author(self._s(e.get("authors", "")))
        return f"[{author}]"
    
    def cite_footnote(self, e: dict) -> RunList:
        return self.format_bibliography(e)


class CitationStyleEngine:
    """
    Manager for formatting bibliography entries using Strategy Pattern.
    """
    _BUILTIN_STYLES = [
        PreistoriaAlpinaStyle(),
        ApaStyle(),
        MlaStyle(),
        ChicagoStyle(),
        HarvardStyle()
    ]
    CUSTOM_STYLES: dict = {}

    @classmethod
    def load_custom_styles(cls, settings_dict: dict):
        cls.CUSTOM_STYLES = settings_dict

    @classmethod
    def get_all_styles(cls) -> list[str]:
        return [s.name for s in cls._BUILTIN_STYLES] + list(cls.CUSTOM_STYLES.keys())

    @classmethod
    def _get_strategy(cls, style_name: str) -> CitationStyle:
        if style_name in cls.CUSTOM_STYLES:
            return CustomStyle(style_name, cls.CUSTOM_STYLES[style_name])
        for s in cls._BUILTIN_STYLES:
            if s.name == style_name:
                return s
        return cls._BUILTIN_STYLES[0]

    @classmethod
    def format_plain(cls, e: dict, style: str) -> str:
        """Return a plain-text citation for preview."""
        strategy = cls._get_strategy(style)
        runs = strategy.format_bibliography(e)
        return "".join(t for t, _, _ in runs)

    @classmethod
    def format_runs(cls, e: dict, style: str) -> list[tuple[str, bool, bool]]:
        """Return [(text, bold, italic), …] for DOCX run building."""
        strategy = cls._get_strategy(style)
        return strategy.format_bibliography(e)

    @classmethod
    def cite_inline(cls, e: dict, style: str) -> str:
        """Return in-text citation, e.g. (Author, 2024)."""
        strategy = cls._get_strategy(style)
        return strategy.cite_inline(e)

    @classmethod
    def cite_footnote(cls, e: dict, style: str) -> list[tuple[str, bool, bool]]:
        """Return footnote citation formatted runs."""
        strategy = cls._get_strategy(style)
        return strategy.cite_footnote(e)
