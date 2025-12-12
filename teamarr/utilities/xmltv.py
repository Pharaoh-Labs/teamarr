"""XMLTV generation utilities.

Converts Programme dataclasses to XMLTV format.
"""

from datetime import datetime
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring

from teamarr.core import Programme


def programmes_to_xmltv(
    programmes: list[Programme],
    channels: list[dict],
    generator_name: str = "Teamarr",
) -> str:
    """Generate XMLTV XML from programmes.

    Args:
        programmes: List of Programme objects
        channels: List of channel dicts with 'id', 'name', 'icon' keys
        generator_name: Generator info for XML header

    Returns:
        XMLTV XML string
    """
    root = Element("tv")
    root.set("generator-info-name", generator_name)

    for channel in channels:
        _add_channel(root, channel)

    for programme in programmes:
        _add_programme(root, programme)

    xml_str = tostring(root, encoding="unicode")
    return _prettify(xml_str)


def _add_channel(root: Element, channel: dict) -> None:
    """Add a channel element to the TV root."""
    chan_elem = SubElement(root, "channel")
    chan_elem.set("id", channel["id"])

    name_elem = SubElement(chan_elem, "display-name")
    name_elem.text = channel["name"]

    if channel.get("icon"):
        icon_elem = SubElement(chan_elem, "icon")
        icon_elem.set("src", channel["icon"])


def _add_programme(root: Element, programme: Programme) -> None:
    """Add a programme element to the TV root."""
    prog_elem = SubElement(root, "programme")
    prog_elem.set("start", _format_datetime(programme.start))
    prog_elem.set("stop", _format_datetime(programme.stop))
    prog_elem.set("channel", programme.channel_id)

    title_elem = SubElement(prog_elem, "title")
    title_elem.set("lang", "en")
    title_elem.text = programme.title

    if programme.description:
        desc_elem = SubElement(prog_elem, "desc")
        desc_elem.set("lang", "en")
        desc_elem.text = programme.description

    if programme.category:
        cat_elem = SubElement(prog_elem, "category")
        cat_elem.set("lang", "en")
        cat_elem.text = programme.category

    if programme.icon:
        icon_elem = SubElement(prog_elem, "icon")
        icon_elem.set("src", programme.icon)


def _format_datetime(dt: datetime) -> str:
    """Format datetime to XMLTV format: YYYYMMDDHHMMSS +ZZZZ."""
    if dt.tzinfo is None:
        offset = "+0000"
    else:
        utc_offset = dt.utcoffset()
        if utc_offset is None:
            offset = "+0000"
        else:
            total_seconds = int(utc_offset.total_seconds())
            hours, remainder = divmod(abs(total_seconds), 3600)
            minutes = remainder // 60
            sign = "+" if total_seconds >= 0 else "-"
            offset = f"{sign}{hours:02d}{minutes:02d}"

    return dt.strftime("%Y%m%d%H%M%S") + " " + offset


def _prettify(xml_str: str) -> str:
    """Return pretty-printed XML string."""
    dom = minidom.parseString(xml_str)
    return dom.toprettyxml(indent="  ")
