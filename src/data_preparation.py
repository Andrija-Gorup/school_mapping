import os
import pandas as pd
import geopandas as gpd
import logging
import argparse

import sys

sys.path.insert(0, "../utils/")
import clean_utils
import config_utils

import warnings
warnings.filterwarnings("ignore")
warnings.simplefilter("ignore")


def main():
    parser = argparse.ArgumentParser(description="Data Cleaning Pipeline")
    parser.add_argument("--config", help="Config file", default="configs/config_full.yaml")
    args = parser.parse_args()
    
    cwd = os.path.dirname(os.getcwd())
    config_file = os.path.join(cwd, args.config)
    config = config_utils.load_config(config_file)

    #clean_utils.clean_data(config, category=config["pos_class"])
    clean_utils.clean_data(config, category=config["neg_class"])


if __name__ == "__main__":
    main()
