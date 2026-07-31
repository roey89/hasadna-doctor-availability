"""Parsers for Clalit /Zimunet/ responses. Pure functions, no network."""

import json
import re
from bs4 import BeautifulSoup

GUID_RE = re.compile(r"([0-9a-fA-F-]{36})")


def unwrap(body):
    """Most endpoints return {"data": "<html>", "errorType":0, "message":null},
    but some return raw HTML, and on errors/redirects "data" can be null or a
    nested object. Always hand back a string so the parsers stay safe."""
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, dict):
        obj = body
    else:
        body = str(body).strip()
        if not body.startswith("{"):
            return body
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            return body
    if not isinstance(obj, dict):
        return str(obj)
    data = obj.get("data")
    if isinstance(data, str):
        return data
    if data is None:
        return ""
    # Unexpected shape - stringify so the caller can log it rather than crash.
    return json.dumps(data, ensure_ascii=False)


def envelope_info(body):
    """Pull errorType/message out of the JSON envelope, when present."""
    try:
        obj = json.loads(body) if isinstance(body, str) else body
        if isinstance(obj, dict):
            return {
                "errorType": obj.get("errorType"),
                "message": obj.get("message"),
                "data_type": type(obj.get("data")).__name__,
            }
    except Exception:
        pass
    return {}


# Text shown in the "no appointments" modal (errorType 3).
NO_RESULTS_MARKERS = ("לא נמצאו תורים", "שנה את הבחירה", "לתשומת לבך")


def is_no_results(body, html=None):
    """True when SearchDiaries returned the 'no appointments here' popup.
    Encoded as errorType 3 with a modal fragment, NOT a 'found 0' result."""
    info = envelope_info(body)
    if info.get("errorType") == 3:
        return True
    text = html if html is not None else (body if isinstance(body, str) else "")
    return any(m in text for m in NO_RESULTS_MARKERS)


def _as_soup(html):
    """Defensive BeautifulSoup construction."""
    if not isinstance(html, str):
        html = "" if html is None else str(html)
    return BeautifulSoup(html, "lxml")


def _txt(node, default=""):
    return node.get_text(" ", strip=True) if node else default


def _guid(href):
    if not href:
        return None
    m = GUID_RE.search(href)
    return m.group(1) if m else None


def parse_result_header(html):
    """'נמצאו 77 תוצאות חיפוש עבור אורתופדיה באזור: תל אביב יפו' -> (77, ...)"""
    soup = _as_soup(html)
    h2 = soup.find("h2")
    text = _txt(h2)
    m = re.search(r"נמצאו\s+(\d+)", text)
    return (int(m.group(1)) if m else None), text


def parse_pager(html):
    """Return sorted list of page numbers referenced by the pager."""
    soup = _as_soup(html)
    pages = set()
    for a in soup.select("#pager a[data-action-link]"):
        m = re.search(r"pageNumber=(\d+)", a["data-action-link"])
        if m:
            pages.add(int(m.group(1)))
    cur = soup.select_one("#pager .currentPage")
    if cur and cur.get_text(strip=True).isdigit():
        pages.add(int(cur.get_text(strip=True)))
    return sorted(pages)


def parse_diaries(html):
    """Parse <li class='diary'> rows from a SearchDiaries / Paging fragment."""
    soup = _as_soup(html)
    rows = []

    for li in soup.select("li.diary"):
        # An advertising banner is injected as an <li class="diary"> too.
        if li.get("id") == "clalitMushlamBannerListItem" or li.select_one(".bannerMushlam"):
            continue

        det = li.select_one("a.doctorDetails[data-action-link]")
        diary_guid = _guid(det["data-action-link"]) if det else None
        if not diary_guid:
            continue

        name_a = li.select_one(".doctorName a")
        clinic_a = li.select_one(".diaryClinic a.clinicDetails")

        # Next free appointment date
        next_date = None
        for span in li.select("span.visitDateTime"):
            t = span.get_text(strip=True)
            if re.match(r"\d{2}\.\d{2}\.\d{4}", t):
                next_date = t
                break

        address = distance = phone = None
        for div in li.select(".diaryClinic .clinicDetails"):
            t = _txt(div)
            if t.startswith("כתובת:"):
                address = t.replace("כתובת:", "").strip()
            elif "מרחק מהבית" in t:
                distance = t.split(":", 1)[-1].strip()
        tel = li.select_one(".clinicTelephone a")
        if tel:
            phone = _txt(tel)

        visit_types = [
            _txt(d) for d in li.select(".diaryZoharVisitTypeDesc")
        ]

        map_a = li.select_one("a.mapLocationLink")

        all_slots = li.select_one("a.createVisitButton[data-action-link]")

        rows.append({
            "diary_guid": diary_guid,
            "doctor_name": _txt(name_a),
            "profession": _txt(li.select_one(".professionName")),
            "next_available_date": next_date,
            "clinic_name": clinic_a.get("title") if clinic_a else _txt(clinic_a),
            "clinic_address": address,
            "distance": distance,
            "phone": phone,
            "visit_types": "|".join(v for v in visit_types if v),
            "map_url": map_a.get("href") if map_a else None,
            "slots_link": all_slots.get("data-action-link") if all_slots else None,
        })

    return rows


def parse_filter_counts(html):
    """Gender / language / visit-type facet counts, free with every search."""
    soup = _as_soup(html)
    out = {}
    for sec, key in (("#filterByGender", "gender"),
                     ("#filterByZoharVisitType", "visit_type"),
                     ("#filterByLanguage", "language")):
        node = soup.select_one(sec)
        if not node:
            continue
        items = {}
        for a in node.select("a[title]"):
            t = a["title"]
            m = re.match(r"(.+?)\s*\((\d+)\)\s*$", t)
            if m:
                items[m.group(1).strip()] = int(m.group(2))
        if items:
            out[key] = items
    return out


def parse_available_days(html):
    """Pull availableDays: ['30.7.2026', ...] out of the z.init(...) block."""
    if not isinstance(html, str):
        return []
    m = re.search(r"availableDays\s*:\s*\[(.*?)\]", html, re.S)
    if not m:
        return []
    return re.findall(r"'([^']+)'", m.group(1))


def parse_visit_page_meta(html):
    """Metadata from an AvailableVisit/Index page."""
    soup = _as_soup(html)
    clinic = soup.select_one("#availableVisitsClinicDetails")
    meta = {
        "diary_title": _txt(soup.select_one("#diaryName")),
        "clinic_name": clinic.get("title") if clinic else None,
        "clinic_code": clinic.get("data-clinic-code") if clinic else None,
        "available_days": parse_available_days(html),
    }
    m = re.search(r"datePickerMinDate\s*:\s*'([^']+)'", html) if isinstance(html, str) else None
    meta["date_picker_min"] = m.group(1) if m else None
    return meta


def parse_slots(html, day_hint=None):
    """Parse individual time slots from an AvailableVisit page or
    GetDailyAvailableVisit fragment."""
    soup = _as_soup(html)
    slots = []

    # Header often states which day these slots belong to.
    day = day_hint
    hdr = soup.select_one("#queues header") or soup.find("header")
    if hdr:
        m = re.search(r"(\d{2}\.\d{2}\.\d{4})", _txt(hdr))
        if m:
            day = m.group(1)

    for part in soup.select("div.day-part"):
        part_id = part.get("id") or ""
        for li in part.select("li"):
            time_span = li.find("span")
            t = _txt(time_span)
            if not re.match(r"^\d{1,2}:\d{2}$", t):
                continue
            create = li.select_one("a.createVisitButton[data-action-link]")
            link = create.get("data-action-link") if create else None
            zohar = None
            if link:
                mz = re.search(r"selectedZoharVisitType=([^&]+)", link)
                zohar = mz.group(1) if mz else None
            slots.append({
                "day": day,
                "day_part": part_id,
                "time": t,
                "slot_guid": _guid(link),
                "zohar_visit_type": zohar,
                "doctor_name_inline": _txt(li.select_one(".doctorName")) or None,
                "doctor_license": li.get("data-doctor-license"),
                "doctor_gender": li.get("data-doctor-gender"),
                "family_profession": li.get("data-family-doctor-profession"),
                # bs4 lowercases attribute names, so data-PatientAge -> data-patientage
                "patient_age": (create.get("data-patientage")
                                or create.get("data-PatientAge")) if create else None,
            })

    return slots