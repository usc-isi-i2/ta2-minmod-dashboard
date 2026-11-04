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
# Local runs only: makes the "derived" mineral-site links absolute, since a local
# dashboard isn't served under MinMod's domain. To use it, uncomment this line and the
# FRONTEND_ENDPOINT lines in models/geo.py, models/gt.py and models/ms.py.
# FRONTEND_ENDPOINT = os.environ.get("FRONTEND_ENDPOINT", "https://minmod.isi.edu")

#geochem
# The GeoChem papers API is only served on dev (production returns 404 for /papers), so it
# cannot share API_ENDPOINT.
GEOCHEM_API_ENDPOINT = os.environ.get("GEOCHEM_API_ENDPOINT", "http://dev.minmod.isi.edu/api/v1")
# The API's own element table; the By-Product commodity dropdown and the name <-> symbol
# mapping are read from it so they always match how the API resolves `element`.
GEOCHEM_ELEMENTS_CSV_URL = os.environ.get(
    "GEOCHEM_ELEMENTS_CSV_URL",
    "https://raw.githubusercontent.com/usc-isi-i2/ta2-minmod-kg/main/minmodkg/misc/elements.csv",
)