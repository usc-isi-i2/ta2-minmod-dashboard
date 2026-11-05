import pandas as pd
from helpers import dataservice_utils
from helpers.exceptions import EmptyDedupDataFrame
from constants import API_ENDPOINT, FRONTEND_ENDPOINT
import asyncio


class MineralSite:
    """A class for holding the mineral site data"""

    def __init__(self, commodity):
        self.commodity = commodity.lower()
        self.deposit_types = []
        self.country = []
        self.data_cache = {
            "countries": {},
            "deposit-types": {},
            "states-or-provinces": {},
            "commodities": {},
        }

    def init(self):
        """Initialize and load data from query path using the function reference"""

        self.load_data_cache()

        self.df = pd.DataFrame(
            self.clean_and_fix(
                dataservice_utils.fetch_api_data(
                    "/dedup-mineral-sites",
                    params={"commodity": self.commodity},
                    ssl_flag=False,
                )
            )
        )
        if self.df.empty:
            raise EmptyDedupDataFrame("No Data Available")

        self.df = self.clean_df(self.df)
        self.deposit_types = self.df["Deposit Type"].drop_duplicates().to_list()
        self.country = self.df["Country"].drop_duplicates().to_list()

    def load_data_cache(self):
        data_list = sorted(self.data_cache.keys())

        data_results = asyncio.run(
            dataservice_utils.fetch_all([("/" + url, None) for url in data_list])
        )

        for i in range(len(data_list)):
            for data in data_results[i]:
                q_key = data["uri"].split("/")[-1]
                self.data_cache[data_list[i]][q_key] = data

    def update_commodity(self, selected_commodity):
        """sets new commodity"""
        self.commodity = selected_commodity.lower()

    def clean_and_fix(self, raw_data):
        results = []
        for data in raw_data:

            combined_data = {}
            combined_data["ms"] = "/".join([FRONTEND_ENDPOINT, "derived", data["id"]])
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
                    highest_confidence_deposit["id"], None
                )

                combined_data["top1_deposit_name"] = deposit_details["name"]
                combined_data["top1_deposit_group"] = deposit_details["group"]
                combined_data["top1_deposit_environment"] = deposit_details[
                    "environment"
                ]
                combined_data["top1_deposit_confidence"] = highest_confidence_deposit[
                    "confidence"
                ]
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
                combined_data["total_grade"] = data["grade_tonnage"][0]["total_grade"]
                combined_data["total_tonnage"] = data["grade_tonnage"][0][
                    "total_tonnage"
                ]
                combined_data["total_contained_metal"] = data["grade_tonnage"][0][
                    "total_contained_metal"
                ]

            results.append(combined_data)
        return results

    def clean_df(self, df):
        """A cleaner method to clean the raw data obtained from the SPARQL endpoint"""
        drop_columns = [
            "commodity",
        ]
        if "total_contained_metal" in df.columns:
            drop_columns.append("total_contained_metal")

        df_selected = df.drop(drop_columns, axis=1)

        # rename columns
        col_names = {
            "ms": "Mineral Site URI",
            "ms_name": "Mineral Site Name",
            "ms_type": "Mineral Site Type",
            "ms_rank": "Mineral Site Rank",
            "country": "Country",
            "state_or_province": "State/Province",
            "lat": "Latitude",
            "lon": "Longitude",
            "total_tonnage": "Total Tonnage",
            "total_grade": "Total Grade",
            "top1_deposit_name": "Deposit Type",
            "top1_deposit_group": "Deposit Group",
            "top1_deposit_environment": "Deposit Environment",
            "top1_deposit_confidence": "Deposit Classification Confidence",
            "top1_deposit_source": "Deposit Classification Source",
        }

        df_selected = df_selected.rename(columns=col_names)

        df_selected["Mineral Site Name"] = df_selected.apply(
            lambda row: f"[{row['Mineral Site Name']}]({row['Mineral Site URI']})",
            axis=1,
        )
        df_selected = df_selected.drop(["Mineral Site URI"], axis=1)

        return df_selected
