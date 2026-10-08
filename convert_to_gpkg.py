from pathlib import Path
import geopandas as gpd


def convert_to_gpkg(input_path: str | Path, output_dir: str | Path = "./converted") -> Path:
    """
    Converts a vector file into an OGC GeoPackage (.gpkg).

    :param input_path: Path to the input vector file.
    :param output_dir: Directory where the converted .gpkg will be saved.
    :return: Path to the newly created .gpkg file.
    :raises FileNotFoundError: If the input file does not exist.
    :raises ValueError: If the vector layer is missing a CRS definition.
    """
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"Vector file not found: {src.resolve()}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_gpkg = out_dir / f"{src.stem}.gpkg"

    # Read vector data
    gdf = gpd.read_file(src)

    # Validate that CRS is present before saving
    if gdf.crs is None:
        raise ValueError(
            f"Cannot convert '{src.name}' to GeoPackage: CRS is missing."
        )

    # Sanitize layer name for SQLite/OGC table standards
    layer_name = src.stem.replace("-", "_").replace(" ", "_").lower()

    # Write layer to GeoPackage format
    gdf.to_file(target_gpkg, layer=layer_name, driver="GPKG")

    return target_gpkg