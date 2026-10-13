"""Anonymization tests. All identifiers are generated here with valid checksums; names are invented."""

from __future__ import annotations

from pipeline.anonymize import (
    Anonymizer,
    _KW_CHARS,
    anonymize_pages,
    find_leaks,
    restore,
    valid_id_card,
    valid_iban_pl,
    valid_kw,
    valid_nip,
    valid_pesel,
    valid_regon,
)


def make_pesel(first10: str) -> str:
    w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return first10 + str((10 - sum(int(d) * k for d, k in zip(first10, w)) % 10) % 10)


def make_nip(first9: str) -> str:
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    for _ in range(10):
        c = sum(int(x) * k for x, k in zip(first9, w)) % 11
        if c != 10:
            return first9 + str(c)
        first9 = first9[:-1] + str((int(first9[-1]) + 1) % 10)
    raise AssertionError


def make_regon9(first8: str) -> str:
    w = (8, 9, 2, 3, 4, 5, 6, 7)
    return first8 + str(sum(int(x) * k for x, k in zip(first8, w)) % 11 % 10)


def make_iban(bank24: str) -> str:
    check = 98 - int(bank24 + "252100") % 97
    return f"{check:02d}{bank24}"


def make_id_card(letters: str, digits5: str) -> str:
    values = [ord(c) - 55 for c in letters] + [0] + [int(c) for c in digits5]
    w = (7, 3, 1, 0, 7, 3, 1, 7, 3)
    return f"{letters}{sum(v * k for v, k in zip(values, w)) % 10}{digits5}"


def make_kw(court: str, number8: str) -> str:
    w = (1, 3, 7, 1, 3, 7, 1, 3, 7, 1, 3, 7)
    total = sum(_KW_CHARS.index(c) * k for c, k in zip(court + number8, w))
    return f"{court}/{number8}/{total % 10}"


PESEL = make_pesel("9001011234")
NIP = make_nip("123456789")
NIP_FMT = f"{NIP[:3]}-{NIP[3:6]}-{NIP[6:8]}-{NIP[8:]}"
REGON = make_regon9("12345678")
IBAN = make_iban("109010140000071219812874")
IBAN_FMT = " ".join([IBAN[:2]] + [IBAN[i:i + 4] for i in range(2, 26, 4)])
ID_CARD = make_id_card("ABC", "23456")
KW = make_kw("WA1M", "00012345")


def test_checksums():
    assert valid_pesel(PESEL) and not valid_pesel(PESEL[:-1] + str((int(PESEL[-1]) + 1) % 10))
    assert not valid_pesel("123")
    assert valid_nip(NIP) and valid_nip(NIP_FMT) and not valid_nip("1234567890") and not valid_nip("12")
    assert valid_regon(REGON) and not valid_regon("123456789") and not valid_regon("1234")
    assert valid_regon(make_regon14())
    assert valid_iban_pl(IBAN) and valid_iban_pl("PL" + IBAN_FMT) and not valid_iban_pl("1" * 26)
    assert not valid_iban_pl("123")
    assert valid_id_card(ID_CARD) and not valid_id_card("ABC000000") and not valid_id_card("12")
    assert valid_kw(KW) and not valid_kw(KW[:-1] + str((int(KW[-1]) + 1) % 10)) and not valid_kw("x")


def make_regon14() -> str:
    first13 = "1234567890123"
    w = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
    return first13 + str(sum(int(x) * k for x, k in zip(first13, w)) % 11 % 10)


AGREEMENT = (
    "UMOWA DEWELOPERSKA zawarta pomiędzy Budowa Test Spółka z o.o. (NIP: " + NIP_FMT + ", REGON: " + REGON + ") "
    "a Panem Tomaszem Przykładowym, PESEL " + PESEL + ", legitymującym się dowodem osobistym nr " + ID_CARD + ", "
    "zamieszkałym w Krakowie przy ul. Długiej 15/4, 31-147 Kraków, tel. 600 100 200, e-mail tp@example.com. "
    "Wpłaty na rachunek nr " + IBAN_FMT + ". Księga wieczysta " + KW + ". "
    "Cena brutto wynosi 450.000,00 zł. Lokal zostanie wydany do dnia 31 marca 2024 r."
)
DEED = "Kupujący Tomasz Przykładowy oświadcza, że Przykładowego nie łączą z Deweloperem żadne spory."


def test_anonymize_agreement_removes_all_identifiers():
    pages, anon = anonymize_pages({"doc_1": [AGREEMENT], "doc_2": [DEED]})
    text = pages["doc_1"][0] + pages["doc_2"][0]
    secrets = [PESEL, NIP_FMT, REGON, ID_CARD, IBAN_FMT, KW, "Długiej 15/4", "31-147", "600 100 200",
               "tp@example.com", "Tomasz", "Tomaszem", "Przykładowym", "Przykładowego", "Przykładowy"]
    assert find_leaks(text, secrets) == []
    # Business data stays
    for kept in ("Budowa Test Spółka z o.o.", "450.000,00 zł", "31 marca 2024", "Deweloperem", "Kupujący"):
        assert kept in text
    # One token for the person across documents and inflections
    persons = {t.split(".")[0].rstrip("]") for t in anon.mapping if t.startswith("[OSOBA_")}
    assert persons == {"[OSOBA_1"}
    # Every token restores exactly the form it replaced
    assert restore(pages["doc_2"][0], anon.mapping) == DEED


def test_restore_round_trip_and_stable_tokens():
    anon = Anonymizer()
    a = anon.anonymize(f"PESEL {PESEL} i ponownie {PESEL}")
    assert a.count("[PESEL_1]") == 2
    assert restore(a, anon.mapping) == f"PESEL {PESEL} i ponownie {PESEL}"
    assert restore("[NIEZNANY_9]", anon.mapping) == "[NIEZNANY_9]"


def test_pesel_with_bad_checksum_still_masked_after_keyword():
    bad = PESEL[:-1] + str((int(PESEL[-1]) + 1) % 10)
    assert bad not in Anonymizer().anonymize(f"PESEL: {bad}")
    # but a random 11-digit number without the keyword stays (e.g. a reference number)
    assert bad in Anonymizer().anonymize(f"numer sprawy {bad}")


def test_account_without_checksum_masked_near_keyword():
    fake = "11 2222 3333 4444 5555 6666 7777"
    assert fake not in Anonymizer().anonymize(f"na rachunek bankowy nr {fake}")


def test_person_before_pesel_without_honorific():
    pages, _ = anonymize_pages({"d": [f"Anna Testowa, PESEL {PESEL}, oraz Annie Testowej doręczono."]})
    assert find_leaks(pages["d"][0], ["Anna", "Testowa", "Testowej", "Annie"]) == []


def test_stop_words_not_treated_as_names():
    pages, anon = anonymize_pages({"d": ["Pan Deweloper Spółka oświadcza."]})
    assert "Deweloper" in pages["d"][0] and not any(t.startswith("[OSOBA") for t in anon.mapping)


class FakeNER:
    def detect(self, text):
        out = []
        if "Zofia Wymyślona" in text:
            out.append(("OSOBA", "Zofia Wymyślona"))
        if "Pruszków" in text:
            out.append(("MIEJSCE", "Pruszków"))
        out.append(("OSOBA", "Jednowyrazowa"))
        return out


def test_external_detector_names_and_places():
    pages, anon = anonymize_pages({"d": ["Pełnomocnik Zofia Wymyślona z Pruszków podpisała. Wymyślonej przekazano."]},
                                  detectors=[FakeNER()])
    assert find_leaks(pages["d"][0], ["Zofia", "Wymyślona", "Wymyślonej", "Pruszków"]) == []
    assert "[MIEJSCE_1]" in pages["d"][0]


def test_replacements_are_reported_for_review():
    anon = Anonymizer()
    anon.anonymize(f"PESEL {PESEL}")
    assert [(r.token, r.label) for r in anon.replacements] == [("[PESEL_1]", "PESEL")]


def test_family_members_restore_exactly():
    text = "Nabywca: Natalia Testowa\nNabywca: Paweł Testowy\nPawłowi Testowemu i Natalii Testowej wydano lokal."
    pages, anon = anonymize_pages({"d": [text]})
    assert find_leaks(pages["d"][0], ["Natalia", "Paweł", "Testow", "Pawłowi", "Natalii"]) == []
    assert restore(pages["d"][0], anon.mapping) == text


def test_defined_contract_terms_are_not_persons():
    text = ("Nabywca: Natalia Testowa\nNabywca zapłaci Deweloperowi Cenę Całkowitą. Nabywcy Cenę Całkowitą "
            "powiększy Miejsce Postojowe. Zawarcie Umowy Przenoszącej nastąpi po Wydaniu Lokalu Mieszkalnego. "
            "Przedstawiciel Dewelopera oświadcza.")
    pages, anon = anonymize_pages({"d": [text]})
    out = pages["d"][0]
    for term in ("Cenę Całkowitą", "Miejsce Postojowe", "Umowy Przenoszącej", "Wydaniu Lokalu Mieszkalnego"):
        assert term in out
    assert "Natalia" not in out and "Testowa" not in out
    assert {v for k, v in anon.mapping.items() if k.startswith("[OSOBA_") and "." not in k} == {"Natalia Testowa"}


def test_real_names_resembling_terms_are_still_persons():
    text = "Nabywca: Karol Stroński\nNabywca: Celina Sądecka\nKarolowi Strońskiemu i Celinie Sądeckiej wydano Lokal."
    pages, _ = anonymize_pages({"d": [text]})
    assert find_leaks(pages["d"][0], ["Karol", "Stroński", "Celina", "Sądecka", "Strońskiemu", "Sądeckiej"]) == []
    assert "Lokal" in pages["d"][0]


def test_persons_with_roles_and_addresses():
    text = ("Przedstawiciel Dewelopera: Michał Fikcyjny\nAdres: 00-000 Testowo, ul. Przykładowa 15/7.\n"
            "Nabywca: Natalia Wymyślona\nImiona rodziców: Jan i Helena.\nAdres: 00-001 Próbna, ul. Długa 2/3.\n"
            "przed notariuszem Dorota Zmyślona")
    _, anon = anonymize_pages({"d": [text]})
    people = {p["name"]: p for p in anon.persons.values()}
    assert people["Natalia Wymyślona"]["role"] == "buyer"
    assert people["Natalia Wymyślona"]["address"] == "00-001 Próbna, ul. Długa 2/3"
    assert people["Michał Fikcyjny"]["role"] == "representative"
    assert people["Michał Fikcyjny"]["address"] == "00-000 Testowo, ul. Przykładowa 15/7"
    assert people["Dorota Zmyślona"]["role"] == "notary"
