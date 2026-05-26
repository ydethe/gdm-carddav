from collections.abc import AsyncGenerator
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from loguru import logger
from lxml import etree
from sqlalchemy.ext.asyncio import AsyncSession

from gdm_carddav.repository import PeopleRepository
from gdm_carddav.service import CardDAVService
from gdm_carddav.settings import Settings, get_settings
from gdm_carddav.vcard import id_from_uid, uid_from_id

# XML namespaces
_DAV = "DAV:"
_CARD = "urn:ietf:params:xml:ns:carddav"
_CS = "http://calendarserver.org/ns/"
_NSMAP = {"d": _DAV, "card": _CARD, "cs": _CS}

_ALLOW = "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, REPORT, MKCOL, PROPPATCH"
_VCARD_CT = "text/vcard; charset=utf-8"

router = APIRouter()
security = HTTPBasic()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def require_auth(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    if credentials.username != settings.CARDDAV_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": f'Basic realm="{settings.CARDDAV_REALM}"'},
        )
    stored = settings.CARDDAV_PASSWORD
    if stored.startswith("$2b$"):
        ok = bcrypt.checkpw(credentials.password.encode(), stored.encode())
    else:
        ok = credentials.password == stored
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": f'Basic realm="{settings.CARDDAV_REALM}"'},
        )
    return credentials.username


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------


def _multistatus() -> etree._Element:
    return etree.Element(f"{{{_DAV}}}multistatus", nsmap=_NSMAP)


def _to_xml(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _xml_response(status_code: int, root: etree._Element) -> Response:
    return Response(
        content=_to_xml(root),
        status_code=status_code,
        media_type="application/xml; charset=utf-8",
    )


def _add_propstat(
    response_el: etree._Element, props: dict[str, str | etree._Element | None], http_status: str
) -> None:
    propstat = etree.SubElement(response_el, f"{{{_DAV}}}propstat")
    prop = etree.SubElement(propstat, f"{{{_DAV}}}prop")
    for tag, value in props.items():
        if isinstance(value, etree._Element):
            # value is already the correctly-tagged property element — append directly
            prop.append(value)
        else:
            el = etree.SubElement(prop, tag)
            if value is not None:
                el.text = value
    etree.SubElement(propstat, f"{{{_DAV}}}status").text = http_status


def _build_root_propfind(username: str) -> etree._Element:
    ms = _multistatus()
    resp = etree.SubElement(ms, f"{{{_DAV}}}response")
    etree.SubElement(resp, f"{{{_DAV}}}href").text = "/"
    principal_href = etree.Element(f"{{{_DAV}}}href")
    principal_href.text = f"/principals/{username}/"
    cup = etree.Element(f"{{{_DAV}}}current-user-principal")
    cup.append(principal_href)
    _add_propstat(resp, {f"{{{_DAV}}}current-user-principal": cup}, "HTTP/1.1 200 OK")
    return ms


def _build_principal_propfind(username: str) -> etree._Element:
    ms = _multistatus()
    resp = etree.SubElement(ms, f"{{{_DAV}}}response")
    etree.SubElement(resp, f"{{{_DAV}}}href").text = f"/principals/{username}/"

    rt = etree.Element(f"{{{_DAV}}}resourcetype")
    etree.SubElement(rt, f"{{{_DAV}}}principal")
    _add_propstat(resp, {f"{{{_DAV}}}resourcetype": rt}, "HTTP/1.1 200 OK")

    home_href = etree.Element(f"{{{_DAV}}}href")
    home_href.text = f"/principals/{username}/contacts/"
    home_set = etree.Element(f"{{{_CARD}}}addressbook-home-set")
    home_set.append(home_href)
    _add_propstat(resp, {f"{{{_CARD}}}addressbook-home-set": home_set}, "HTTP/1.1 200 OK")
    return ms


def _collection_response_el(
    href: str, ctag: str | None, sync_token: str, username: str
) -> etree._Element:
    resp = etree.Element(f"{{{_DAV}}}response")
    etree.SubElement(resp, f"{{{_DAV}}}href").text = href

    rt = etree.Element(f"{{{_DAV}}}resourcetype")
    etree.SubElement(rt, f"{{{_DAV}}}collection")
    etree.SubElement(rt, f"{{{_CARD}}}addressbook")

    props: dict[str, str | etree._Element | None] = {
        f"{{{_DAV}}}displayname": "Contacts",
        f"{{{_DAV}}}resourcetype": rt,
        f"{{{_DAV}}}sync-token": sync_token,
    }
    if ctag is not None:
        props[f"{{{_CS}}}getctag"] = ctag

    _add_propstat(resp, props, "HTTP/1.1 200 OK")
    return resp


def _contact_response_el(href: str, etag: str) -> etree._Element:
    resp = etree.Element(f"{{{_DAV}}}response")
    etree.SubElement(resp, f"{{{_DAV}}}href").text = href
    _add_propstat(
        resp,
        {
            f"{{{_DAV}}}getetag": etag,
            f"{{{_DAV}}}getcontenttype": _VCARD_CT,
            f"{{{_DAV}}}resourcetype": None,
        },
        "HTTP/1.1 200 OK",
    )
    return resp


def _contact_data_response_el(
    href: str, etag: str, vcard_str: str, include_data: bool
) -> etree._Element:
    resp = etree.Element(f"{{{_DAV}}}response")
    etree.SubElement(resp, f"{{{_DAV}}}href").text = href
    props: dict[str, str | etree._Element | None] = {f"{{{_DAV}}}getetag": etag}
    if include_data:
        props[f"{{{_CARD}}}address-data"] = vcard_str
    _add_propstat(resp, props, "HTTP/1.1 200 OK")
    return resp


def _uid_from_filename(filename: str) -> int | None:
    uid = filename.removesuffix(".vcf")
    return id_from_uid(uid)


# ---------------------------------------------------------------------------
# REPORT dispatch helpers
# ---------------------------------------------------------------------------


async def _handle_multiget(root: etree._Element, username: str, svc: CardDAVService) -> Response:
    hrefs = root.findall(f"{{{_DAV}}}href")
    ids: list[int] = []
    for h in hrefs:
        if h.text:
            filename = h.text.rstrip("/").split("/")[-1]
            pid = _uid_from_filename(filename)
            if pid is not None:
                ids.append(pid)
    contacts = await svc.get_by_ids(ids)
    ms = _multistatus()
    for person, etag, vcard_str in contacts:
        uid = uid_from_id(person.id)
        href = f"/principals/{username}/contacts/{uid}.vcf"
        ms.append(_contact_data_response_el(href, etag, vcard_str, include_data=True))
    return _xml_response(207, ms)


async def _handle_addressbook_query(username: str, svc: CardDAVService) -> Response:
    contacts = await svc.get_all()
    ms = _multistatus()
    for person, etag, vcard_str in contacts:
        uid = uid_from_id(person.id)
        href = f"/principals/{username}/contacts/{uid}.vcf"
        ms.append(_contact_data_response_el(href, etag, vcard_str, include_data=True))
    return _xml_response(207, ms)


async def _handle_sync_collection(
    root: etree._Element, username: str, svc: CardDAVService
) -> Response:
    token_el = root.find(f"{{{_DAV}}}sync-token")
    token = token_el.text if token_el is not None and token_el.text else ""
    contacts = await svc.get_changes_since(token)
    new_token = await svc.get_sync_token()
    ms = _multistatus()
    etree.SubElement(ms, f"{{{_DAV}}}sync-token").text = new_token
    for person, etag, vcard_str in contacts:
        uid = uid_from_id(person.id)
        href = f"/principals/{username}/contacts/{uid}.vcf"
        ms.append(_contact_data_response_el(href, etag, vcard_str, include_data=False))
    return _xml_response(207, ms)


# ---------------------------------------------------------------------------
# Routes — specific before wildcard
# ---------------------------------------------------------------------------

_Auth = Annotated[str, Depends(require_auth)]
_DB = Annotated[AsyncSession, Depends(get_db)]
_Sett = Annotated[Settings, Depends(get_settings)]


@router.get("/.well-known/carddav")
async def well_known_carddav(settings: _Sett, _: _Auth) -> RedirectResponse:
    url = f"/principals/{settings.CARDDAV_USERNAME}/contacts/"
    return RedirectResponse(url=url, status_code=301)


@router.api_route("/", methods=["PROPFIND"])
async def propfind_root(settings: _Sett, _: _Auth) -> Response:
    return _xml_response(207, _build_root_propfind(settings.CARDDAV_USERNAME))


@router.api_route("/principals/{username}/", methods=["PROPFIND"])
async def propfind_principal(username: str, _: _Auth) -> Response:
    return _xml_response(207, _build_principal_propfind(username))


@router.api_route("/principals/{username}/contacts/", methods=["PROPFIND"])
async def propfind_collection(username: str, request: Request, db: _DB, _: _Auth) -> Response:
    svc = CardDAVService(PeopleRepository(db))
    depth = request.headers.get("Depth", "1")
    ctag = await svc.get_ctag()
    sync_token = await svc.get_sync_token()

    ms = _multistatus()
    collection_href = f"/principals/{username}/contacts/"
    ms.append(_collection_response_el(collection_href, ctag, sync_token, username))

    if depth in ("1", "infinity"):
        contacts = await svc.get_all()
        for person, etag, _ in contacts:
            uid = uid_from_id(person.id)
            href = f"/principals/{username}/contacts/{uid}.vcf"
            ms.append(_contact_response_el(href, etag))

    return _xml_response(207, ms)


@router.api_route("/principals/{username}/contacts/{filename}", methods=["PROPFIND"])
async def propfind_contact(username: str, filename: str, db: _DB, _: _Auth) -> Response:
    person_id = _uid_from_filename(filename)
    if person_id is None:
        raise HTTPException(status_code=404)
    svc = CardDAVService(PeopleRepository(db))
    result = await svc.get_by_id(person_id)
    if result is None:
        raise HTTPException(status_code=404)
    person, etag, _ = result
    uid = uid_from_id(person.id)
    href = f"/principals/{username}/contacts/{uid}.vcf"
    ms = _multistatus()
    ms.append(_contact_response_el(href, etag))
    return _xml_response(207, ms)


@router.api_route("/principals/{username}/contacts/", methods=["REPORT"])
async def report_collection(username: str, request: Request, db: _DB, _: _Auth) -> Response:
    body = await request.body()
    try:
        root = etree.fromstring(body)
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status_code=400, detail="Invalid XML body") from exc

    svc = CardDAVService(PeopleRepository(db))
    tag = root.tag

    if tag == f"{{{_CARD}}}addressbook-multiget":
        return await _handle_multiget(root, username, svc)
    elif tag == f"{{{_CARD}}}addressbook-query":
        return await _handle_addressbook_query(username, svc)
    elif tag == f"{{{_DAV}}}sync-collection":
        return await _handle_sync_collection(root, username, svc)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown REPORT type: {tag}")


@router.get("/principals/{username}/contacts/{filename}")
async def get_contact(username: str, filename: str, db: _DB, _: _Auth) -> Response:
    person_id = _uid_from_filename(filename)
    if person_id is None:
        raise HTTPException(status_code=404)
    svc = CardDAVService(PeopleRepository(db))
    result = await svc.get_by_id(person_id)
    if result is None:
        raise HTTPException(status_code=404)
    _, etag, vcard_str = result
    return Response(
        content=vcard_str,
        media_type=_VCARD_CT,
        headers={"ETag": etag},
    )


@router.head("/principals/{username}/contacts/{filename}")
async def head_contact(username: str, filename: str, db: _DB, _: _Auth) -> Response:
    person_id = _uid_from_filename(filename)
    if person_id is None:
        raise HTTPException(status_code=404)
    svc = CardDAVService(PeopleRepository(db))
    result = await svc.get_by_id(person_id)
    if result is None:
        raise HTTPException(status_code=404)
    _, etag, _ = result
    return Response(
        status_code=200,
        headers={"ETag": etag, "Content-Type": _VCARD_CT},
    )


@router.put("/principals/{username}/contacts/{filename}")
async def put_contact(username: str, filename: str, request: Request, _: _Auth) -> Response:
    body = await request.body()
    logger.warning(
        "PUT ignored (read-only): user={} file={} size={}", username, filename, len(body)
    )
    return Response(status_code=201)


@router.delete("/principals/{username}/contacts/{filename}")
async def delete_contact(username: str, filename: str, _: _Auth) -> Response:
    logger.warning("DELETE ignored (read-only): user={} file={}", username, filename)
    return Response(status_code=204)


@router.api_route("/{path:path}", methods=["MKCOL"])
async def mkcol(path: str, _: _Auth) -> Response:
    logger.warning("MKCOL ignored (read-only): path=/{}", path)
    return Response(status_code=201)


@router.api_route("/{path:path}", methods=["PROPPATCH"])
async def proppatch(path: str, _: _Auth) -> Response:
    logger.warning("PROPPATCH ignored (read-only): path=/{}", path)
    ms = _multistatus()
    resp = etree.SubElement(ms, f"{{{_DAV}}}response")
    etree.SubElement(resp, f"{{{_DAV}}}href").text = f"/{path}"
    propstat = etree.SubElement(resp, f"{{{_DAV}}}propstat")
    etree.SubElement(propstat, f"{{{_DAV}}}prop")
    etree.SubElement(propstat, f"{{{_DAV}}}status").text = "HTTP/1.1 200 OK"
    return _xml_response(207, ms)


@router.api_route("/", methods=["OPTIONS"])
@router.api_route("/{path:path}", methods=["OPTIONS"])
async def options_handler(_: _Auth) -> Response:
    return Response(status_code=200, headers={"Allow": _ALLOW})
