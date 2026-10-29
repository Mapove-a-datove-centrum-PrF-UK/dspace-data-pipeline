from pathlib import Path
import geopandas as gpd


def convert_to_geojson(input_path: str | Path, output_dir: str | Path = "./converted") -> Path:
    """
    Converts a vector file (e.g. .shp, .gpkg) into GeoJSON.
    The original CRS is kept (reprojection to WGS84 is done later in the preview step).

    :param input_path: Path to the input vector file.
    :param output_dir: Directory where the converted .geojson will be saved.
    :return: Path to the newly created .geojson file.
    :raises FileNotFoundError: If the input file does not exist.
    :raises ValueError: If the vector layer is missing a CRS definition.
    """
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"Vector file not found: {src.resolve()}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_geojson = out_dir / f"{src.stem}.geojson"

    # Read vector data (for multi-layer sources like GeoPackage, the first layer is used)
    gdf = gpd.read_file(src)

    # Validate that CRS is present before saving
    if gdf.crs is None:
        raise ValueError(
            f"Cannot convert '{src.name}' to GeoJSON: CRS is missing."
        )

    # Write layer to GeoJSON format
    gdf.to_file(target_geojson, driver="GeoJSON")

    return target_geojson
