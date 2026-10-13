"""Step 1: local anonymization before anything is sent to the API (CLAUDE.md, section 4).

Rules (regex + checksums) for identifiers, a komparycja-based detector for
names and addresses, and an optional NER detector (spaCy) plugged in through
the `EntityDetector` protocol. One `Anonymizer` per case keeps tokens stable
across documents. The mapping never leaves the server; the app stores it
encrypted (see app/crypto.py).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

# --- checksums -------------------------------------------------------------------


def valid_pesel(s: str) -> bool:
    if not re.fullmatch(r"\d{11}", s):
        return False
    w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return (10 - sum(int(d) * k for d, k in zip(s, w)) % 10) % 10 == int(s[10])


def valid_nip(s: str) -> bool:
    d = re.sub(r"\D", "", s)
    if len(d) != 10:
        return False
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    c = sum(int(x) * k for x, k in zip(d, w)) % 11
    return c != 10 and c == int(d[9])


def valid_regon(s: str) -> bool:
    d = re.sub(r"\D", "", s)
    if len(d) == 9:
        w = (8, 9, 2, 3, 4, 5, 6, 7)
    elif len(d) == 14:
        w = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
    else:
        return False
    return sum(int(x) * k for x, k in zip(d, w)) % 11 % 10 == int(d[-1])


def valid_id_card(s: str) -> bool:
    s = s.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{3}\d{6}", s):
        return False
    values = [ord(c) - 55 for c in s[:3]] + [int(c) for c in s[3:]]
    w = (7, 3, 1, 0, 7, 3, 1, 7, 3)  # position 4 is the check digit
    return sum(v * k for v, k in zip(values, w)) % 10 == values[3]


_KW_CHARS = "0123456789XABCDEFGHIJKLMNOPRSTUWYZ"


def valid_kw(s: str) -> bool:
    m = re.fullmatch(r"([A-Z]{2}\d[A-Z])/(\d{8})/(\d)", s.upper())
    if not m:
        return False
    chars = m.group(1) + m.group(2)
    w = (1, 3, 7, 1, 3, 7, 1, 3, 7, 1, 3, 7)
    total = sum(_KW_CHARS.index(c) * k for c, k in zip(chars, w))
    return total % 10 == int(m.group(3))


def valid_iban_pl(s: str) -> bool:
    d = re.sub(r"\s", "", s).upper()
    if d.startswith("PL"):
        d = d[2:]
    if not re.fullmatch(r"\d{26}", d):
        return False
    rearranged = d[2:] + "2521" + d[:2]  # P=25, L=21
    return int(rearranged) % 97 == 1


# --- rules ------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    label: str
    pattern: re.Pattern[str]
    check: Callable[[str], bool] | None = None
    group: int = 0


RULES: tuple[Rule, ...] = (
    # Also as OCR reads it: "jan. kowalskiQexample.com", "jan ©example.pl", "jan(at)example.pl".
    Rule("EMAIL", re.compile(r"[\w.+-]+(?:(?<=\.)\s[\w.+-]+)?\s?(?:@|©|\(at\)|Q(?=[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?!\w)))\s?[\w-]+(?:\.[\w-]+)+")),
    Rule("KONTO", re.compile(r"(?<![\w])(?:PL\s?)?\d{2}(?:[ ]?\d{4}){6}(?!\d)"), valid_iban_pl),
    Rule("KONTO", re.compile(r"(?i)(?:rachun\w*|konto|konta|nr\s+rach\.?)[^\d]{0,40}((?:PL\s?)?\d{2}(?:[ ]?\d{4}){6})"),
         None, 1),
    Rule("KW", re.compile(r"\b[A-Z]{2}\d[A-Z]/\d{8}/\d\b"), None),
    Rule("PESEL", re.compile(r"(?<!\d)\d{11}(?!\d)"), valid_pesel),
    Rule("PESEL", re.compile(r"(?i)PESEL[:\s]*(?:nr\s*)?([\dOoIl]{11})(?![\dOoIl])"), None, 1),
    Rule("NIP", re.compile(r"(?i)NIP[:\s]*((?:PL)?\d{3}-?\d{3}-?\d{2}-?\d{2}|\d{3}-\d{2}-\d{2}-\d{3})"), None, 1),
    Rule("NIP", re.compile(r"(?<![\d-])\d{3}-\d{3}-\d{2}-\d{2}(?![\d-])"), valid_nip),
    Rule("REGON", re.compile(r"(?i)REGON[:\s]*(\d{9}(?:\d{5})?)"), None, 1),
    Rule("DOWOD", re.compile(r"\b[A-Z]{3}\s?\d{6}\b"), valid_id_card),
    # "dowodem osobistym serii i nr: ABC 123456", "paszportem nr FA1234567"
    Rule("DOWOD", re.compile(r"(?i)(?:dow\w*\s+osobist\w*|paszport\w*)[^\n\d]{0,40}?(?<![A-Za-z])"
                             r"((?-i:[A-Z][A-Z0-9]{1,3}\s?[0-9OoIl]{5,7}))(?![A-Za-z0-9])"), None, 1),
    # Date of birth: "urodzony dnia 1 stycznia 1990 roku", "ur. 01.01.1990", "data urodzenia: 1990-01-01"
    Rule("URODZENIE", re.compile(r"(?i)\b(?:urodzon\w*|ur\.|data\s+urodzenia:?)\s+(?:w\s+dniu\s+|dnia\s+)?"
                               r"(\d{1,2}[.\s/-]+(?:\d{1,2}|[a-ząćęłńóśźż]{4,})[.\s/-]+\d{4}|\d{4}-\d{2}-\d{2})"), None, 1),
    # Maiden / previous surname: "z domu Kowalska", "nazwisko rodowe: Kowalska", "primo voto Nowak"
    Rule("NAZWISKO", re.compile(r"(?i)\b(?:z\s+domu|nazwisk\w*\s+rodow\w*:?|primo\s+voto|secundo\s+voto)\s+"
                                r"((?-i:[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+(?:\s?[-–]\s?[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+)?))"), None, 1),
    # Parents' first names in the komparycja ("Imiona rodziców: Jan i Helena", "córka Adama i Ewy").
    Rule("RODZICE", re.compile(r"(?i)(?:imiona\s+rodzic\w*|imię\s+ojca\s+i\s+matki)[:\s]+"
                               r"((?-i:[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+)(?:\s*(?:i|,)\s*(?-i:[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+))*)"),
         None, 1),
    # "syn Romana i Teresy", "córka Pawła"
    Rule("RODZICE", re.compile(r"\b(?:syn|córka)\s+([A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+(?:\s+i\s+[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+)?)"),
         None, 1),
    Rule("TELEFON", re.compile(r"(?<![\d/])(?:\+48[\s-]?)?\d{3}[\s-]\d{3}[\s-]\d{3}(?![\d/])")),
    Rule("TELEFON", re.compile(r"(?<![\d/])\+48\s?\d{9}(?!\d)")),
    # Landline: "(22) 123 45 67", "22 123-45-67"
    Rule("TELEFON", re.compile(r"(?<![\d/])(?:\+48[\s-]?)?\(?\d{2}\)?[\s-]\d{3}[\s-]\d{2}[\s-]\d{2}(?![\d/])")),
    Rule("TELEFON", re.compile(r"(?i)(?:tel\.?|telefon\w*)[:\s]*(\+?\(?\d[\d\s()-]{7,16}\d)"), None, 1),
    Rule("KOD", re.compile(r"(?<![\d-])\d{2}-\d{3}(?![\d-])")),
)

# Addresses: street prefix + name + house number (with optional flat number).
ADDRESS = re.compile(
    r"\b(?:ul\.|ulicy|ulica|al\.|alei|aleja|pl\.|placu|plac|os\.|osiedle|osiedlu)\s+"
    r"(?:[A-ZŁŚŻŹĆŃÓĘĄ0-9][\w.\-]*\s+){1,4}?\d+[A-Za-z]?(?:\s?/\s?\d+[A-Za-z]?|\s+(?:lok\.|m\.)\s*\d+)?"
)

# Persons in the komparycja: honorific or role followed by a capitalized first and last name.
# A name word; double surnames with a hyphen or a spaced dash, also broken at the line end ("Nowak-\nKowalska").
_WORD = r"[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+"
_NAME = rf"{_WORD}(?:(?:[ ]?[-–][ ]?|-\n){_WORD})?"
_CAPS = r"[A-ZŁŚŻŹĆŃÓĘĄ]{2,}(?:-[A-ZŁŚŻŹĆŃÓĘĄ]{2,})?"  # names written in capitals ("JAN KOWALSKI")
_ANY = rf"(?:{_NAME}|{_CAPS})"
# Surname with a particle: "van der Berg", "de Gaulle", "von Braun".
_LAST = rf"(?:(?:van|von|de|der|den|del|da|di|du|dos|la|le)\s+){{0,2}}{_NAME}"
_TITLES = r"(?:\s+(?:dr|hab|prof|mgr|mec)\.){0,3}"
PERSON = re.compile(
    rf"\b(?:Pan|Pani|Panem|Panią|Pana|Panu|p\.){_TITLES}\s+({_NAME})\s+({_LAST})(?:[ \t]+({_LAST})(?=\s*,))?"
)
_ROLE_WITH_SEPARATOR = (r"(?i:nabywc\w*|nabywczyni\w*|kupując\w*|sprzedając\w*|przedstawiciel\w*(?:\s+dewelopera)?|"
                        r"pełnomocni\w*(?:\s+[A-ZŁŚŻ]{2,})?|stawając\w*|wnioskodawc\w*|uczestni\w*|świadek|"
                        r"kancelaria\s+notarialna|imię\s+i\s+nazwisko(?:\s+\w+)?|odbierając\w*|przekazując\w*)")
_ROLE_FREE = (r"(?i:notariusz\w*(?:\s+w\s+(?-i:[A-ZŁŚŻŹĆŃÓ])\w+)?" + _TITLES
              + r"|zastępc\w*\s+notarialn\w*|reprezentowan\w*\s+przez)")
PERSON_BY_ROLE = re.compile(
    rf"(?:{_ROLE_WITH_SEPARATOR}\s*[:—–-]\s*|{_ROLE_FREE}\s+)({_ANY})\s+({_LAST}|{_CAPS})(?:[ \t]+({_LAST}|{_CAPS}))?"
)
# Two first names, as notaries write them: "Adam Michał Nowak, używający (pierwszego) imienia Adam".
PERSON_TWO_NAMES = re.compile(
    rf"({_NAME})\s+({_NAME})\s+({_LAST}),?\s+(?i:używając\w*)\s+(?i:pierwszego\s+)?(?i:imienia)\b"
)
PERSON_BEFORE_ID = re.compile(
    rf"({_NAME})\s+({_LAST}),?\s+(?:\(?\s*)?(?:PESEL|legitymując\w*|zamieszkał\w*|córk\w*|syn\b|"
    r"(?i:według\s+oświadcz\w*|wg\.?\s+ośw\w*|imiona\s+rodzic\w*|imię\s+ojca|obywatel\w*|urodzon\w*|"
    r"działając\w*|używając\w*|z\s+domu|dow\w*\s+osobist\w*))"
)
# Name before the notary's title: "przede mną Katarzyną Nowak, notariuszem", "Jana Nowaka, zastępcę notarialnego".
PERSON_BEFORE_NOTARY = re.compile(
    rf"({_NAME})[ \t]+({_LAST})(?:[ \t]+({_LAST}))?,?\s+(?i:notariusz\w*|zastępc\w*\s+notarialn\w*|asesor\w*\s+notarialn\w*)"
)
# Two persons at once: "Nabywcą: Jan Nowak i Anna Nowak", "notariuszem Janem Nowakiem/Anną Kowalską".
PERSON_PAIR = re.compile(
    rf"(?:{_ROLE_WITH_SEPARATOR}\s*[:—–-]\s*|{_ROLE_FREE}\s+|\b(?:Państwo|Państwa|małżonkowie|małżonków)\s+)"
    rf"({_NAME})\s+({_LAST})\s*(?:\s(?:i|oraz)\s|/)\s*({_NAME})\s+({_LAST})"
)
# Spouses with a shared surname: "Państwo Jan i Anna Nowakowie".
PERSON_SHARED = re.compile(rf"\b(?:Państwo|Państwa|małżonkowie|małżonków)\s+({_NAME})\s+i\s+({_NAME})\s+({_LAST})")
# Safety net in the komparycja: a numbered entry starting with a name ("1. Jan Nowak,", "2/ Anna Maria Kowalska –").
PERSON_ENTRY = re.compile(
    rf"(?m)^[ \t]*(?:\d{{1,2}}[ \t]?[.)/]|ad[ \t]?\d{{1,2}}[.)]?)[ \t]*(?:(?:Pan|Pani){_TITLES}[ \t]+)?"
    rf"({_ANY})[ \t]+({_LAST}|{_CAPS})(?:[ \t]+({_LAST}|{_CAPS}))?(?=[ \t]*[,(]|[ \t]+[-–][ \t])"
)
_KOMPARYCJA_START = re.compile(r"(?i)stawi\w*\s+si[ęe]")
_KOMPARYCJA_END = re.compile(r"(?i)umowa\s+deweloperska|umowa\s+sprzeda|§\s*1(?!\d)|tożsamość\s+stawając")
_KOMPARYCJA_MAX = 6000
# Words replaced in the text once a person is known (single words; capitals too: "KOWALSKI").
_PERSON_WORD = re.compile(rf"\b(?:{_WORD}|[A-ZŁŚŻŹĆŃÓĘĄ]{{2,}})\b")
# Words that look like names but are not.
_STOP = {"Spółka", "Spółki", "Deweloper", "Dewelopera", "Nabywca", "Nabywcy", "Kupujący", "Sprzedający",
         "Notariusz", "Rzeczypospolitej", "Polskiej", "Warszawa", "Warszawie", "Sądu", "Rejonowego",
         "Imiona", "Dowód", "Adres", "Lokalu", "Lokal", "Dewelopera", "Krajowego", "Ośrodka", "Skarbu", "Państwa"}


# Defined contract terms are never names. Long stems match as prefixes (all inflections);
# short ones only exactly, so real names like Karol, Stroński or Sądecki are not excluded.
_TERM_PREFIXES = (
    "całkowit", "przenosząc", "budynk", "budynek", "nieruchomoś", "harmonogram", "rachun", "dewelop",
    "nabywc", "inwestycj", "dokumentacj", "odbior", "odbiór", "wydani", "protok", "opłat", "komórk",
    "lokatorsk", "garaż", "wspóln", "zadani", "przedsięwzię", "prospekt", "załącznik", "regulamin",
    "rozporządzeni", "kodeks", "notarialn", "repertorium", "spółk", "pozwoleni", "postojow", "mieszkaln",
    "tożsamoś", "stawając", "zastrzeż", "numer", "rejestr", "komplementariusz", "komandyt", "ewidencj",
    "informacj", "centraln",
)
_TERM_STEMS = {"cen", "kar", "stron", "sąd", "umow", "lokal", "termin", "aneks", "miejsc", "artykuł", "ustaw",
               "decyzj", "warunk", "zarząd"}


def _is_term(word: str) -> bool:
    w = word.lower()
    return word in _STOP or _stem(word) in _TERM_STEMS or any(w.startswith(t) for t in _TERM_PREFIXES)


# Role given after the person's entry in the komparycja: "..., zwani dalej „Nabywcą”",
# "Natalia Nowak zwana będzie również jako „Nabywca”", "Adam Nowak również jako „Przedstawiciel Dewelopera”".
_ROLE_FILL = (r"(?:dalej|łącznie|także|również|każdy\s+z\s+osobna|będzie|będą|jest|są|"
              r"w\s+(?:dalszej\s+treści(?:\s+niniejszego)?\s+(?:aktu|umowy)|niniejszej\s+umowie|niniejszym\s+akcie))")
ROLE_AFTER = re.compile(
    rf"(?i:(?:zwan|nazywan|określan)\w*(?:/\w+)?\s+(?:{_ROLE_FILL}:?\s+)*(?:jako\s+)?|(?:{_ROLE_FILL}\s+)*jako\s+(?=[„\"”']))"
    r"[„\"”']?\s*(?:(?i:spółk)\w*[”\"]?\s+(?i:lub)\s+[„\"]?)?"
    r"((?i:nabywc|kupując|sprzedając|dewelop|przedstawiciel|pełnomocni)\w*)"
)
_NAME_BEFORE_MARKER = re.compile(rf"({_NAME})\s+({_LAST})[\s,]*$")
_ROLE_AFTER_NAMES = (("buyer", ("nabywc", "kupując")), ("seller", ("sprzedając",)),
                     ("representative", ("dewelop", "przedstawiciel", "pełnomocni")))
_ROLE_AFTER_REACH = 1500  # characters before the marker that may belong to the same komparycja entry


def _role_after(word: str) -> str | None:
    w = word.lower()
    return next((role for role, prefixes in _ROLE_AFTER_NAMES if any(w.startswith(p) for p in prefixes)), None)


_ROLE_NAMES = (
    ("buyer", ("nabywc", "nabywczyni", "kupując", "odbierając")),
    ("seller", ("sprzedając",)),
    ("representative", ("przedstawiciel", "pełnomocni", "reprezentowan", "przekazując")),
    ("notary", ("notariusz", "zastępc", "kancelaria", "asesor")),
)


def _komparycja(text: str) -> tuple[int, int]:
    """Span of the komparycja: from "stawili się" to the start of the agreement (or a fixed length)."""
    start = _KOMPARYCJA_START.search(text)
    if not start:
        return (0, 0)
    end = _KOMPARYCJA_END.search(text, start.end())
    return (start.start(), min(end.start() if end else len(text), start.start() + _KOMPARYCJA_MAX))


def _parts(name: str) -> list[str]:
    """Capitalized parts of a name: "van der Berg" -> [Berg], "Nowak – Kowalska" -> [Nowak, Kowalska]."""
    return [p for p in re.split(r"[\s\-–]+", name) if p and p[0].isupper()]


def _display(name: str) -> str:
    """Name for the UI and letters: one line, "JAN KOWALSKI" -> "Jan Kowalski"."""
    name = re.sub(r"\s*\n\s*", "", name) if "-\n" in name else re.sub(r"\s+", " ", name)
    if re.search(r"[a-ząćęłńóśźż]", re.sub(r"\b(?:van|von|de|der|den|del|da|di|du|dos|la|le)\b", "", name)):
        return name
    return re.sub(r"[A-ZŁŚŻŹĆŃÓĘĄ]{2,}", lambda m: m.group(0)[0] + m.group(0)[1:].lower(), name)


def _clean(word: str | None) -> str | None:
    """Drops trailing parts of a compound that are contract terms ("Nowak – Deweloper" -> "Nowak");
    None when the name itself is a term."""
    if not word:
        return None
    pieces = re.split(r"(\s?[-–]\s?|-\n)", word)
    if not _parts(pieces[0]) or any(_is_term(p) for p in _parts(pieces[0])):
        return None
    kept = pieces[0]
    for sep, piece in zip(pieces[1::2], pieces[2::2]):
        if _is_term(piece):
            break
        kept += sep + piece
    return kept
_ADDRESS_LINE = re.compile(
    r"(?i)(?:adres\w*\s*:|zamieszkał\w*|zam\.)\s*(?:w\s+\w+\s*,?\s*)?(?:przy\s+)?"
    r"([^\n]{5,140}?)"
    # Sentence end: a dot that does not close an abbreviation used in addresses.
    r"(?:(?<!\bul)(?<!\bal)(?<!\bpl)(?<!\bos)(?<!\bm)(?<!\blok)(?<!\bnr)\.(?:\s|$)|\n|$)"
)


def _role_of(matched: str) -> str | None:
    head = matched.lower()
    for role, prefixes in _ROLE_NAMES:
        if any(head.startswith(p) or f" {p}" in head[:40] for p in prefixes):
            return role
    return None


def _address_after(text: str, pos: int) -> str | None:
    """First address line in the komparycja entry that follows a person (until the next person)."""
    window = text[pos:pos + 400]
    nxt = PERSON_BY_ROLE.search(window)
    if nxt:
        window = window[:nxt.start()]
    m = _ADDRESS_LINE.search(window)
    return m.group(1).strip().rstrip(",;") if m else None


class EntityDetector(Protocol):
    """Optional NER: returns (label, text) pairs found in the text, e.g. ("OSOBA", "Jan Kowalski")."""

    def detect(self, text: str) -> Iterable[tuple[str, str]]: ...


@dataclass
class Replacement:
    token: str
    original: str
    label: str


@dataclass
class Anonymizer:
    detectors: list[EntityDetector] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)  # token -> original
    _by_original: dict[tuple[str, str], str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)
    _person_stems: dict[str, str] = field(default_factory=dict)  # stem -> token
    _person_bases: dict[str, str] = field(default_factory=dict)  # name without final vowels -> token
    replacements: list[Replacement] = field(default_factory=list)
    persons: dict[str, dict[str, str | None]] = field(default_factory=dict)  # token -> name, role, address

    def _token(self, label: str, original: str) -> str:
        key = (label, original)
        if key not in self._by_original:
            self._counters[label] = self._counters.get(label, 0) + 1
            token = f"[{label}_{self._counters[label]}]"
            self._by_original[key] = token
            self.mapping[token] = original
        token = self._by_original[key]
        self.replacements.append(Replacement(token, original, label))
        return token

    # Names are collected from all documents first, then replaced everywhere,
    # so a surname from the agreement's komparycja is also removed from the deed.
    def learn_names(self, texts: Iterable[str]) -> None:
        for text in texts:
            found: list[tuple[int, str]] = []  # (position, token) of persons in this text

            def add(pos: int, end: int, first: str, second: str, third: str | None, role: str | None) -> None:
                first_c, second_c, third_c = _clean(first), _clean(second), _clean(third)
                middle, last = (second_c, third_c) if third_c else (None, second_c)
                if not first_c or not second_c:
                    return
                token = self._register_person(first_c, last, middle)
                name = _display(f"{first_c} {middle} {last}" if middle else f"{first_c} {last}")
                self._note_person(token, name, role, _address_after(text, end))
                found.append((pos, token))

            for regex in (PERSON_TWO_NAMES, PERSON, PERSON_BEFORE_ID, PERSON_BY_ROLE, PERSON_BEFORE_NOTARY):
                for m in regex.finditer(text):
                    role = (_role_of(m.group(0)) if regex is PERSON_BY_ROLE
                            else "notary" if regex is PERSON_BEFORE_NOTARY else None)
                    third = m.group(3) if regex in (PERSON_TWO_NAMES, PERSON, PERSON_BY_ROLE, PERSON_BEFORE_NOTARY) else None
                    add(m.start(), m.end(), m.group(1), m.group(2), third, role)
            for m in PERSON_PAIR.finditer(text):
                role = _role_of(m.group(0))
                add(m.start(), m.end(), m.group(1), m.group(2), None, role)
                add(m.start(3), m.end(), m.group(3), m.group(4), None, role)
            for m in PERSON_SHARED.finditer(text):
                add(m.start(), m.end(), m.group(1), m.group(3), None, None)
                add(m.start(2), m.end(), m.group(2), m.group(3), None, None)
            start, end = _komparycja(text)
            for m in PERSON_ENTRY.finditer(text, start, end):
                add(m.start(), m.end(), m.group(1), m.group(2), m.group(3), None)
            self._roles_after(text, found)
            for detector in self.detectors:
                for label, value in detector.detect(text):
                    if label == "OSOBA":
                        parts = value.split()
                        if len(parts) >= 2:
                            self._register_person(parts[0], parts[-1])

    def _roles_after(self, text: str, found: list[tuple[int, str]]) -> None:
        """Persons without a role get the one named after them ("zwani dalej Nabywcą")."""
        markers = [(m, _role_after(m.group(1))) for m in ROLE_AFTER.finditer(text)]
        untargeted = []
        for m, role in markers:  # "Natalia Nowak zwana będzie jako Nabywca": that person only
            named = _NAME_BEFORE_MARKER.search(text[max(0, m.start() - 80):m.start()])
            token = self._known_person(named.group(1), named.group(2)) if named else None
            if token:
                if role and self.persons.get(token, {}).get("role", "x") is None:
                    self.persons[token]["role"] = role
            else:
                untargeted.append((m, role))
        boundary = 0
        for m, role in markers:  # "..., PESEL ..., zwani dalej Nabywcą": entries since the previous marker
            if (m, role) in untargeted:
                start = max(boundary, m.start() - _ROLE_AFTER_REACH)
                for pos, token in found:
                    if role and start <= pos < m.start() and self.persons[token]["role"] is None:
                        self.persons[token]["role"] = role
            boundary = m.end()

    def _known_person(self, first: str, last: str) -> str | None:
        t1 = self._word_token(_parts(first)[0]) if _parts(first) else None
        t2 = self._word_token(_parts(last)[0]) if _parts(last) else None
        return t1 if t1 and t1 == t2 else None

    def _word_token(self, word: str) -> str | None:
        return self._person_stems.get(_stem(word)) or self._token_by_base(word)

    def _note_person(self, token: str, name: str, role: str | None, address: str | None) -> None:
        entry = self.persons.setdefault(token, {"name": name, "role": None, "address": None})
        entry["role"] = entry["role"] or role
        entry["address"] = entry["address"] or address

    def _register_person(self, first: str, last: str, middle: str | None = None) -> str:
        key = ("OSOBA", f"{first} {last}")
        known_first = self._word_token(_parts(first)[0])
        known_last = self._word_token(_parts(last)[0])
        if key not in self._by_original and known_first and known_first == known_last:
            self._by_original[key] = known_first
        if key not in self._by_original:
            self._counters["OSOBA"] = self._counters.get("OSOBA", 0) + 1
            token = f"[OSOBA_{self._counters['OSOBA']}]"
            self._by_original[key] = token
            self.mapping[token] = f"{first} {middle} {last}" if middle else f"{first} {last}"
        token = self._by_original[key]
        for word in (w for name in (first, last, middle) if name for w in _parts(name)):
            self._person_stems.setdefault(_stem(word), token)
            base = word.lower().rstrip("aeiouyąę")
            # Fleeting "e" in Polish inflection: Paweł -> Pawła/Pawłowi, Marek -> Marka, Jacek -> Jacka.
            fleeting = re.sub(r"e(?=[a-ząćęłńóśźż]$)", "", base)
            for variant in {base, fleeting}:
                if len(variant) >= 4:
                    self._person_bases.setdefault(variant, token)
        return self._by_original[key]

    def anonymize(self, text: str) -> str:
        for rule in RULES:
            text = self._apply_rule(text, rule)
        text = ADDRESS.sub(lambda m: self._token("ADRES", m.group(0)), text)
        for detector in self.detectors:
            for label, value in detector.detect(text):
                if label != "OSOBA" and value and value in text:
                    text = text.replace(value, self._token(label, value))
        return self._replace_person_words(text)

    def _apply_rule(self, text: str, rule: Rule) -> str:
        def repl(m: re.Match[str]) -> str:
            value = m.group(rule.group)
            if value.startswith("[") or (rule.check and not rule.check(value)):
                return m.group(0)
            token = self._token(rule.label, value)
            if rule.group == 0:
                return token
            start, end = m.start(rule.group) - m.start(), m.end(rule.group) - m.start()
            whole = m.group(0)
            return whole[:start] + token + whole[end:]

        return rule.pattern.sub(repl, text)

    def _token_by_base(self, word: str) -> str | None:
        """Inflected form starting with a known name's base (Bartłomiej -> Bartłomiejowi)."""
        lowered = word.lower()
        for base, token in self._person_bases.items():
            if lowered.startswith(base) and len(lowered) - len(base) <= 4:
                return token
        return None

    def _form_token(self, token: str, form: str) -> str:
        """Token for an exact surface form: the full registered name keeps `token`,
        any other form (single word, inflection) gets `[OSOBA_n.k]` restoring exactly that form."""
        if self.mapping.get(token) == form:
            return token
        key = ("FORM", f"{token}|{form}")
        if key not in self._by_original:
            k = sum(1 for t in self.mapping if t.startswith(token[:-1] + ".")) + 1
            sub_token = f"{token[:-1]}.{k}]"
            self._by_original[key] = sub_token
            self.mapping[sub_token] = form
        return self._by_original[key]

    def _replace_person_words(self, text: str) -> str:
        if not self._person_stems:
            return text
        # Full "First Last" pairs first, so both words map to one token. Scanned word by word
        # (overlapping), so a capitalized word before the name ("Panem Jan Nowakowski") is skipped.
        words = list(_PERSON_WORD.finditer(text))
        out: list[str] = []
        pos = 0
        i = 0
        while i < len(words) - 1:
            a, b = words[i], words[i + 1]
            if text[a.end():b.start()].strip() == "" and "\n\n" not in text[a.end():b.start()]:
                t1 = self._word_token(a.group(0))
                t2 = self._word_token(b.group(0))
                if t1 and t1 == t2:
                    while i + 2 < len(words):
                        c = words[i + 2]
                        gap = text[b.end():c.start()]
                        tc = self._word_token(c.group(0))
                        if gap.strip() or "\n\n" in gap or tc != t1:
                            break
                        b = c
                        i += 1
                    form = text[a.start():b.end()]
                    token = self._form_token(t1, form)
                    self.replacements.append(Replacement(token, form, "OSOBA"))
                    out.append(text[pos:a.start()] + token)
                    pos = b.end()
                    i += 2
                    continue
            i += 1
        text = "".join(out) + text[pos:]

        def single(m: re.Match[str]) -> str:
            word = m.group(0)
            token = self._word_token(word)
            if token and word not in _STOP:
                token = self._form_token(token, word)
                self.replacements.append(Replacement(token, word, "OSOBA"))
                return token
            return word

        return _PERSON_WORD.sub(single, text)


_SUFFIXES = sorted(
    ("iego", "iemu", "ymi", "imi", "ich", "ych", "ego", "emu", "owi", "iej", "ach", "ami", "ów",
     "ej", "ym", "im", "em", "ie", "om", "ą", "ę", "y", "i", "a", "e", "u", "o"),
    key=len, reverse=True,
)


def _stem(word: str) -> str:
    """Crude stem for Polish name inflection (Kowalski/Kowalskiego, Testowa/Testowej, Anna/Annie)."""
    w = word.lower()
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put original values back (locally, e.g. for the letter or the UI)."""
    return re.sub(r"\[[A-Z]+_\d+(?:\.\d+)?\]", lambda m: mapping.get(m.group(0), m.group(0)), text)


def anonymize_pages(documents: dict[str, list[str]], detectors: list[EntityDetector] | None = None
                    ) -> tuple[dict[str, list[str]], Anonymizer]:
    anon = Anonymizer(detectors=list(detectors or []))
    anon.learn_names(page for pages in documents.values() for page in pages)
    out = {doc_id: [anon.anonymize(p) for p in pages] for doc_id, pages in documents.items()}
    return out, anon


def find_leaks(text: str, known_values: Iterable[str]) -> list[str]:
    """Quality gate helper: known personal values still present in anonymized text."""
    norm = re.sub(r"\s+", " ", text)
    return [v for v in known_values if v and re.sub(r"\s+", " ", v) in norm]
