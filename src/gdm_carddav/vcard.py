from datetime import timezone

from loguru import logger

from gdm_carddav.models import People

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d")

_UID_PREFIX = "gdm-"
_UID_SUFFIX = "@gdm_carddav"


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    from datetime import datetime

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    logger.warning("Cannot parse date {!r} — field omitted", value)
    return None


def compute_etag(person: People) -> str:
    unix_ts = int(person.updatedAt.timestamp())
    return f'"{person.id}-{unix_ts}"'


def uid_from_id(person_id: int) -> str:
    return f"{_UID_PREFIX}{person_id}{_UID_SUFFIX}"


def id_from_uid(uid: str) -> int | None:
    if not uid.startswith(_UID_PREFIX) or not uid.endswith(_UID_SUFFIX):
        return None
    id_str = uid[len(_UID_PREFIX) : -len(_UID_SUFFIX)]
    try:
        return int(id_str)
    except ValueError:
        return None


def people_to_vcard(person: People) -> str:
    dt = person.updatedAt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    rev = dt.strftime("%Y%m%dT%H%M%SZ")

    lines: list[str] = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"UID:{uid_from_id(person.id)}",
        f"FN:{person.prenom} {person.nom}",
        f"N:{person.nom};{person.prenom};;;",
        f"X-GENDER:{person.sexe}",
        f"REV:{rev}",
    ]

    if person.email:
        lines.append(f"EMAIL;TYPE=HOME:{person.email}")
    if person.tel:
        lines.append(f"TEL;TYPE=CELL:{person.tel}")
    if person.photo:
        lines.append(f"PHOTO;VALUE=URI:{person.photo}")

    if any([person.adresse, person.ville, person.codePostal]):
        lines.append(
            f"ADR;TYPE=HOME:;;{person.adresse or ''};{person.ville or ''};;{person.codePostal or ''};"
        )
    if any([person.adresse2, person.ville2, person.codePostal2]):
        lines.append(
            f"ADR;TYPE=WORK:;;{person.adresse2 or ''};{person.ville2 or ''};;{person.codePostal2 or ''};"
        )

    if person.latitude is not None and person.longitude is not None:
        lines.append(f"GEO:{person.latitude};{person.longitude}")

    bday = _parse_date(person.dateNaissance)
    if bday:
        lines.append(f"BDAY:{bday}")
    if person.lieuNaissance:
        lines.append(f"BIRTHPLACE:{person.lieuNaissance}")

    deathdate = _parse_date(person.dateDeces)
    if deathdate:
        lines.append(f"DEATHDATE:{deathdate}")

    anniversary = _parse_date(person.dateMariage)
    if anniversary:
        lines.append(f"ANNIVERSARY:{anniversary}")

    if person.metier:
        lines.append(f"TITLE:{person.metier}")
    if person.notes:
        lines.append(f"NOTE:{person.notes}")

    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"
