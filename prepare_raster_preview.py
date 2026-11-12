import os
import json
import math
import colorsys
import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import array_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, transform_bounds


# Leaflet stretches an image overlay linearly in Web Mercator, so the preview must be in this CRS
WEB_MERCATOR = "EPSG:3857"
# Web Mercator is not defined at the poles
MAX_MERCATOR_LAT = 85.05


# Integer single-band rasters with at most this many distinct values are treated as categorical
MAX_CATEGORICAL_VALUES = 64


def has_colormap(src):
    try:
        src.colormap(1)
        return True
    except ValueError:
        return False


def detect_raster_type(src):
    """Returns 'image' (3+ bands), 'categorical' or 'continuous' (single band)."""
    if src.count >= 3:
        return "image"
    if has_colormap(src):
        return "categorical"
    if np.issubdtype(np.dtype(src.dtypes[0]), np.integer):
        # Distinct values are counted on a decimated read (nearest neighbour keeps original values)
        scale = max(1, max(src.width, src.height) // 1024)
        sample = src.read(1, out_shape=(src.height // scale, src.width // scale), masked=True)
        if len(np.unique(sample.compressed())) <= MAX_CATEGORICAL_VALUES:
            return "categorical"
    return "continuous"


def select_bands(src, raster_type, bands):
    """Returns 1-based indexes of the bands to show: one band, or three bands as red, green, blue."""
    if bands is not None:
        if len(bands) not in (1, 3):
            raise ValueError("Parameter 'bands' must contain 1 or 3 band indexes.")
        return list(bands)
    if raster_type != "image":
        return [1]
    rgb = [ColorInterp.red, ColorInterp.green, ColorInterp.blue]
    if all(c in src.colorinterp for c in rgb):
        return [src.colorinterp.index(c) + 1 for c in rgb]
    return [1, 2, 3]


def web_mercator_grid(src):
    """Returns (transform, width, height) of the raster warped to Web Mercator at its original resolution."""
    left, bottom, right, top = src.bounds
    if src.crs.is_geographic:
        bottom, top = max(bottom, -MAX_MERCATOR_LAT), min(top, MAX_MERCATOR_LAT)
    return calculate_default_transform(src.crs, WEB_MERCATOR, src.width, src.height, left, bottom, right, top)


def warp_bands(src, band_indexes, transform, width, height, resampling):
    """Warps the selected bands onto the given Web Mercator grid.
    Returns (data, valid), where valid is False for nodata and for pixels outside the raster."""
    has_alpha = ColorInterp.alpha in src.colorinterp
    with WarpedVRT(src, crs=WEB_MERCATOR, transform=transform, width=width, height=height,
                   resampling=resampling, add_alpha=not has_alpha) as vrt:
        alpha_index = src.colorinterp.index(ColorInterp.alpha) + 1 if has_alpha else vrt.count
        warped = vrt.read(band_indexes + [alpha_index])
    data, valid = warped[:-1], warped[-1] > 0
    if np.issubdtype(data.dtype, np.floating):
        valid &= np.isfinite(data).all(axis=0)
    return data, valid


def stretch_to_uint8(data, valid):
    """Stretches each band to 0-255 between its 2nd and 98th percentile. Returns (data, value ranges)."""
    out = np.zeros(data.shape, dtype=np.uint8)
    ranges = []
    for i, band in enumerate(data):
        low, high = np.percentile(band[valid], [2, 98]) if valid.any() else (0, 1)
        band = np.where(valid, band, low).astype(np.float32)
        out[i] = np.clip((band - low) / ((high - low) or 1) * 255, 0, 255)
        ranges.append([round(float(low), 4), round(float(high), 4)])
    return out, ranges


def to_palette(data, valid, src_colormap):
    """Replaces class values by palette indexes 1..n (0 = transparent).
    Returns (data, colormap for the PNG, {class value: colour} for a legend)."""
    values = np.unique(data[0][valid])
    if len(values) > 255:
        raise ValueError("Too many classes for a palette preview.")
    indexed = np.searchsorted(values, data[0]) + 1
    indexed[~valid] = 0

    colormap = {0: (0, 0, 0, 0)}
    categories = {}
    for i, value in enumerate(values.tolist(), start=1):
        if src_colormap:
            rgb = src_colormap[value][:3]
        else:
            rgb = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(i * 0.618 % 1, 0.65, 0.95))
        colormap[i] = (*rgb, 255)
        categories[str(value)] = "#%02x%02x%02x" % rgb
    return indexed.astype(np.uint8)[np.newaxis], colormap, categories


def render_preview(src, raster_type, band_indexes, transform, width, height, fast=False):
    """Renders the raster onto the given Web Mercator grid as 8-bit PNG bands.
    Returns (pixels, colormap or None, details for the log).
    fast=True uses nearest neighbour resampling (only for estimating the file size)."""
    if fast:
        resampling = Resampling.nearest
    else:
        resampling = Resampling.mode if raster_type == "categorical" else Resampling.average
    data, valid = warp_bands(src, band_indexes, transform, width, height, resampling)
    details = {}

    if raster_type == "categorical":
        pixels, colormap, details["categories"] = to_palette(data, valid, src.colormap(1) if has_colormap(src) else None)
        return pixels, colormap, details

    if data.dtype != np.uint8:
        data, details["value_ranges"] = stretch_to_uint8(data, valid)
    if not valid.all():
        alpha = (valid * 255).astype(np.uint8)
        data = np.concatenate([data * valid, alpha[np.newaxis]])
    return data, None, details



def write_png(path, pixels, colormap, transform):
    # PAM disabled: no .aux.xml file next to the PNG
    with rasterio.Env(GDAL_PAM_ENABLED="NO"):
        with rasterio.open(path, "w", driver="PNG", width=pixels.shape[2], height=pixels.shape[1],
                           count=pixels.shape[0], dtype="uint8", crs=WEB_MERCATOR, transform=transform) as dst:
            dst.write(pixels)
            if colormap:
                dst.write_colormap(1, colormap)
    return os.path.getsize(path) / (1024 * 1024)


def valid_data_window(src, full_transform, full_width, full_height):
    """Finds the part of the Web Mercator grid that contains valid data, using a coarse render.
    Returns (col_off, row_off, width, height) in pixels of the full resolution grid."""
    scale = max(1, max(full_width, full_height) / 512)
    width, height = math.ceil(full_width / scale), math.ceil(full_height / scale)
    transform = full_transform * Affine.scale(full_width / width, full_height / height)
    _, valid = warp_bands(src, [1], transform, width, height, Resampling.nearest)

    cols = np.flatnonzero(valid.any(axis=0))
    rows = np.flatnonzero(valid.any(axis=1))
    if len(cols) == 0:
        raise ValueError(f"Cannot create preview for '{os.path.basename(src.name)}': raster contains no valid data.")

    # One coarse pixel is added on each side so that no valid data is cut off
    col_min, col_max = max(0, cols[0] - 1), min(width, cols[-1] + 2)
    row_min, row_max = max(0, rows[0] - 1), min(height, rows[-1] + 2)
    scale_x, scale_y = full_width / width, full_height / height
    return (col_min * scale_x, row_min * scale_y, (col_max - col_min) * scale_x, (row_max - row_min) * scale_y)


def preview_grid(full_transform, window, reduction, max_downsample):
    """Returns the output grid for a linear reduction of the pixel count (reduction >= 1).
    Pixels are made coarser up to max_downsample; any reduction beyond that is achieved
    by cropping around the centre of the window instead.
    Returns (transform, width, height, downsample factor, kept share of the window side)."""
    col_off, row_off, win_width, win_height = window
    factor = min(reduction, max_downsample) if max_downsample else reduction
    kept = factor / reduction
    col_off += win_width * (1 - kept) / 2
    row_off += win_height * (1 - kept) / 2
    win_width, win_height = win_width * kept, win_height * kept

    width, height = max(1, round(win_width / factor)), max(1, round(win_height / factor))
    transform = full_transform * Affine.translation(col_off, row_off) * Affine.scale(win_width / width, win_height / height)
    return transform, width, height, factor, kept


def find_reduction(get_size_mb, reduction, max_mb):
    """Searches for the smallest reduction (>= 1) whose PNG fits under max_mb.
    The next attempt is estimated from the size ratio, because the PNG size is roughly
    proportional to the pixel count, i.e. to 1 / reduction^2."""
    too_big, fits = None, None
    for _ in range(8):
        size_mb = get_size_mb(reduction)
        if size_mb <= max_mb:
            fits = reduction
            if reduction == 1 or size_mb >= 0.8 * max_mb:
                break
        else:
            too_big = reduction
        if too_big and fits and fits / too_big < 1.03:
            break
        next_reduction = max(1.0, reduction * math.sqrt(size_mb / (0.9 * max_mb)))
        if too_big and fits and not too_big < next_reduction < fits:
            next_reduction = math.sqrt(too_big * fits)
        reduction = next_reduction
    return fits or reduction


def save_png_preview_with_metadata(temp_path, output_path, log_data):
    """Moves the PNG to its final path, writes the log to a JSON file next to it, and returns the log."""
    details = log_data["details"]
    steps = log_data["steps_applied"]

    messages = [f"converted from {log_data['converted_from']} to PNG"]
    if "band_reduction" in steps:
        messages.append(f"bands {details['bands_used']} of {details['original_band_count']} shown")
    if "reprojection" in steps:
        messages.append(f"reprojected from {log_data['original_crs']} to Web Mercator")
    if "bit_depth_reduction" in steps:
        messages.append(f"values stretched from {details['original_dtype']} to 8 bits")
    if "nodata_trim" in steps:
        messages.append("empty margins trimmed")
    if "resolution_reduction" in steps:
        messages.append(f"resolution reduced {details['downsample_factor']}x")
    if "spatial_crop" in steps:
        messages.append(f"central crop shown ({details['crop_kept_percentage']}% of the area)")
    log_data["ui_summary"] = "Preview optimization applied: " + ", ".join(messages) + "."

    os.replace(temp_path, output_path)
    metadata_path = os.path.splitext(output_path)[0] + ".json"
    log_data["metadata_file"] = os.path.basename(metadata_path)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    return log_data


def raster_preview(input_path, output_path, max_mb=5.0, max_downsample=16, bands=None):
    """
    Generates a lightweight PNG preview suitable for web map visualization (Leaflet imageOverlay).
    Reduces bands, bit depth and resolution until the file size is below max_mb,
    writes a metadata log to a JSON file next to the PNG, and returns the log dictionary.
    """
    temp_path = f"{output_path}.tmp"
    original_size_mb = os.path.getsize(input_path) / (1024 * 1024)

    log = {
        "status": "in_progress",
        "input_file": os.path.basename(input_path),
        "output_file": os.path.basename(output_path),
        "metadata_file": None,
        "max_allowed_mb": max_mb,
        "original_size_mb": round(original_size_mb, 2),
        "final_size_mb": None,
        "original_crs": None,
        "steps_applied": [],
        "details": {},
        "ui_summary": ""
    }

    # 0. Check if the input file is a readable raster file
    try:
        src = rasterio.open(input_path)
    except Exception as e:
        raise ValueError(f"Error opening file: {e}")

    with src:
        if src.crs is None:
            raise ValueError(f"Cannot create preview for '{os.path.basename(input_path)}': CRS is missing.")

        log["converted_from"] = src.driver
        log["original_crs"] = src.crs.to_string()
        log["original_bbox_wgs84"] = [round(float(v), 6) for v in transform_bounds(src.crs, "EPSG:4326", *src.bounds)]
        log["details"]["original_width"] = src.width
        log["details"]["original_height"] = src.height
        log["details"]["original_band_count"] = src.count
        log["details"]["original_dtype"] = src.dtypes[0]

        # --- STEP 1: Detect raster type (drives band selection, resampling and colour handling) ---
        raster_type = detect_raster_type(src)

        # --- STEP 2: Band reduction (one band, or three bands shown as RGB) ---
        band_indexes = select_bands(src, raster_type, bands)
        if raster_type == "image" and len(band_indexes) == 1:
            raster_type = "continuous"
        log["details"]["raster_type"] = raster_type
        log["details"]["bands_used"] = band_indexes
        if len(band_indexes) < src.count - (ColorInterp.alpha in src.colorinterp):
            log["steps_applied"].append("band_reduction")

        # --- STEP 3: Reprojection to Web Mercator ---
        # Only the target grid is prepared here. Warping, resampling and the reduction
        # to 8 bits (STEP 4) are done together in render_preview for each tested resolution.
        full_transform, full_width, full_height = web_mercator_grid(src)
        if src.crs.to_epsg() != 3857:
            log["steps_applied"].append("reprojection")

        # --- STEP 5: Trim empty (nodata) margins, if they take more than 2 % of the area ---
        window = valid_data_window(src, full_transform, full_width, full_height)
        if window[2] * window[3] < 0.98 * full_width * full_height:
            log["steps_applied"].append("nodata_trim")
        else:
            window = (0, 0, full_width, full_height)

        # --- STEP 6 + 7: Reduce resolution until the PNG fits under max_mb; if the pixels would
        # become more than max_downsample times coarser, crop around the centre instead ---
        # The search uses fast nearest neighbour renders; the final render uses proper resampling.
        def render_and_save(reduction, fast):
            transform, width, height, factor, kept = preview_grid(full_transform, window, reduction, max_downsample)
            # Majority resampling is slow and has nothing to choose from when pixels are barely reduced
            fast = fast or (raster_type == "categorical" and factor < 2)
            pixels, colormap, details = render_preview(src, raster_type, band_indexes, transform, width, height, fast)
            size_mb = write_png(temp_path, pixels, colormap, transform)
            print(f"  {width} x {height} px, downsampled {factor:.2f}x, {kept * kept:.0%} of area: {size_mb:.2f} MB")
            return size_mb, transform, width, height, factor, kept, details

        print("Searching for the preview resolution...")
        start = math.sqrt(window[2] * window[3] * len(band_indexes) / (4 * max_mb * 1024 * 1024))
        reduction = find_reduction(lambda r: render_and_save(r, fast=True)[0], max(1.0, start), max_mb)

        print("Rendering the final preview...")
        for _ in range(4):
            size_mb, transform, width, height, factor, kept, details = render_and_save(reduction, fast=False)
            if size_mb <= max_mb:
                break
            reduction *= 1.05 * math.sqrt(size_mb / max_mb)

    log["details"].update(details)
    if "value_ranges" in details:
        log["steps_applied"].append("bit_depth_reduction")
    if factor > 1.01:
        log["steps_applied"].append("resolution_reduction")
    if kept < 1:
        log["steps_applied"].append("spatial_crop")
        log["details"]["crop_kept_percentage"] = round(kept * kept * 100, 2)
    log["details"]["downsample_factor"] = round(factor, 2)
    log["details"]["preview_width"] = width
    log["details"]["preview_height"] = height

    # Position of the image in the map, same order as original_bbox_wgs84
    image_bounds = array_bounds(height, width, transform)
    log["image_bbox_wgs84"] = [round(float(v), 6) for v in transform_bounds(WEB_MERCATOR, "EPSG:4326", *image_bounds)]

    log["final_size_mb"] = round(size_mb, 2)
    if size_mb <= max_mb:
        log["status"] = "success"
        print(f"Done. Size: {size_mb:.2f} MB")
    else:
        log["status"] = "warning_size_exceeded"
        print(f"Warning: Could not reduce size below {max_mb} MB. Final size: {size_mb:.2f} MB")

    return save_png_preview_with_metadata(temp_path, output_path, log)


# Example usage (runs only when this file is executed directly, not on import):
if __name__ == "__main__":
    result_log = raster_preview(
        "/home/pepa/MDC/test_data/dem_praha.tif",
        "/home/pepa/MDC/test_data/dem_praha_preview.png",
        max_mb=5.0
    )
    print(json.dumps(result_log, indent=2))
