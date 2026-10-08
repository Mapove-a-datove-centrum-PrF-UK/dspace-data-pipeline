import math
from pathlib import Path
import geopandas as gpd
import rasterio
from rasterio.warp import transform_bounds
from shapely.geometry import box


def _format_crs_uri(crs_obj) -> str:
    """Formats a validated CRS instance into an official OGC URI."""

    epsg_code = crs_obj.to_epsg()

    if epsg_code:
        return f"http://www.opengis.net/def/crs/EPSG/0/{epsg_code}"
    
    return f"urn:ogc:def:crs:{crs_obj.to_string()}"

def extract_gis_metadata(file_path: str | Path) -> dict:
    """
    Extracts INSPIRE-CCMM metadata attributes from standardized datasets (.gpkg or .tif).
    Assumes the dataset has already passed CRS inspection.
    """

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Spatial data file not found: {path.resolve()}")

    file_bytes = path.stat().st_size
    suffix = path.suffix.lower()

    if suffix in [".tif", ".tiff"]:
        return _extract_raster_metadata(path, file_bytes)
    elif suffix == ".gpkg":
        return _extract_vector_metadata(path, file_bytes)
    else:
        raise ValueError(
            f"Unsupported file format for extraction: '{suffix}'. "
            "Expected .gpkg for vectors or .tif/.tiff for rasters."
        )

def _extract_vector_metadata(path: Path, file_bytes: int) -> dict:
    """
    Extracts MDC metadata from a standardized GeoPackage dataset.
    Fields: mdc.spatial.bbox, mdc.spatial.crs, mdc.spatial.representation,
            mdc.spatial.geometry, mdc.distribution (bytes, crs)
    """
    gdf = gpd.read_file(path)

    # Reproject bounds to WGS84 for INSPIRE bounding box
    minx, miny, maxx, maxy = transform_bounds(gdf.crs, "EPSG:4326", *gdf.total_bounds)

    # build complex DSpace slot format for mdc.spatial.bbox: west;east;south;north
    bbox_slot = f"{round(float(minx), 8)};{round(float(maxx), 8)};{round(float(miny), 8)};{round(float(maxy), 8)}"

    # footprint bounding box in WKT format (EPSG:4326)
    bbox_wkt = box(minx, miny, maxx, maxy).wkt

    return {
        "representation": "vector",
        "bytes": file_bytes,
        "crs_uri": _format_crs_uri(gdf.crs),
        "bbox": bbox_slot,
        "geometry_wkt": bbox_wkt,
        "filename": path.name,
    }


def _extract_raster_metadata(path: Path, file_bytes: int) -> dict:
    """
    Extracts spatial, resolution, and band metadata from raster datasets.
    Fields: mdc.spatial.bbox, mdc.spatial.crs, mdc.spatial.representation,
            mdc.spatial.geometry, mdc.spatial.resolution, mdc.spatial.raster,
            mdc.distribution (bytes, crs)
    """
    with rasterio.open(path) as src:

        # Transform raster bounds to WGS84 (EPSG:4326)
        if src.crs.to_epsg() != 4326:
            west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        else:
            west, south, east, north = src.bounds

        # complex DSpace slot format for mdc.spatial.bbox: west;east;south;north
        bbox_slot = f"{round(float(west), 8)};{round(float(east), 8)};{round(float(south), 8)};{round(float(north), 8)}"

        # bounding box in WKT format (EPSG:4326)
        bbox_wkt = box(west, south, east, north).wkt

        # Extract spatial resolution (distance in metres)
        res_x = abs(src.transform[0])

        if src.crs.is_projected:
            res_m = res_x
        else:
            # Approximate conversion of degrees to metres at median latitude
            mid_lat = (south + north) / 2.0
            meters_per_deg = 111_320.0 * math.cos(math.radians(mid_lat))
            res_m = res_x * meters_per_deg

        # Complex DSpace slot for mdc.spatial.resolution: distance;scale (scale left empty)
        resolution_slot = f"{round(float(res_m), 2)};"

        # Complex DSpace slot for mdc.spatial.raster: band;description;unit;dataType;noData;wavelength
        raster_bands_slots = []
        for i in range(1, src.count + 1):
            band_desc = src.descriptions[i - 1] or ""
            data_type = src.dtypes[i - 1]
            nodata_val = str(src.nodatavals[i - 1]) if src.nodatavals[i - 1] is not None else ""

            band_slot = f"{i};{band_desc};;{data_type};{nodata_val};"
            raster_bands_slots.append(band_slot)

        return {
            "representation": "grid",
            "bytes": file_bytes,
            "crs_uri": _format_crs_uri(src.crs),
            "bbox": bbox_slot,
            "geometry_wkt": bbox_wkt,
            "filename": path.name,
            "resolution_slot": resolution_slot,
            "raster_bands_slots": raster_bands_slots,
        }