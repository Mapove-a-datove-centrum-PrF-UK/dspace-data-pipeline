import io
from pathlib import Path
import zipfile

# Shapefile is a set of files sharing one name; all of them belong to the dataset
SHAPEFILE_EXTENSIONS = [
    ".shp",     # Main shape geometry (mandatory)
    ".shx",     # Shape positional index (mandatory)
    ".dbf",     # Attribute format table (mandatory)
    ".prj",     # Projection description / CRS (WKT)
    ".cpg",     # Code page / character encoding identifier
    ".qpj",     # QGIS projection file
    ".qmd",     # QGIS metadata
    ".sbn",     # ESRI spatial index
    ".sbx",     # ESRI spatial index
    ".fbn",     # Read-only spatial index
    ".fbx",     # Read-only spatial index
    ".ain",     # Attribute index
    ".aix",     # Attribute index
    ".ixs",     # Geocoding index
    ".mxs",     # Geocoding index
    ".atx",     # Attribute index created in ArcGIS
    ".shp.xml"  # ESRI metadata format
]

SHAPEFILE_MANDATORY = [".shp", ".shx", ".dbf"]


def dataset_files(file_path: str | Path) -> list[Path]:
  """Returns all files that make up the dataset.

  For a shapefile these are the .shp and its sidecar files with the same name,
  for other formats (.gpkg, .geojson, .tif) only the file itself.
  """
  src = Path(file_path)

  if src.suffix.lower() != ".shp":
    return [src]

  # exact name match (stem + known extension), so e.g. 'data.gpkg' next to 'data.shp' is not included
  stem = src.stem.lower()
  wanted = {stem + ext for ext in SHAPEFILE_EXTENSIONS}
  files = sorted(
      f for f in src.parent.iterdir()
      if f.is_file() and f.name.lower() in wanted
  )

  # check that mandatory shapefile parts are present
  found = {f.name.lower() for f in files}
  missing = [ext for ext in SHAPEFILE_MANDATORY if stem + ext not in found]
  if missing:
    raise FileNotFoundError(
        f"Shapefile '{src.name}' is incomplete, missing: {', '.join(missing)}"
    )

  return files


def zip_in_memory(file_path: str | Path) -> tuple[io.BytesIO, str, int]:
  """Compresses a spatial dataset (.gpkg, .geojson, .shp incl. sidecars, .tif) into an in-memory ZIP archive.

  Returns:
      (zip_buffer, zip_filename, zip_bytes)
  """
  src = Path(file_path)
  if not src.exists():
    raise FileNotFoundError(f"Source file not found: {src.resolve()}")

  zip_buffer = io.BytesIO()

  with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for f in dataset_files(src):
      zf.write(f, arcname=f.name)

  zip_bytes = zip_buffer.tell()
  zip_buffer.seek(0)

  zip_filename = f"{src.stem}.zip"

  return zip_buffer, zip_filename, zip_bytes
