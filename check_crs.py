from pathlib import Path
import pyogrio
import rasterio
from pyproj import CRS
from pyproj.exceptions import CRSError


def has_crs(file_path: str | Path) -> bool:
    """
    Fast check if the file defines a valid, PROJ-parseable CRS.
    Returns True if CRS exists and is recognized, False otherwise.
    """
    path = Path(file_path)
    if not path.exists():
        return False

    suffix = path.suffix.lower()
    raw_crs = None

    try:
        if suffix in [".shp", ".geojson", ".json", ".gpkg"]:
            info = pyogrio.read_info(path)
            raw_crs = info.get("crs")
        elif suffix in [".tif", ".tiff"]:
            with rasterio.open(path) as src:
                raw_crs = src.crs
        else:
            return False

        if not raw_crs:
            return False

        # validate if the CRS exists in PROJ
        proj_crs = CRS.from_user_input(raw_crs)
        epsg = proj_crs.to_epsg()
        if epsg is not None:
            CRS.from_epsg(epsg)

        return True

    except (CRSError, Exception):
        return False