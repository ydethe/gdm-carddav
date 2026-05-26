from datetime import datetime, timezone


from gdm_carddav.vcard import (
    _parse_date,
    compute_etag,
    id_from_uid,
    people_to_vcard,
    uid_from_id,
)
from tests.conftest import make_person


# ---------------------------------------------------------------------------
# uid_from_id / id_from_uid
# ---------------------------------------------------------------------------


def test_uid_from_id():
    assert uid_from_id(42) == "gdm-42@gdm_carddav"


def test_id_from_uid_valid():
    assert id_from_uid("gdm-42@gdm_carddav") == 42


def test_id_from_uid_round_trip():
    assert id_from_uid(uid_from_id(123)) == 123


def test_id_from_uid_missing_prefix():
    assert id_from_uid("42@gdm_carddav") is None


def test_id_from_uid_missing_suffix():
    assert id_from_uid("gdm-42") is None


def test_id_from_uid_non_numeric():
    assert id_from_uid("gdm-abc@gdm_carddav") is None


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


def test_parse_date_iso():
    assert _parse_date("1985-03-15") == "1985-03-15"


def test_parse_date_french_slash():
    assert _parse_date("15/03/1985") == "1985-03-15"


def test_parse_date_french_dash():
    assert _parse_date("15-03-1985") == "1985-03-15"


def test_parse_date_compact():
    assert _parse_date("19850315") == "1985-03-15"


def test_parse_date_none():
    assert _parse_date(None) is None


def test_parse_date_empty_string():
    assert _parse_date("") is None


def test_parse_date_unparseable():
    assert _parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# compute_etag
# ---------------------------------------------------------------------------


def test_compute_etag_format():
    person = make_person(id=42, updatedAt=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc))
    etag = compute_etag(person)
    assert etag.startswith('"42-')
    assert etag.endswith('"')


def test_compute_etag_deterministic():
    person = make_person(id=1, updatedAt=datetime(2025, 6, 1, tzinfo=timezone.utc))
    assert compute_etag(person) == compute_etag(person)


def test_compute_etag_differs_by_id():
    ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert compute_etag(make_person(id=1, updatedAt=ts)) != compute_etag(
        make_person(id=2, updatedAt=ts)
    )


# ---------------------------------------------------------------------------
# people_to_vcard — structure
# ---------------------------------------------------------------------------


def test_vcard_starts_and_ends():
    vcard = people_to_vcard(make_person(id=1))
    assert vcard.startswith("BEGIN:VCARD\r\n")
    assert vcard.endswith("END:VCARD\r\n")


def test_vcard_version():
    assert "VERSION:3.0\r\n" in people_to_vcard(make_person(id=1))


def test_vcard_crlf_line_endings():
    vcard = people_to_vcard(make_person(id=1))
    # Every line separator must be \r\n — no bare \n
    lines = vcard.split("\r\n")
    assert lines[-1] == ""  # trailing \r\n produces empty final element
    assert all("\n" not in line for line in lines)


# ---------------------------------------------------------------------------
# people_to_vcard — required fields
# ---------------------------------------------------------------------------


def test_vcard_uid():
    assert "UID:gdm-42@gdm_carddav\r\n" in people_to_vcard(make_person(id=42))


def test_vcard_fn():
    vcard = people_to_vcard(make_person(id=1, prenom="Jean", nom="Dupont"))
    assert "FN:Jean Dupont\r\n" in vcard


def test_vcard_n():
    vcard = people_to_vcard(make_person(id=1, prenom="Jean", nom="Dupont"))
    assert "N:Dupont;Jean;;;\r\n" in vcard


def test_vcard_rev_utc_format():
    person = make_person(id=1, updatedAt=datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc))
    assert "REV:20250115T103000Z\r\n" in people_to_vcard(person)


def test_vcard_rev_naive_treated_as_utc():
    person = make_person(id=1, updatedAt=datetime(2025, 1, 15, 10, 30, 0))
    assert "REV:20250115T103000Z\r\n" in people_to_vcard(person)


# ---------------------------------------------------------------------------
# people_to_vcard — optional fields present
# ---------------------------------------------------------------------------


def test_vcard_email():
    vcard = people_to_vcard(make_person(id=1, email="jean@example.com"))
    assert "EMAIL;TYPE=HOME:jean@example.com\r\n" in vcard


def test_vcard_tel():
    vcard = people_to_vcard(make_person(id=1, tel="+33612345678"))
    assert "TEL;TYPE=CELL:+33612345678\r\n" in vcard


def test_vcard_photo():
    vcard = people_to_vcard(make_person(id=1, photo="https://example.com/photo.jpg"))
    assert "PHOTO;VALUE=URI:https://example.com/photo.jpg\r\n" in vcard


def test_vcard_adr_home():
    vcard = people_to_vcard(
        make_person(id=1, adresse="12 rue de la Paix", ville="Paris", codePostal="75002")
    )
    assert "ADR;TYPE=HOME:;;12 rue de la Paix;Paris;;75002;\r\n" in vcard


def test_vcard_adr_work():
    vcard = people_to_vcard(
        make_person(id=1, adresse2="5 av Hugo", ville2="Lyon", codePostal2="69001")
    )
    assert "ADR;TYPE=WORK:;;5 av Hugo;Lyon;;69001;\r\n" in vcard


def test_vcard_geo():
    vcard = people_to_vcard(make_person(id=1, latitude=48.8698, longitude=2.3311))
    assert "GEO:48.8698;2.3311\r\n" in vcard


def test_vcard_bday():
    vcard = people_to_vcard(make_person(id=1, dateNaissance="1985-03-15"))
    assert "BDAY:1985-03-15\r\n" in vcard


def test_vcard_anniversary():
    vcard = people_to_vcard(make_person(id=1, dateMariage="2010-06-20"))
    assert "ANNIVERSARY:2010-06-20\r\n" in vcard


def test_vcard_title():
    vcard = people_to_vcard(make_person(id=1, metier="Ingenieur"))
    assert "TITLE:Ingenieur\r\n" in vcard


def test_vcard_note():
    vcard = people_to_vcard(make_person(id=1, notes="A short note"))
    assert "NOTE:A short note\r\n" in vcard


# ---------------------------------------------------------------------------
# people_to_vcard — optional fields omitted when None
# ---------------------------------------------------------------------------


def test_vcard_omits_email_when_none():
    assert "EMAIL" not in people_to_vcard(make_person(id=1, email=None))


def test_vcard_omits_tel_when_none():
    assert "TEL" not in people_to_vcard(make_person(id=1, tel=None))


def test_vcard_omits_adr_home_when_all_none():
    vcard = people_to_vcard(make_person(id=1, adresse=None, ville=None, codePostal=None))
    assert "ADR;TYPE=HOME" not in vcard


def test_vcard_omits_geo_when_latitude_none():
    assert "GEO" not in people_to_vcard(make_person(id=1, latitude=None, longitude=2.3))


def test_vcard_omits_bday_when_unparseable():
    assert "BDAY" not in people_to_vcard(make_person(id=1, dateNaissance="bad-date"))
