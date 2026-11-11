import math
from pathlib import Path
import geopandas as gpd
import rasterio
from rasterio.warp import transform_bounds

def _format_crs_uri(crs_obj) -> str:
    """Formats a validated CRS instance into an official OGC URI."""

    epsg_code = crs_obj.to_epsg()

    if epsg_code:
        return f"http://www.opengis.net/def/crs/EPSG/0/{epsg_code}"

    return f"urn:ogc:def:crs:{crs_obj.to_string()}"

def _extract_vector_metadata(path: Path) -> dict:
    """
    Extracts GeoCCMM metadata from a vector dataset (GeoPackage, Shapefile, GeoJSON).
    Fields: geoccmm.bbox, geoccmm.crs, geoccmm.representation, geoccmm.distribution (bytes)
    """
    gdf = gpd.read_file(path)

    # Reproject bounds to WGS84 for INSPIRE bounding box
    minx, miny, maxx, maxy = transform_bounds(gdf.crs, "EPSG:4326", *gdf.total_bounds)

    # build complex DSpace slot format for geoccmm.bbox: west;east;south;north
    bbox_slot = f"{round(float(minx), 8)};{round(float(maxx), 8)};{round(float(miny), 8)};{round(float(maxy), 8)}"

    return {
        "representation": "vector",
        "crs_uri": _format_crs_uri(gdf.crs),
        "bbox": bbox_slot
    }


def _extract_raster_metadata(path: Path) -> dict:
    """
    Extracts spatial and resolution metadata from raster datasets.
    Fields: geoccmm.bbox, geoccmm.crs, geoccmm.representation,
            geoccmm.resolution, geoccmm.distribution (bytes)
    """
    with rasterio.open(path) as src:

        # Transform raster bounds to WGS84 (EPSG:4326)
        if src.crs.to_epsg() != 4326:
            west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        else:
            west, south, east, north = src.bounds

        # complex DSpace slot format for geoccmm.bbox: west;east;south;north
        bbox_slot = f"{round(float(west), 8)};{round(float(east), 8)};{round(float(south), 8)};{round(float(north), 8)}"

        # Extract spatial resolution (distance in metres)
        res_x = abs(src.transform[0])

        if src.crs.is_projected:
            res_m = res_x
        else:
            # Approximate conversion of degrees to metres at median latitude
            mid_lat = (south + north) / 2.0
            meters_per_deg = 111_320.0 * math.cos(math.radians(mid_lat))
            res_m = res_x * meters_per_deg

        # Complex DSpace slot for geoccmm.resolution: distance;scale (scale left empty)
        resolution_slot = f"{round(float(res_m), 2)};"

        return {
            "representation": "grid",
            "crs_uri": _format_crs_uri(src.crs),
            "bbox": bbox_slot,
            "resolution_slot": resolution_slot,
        }

def extract_gis_metadata(file_path: str | Path) -> dict:
    """
    Extracts GeoCCMM metadata attributes from datasets (.gpkg, .shp, .geojson or .tif).
    Assumes the dataset has already passed CRS inspection.
    """

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Spatial data file not found: {path.resolve()}")

    suffix = path.suffix.lower()

    if suffix in [".tif", ".tiff"]:
        return _extract_raster_metadata(path)
    elif suffix in [".gpkg", ".shp", ".geojson"]:
        return _extract_vector_metadata(path)
    else:
        raise ValueError(
            f"Unsupported file format for extraction: '{suffix}'. "
            "Expected .gpkg/.shp/.geojson for vectors or .tif/.tiff for rasters."
        )