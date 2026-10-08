import os
import math
import geopandas as gpd
import fiona
import shapely

def export_and_get_size(gdf_to_save, temp_file_path):
    gdf_to_save.to_file(temp_file_path, driver='GeoJSON', coordinate_precision=5)
    return os.path.getsize(temp_file_path) / (1024 * 1024)

def geojson_preview(input_path, output_path, max_mb=5.0):
    # input: valid geojson (points, lines, polygons) with set CRS

    # check if it is geojson, find its coordinate system, and check if it is valid

    # project the geojson to WGS84 (leaflet geojson parser expects WGS84)

    # reduce the geojson to a smaller size if it is too large ->
    #   - reduce number of decimal places in coordinates
    #   - reduce the attributes - only leave the most important ones for the preview (which? and is it a good idea to reduce the attributees?)
    #   - reduce the precision of the shape of the features (algorithm: Douglas-Peucker, Visvalingam–Whyatt ?)
    #   - reduce number of points, lines and polygons if needed (how?)
    #       since the aim is to cerate dataset for a preview of the data, it is possible to only keep some features if the data is huge. then, we only would show a sample of points, lines or polygons. (how to choose the bounding box of the sample? size? where?)

    # other checks?

    # test on datasets of: small amount of points, large amount of points (etc. all czech villages), lines - dibavod czech rivers, lines - roades in prague, polygons - boundaries of the world, polygons - buildings in prague/czechia


    # output: reduced geojson in WGS84, max 5MB, thats is the given maximum size for a non-problematic leaflet online visualisation.

    temp_path = output_path + ".tmp"

    #check if geojson
    try:
        with fiona.open(input_path) as src:
            if src.driver not in ['GeoJSON', 'GeoJSONSeq']:
                raise ValueError(f"Not GeoJSON, but: {src.driver}")
    except Exception as e:
        raise ValueError(f"Error: {e}")
    
    gdf = gpd.read_file(input_path)

    if gdf.empty:
        raise ValueError("No data in GeoJSON.")

    #checking CRS
    if gdf.crs is None:
        print("Missing crs information. Assuming WGS84 (EPSG:4326).")
        gdf.set_crs(epsg=4326, inplace=True)
    elif gdf.crs.to_epsg() != 4326:
        print(f"Reprojecting from {gdf.crs.name} to WGS84...")
        gdf = gdf.to_crs(epsg=4326)

    # 1. reducing precision of coordinates to reduce file size, 5 decimal places = about 1 meter precision
    print("Reducing coordinate precision to 5 decimal places...")
    gdf['geometry'] = shapely.set_precision(gdf['geometry'].values, grid_size=0.00001)

    size_mb = export_and_get_size(gdf, temp_path)

    if size_mb <= max_mb:
        os.replace(temp_path, output_path)
        print(f"Done. Steps: reduced coordinate precision. Size: {size_mb:.2f} MB")
        return output_path

    
    # 2. attribute reduction - keep only the most important columns (id, name, nazev, typ, type, kategorie)
    geom_col = gdf.geometry.name  # getting the name of the geometry column (usually 'geometry')
    print("Reducing attributes to only the most important ones...")
    keep_cols = [col for col in gdf.columns if col.lower() in ['id', 'name', 'nazev', 'typ', 'type', 'kategorie', 'category']]
    
    # if none of the important columns are present, we will keep the first column (if it is not the geometry column)
    if not keep_cols:
        first_col = gdf.columns[0]
        if first_col != geom_col:
            keep_cols.append(first_col)
            
    # append the geometry column to the list of columns to keep
    keep_cols.append(geom_col)
    
    # only keep the selected columns in the gdf
    gdf = gdf[keep_cols]

    size_mb = export_and_get_size(gdf, temp_path)
    
    if size_mb <= max_mb:
        os.replace(temp_path, output_path)
        print(f"Done. Steps: reduced coordinate precision, reduced attributes. Size: {size_mb:.2f} MB")
        return output_path

    # 3. reduce the geometry shapes using Douglas-Peucker algorithm
    geom_types = gdf.geom_type.unique()
    is_point_only = all(t in ['Point', 'MultiPoint'] for t in geom_types) #check if the dataset contains only points
    if not is_point_only:
        print("Simplifying geometry...")
        gdf[geom_col] = gdf[geom_col].simplify(tolerance=0.0005, preserve_topology=True)

    size_mb = export_and_get_size(gdf, temp_path)
        
    if size_mb <= max_mb:
        os.replace(temp_path, output_path)
        print(f"Done. Steps: reduced coordinate precision, reduced attributes, simplified geometry. Size: {size_mb:.2f} MB")
        return output_path

    # 4. reduce number of features
    print("Reducing number of features...")

    # finding bounding boxes of the features and finding the center of the bounding box of the whole dataset
    bounds = gdf.bounds
    center_x = (bounds['minx'] + bounds['maxx']) / 2.0
    center_y = (bounds['miny'] + bounds['maxy']) / 2.0

    # finding where the data is densest - median of bounding boxes' centers
    median_x = center_x.median()
    median_y = center_y.median()

    # counting squared distances from the median point to each feature's bounding box center (no need of square root(=exact distance), saves time)
    cos_lat = math.cos(math.radians(median_y)) # WGS -> correction for longtitude distance
    gdf['dist_sq'] = ((center_x - median_x) * cos_lat)**2 + (center_y - median_y)**2

    # calculating how many features to keep based on the size of the dataset and the maximum allowed size
    keep_percentage = (max_mb / size_mb) * 0.90
    num_features_to_keep = max(10, int(len(gdf) * keep_percentage)) # at least 10 features are kept

    # n closest features to the median point are kept
    gdf = gdf.nsmallest(num_features_to_keep, 'dist_sq')
    gdf = gdf.drop(columns=['dist_sq'])

    # final export and size check
    final_size_mb = export_and_get_size(gdf, temp_path)
    if final_size_mb <= max_mb:
        os.replace(temp_path, output_path)
        print(f"Done. Steps: reduced coordinate precision, reduced attributes, simplified geometry, removed {100 - keep_percentage * 100:.1f}% of features. Final size: {final_size_mb:.2f} MB")
        return output_path
    else:
        os.replace(temp_path, output_path)
        print(f"Could not reduce the size below {max_mb} MB. Final size: {final_size_mb:.2f} MB")
        return output_path


geojson_preview("/home/pepa/MDC/test_data/czech_rivers.geojson", "/home/pepa/MDC/test_data/czech_rivers_simplified.geojson", max_mb=5)