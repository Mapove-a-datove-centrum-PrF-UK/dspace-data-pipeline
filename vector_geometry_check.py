from pathlib import Path
import geopandas as gpd
import shapely
from shapely.validation import explain_validity


# =====================================================================
# 1. COMPLETENESS CHECK (Check if the dataset contains at least one record)
# =====================================================================
def check_not_empty(gdf: gpd.GeoDataFrame) -> dict:
  """Checks if the dataset contains at least one record."""
  total_features = len(gdf)
  passed = total_features > 0

  return {
      "check": "not_empty",
      "passed": passed,
      "message": (
          f"Dataset contains {total_features} features."
          if passed
          else "Dataset contains 0 features (empty)."
      ),
  }


# =====================================================================
# 2. MISSING & EMPTY GEOMETRIES (check for rows with missing or empty geometry)
# =====================================================================
def check_missing_geometries(gdf: gpd.GeoDataFrame) -> dict:
  """Finds rows where geometry is missing (None/NaN) or EMPTY."""

  null_count = int(gdf.geometry.isna().sum())
  empty_count = int(gdf.geometry.is_empty.sum())

  total_missing = null_count + empty_count
  passed = total_missing == 0

  details = []
  if null_count > 0:
    details.append(f"{null_count} NULL geometry records")
  if empty_count > 0:
    details.append(f"{empty_count} EMPTY geometry records")

  return {
      "check": "missing_geometry",
      "passed": passed,
      "error_count": total_missing,
      "details": details,
      "message": (
          "All features have geometries."
          if passed
          else f"Found {total_missing} missing/empty geometries:"
          f" {', '.join(details)}."
      ),
  }


# =====================================================================
# 3. GEOMETRY TYPE CONSISTENCY (mixed geometry types within a dataset)
# =====================================================================
def check_geometry_types(gdf: gpd.GeoDataFrame) -> dict:
  """Inspects whether the dataset contains a single consistent geometry type.

  Evaluates only existing, non-empty geometries.
  """
  valid_geoms = gdf.geometry[gdf.geometry.notna() & (~gdf.geometry.is_empty)]
  types_found = sorted(list(valid_geoms.geom_type.unique()))

  if not types_found:
    return {
        "check": "geometry_types",
        "passed": False,
        "types_found": [],
        "message": (
            "No geometry types could be determined (geometries are missing or"
            " empty)."
        ),
    }
  
  allowed = [
      {"Polygon", "MultiPolygon"},
      {"LineString", "MultiLineString"},
      {"Point", "MultiPoint"},
  ]

  found_set = set(types_found)

  # valid if one or all types from the allowed
  is_consistent_family = any(
      found_set.issubset(family) for family in allowed
  )
  passed = len(types_found) == 1 or is_consistent_family

  return {
      "check": "geometry_types",
      "passed": passed,
      "types_found": types_found,
      "message": (
          f"Consistent geometry type: {', '.join(types_found)}."
          if passed
          else f"Mixed geometry types detected: {', '.join(types_found)}."
      ),
  }


# =====================================================================
# 4. OGC GEOMETRIC VALIDITY
# =====================================================================
def check_ogc_validity(gdf: gpd.GeoDataFrame) -> dict:
  """Validates geometries against OGC Simple Features standards.

  Ignores missing/empty geometries (which are captured by check_missing_geometries).
  """
  geoms_to_check = gdf.geometry[
      gdf.geometry.notna() & (~gdf.geometry.is_empty)
  ]

  if geoms_to_check.empty:
    return {
        "check": "ogc_validity",
        "passed": True,
        "invalid_count": 0,
        "error_types": [],
        "message": "No geometries present to validate.",
    }

  valid_mask = geoms_to_check.is_valid
  invalid_count = int((~valid_mask).sum())
  passed = invalid_count == 0

  error_types = set()
  if not passed:
    invalid_geoms = geoms_to_check.loc[~valid_mask]
    for geom in invalid_geoms:
      raw_reason = explain_validity(geom)
      error_type = raw_reason.split("[")[0].strip()
      error_types.add(error_type)

  unique_errors = sorted(list(error_types))

  return {
      "check": "ogc_validity",
      "passed": passed,
      "invalid_count": invalid_count,
      "error_types": unique_errors,
      "message": (
          "All geometries are OGC valid."
          if passed
          else f"Found {invalid_count} invalid geometries with errors:"
          f" {', '.join(unique_errors)}."
      ),
  }


# =====================================================================
# 5. DUPLICATE GEOMETRIES
# =====================================================================
def check_duplicate_geometries(gdf: gpd.GeoDataFrame) -> dict:
  """Detects features with identical stacked geometries."""
  geoms_to_check = gdf.geometry[
      gdf.geometry.notna() & (~gdf.geometry.is_empty)
  ]
  duplicates_count = int(geoms_to_check.duplicated().sum())
  passed = duplicates_count == 0

  return {
      "check": "duplicate_geometries",
      "passed": passed,
      "duplicate_count": duplicates_count,
      "message": (
          "No duplicate geometries found."
          if passed
          else f"Found {duplicates_count} identical stacked geometries."
      ),
  }


# =====================================================================
# 6. POLYGON OVERLAPS
# =====================================================================
def check_polygon_overlaps(gdf: gpd.GeoDataFrame) -> dict:
    """
    Checks whether polygons overlap each other (sharing 2D area).
    Reports the distinct count of affected features involved in overlaps.
    """
    poly_mask = (
        gdf.geom_type.isin(["Polygon", "MultiPolygon"])
        & gdf.geometry.notna()
        & (~gdf.geometry.is_empty)
    )
    all_polys = gdf.loc[poly_mask]

    valid_polys_mask = all_polys.geometry.is_valid
    invalid_skipped = int((~valid_polys_mask).sum())

    polys = all_polys.loc[valid_polys_mask].reset_index(drop=False)
    total_valid = len(polys)

    if total_valid <= 1:
        msg = "Dataset has 1 or fewer valid polygons; skipping overlap check."
        if invalid_skipped > 0:
            msg += f" ({invalid_skipped} invalid polygon(s) skipped)."
        return {
            "check": "polygon_overlaps",
            "passed": True,
            "overlapping_features_count": 0,
            "message": msg,
        }

    sindex = polys.sindex
    affected_indices = set()

    try:
        for i, row in polys.iterrows():
            geom = row.geometry
            orig_idx_a = row["index"]

            possible_matches_idx = [
                idx for idx in sindex.intersection(geom.bounds) if idx > i
            ]
            if not possible_matches_idx:
                continue

            candidates = polys.iloc[possible_matches_idx]
            for _, other_row in candidates.iterrows():
                other_geom = other_row.geometry
                orig_idx_b = other_row["index"]

                if geom.intersects(other_geom):
                    inter = geom.intersection(other_geom)

                    has_2d_overlap = False
                    if inter.geom_type in ["Polygon", "MultiPolygon"]:
                        has_2d_overlap = True
                    elif inter.geom_type == "GeometryCollection":
                        has_2d_overlap = any(
                            g.geom_type in ["Polygon", "MultiPolygon"]
                            for g in inter.geoms
                        )

                    if has_2d_overlap:
                        affected_indices.add(orig_idx_a)
                        affected_indices.add(orig_idx_b)

    except Exception as e:
        return {
            "check": "polygon_overlaps",
            "passed": False,
            "overlapping_features_count": len(affected_indices),
            "message": f"Overlap calculation aborted due to topological error: {e}",
        }

    count = len(affected_indices)
    passed = count == 0

    if passed:
        base_msg = "No polygon overlaps detected."
    else:
        base_msg = f"Found {count} overlapping feature(s)."

    if invalid_skipped > 0:
        base_msg += f" Note: {invalid_skipped} OGC invalid polygon(s) were excluded from the check."

    return {
        "check": "polygon_overlaps",
        "passed": passed,
        "overlapping_features_count": count,
        "message": base_msg,
    }


# =====================================================================
# PIPELINE AGGREGATOR
# =====================================================================
def inspect_vector_quality(source: str | Path | gpd.GeoDataFrame) -> dict:
  """Performs an audit-style inspection on a vector dataset.

  Stops only if the dataset has 0 rows; otherwise collects results
  across all checks.
  """
  if isinstance(source, (str, Path)):
    path = Path(source)
    if not path.exists():
      raise FileNotFoundError(f"File not found: {path.resolve()}")
    gdf = gpd.read_file(path)
    dataset_name = path.name
  else:
    gdf = source
    dataset_name = "in-memory-layer"

  # 1. Hard stop on empty file
  c1 = check_not_empty(gdf)
  if not c1["passed"]:
    return {"dataset": dataset_name, "all_passed": False, "checks": [c1]}

  # 2. Run all other checks in audit mode
  checks = [
      c1,
      check_missing_geometries(gdf),
      check_geometry_types(gdf),
      check_ogc_validity(gdf),
      check_duplicate_geometries(gdf),
      check_polygon_overlaps(gdf),
  ]

  return {
      "dataset": dataset_name,
      "all_passed": all(c["passed"] for c in checks),
      "checks": checks,
  }