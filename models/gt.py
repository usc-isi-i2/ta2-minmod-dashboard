import pandas as pd
from helpers import dataservice_utils
from math import radians, sin, cos, sqrt, atan2
from functools import lru_cache
import numpy as np
from helpers.exceptions import EmptyDedupDataFrame, EmtpyGTDataFrame
from datetime import datetime, timedelta
import asyncio
from helpers.kpis import get_commodity_dict
from constants import API_ENDPOINT
# from constants import FRONTEND_ENDPOINT  # local runs only, see constants.py

# Define a constant date range (e.g., 30 days)
CACHE_DURATION_DAYS = 3

# Cache storage for the last-used timestamps
cache_access_times = {}


# Decorator to create a cache with a time-based expiration
def lru_cache_with_date_range(maxsize=128):
    def decorator(func):
        # LRU Cache
        @lru_cache(maxsize=maxsize)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Function to check and clear outdated cache entries
        def clear_expired_cache():
            current_time = datetime.now()
            for key in list(cache_access_times.keys()):
                if current_time - cache_access_times[key] > timedelta(
                    days=CACHE_DURATION_DAYS
                ):
                    wrapper.cache_clear()  # Clear the entire cache if one entry is too old
                    break  # You can modify this to clear only the expired keys if needed

        # Wrap the original function to track access times
        def cached_func(*args, **kwargs):
            clear_expired_cache()  # Check and clear expired cache before any function call
            result = wrapper(*args, **kwargs)
            cache_access_times[args] = (
                datetime.now()
            )  # Track when the cache was last used
            return result

        return cached_func

    return decorator


# Earth radius in kms
EARTH_RADIUS = 6371.0  # in kms


class GradeTonnage:
    """A class for holding the grade tonnage model plot"""

    def __init__(self, commodities, proximity_value=0):
        self.commodities = [commodity.lower() for commodity in commodities]
        self.deposit_types = []
        self.country = []
        self.distance_caches = {}
        self.proximity_value = proximity_value
        self.visible_traces = []
        self.aggregated_df = []
        self.data_cache = {
            "countries": {},
            "deposit-types": {},
            "states-or-provinces": {},
            "commodities": {},
        }

    def init(self):
        """Initialize and load data from query path using the function reference"""
        # self.df = pd.DataFrame(
        #     self.clean_and_fix(
        #         dataservice_utils.fetch_api_data(
        #             "/dedup_mineral_sites/" + self.commodity, ssl_flag=False
        #         )
        #     )
        # )

        self.load_data_cache()

        dataframes = [
            pd.DataFrame(data)
            for data in self.clean_and_fix(
                asyncio.run(
                    dataservice_utils.fetch_all(
                        [
                            ("/dedup-mineral-sites", {"commodity": commodity})
                            for commodity in self.commodities
                        ]
                    )
                )
            )
        ]

        for i, df in enumerate(dataframes):
            if df.empty:
                raise EmptyDedupDataFrame(
                    f"No Data Available for : {self.commodities(i)}"
                )

        self.df = pd.concat(
            dataframes,
            ignore_index=True,
        )

        if self.df.empty:
            raise EmptyDedupDataFrame("No Data Available")

        self.df = self.clean_df(self.df)
        self.deposit_types = self.df["top1_deposit_name"].drop_duplicates().to_list()
        self.country = self.df["country"].to_list()

        if self.proximity_value != 0:
            self.distance_caches = self.compute_all_distances(tuple(self.commodities))

    def load_data_cache(self):
        data_list = sorted(self.data_cache.keys())

        data_results = asyncio.run(
            dataservice_utils.fetch_all([("/" + url, None) for url in data_list])
        )

        for i in range(len(data_list)):
            for data in data_results[i]:
                q_key = data["uri"].split("/")[-1]
                self.data_cache[data_list[i]][q_key] = data

    def update_commodity(self, selected_commodities):
        """sets new commodity"""
        self.commodities = [
            selected_commodity.lower() for selected_commodity in selected_commodities
        ]
        self.visible_traces = []
        self.aggregated_df = []

    def update_proximity(self, proximity_value):
        """sets new proximity"""
        self.proximity_value = proximity_value

    def clean_and_fix(self, raw_data_list):
        result_list = []
        for raw_data in raw_data_list:
            results = []
            for data in raw_data:

                combined_data = {}
                combined_data["ms"] = "/".join(["/derived", data["id"]])
                # combined_data["ms"] = "/".join([FRONTEND_ENDPOINT, "derived", data["id"]])  # local runs only
                combined_data["ms_name"] = data["name"]
                combined_data["ms_type"] = data["type"]
                combined_data["ms_rank"] = data["rank"]

                # Location details
                if (
                    "location" in data
                    and "country" in data["location"]
                    and data["location"]["country"]
                    and data["location"]["country"][0] in self.data_cache["countries"]
                ):
                    combined_data["country"] = self.data_cache["countries"][
                        data["location"]["country"][0]
                    ]["name"]
                else:
                    combined_data["country"] = None

                if (
                    "location" in data
                    and "state_or_province" in data["location"]
                    and data["location"]["state_or_province"]
                    and data["location"]["state_or_province"][0]
                    in self.data_cache["states-or-provinces"]
                ):
                    combined_data["state_or_province"] = self.data_cache[
                        "states-or-provinces"
                    ][data["location"]["state_or_province"][0]]["name"]
                else:
                    combined_data["state_or_province"] = None

                if "location" in data:
                    combined_data["lat"] = data["location"].get("lat", None)
                    combined_data["lon"] = data["location"].get("lon", None)

                # Deposit Type details
                if data["deposit_types"]:
                    highest_confidence_deposit = max(
                        data["deposit_types"], key=lambda x: x["confidence"]
                    )

                    deposit_details = self.data_cache["deposit-types"].get(
                        highest_confidence_deposit["id"], False
                    )

                    combined_data["top1_deposit_name"] = deposit_details["name"]
                    combined_data["top1_deposit_group"] = deposit_details["group"]
                    combined_data["top1_deposit_environment"] = deposit_details[
                        "environment"
                    ]
                    combined_data["top1_deposit_confidence"] = (
                        highest_confidence_deposit["confidence"]
                    )
                    combined_data["top1_deposit_source"] = highest_confidence_deposit[
                        "source"
                    ]
                else:
                    combined_data["top1_deposit_name"] = "Unknown"
                    combined_data["top1_deposit_group"] = "Unknown"
                    combined_data["top1_deposit_environment"] = "Unknown"
                    combined_data["top1_deposit_confidence"] = 0
                    combined_data["top1_deposit_source"] = "Unknown"

                # Commodity details
                combined_data["commodity"] = data["grade_tonnage"][0]["commodity"]

                # GT details
                if "total_grade" in data["grade_tonnage"][0]:
                    combined_data["total_grade"] = data["grade_tonnage"][0][
                        "total_grade"
                    ]
                    combined_data["total_tonnage"] = data["grade_tonnage"][0][
                        "total_tonnage"
                    ]
                    combined_data["total_contained_metal"] = data["grade_tonnage"][0][
                        "total_contained_metal"
                    ]

                # Setting Unkown Deposit Types
                if not combined_data.get("total_tonnage") or not combined_data.get(
                    "total_grade"
                ):
                    combined_data["top1_deposit_name"] = "Unknown-GT"

                results.append(combined_data)
            result_list.append(results)
        return result_list

    def clean_df(self, df):
        """A cleaner method to clean the raw data obtained from the SPARQL endpoint"""
        df = df[df["ms_name"].notna()]

        commodities = df["commodity"].unique()

        # filtering Unkown deposit types
        df = df[df["top1_deposit_name"] != "Unknown-GT"]

        filtered_commodities = df["commodity"].unique()

        if df.empty:
            raise EmtpyGTDataFrame("No Grade or Tonnage Data Available")

        for commodity in commodities:
            if commodity not in filtered_commodities:
                raise EmtpyGTDataFrame(
                    f"No Grade or Tonnage Data Avalable for : {self.data_cache['commodities'][commodity]['name'].capitalize()}"
                )

        return df

    # Haversine distance function to calculate distance in miles
    def haversine(self, lat1, lon1, lat2, lon2):
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        return EARTH_RADIUS * c  # Returns distance in miles

    # Caching approach: Precompute all pairwise distances and store them
    @lru_cache_with_date_range(maxsize=10)
    def compute_all_distances(self, commodities):
        distances = {}
        indices = self.df.index

        for i in indices:
            for j in indices:
                if i < j:
                    distance = self.haversine(
                        self.df.loc[i, "lat"],
                        self.df.loc[i, "lon"],
                        self.df.loc[j, "lat"],
                        self.df.loc[j, "lon"],
                    )
                    distances[(i, j)] = distance
                    distances[(j, i)] = distance

        return distances

    def extract_lat_lon(self, wkt_point):
        if pd.isnull(wkt_point):
            return pd.Series([np.nan, np.nan])  # Return NaN if the value is null
        # Remove 'POINT(' and ')' and split by space
        wkt_point = wkt_point.replace("POINT (", "").replace(")", "")
        lon, lat = map(float, wkt_point.split())
        return pd.Series([lat, lon])
