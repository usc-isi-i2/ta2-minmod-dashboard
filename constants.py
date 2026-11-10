import os
import yaml

# Load the YAML configuration
with open("critical_minerals.yaml", "r") as file:
    config = yaml.safe_load(file)

minerals = set(mineral.lower() for mineral in config["CRITICAL_MINERALS"])
ree_minerals = list(set(mineral.lower().capitalize() for mineral in config["REE"]))
pge_minerals = list(set(mineral.lower().capitalize() for mineral in config["PGE"]))
heavy_ree_minerals = list(
    set(mineral.lower().capitalize() for mineral in config["HEAVY_REE"])
)
light_ree_minerals = list(
    set(mineral.lower().capitalize() for mineral in config["LIGHT_REE"])
)

CRITICAL_MINERALS = minerals.union(ree_minerals)
SPARQL_ENDPOINT = os.environ.get("SPARQL_ENDPOINT", "https://minmod.isi.edu/sparql")
API_ENDPOINT = os.environ.get("API_ENDPOINT", "https://minmod.isi.edu/api/v1")
# Prefix for the "derived" mineral-site links. Empty in production, so the links stay
# relative (/derived/<id>); set it to https://minmod.isi.edu when running locally.
FRONTEND_ENDPOINT = os.environ.get("FRONTEND_ENDPOINT", "").rstrip("/")

#geochem
# The GeoChem papers API is only served on dev (production returns 404 for /papers), so it
# cannot share API_ENDPOINT.
GEOCHEM_API_ENDPOINT = os.environ.get("GEOCHEM_API_ENDPOINT", "http://dev.minmod.isi.edu/api/v1")
# The API's own element table. The By-Product tab maps critical_minerals.yaml names to
# symbols with it, so they always match how the API resolves `element`.
GEOCHEM_ELEMENTS_CSV_URL = os.environ.get(
    "GEOCHEM_ELEMENTS_CSV_URL",
    "https://raw.githubusercontent.com/usc-isi-i2/ta2-minmod-kg/main/minmodkg/misc/elements.csv",
)