import os
import json
import math
import tempfile
import geopandas as gpd
import pyogrio
import shapely

from convert_to_geojson import convert_to_geojson

# Below this average number of vertices per feature, geometry simplification is skipped
# (a rectangle has 5, typical buildings 5-10).
MIN_AVG_VERTICES_FOR_SIMPLIFICATION = 15

def export_and_get_size(gdf_to_save, temp_file_path, precision=5):
    """Exports the GeoDataFrame to a temporary GeoJSON file and returns its size in MB.
    precision=None keeps the full coordinate precision."""
    if precision is None:
        gdf_to_save.to_file(temp_file_path, driver='GeoJSON')
    else:
        gdf_to_save.to_file(temp_file_path, driver='GeoJSON', coordinate_precision=precision)
    return os.path.getsize(temp_file_path) / (1024 * 1024)

def save_geojson_preview_with_metadata(temp_path, output_path, log_data):
    """Embeds reduction metadata directly into the root of the GeoJSON file, saves it, and returns the log."""
    
    # 1. Build a human-readable summary for the frontend UI (e.g., Leaflet info banner)
    messages = []
    if "converted_from" in log_data:
        messages.append(f"converted from {log_data['converted_from']} to GeoJSON")
    if "reprojection" in log_data["steps_applied"]:
        messages.append(f"reprojected from {log_data['original_crs']} to WGS84")
    if "coordinate_precision" in log_data["steps_applied"]:
        decimals = log_data["details"]["coordinate_precision"]
        approx = {5: "~1 m", 6: "~10 cm", 7: "~1 cm"}[decimals]
        messages.append(f"coordinate precision reduced to {decimals} decimal places ({approx})")
    if "attribute_reduction" in log_data["steps_applied"]:
        kept = len(log_data["details"]["attributes_kept"])
        orig = log_data["details"]["attributes_original_count"]
        messages.append(f"attributes reduced ({kept} of {orig} kept)")
    if "geometry_simplification" in log_data["steps_applied"]:
        messages.append("geometry simplified")
    if "feature_sampling" in log_data["steps_applied"]:
        pct = log_data["details"]["features_kept_percentage"]
        messages.append(f"spatial sample selected ({pct}% of features shown)")
        
    if messages:
        log_data["ui_summary"] = "Preview optimization applied: " + ", ".join(messages) + "."
    else:
        log_data["ui_summary"] = "Full dataset displayed without content reduction."

    # 2. Load the temporary GeoJSON and inject 'preview_metadata'
    with open(temp_path, "r", encoding="utf-8") as f:
        geojson_dict = json.load(f)

    geojson_dict["preview_metadata"] = log_data

    # 3. Write back using compact separators to prevent whitespace file-size inflation
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(geojson_dict, f, ensure_ascii=False, separators=(',', ':'))

    # Update final size after embedding metadata
    log_data["final_size_mb"] = round(os.path.getsize(temp_path) / (1024 * 1024), 2)
    
    os.replace(temp_path, output_path)
    return log_data


def geojson_preview(input_path, output_path, max_mb=5.0):
    """
    Generates a lightweight GeoJSON preview suitable for web map visualization (Leaflet).
    Progressively applies reduction steps until the file size is below max_mb,
    embeds a metadata log directly into the resulting GeoJSON, and returns the log dictionary.
    """
    temp_path = f"{output_path}.tmp"
    original_size_mb = os.path.getsize(input_path) / (1024 * 1024)

    log = {
        "status": "in_progress",
        "input_file": os.path.basename(input_path),
        "output_file": os.path.basename(output_path),
        "max_allowed_mb": max_mb,
        "original_size_mb": round(original_size_mb, 2),
        "final_size_mb": None,
        "original_crs": None,
        "reprojected_to_wgs84": False,
        "steps_applied": [],
        "details": {},
        "ui_summary": ""
    }

    # 0. Check if the input file is a readable vector file
    try:
        driver = pyogrio.read_info(input_path)["driver"]
    except Exception as e:
        raise ValueError(f"Error opening file: {e}")

    # Any supported vector format is read directly; the output is always written as GeoJSON
    gdf = gpd.read_file(input_path)
    if driver not in ['GeoJSON', 'GeoJSONSeq']:
        log["converted_from"] = driver

    if gdf.crs is None:
        raise ValueError(f"Cannot create preview for '{os.path.basename(input_path)}': CRS is missing.")
    
    original_feature_count = len(gdf)
    log["details"]["features_original_count"] = original_feature_count
    log["details"]["features_kept_count"] = original_feature_count
    log["details"]["features_kept_percentage"] = 100.0

    # Reproject to WGS84 (EPSG:4326) if not already
    log["original_crs"] = gdf.crs.to_string()
    if gdf.crs.to_epsg() != 4326:
        print(f"Reprojecting from {gdf.crs.name} to WGS84...")
        gdf = gdf.to_crs(epsg=4326)
        log["reprojected_to_wgs84"] = True
        log["steps_applied"].append("reprojection")

    # If the data already fits under max_mb, keep it unchanged (only reprojected, full precision)
    size_mb = export_and_get_size(gdf, temp_path, precision=None)
    if size_mb <= max_mb:
        log["status"] = "success"
        print(f"Done without reduction. Size: {size_mb:.2f} MB")
        return save_geojson_preview_with_metadata(temp_path, output_path, log)

    # Typical feature size: for each feature take the longer side of its bounding box,
    # then take the median over all features (robust to a few huge/tiny ones).
    # Used to adapt the coordinate precision (STEP 1) and the simplification tolerance (STEP 3).
    bounds = gdf.bounds
    median_size = float((bounds['maxx'] - bounds['minx']).combine(bounds['maxy'] - bounds['miny'], max).median())

    # --- STEP 1: Reduce coordinate precision ---
    # A fixed 5 decimal places (~1 m grid) is fine for large features but visibly distorts
    # small ones (building corners shift by up to 0.5 m, right angles are lost).
    # Therefore the precision follows the typical feature size:
    #   < 0.0001° (~10 m)   -> 7 decimal places (~1 cm)
    #   < 0.005°  (~0.5 km) -> 6 decimal places (~10 cm)
    #   otherwise (and points, size 0) -> 5 decimal places (~1 m)
    if 0 < median_size < 0.0001:
        precision = 7
    elif 0 < median_size < 0.005:
        precision = 6
    else:
        precision = 5
    grid_size = 10 ** -precision

    print(f"Reducing coordinate precision to {precision} decimal places...")
    gdf['geometry'] = shapely.set_precision(gdf['geometry'].values, grid_size=grid_size)
    size_mb = export_and_get_size(gdf, temp_path, precision=precision)

    log["steps_applied"].append("coordinate_precision")
    log["details"]["coordinate_precision"] = precision

    if size_mb <= max_mb:
        log["status"] = "success"
        print(f"Done. Size: {size_mb:.2f} MB")
        return save_geojson_preview_with_metadata(temp_path, output_path, log)

    # --- STEP 2: Attribute reduction (keep only key identifier/name/type columns) ---
    geom_col = gdf.geometry.name
    all_cols = list(gdf.columns)
    print("Reducing attributes to only the most important ones...")
    keep_cols = [col for col in all_cols if col.lower() in ['id', 'name', 'nazev', 'typ', 'type', 'kategorie', 'category']]

    # Fallback: keep the first non-geometry column if none of the target columns exist
    if not keep_cols:
        first_col = all_cols[0]
        if first_col != geom_col:
            keep_cols.append(first_col)

    keep_cols.append(geom_col)
    gdf = gdf[keep_cols]

    size_mb = export_and_get_size(gdf, temp_path, precision=precision)
    
    log["steps_applied"].append("attribute_reduction")
    log["details"]["attributes_original_count"] = len(all_cols) - 1
    log["details"]["attributes_kept"] = [c for c in keep_cols if c != geom_col]

    if size_mb <= max_mb:
        log["status"] = "success"
        print(f"Done. Size: {size_mb:.2f} MB")
        return save_geojson_preview_with_metadata(temp_path, output_path, log)

    # --- STEP 3: Simplify geometry shapes ---
    # File size is driven mainly by the number of vertices, so we remove vertices
    # while keeping shapes recognizable. Points have nothing to simplify.
    geom_types = gdf.geom_type.unique()
    is_point_only = all(t in ['Point', 'MultiPoint'] for t in geom_types)
    is_polygon_only = all(t in ['Polygon', 'MultiPolygon'] for t in geom_types)

    # Features with only a few vertices (e.g. buildings, ~5-10 vertices) have nothing to remove:
    # simplification would only deform them (rectangle -> triangle) and save almost nothing.
    # In that case skip simplification and go straight to reducing the number of features.
    avg_vertices = float(shapely.get_num_coordinates(gdf[geom_col].values).mean())
    log["details"]["avg_vertices_per_feature"] = round(avg_vertices, 1)
    too_few_vertices = avg_vertices < MIN_AVG_VERTICES_FOR_SIMPLIFICATION

    if too_few_vertices and not is_point_only:
        print(f"Skipping simplification (only {avg_vertices:.1f} vertices per feature on average).")
        log["details"]["simplification_skipped"] = "too few vertices per feature"

    if not is_point_only and not too_few_vertices:
        print("Simplifying geometry...")

        # Tolerance = how far the simplified outline may deviate from the original.
        # A fixed tolerance does not fit all data: 50 m is negligible for a country (~600 km)
        # but turns a building (~20 m) into a triangle. Therefore the tolerance is derived
        # from the typical feature size (median_size, computed before STEP 1).

        # Polygon coverage (non-overlapping polygons, e.g. countries): shared borders are
        # simplified once, so neighbours stay without gaps/overlaps.
        # Otherwise each feature is simplified on its own (borders may no longer match).
        use_coverage = is_polygon_only and shapely.coverage_is_valid(gdf[geom_col].values)
        algorithm = "Visvalingam-Whyatt (coverage)" if use_coverage else "Douglas-Peucker (topology preserving)"

        # Try increasingly coarse tolerances (0.1-10 % of median feature size), stop at first fit.
        # Each attempt simplifies the original geometry; if none fits, continue to STEP 4.
        original_geoms = gdf[geom_col]
        for factor in [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1]:
            tolerance = round(factor * median_size, 7)
            # Coordinates were already snapped to the STEP 1 grid, so a smaller
            # tolerance would change nothing; skip it to avoid a useless export.
            # The last factor always runs so that the loop produces a result.
            if tolerance < grid_size and factor < 0.1:
                continue
            if use_coverage:
                gdf[geom_col] = original_geoms.simplify_coverage(tolerance=tolerance)
            else:
                gdf[geom_col] = original_geoms.simplify(tolerance=tolerance, preserve_topology=True)
            size_mb = export_and_get_size(gdf, temp_path, precision=precision)
            print(f"  tolerance {tolerance}° ({factor} x median feature size): {size_mb:.2f} MB")
            if size_mb <= max_mb:
                break

        log["steps_applied"].append("geometry_simplification")
        log["details"]["simplification_algorithm"] = algorithm
        log["details"]["simplification_tolerance_deg"] = tolerance
        log["details"]["simplification_tolerance_factor"] = factor

        if size_mb <= max_mb:
            log["status"] = "success"
            print(f"Done. Size: {size_mb:.2f} MB")
            return save_geojson_preview_with_metadata(temp_path, output_path, log)

    # --- STEP 4: Reduce number of features (spatial sample around median center) ---
    print("Reducing number of features...")
    bounds = gdf.bounds
    center_x = (bounds['minx'] + bounds['maxx']) / 2.0
    center_y = (bounds['miny'] + bounds['maxy']) / 2.0

    # Find the densest area using the median of bounding box centers
    median_x = center_x.median()
    median_y = center_y.median()

    # Calculate squared distances from the median point (with longitude cosine correction)
    cos_lat = math.cos(math.radians(median_y))
    gdf['dist_sq'] = ((center_x - median_x) * cos_lat)**2 + (center_y - median_y)**2

    # Estimate the proportion of features to keep (with a 0.90 safety factor)
    keep_percentage = (max_mb / size_mb) * 0.90
    num_features_to_keep = max(10, int(original_feature_count * keep_percentage))

    gdf = gdf.nsmallest(num_features_to_keep, 'dist_sq').drop(columns=['dist_sq'])

    final_size_mb = export_and_get_size(gdf, temp_path, precision=precision)
    
    actual_kept_pct = round((len(gdf) / original_feature_count) * 100, 2)
    log["steps_applied"].append("feature_sampling")
    log["details"]["sampling_method"] = "spatial_median_cluster"
    log["details"]["sampling_center_lon_lat"] = [round(float(median_x), 5), round(float(median_y), 5)]
    log["details"]["features_kept_count"] = len(gdf)
    log["details"]["features_kept_percentage"] = actual_kept_pct

    if final_size_mb <= max_mb:
        log["status"] = "success"
        print(f"Done. Kept {actual_kept_pct}% of features. Final size: {final_size_mb:.2f} MB")
    else:
        log["status"] = "warning_size_exceeded"
        print(f"Warning: Could not reduce size below {max_mb} MB. Final size: {final_size_mb:.2f} MB")

    return save_geojson_preview_with_metadata(temp_path, output_path, log)


# Example usage (runs only when this file is executed directly, not on import):
if __name__ == "__main__":
    result_log = geojson_preview(
        "/home/pepa/MDC/test_data/world_countries.geojson",
        "/home/pepa/MDC/test_data/world_countries_simplified.geojson",
        max_mb=5.0
    )
    print(json.dumps(result_log, indent=2))