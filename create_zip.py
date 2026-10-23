import io
from pathlib import Path
import zipfile


def zip_in_memory(file_path: str | Path) -> tuple[io.BytesIO, str, int]:
  """Compresses a spatial dataset (.gpkg, .tif) into an in-memory ZIP archive.

  Returns:
      (zip_buffer, zip_filename, zip_bytes)
  """
  src = Path(file_path)
  if not src.exists():
    raise FileNotFoundError(f"Source file not found: {src.resolve()}")

  zip_buffer = io.BytesIO()

  with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    zf.write(src, arcname=src.name)

  zip_bytes = zip_buffer.tell()
  zip_buffer.seek(0)

  zip_filename = f"{src.stem}.zip"

  return zip_buffer, zip_filename, zip_bytes