# dspace-data-pipeline

### `prepare_geojson_preview.py`
`geojson_preview(input_path, output_path, max_mb=5.0) -> dict`. Takes a vector file and makes a GeoJSON preview that fits under `max_mb`. If the input is not GeoJSON (e.g. Shapefile or GeoPackage), it is first converted with `convert_to_geojson.py` into a temporary file. The original CRS is kept, and the conversion is recorded in the log (`converted_from`). It applies the following reductions in order and stops as soon as the file is small enough:

1. Reproject to WGS84 if needed, then round coordinates to 5 decimal places (about 1 m).
2. Drop attributes, keeping only `id`, `name`, `nazev`, `typ`, `type`, `kategorie`, `category`. If none of these exist, it keeps the first column.
3. Simplify geometry step by step. The tolerance is a fraction of the median feature size (the longer side of its bounding box). It starts at 0.001 × the median size and increases up to 0.1 ×, stopping as soon as the file is small enough. Because the tolerance is relative to feature size, buildings and countries are simplified in proportion to their size. A polygon layer without overlaps (a valid coverage) uses `simplify_coverage`, so neighbouring polygons stay aligned with no gaps or overlaps. All other layers use `simplify(preserve_topology=True)`. Skipped for point layers.
4. Keep only part of the features: the ones closest to the median centre of the dataset.

A reduction log is stored in the output GeoJSON under the top-level key `preview_metadata`. It includes the steps that were applied, feature and attribute counts, and a `ui_summary` sentence that a map page can show in an info banner. The function also returns the log. If the file is still too large after step 4, `status` is set to `warning_size_exceeded`.