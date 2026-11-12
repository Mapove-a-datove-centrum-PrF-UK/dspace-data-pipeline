# dspace-data-pipeline

### `prepare_geojson_preview.py`
`geojson_preview(input_path, output_path, max_mb=5.0) -> dict`. Takes a vector file and makes a GeoJSON preview that fits under `max_mb`. Any vector format that GDAL can read (e.g. Shapefile, GeoPackage, KML) is read directly, and the output is always GeoJSON. The original format is recorded in the log (`converted_from`). It applies the following reductions in order and stops as soon as the file is small enough:

0. Reproject to WGS84 if needed. If the result already fits under `max_mb`, save it with full precision and do nothing else.
1. Round coordinates to 5 decimal places (about 1 m).
2. Drop attributes, keeping only `id`, `name`, `nazev`, `typ`, `type`, `kategorie`, `category`. If none of these exist, it keeps the first column.
3. Simplify geometry step by step. The tolerance is a fraction of the median feature size (the longer side of its bounding box). It starts at 0.001 × the median size and increases up to 0.1 ×, stopping as soon as the file is small enough. Because the tolerance is relative to feature size, buildings and countries are simplified in proportion to their size. A polygon layer without overlaps (a valid coverage) uses `simplify_coverage`, so neighbouring polygons stay aligned with no gaps or overlaps. All other layers use `simplify(preserve_topology=True)`. Skipped for point layers.
4. Keep only part of the features: the ones closest to the median centre of the dataset.

A reduction log is stored in the output GeoJSON under the top-level key `preview_metadata`. It includes the steps that were applied, feature and attribute counts, and a `ui_summary` sentence that a map page can show in an info banner. The function also returns the log. If the file is still too large after step 4, `status` is set to `warning_size_exceeded`.

### `prepare_raster_preview.py`
`raster_preview(input_path, output_path, max_size_px=4096, max_mb=10.0, max_downsample=16, bands=None) -> dict`. Takes a raster file that GDAL can read (e.g. GeoTIFF) and makes an 8-bit PNG preview whose longer side is at most `max_size_px` and whose size is at most `max_mb`, to be shown in Leaflet with `L.imageOverlay`. The steps are:

1. Detect the raster type: `image` (3 or more bands), `categorical` (a band with a colour palette, or an integer band with at most 64 distinct values) or `continuous` (any other single band).
2. Reduce bands. An image keeps three bands as RGB: the bands marked as red, green and blue in the file, otherwise the first three. Other rasters keep the first band. `bands` overrides the choice with 1 or 3 band numbers, e.g. `bands=(3, 2, 1)` for a Sentinel-2 file with bands stored as B02, B03, B04.
3. Reproject to Web Mercator (EPSG:3857), because Leaflet stretches an image overlay linearly in this projection. Nodata, an alpha band and the corners left by the rotation become transparent. Categorical data are resampled by majority, other data by average.
4. Reduce bit depth to 8 bits. Data that are not `uint8` are stretched between the 2nd and 98th percentile of each band (`details.value_ranges`); a single band is shown in greyscale. Categorical data are written as a palette PNG with the original palette, or with generated colours if the file has none (`details.categories`).
5. Trim empty nodata margins, if they take more than 2 % of the area.
6. Reduce resolution so that the longer side is at most `max_size_px`. The limit is set in pixels, not in MB, because what the browser has to handle is the decoded image (width × height × 4 bytes) and the GPU texture size; the PNG file size depends mostly on how well the data compress. 4096 px works on practically all devices, including mobiles. If the PNG is still larger than `max_mb` (noisy images such as satellite RGB compress poorly), the resolution is reduced further, estimated from the size of the previous attempt, so that the preview downloads quickly.
7. If the pixels would have to be more than `max_downsample` times coarser than the original, the resolution stays at this limit and only a crop around the centre is kept (`details.crop_kept_percentage`). `max_downsample=None` turns cropping off.

The log is written to a JSON file next to the PNG (same name, `.json` extension) and returned. It has the same keys as `preview_metadata` of the vector preview, plus `image_bbox_wgs84` (position of the PNG in the map), `original_bbox_wgs84` (extent of the whole raster) and `metadata_file`. If the file is still too large, `status` is set to `warning_size_exceeded`.

### `preview_viewer.html`
Leaflet page that shows a preview set in `DATA_MAP`: either a GeoJSON preview, or the JSON file of a raster preview. It has to be opened through a web server (e.g. `python -m http.server`), not as a local file.

