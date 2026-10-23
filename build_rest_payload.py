from pathlib import Path
import json

def create_dspace_rest_payload(metadata_path: str | Path, gis_metadata: dict) -> dict:
    """Loads REST template JSON, injects GIS fields, and returns payload dict."""

    with open(metadata_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    meta = payload["metadata"]

    # 1. Bounding box (INSPIRE complex slot: west;east;south;north)
    meta["mdc.spatial.bbox"] = [{"value": gis_metadata["bbox"]}]

    # 2. CRS URI
    meta["mdc.spatial.crs"] = [{"value": gis_metadata["crs_uri"]}]

    # 3. Spatial representation ('vector' / 'grid')
    meta["mdc.spatial.representation"] = [{"value": gis_metadata["representation"]}]

    # 4. Detail footprint WKT
    if "geometry_wkt" in gis_metadata:
        meta["mdc.spatial.geometry"] = [{"value": gis_metadata["geometry_wkt"]}]

    # 5. Rastrovo špecifické atribúty
    if "resolution_slot" in gis_metadata:
        meta["mdc.spatial.resolution"] = [{"value": gis_metadata["resolution_slot"]}]
    if "raster_bands_slots" in gis_metadata:
        meta["mdc.spatial.raster"] = [
            {"value": slot} for slot in gis_metadata["raster_bands_slots"]
        ]

    # 6. Bytes and CRS into mdc.distribution
    if "mdc.distribution" in meta and meta["mdc.distribution"]:
        dist_slot_template = meta["mdc.distribution"][0]["value"]
        meta["mdc.distribution"][0]["value"] = (
            dist_slot_template
            .replace("{bytes}", str(gis_metadata.get("bytes", "")))
            .replace("{crs}", gis_metadata.get("crs_uri", ""))
        )

    return payload