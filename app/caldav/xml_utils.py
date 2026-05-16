"""
CalDAV XML 工具模块
Ported from original caldav_service/xml_utils.py — all Django dependencies removed.
"""

import xml.etree.ElementTree as ET

# XML 命名空间
NS_DAV = "DAV:"
NS_CALDAV = "urn:ietf:params:xml:ns:caldav"
NS_CS = "http://calendarserver.org/ns/"
NS_ICAL = "http://apple.com/ns/ical/"

NSMAP = {
    "D": NS_DAV,
    "C": NS_CALDAV,
    "CS": NS_CS,
    "IC": NS_ICAL,
}


def _tag(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def dav(local: str) -> str:
    return _tag(NS_DAV, local)


def caldav(local: str) -> str:
    return _tag(NS_CALDAV, local)


def cs(local: str) -> str:
    return _tag(NS_CS, local)


def ical(local: str) -> str:
    return _tag(NS_ICAL, local)


def make_multistatus() -> ET.Element:
    root = ET.Element(dav("multistatus"))
    for prefix, uri in NSMAP.items():
        root.set(f"xmlns:{prefix}", uri)
    return root


def add_response(parent: ET.Element, href: str) -> ET.Element:
    resp = ET.SubElement(parent, dav("response"))
    href_el = ET.SubElement(resp, dav("href"))
    href_el.text = href
    return resp


def add_propstat(response: ET.Element, status: str = "HTTP/1.1 200 OK") -> ET.Element:
    propstat = ET.SubElement(response, dav("propstat"))
    ET.SubElement(propstat, dav("prop"))
    status_el = ET.SubElement(propstat, dav("status"))
    status_el.text = status
    return propstat


def get_prop(propstat: ET.Element) -> ET.Element:
    return propstat.find(dav("prop"))


def set_text_prop(prop: ET.Element, tag: str, text: str):
    el = ET.SubElement(prop, tag)
    el.text = text


def set_href_prop(prop: ET.Element, tag: str, href: str):
    wrapper = ET.SubElement(prop, tag)
    href_el = ET.SubElement(wrapper, dav("href"))
    href_el.text = href


def serialize_xml(root: ET.Element) -> bytes:
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode").encode("utf-8")


def parse_xml_body(body: bytes) -> ET.Element:
    return ET.fromstring(body)


def get_local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def find_requested_props(body: bytes):
    if not body or not body.strip():
        return None
    root = parse_xml_body(body)
    if root.find(dav("allprop")) is not None:
        return None
    prop_el = root.find(dav("prop"))
    if prop_el is None:
        return None
    return [child.tag for child in prop_el]
