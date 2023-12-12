import re
import os
import uuid
import requests
import logging

import geojson
import numpy as np
import pandas as pd
import geopandas as gpd

from tqdm import tqdm
from pyproj import Proj, Transformer

pd.options.mode.chained_assignment = None
logging.basicConfig(level=logging.INFO)


def _create_progress_bar(items):
    """
    Create a progress bar for iterating through items.

    Args:
    - items (iterable): Collection of items to iterate through.

    Returns:
    - tqdm: Progress bar object initialized with the items and total count.
    """

    bar_format = "{l_bar}{bar:20}{r_bar}{bar:-20b}"
    pbar = tqdm(items, total=len(items), bar_format=bar_format)
    return pbar


def _makedir(out_dir):
    """
    Create a new directory within the current working directory.

    Args:
    - out_dir (str): Name of the directory to be created.

    Returns:
    - str: Absolute path of the created directory.
    """

    cwd = os.path.dirname(os.getcwd())
    out_dir = os.path.join(cwd, out_dir)
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    return out_dir


def _get_iso_regions(config, data, iso_code):
    """
    Adds country, region, and subregion information to a DataFrame based on ISO codes.

    Args:
    - config (dict): Configuration settings.
    - data (DataFrame): DataFrame containing location data.
    - iso_code (str): ISO code for the country.

    Returns:
    - DataFrame: DataFrame with added country, region, and subregion columns.
    """

    # Load ISO codes of countries and regions/subregions
    codes = pd.read_csv(config["iso_regional_codes"])
    subcode = codes.query(f"`alpha-3` == '{iso_code}'")
    data["iso"] = iso_code
    data["country"] = subcode["name"].values[0]
    data["subregion"] = subcode["sub-region"].values[0]
    data["region"] = subcode["region"].values[0]

    return data


def _convert_to_crs(data, src_crs="EPSG:4326", target_crs="EPSG:3857"):
    """
    Converts a GeoDataFrame to a different Coordinate Reference System (CRS).

    Args:
    - data (GeoDataFrame): GeoDataFrame containing spatial data.
    - src_crs (str, optional): Source CRS. Defaults to "EPSG:4326".
    - target_crs (str, optional): Target CRS. Defaults to "EPSG:3857".

    Returns:
    - GeoDataFrame: Converted GeoDataFrame in the target CRS.
    """

    # Convert lat long to the target CRS
    if ("lat" not in data.columns) or ("lon" not in data.columns):
        data["lon"], data["lat"] = data.geometry.x, data.geometry.y
    transformer = Transformer.from_crs(src_crs, target_crs, always_xy=True)
    data["lon"], data["lat"] = transformer.transform(
        data["lon"].values, data["lat"].values
    )
    geometry = gpd.GeoSeries.from_xy(data["lon"], data["lat"])

    # Convert the data to GeoDataFrame
    data = pd.DataFrame(data.drop("geometry", axis=1))
    data = gpd.GeoDataFrame(data, geometry=geometry, crs=target_crs)
    return data


def _concat_data(data, out_file=None, verbose=True):
    """
    Concatenates a list of datasets and converts it to a GeoDataFrame.

    Args:
    - data (list): List of datasets (Pandas DataFrame) to concatenate.
    - out_file (str or None, optional): Output file path for the concatenated GeoDataFrame. Defaults to None.
    - verbose (bool, optional): Whether to display information about the processed data. Defaults to True.

    Returns:
    - GeoDataFrame: Concatenated GeoDataFrame.
    """

    data = pd.concat(data).reset_index(drop=True)
    data = gpd.GeoDataFrame(data, geometry=data["geometry"], crs="EPSG:4326")
    data = data.drop_duplicates("geometry", keep="first")

    if out_file:
        data.to_file(out_file, driver="GeoJSON")
    if verbose:
        logging.info(f"Generated {out_file}")
        logging.info(f"Data dimensions: {data.shape}, CRS: {data.crs}")

    return data


def _generate_uid(data, category):
    """
    Generates a unique identifier based on source, ISO, and category.

    Args:
    - data (DataFrame): Input DataFrame containing source and ISO information.
    - category (str): Category information to be included in the UID.

    Returns:
    - DataFrame: DataFrame with a new column 'UID' containing unique identifiers.
    """

    data["index"] = data.index.to_series().apply(lambda x: str(x).zfill(8))
    data["category"] = category
    uids = data[["source", "iso", "category", "index"]].agg("-".join, axis=1)
    data = data.drop(["index", "category"], axis=1)
    data["UID"] = uids.str.upper()
    return data


def _prepare_data(config, data, iso_code, category, source, columns, out_file=None):
    """
    Prepare datasets to have uniform columns and additional information.

    Args:
    - config (dict): Configuration settings.
    - data (DataFrame): Input DataFrame containing spatial data.
    - iso_code (str): ISO code for the country.
    - category (str): Category information.
    - source (str): Source information.
    - columns (list): Columns to be included in the final data.
    - out_file (str or None, optional): Output file path for the prepared data. Defaults to None.

    Returns:
    - DataFrame: Processed DataFrame with uniform columns and added information.
    """
    for column in columns:
        if column not in data.columns:
            data[column] = None

    data["source"] = source.upper()
    data = data.drop_duplicates("geometry", keep="first")
    data = _get_iso_regions(config, data, iso_code)
    data = _generate_uid(data, category)
    data = data[columns]

    if out_file:
        data.to_file(out_file, driver="GeoJSON")
    return data


def _get_geoboundaries(config, iso_code, out_dir=None, adm_level="ADM0"):
    """
    Fetches the geoboundary for a given ISO code and administrative level.

    Args:
    - config (dict): Configuration settings.
    - iso_code (str): ISO code for the country.
    - out_dir (str or None, optional): Output directory path. Defaults to None.
    - adm_level (str, optional): Administrative level. Defaults to "ADM0".

    Returns:
    - GeoDataFrame: Geoboundary data in GeoDataFrame format.
    """

    # Query geoBoundaries
    if not out_dir:
        cwd = os.path.dirname(os.getcwd())
        out_dir = os.path.join(cwd, config["vectors_dir"], "geoboundaries")
    if not os.path.exists(out_dir):
        out_dir = _makedir(out_dir)

    try:
        url = f"{config['geoboundaries_url']}{iso_code}/{adm_level}/"
        r = requests.get(url)
        download_path = r.json()["gjDownloadURL"]
    except:
        url = f"{config['geoboundaries_url']}{iso_code}/ADM0/"
        r = requests.get(url)
        download_path = r.json()["gjDownloadURL"]

    # Save the result as a GeoJSON
    filename = f"{iso_code}_geoboundary.geojson"
    out_file = os.path.join(out_dir, filename)
    geoboundary = requests.get(download_path).json()
    with open(out_file, "w") as file:
        geojson.dump(geoboundary, file)

    # Read data using GeoPandas
    geoboundary = gpd.read_file(out_file)
    return geoboundary


def _read_data(data_dir, exclude=[]):
    """
    Reads and concatenates data from a directory of files.

    Args:
    - data_dir (str): Directory path containing files to read.
    - exclude (list, optional): List of filenames to exclude. Defaults to an empty list.

    Returns:
    - GeoDataFrame: Concatenated GeoDataFrame containing data from the directory.
    """

    data_dir = _makedir(data_dir)
    files = next(os.walk(data_dir), (None, None, []))[2]
    files = [file for file in files if file not in exclude]

    data = []
    for file in (pbar := _create_progress_bar(files)):
        pbar.set_description(f"Reading {file}")
        filename = os.path.join(data_dir, file)
        subdata = gpd.read_file(filename)
        data.append(subdata)

    # Concatenate files in data_dir
    data = gpd.GeoDataFrame(pd.concat(data).copy(), crs="EPSG:4326")
    data = data.drop_duplicates("geometry", keep="first")
    return data


def get_counts(config, column='iso', categories=["school", "non_school"]):
    """
    Retrieves the counts of specified categories based on a given column in the GeoJSON layers.

    Args:
    - config (dict): Configuration settings.
    - column (str, optional): Column to consider for counting. Defaults to 'iso'.
    - categories (list, optional): List of categories to count. Defaults to ["school", "non_school"].
    - layer (str, optional): Layer name to extract data from. Defaults to "clean".

    Returns:
    - DataFrame: Counts of specified categories based on the given column.
    """
    
    cwd = os.path.dirname(os.getcwd())
    data = {category: [] for category in categories}
    
    iso_codes = config["iso_codes"]
    for iso_code in (pbar := _create_progress_bar(iso_codes)):
        pbar.set_description(f"Reading {iso_code}")
        for category in categories:
            dir = os.path.join(cwd, config['vectors_dir'], category)

            layer = "validated"
            filepath = os.path.join(dir, layer, "{iso_code}_{layer}.geojson")
            if not os.path.isfile(filepath):
                layer = "clean"
                filepath = os.path.join(dir, layer, f"{iso_code}_{layer}.geojson")
                
            subdata = gpd.read_file(filepath)
            if layer == "validated":
                subdata = subdata[subdata[layer] == 0]
                
            data[category].append(subdata)

    for category in categories:
        data[category] = pd.concat(data[category])
    
    counts = pd.merge(
        data[categories[0]][column].value_counts(), 
        data[categories[1]][column].value_counts(), 
        left_index=True, 
        right_index=True
    )
    counts.columns = categories
    return counts
    
