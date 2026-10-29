from pathlib import Path
import json

# pipeline modules
from check_crs import has_crs
from geometadata_extractor import extract_gis_metadata
from vector_geometry_check import inspect_vector_quality
from create_zip import zip_in_memory
from build_rest_payload import create_dspace_rest_payload
from dspace_insert import DSpaceClient
from prepare_geojson_preview import geojson_preview

#### LOAD TEST DATA
#TEST_FILE = "test_data/zanikle.gpkg"
#TEST_FILE = "test_data/zanikle.geojson"
TEST_FILE = "test_data/zanikle.shp"
#TEST_FILE = "test_data/bez_crs/data_bez_crs.shp"

#TEST_FILE = r"test_data/obce_arccr.gpkg"
PREVIEW_FILE = r"test_data/simplified/zanikle_simplified.geojson"
METADATA_REST_FILE = "geoccmm_mandatory_example_restAPIformat.json"
CONFIG_FILE = "config.env"

# supported input formats
VECTOR_SUFFIXES = [".shp", ".geojson", ".gpkg"]
RASTER_SUFFIXES = [".tif", ".tiff"]


def main():
    input_path = Path(TEST_FILE)

    if not input_path.exists():
        print(f"\n[!] Error: Input file not found: {input_path.resolve()}\n")
        return

    suffix = input_path.suffix.lower()
    is_vector = suffix in VECTOR_SUFFIXES

    print(f"\n--- Starting Pipeline ---")
    print(f"Input file: {input_path.name} (type: {suffix})")

    if suffix not in VECTOR_SUFFIXES + RASTER_SUFFIXES:
        print(f"[!] Error: Unsupported file format: {suffix}")
        print("[!] Pipeline aborted.\n")
        return
    
    # 1. Step: CRS check
    print("[>] Validating dataset CRS...")

    if not has_crs(input_path):
        print(f"[!] Error: Dataset '{input_path.name}' is missing a valid CRS (or it is not recognized by PROJ).")
        print("[!] Pipeline aborted.\n")
        return
    
    print("[✓] CRS is present and valid.")

    # 3. Step Vector Quality Checks
    quality_report = None

    if is_vector:
        print("[>] Running vector quality & consistency checks...")
        quality_report = inspect_vector_quality(input_path)

        print("-" * 55)
        for check in quality_report["checks"]:
            status = "[✓] PASS" if check["passed"] else "[!] FAIL"
            print(f" {status:<10} {check['check']:<24} {check['message']}")
        print("-" * 55)

        # if emptyness-checks fails, we immediately stop
        if not quality_report["checks"][0]["passed"]:
            print("[!] Fatal: Dataset is empty. Aborting pipeline.\n")
            return

        if not quality_report["all_passed"]:
            print("[!] Warning: Vector dataset contains geometric/topological issues.")
        else:
            print("[✓] Vector dataset passed all quality checks.")


    # 4. Step: GIS metadata extraction
    print("[>] Extracting metadata attributes...")
    gis_metadata = extract_gis_metadata(input_path)
    #print("[✓] Extraction finished.\n")

    # Print results in JSON
    print("=" * 55)
    print("EXTRACTED METADATA:")
    print("=" * 55)
    print(json.dumps(gis_metadata, indent=2, ensure_ascii=False))
    print("=" * 55 + "\n")

    # 5. step: ZIP
    print("[>] Compressing dataset into memory (ZIP)...")
    zip_stream, zip_name, zip_size = zip_in_memory(input_path)

    gis_metadata["bytes"] = zip_size
    gis_metadata["filename"] = zip_name

    print(f"[✓] In-memory ZIP created: {zip_name} ({zip_size} bytes)")

    # 6. Step: Merge GIS metadata with the other metadata
    template_path = Path(METADATA_REST_FILE)

    if not template_path.exists():
        print(f"[!] Error: Template metadata file not found: {template_path.resolve()}")
        return

    print("[>] Assembling final DSpace REST payload...")
    dspace_payload = create_dspace_rest_payload(template_path, gis_metadata)
    print("[✓] DSpace payload prepared in memory.")

    # -------------------------------------------------------------
    # Print result
    # -------------------------------------------------------------
    print("=" * 55)
    print("FINAL DSPACE REST PAYLOAD (READY FOR INGEST):")
    print("=" * 55)
    print(json.dumps(dspace_payload, indent=2, ensure_ascii=False))
    print("=" * 55 + "\n")

    # 7. step: Create GeoJSON preview
    preview_file = None
    preview_description = None

    if is_vector:
        print("[>] Creating GeoJSON preview...")
        preview_file = PREVIEW_FILE
        result_log = geojson_preview(input_path, preview_file, max_mb=5.0)
        preview_description = result_log["ui_summary"]
        print(json.dumps(result_log, indent=2))
    else:
        print("[i] Raster dataset - GeoJSON preview skipped.")

    # 8. insert ZIP + preview + all metadatas to Dspace
    client = DSpaceClient(config_file=CONFIG_FILE)
    result = client.deposit(
        metadata_payload=dspace_payload,
        spatial_file=zip_stream,
        filename=zip_name,
        preview_file=preview_file,
        preview_description=result_log["ui_summary"],
    )

if __name__ == "__main__":
    main()