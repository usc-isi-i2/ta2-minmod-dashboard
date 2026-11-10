import pandas as pd
from helpers import dataservice_utils
from constants import API_ENDPOINT, FRONTEND_ENDPOINT
import asyncio


class GeoMineral:
    """A class holding geo data for the minmod home page"""

    def __init__(self, commodity):
        self.commodity = commodity.lower()
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

    def load_data_cache(self):
        data_list = sorted(self.data_cache.keys())

        data_results = asyncio.run(
            dataservice_utils.fetch_all([("/" + url, None) for url in data_list])
        )

        for i in range(len(data_list)):
            for data in data_results[i]:
                q_key = data["uri"].split("/")[-1]
                self.data_cache[data_list[i]][q_key] = data

    def clean_and_fix(self, raw_data):
        results = []
        for data in raw_data:

            if len(data["deposit_types"]) == 0:
                continue

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
            highest_confidence_deposit = max(
                data["deposit_types"], key=lambda x: x["confidence"]
            )

            deposit_details = self.data_cache["deposit-types"].get(
                highest_confidence_deposit["id"], None
            )

            if not deposit_details:
                continue
            combined_data["top1_deposit_name"] = deposit_details["name"]
            combined_data["top1_deposit_group"] = deposit_details["group"]
            combined_data["top1_deposit_environment"] = deposit_details["environment"]
            combined_data["top1_deposit_confidence"] = highest_confidence_deposit[
                "confidence"
            ]
            combined_data["top1_deposit_source"] = highest_confidence_deposit["source"]

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

            # Setting Unkown Deposit Types
            if not combined_data.get("total_tonnage") or not combined_data.get(
                "total_grade"
            ):
                combined_data["top1_deposit_name"] = "Unknown"

            results.append(combined_data)
        return results

    def update_commodity(self, selected_commodity):
        """sets new commodity"""
        self.commodity = selected_commodity.lower()
