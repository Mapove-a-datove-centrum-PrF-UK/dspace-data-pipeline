from pathlib import Path
import json

# pipeline modules
from check_crs import has_crs
from convert_to_gpkg import convert_to_gpkg
from geometadata_extractor import extract_gis_metadata
from vector_geometry_check import inspect_vector_quality
#from leaflet_preview import geojson_preview
from build_rest_payload import create_dspace_rest_payload

#### LOAD TEST DATA
#TEST_FILE = "test_data/zanikle.shp"
#TEST_FILE = "test_data/zanikle.gpkg"
#TEST_FILE = "test_data/zanikle.geojson"
#TEST_FILE = "test_data/zanikle.shp"

#TEST_FILE = "test_data/bez_crs/data_bez_crs.shp"

TEST_FILE = "test_data/obce_arccr.gpkg"
METADATA_REST_FILE = "geoccmm_mandatory_example_restAPIformat.json"

OUTPUT_DIR = "test_data/converted"


def main():
    input_path = Path(TEST_FILE)

    if not input_path.exists():
        print(f"\n[!] Error: Input file not found: {input_path.resolve()}\n")
        return

    suffix = input_path.suffix.lower()

    print(f"\n--- Starting Pipeline ---")
    print(f"Input file: {input_path.name} (type: {suffix})")

    # 1. Step: CRS check
    print("[>] Validating dataset CRS...")

    if not has_crs(input_path):
        print(f"[!] Error: Dataset '{input_path.name}' is missing a valid CRS (or it is not recognized by PROJ).")
        print("[!] Pipeline aborted.\n")
        return
    
    print("[✓] CRS is present and valid.")

    # 2. Step: Conversion if it's an unstandardized vector
    is_vector = suffix in [".shp", ".geojson", ".gpkg"]

    if suffix in [".shp", ".geojson", ".json"]:
        print("[>] Converting vector to GeoPackage...")
        spatial_file = convert_to_gpkg(input_path, output_dir=OUTPUT_DIR)
        print(f"[✓] Created GeoPackage: {spatial_file}")
    elif suffix in [".gpkg", ".tif", ".tiff"]:
        print(f"[i] File is already standardized ({suffix}).")
        spatial_file = input_path
    else:
        print(f"[!] Unsupported file format: {suffix}")
        return

    # 3. Step Vector Quality Checks
    quality_report = None
    if is_vector:
        print("[>] Running vector quality & consistency checks...")
        quality_report = inspect_vector_quality(spatial_file)

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
    gis_metadata = extract_gis_metadata(spatial_file)
    #print("[✓] Extraction finished.\n")

    # Print results in JSON
    print("=" * 55)
    print("EXTRACTED METADATA:")
    print("=" * 55)
    print(json.dumps(gis_metadata, indent=2, ensure_ascii=False))
    print("=" * 55 + "\n")

    # 5. Step: Merge GIS metadata with the other metadata (NOT READY YET)
    # template_path = Path(METADATA_REST_FILE)

    # if not template_path.exists():
    #     print(f"[!] Error: Template metadata file not found: {template_path.resolve()}")
    #     return

    # print("[>] Assembling final DSpace REST payload...")
    # dspace_payload = create_dspace_rest_payload(template_path, gis_metadata)
    # print("[✓] DSpace payload prepared in memory.")

    # # -------------------------------------------------------------
    # # Print result
    # # -------------------------------------------------------------
    # print("=" * 55)
    # print("FINAL DSPACE REST PAYLOAD (READY FOR INGEST):")
    # print("=" * 55)
    # print(json.dumps(dspace_payload, indent=2, ensure_ascii=False))
    # print("=" * 55 + "\n")

if __name__ == "__main__":
    main()