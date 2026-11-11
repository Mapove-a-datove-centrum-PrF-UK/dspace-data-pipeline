"""
Builds DSpace REST payload for the geoccmm schema (GeoCCMM Core 1.0, see geoccmm-metadata.xml).

Loads a REST template JSON (e.g. ukazka_deposit_restAPIformat.json) with the descriptive
metadata filled in by the user and overwrites the fields computed from the data
by geometadata_extractor.py.
"""

from pathlib import Path
import json

# geoccmm.distribution parts: name; format; formatVersion; bytes; url
DISTRIBUTION_PARTS = 5


def _clean_part(value) -> str:
    """Makes a value safe for one part of a semicolon-separated slot."""
    return str(value).replace(";", ",").strip()


def _build_distribution(template_value: str | None, gis_metadata: dict) -> str:
    """
    Fills the size of the uploaded file into a geoccmm.distribution slot (name; format; formatVersion; bytes; url).

    Name, format and formatVersion are kept from the template (described by the user).
    If the template has no name, the uploaded filename is used.
    The url stays as in the template (direct link is known only after the upload).
    """
    parts = (template_value or "").split(";")
    parts += [""] * (DISTRIBUTION_PARTS - len(parts))
    name, file_format, format_version, _, url = parts[:DISTRIBUTION_PARTS]

    if not name:
        name = gis_metadata.get("filename", "")

    size = gis_metadata.get("bytes", "")

    return ";".join(
        _clean_part(p) for p in (name, file_format, format_version, size, url)
    )


def create_dspace_rest_payload(metadata_path: str | Path, gis_metadata: dict) -> dict:
    """Loads REST template JSON, injects GIS fields (geoccmm schema), and returns payload dict."""

    with open(metadata_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    meta = payload["metadata"]

    # 1. Bounding box in WGS 84 (west;east;south;north)
    meta["geoccmm.bbox"] = [{"value": gis_metadata["bbox"]}]

    # 2. CRS as EPSG URI
    meta["geoccmm.crs"] = [{"value": gis_metadata["crs_uri"]}]

    # 3. Spatial representation ('vector' / 'grid')
    meta["geoccmm.representation"] = [{"value": gis_metadata["representation"]}]

    # 4. Spatial resolution of rasters (distance;scale), vectors keep the value from the template
    if "resolution_slot" in gis_metadata:
        meta["geoccmm.resolution"] = [{"value": gis_metadata["resolution_slot"]}]

    # 5. Size of the uploaded file in geoccmm.distribution (first row = uploaded ZIP)
    distributions = meta.get("geoccmm.distribution") or [{}]
    distributions[0] = {"value": _build_distribution(distributions[0].get("value"), gis_metadata)}
    meta["geoccmm.distribution"] = distributions

    return payload
