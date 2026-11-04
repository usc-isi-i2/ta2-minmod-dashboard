import dash
from dash import html, callback, dcc
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
from dash_ag_grid import AgGrid

from components import stats_card
from geochem import api
from logger_config import logger


dash.register_page(__name__, path="/byproduct", name="By-Product Data")

DEFAULT_COL_DEF = {"resizable": True, "sortable": True, "filter": True}
GRID_STYLE = {"width": "100%", "height": "50vh"}

layout = html.Div(
    [
        dcc.Location(id="url-byproduct", refresh=True),
        # The selected deposit, kept outside the deposits grid: the grid only
        # exists once a paper is picked, and a callback whose Input is missing
        # from the layout errors in the browser when its other Input (the BDL
        # switch) fires.
        dcc.Store(id="bp-selected-deposit"),
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Label("Commodity"),
                        dbc.Spinner(
                            dcc.Dropdown(
                                id="bp-commodity",
                                options=[],
                                placeholder="Search Commodity",
                            ),
                        ),
                    ],
                    width=4,
                ),
                dbc.Col(
                    [
                        dbc.Label("Country"),
                        dcc.Dropdown(
                            id="bp-country",
                            options=[],
                            placeholder="Search Country",
                        ),
                    ],
                    width=4,
                ),
            ]
        ),
        html.Br(),
        html.H5("Papers"),
        dbc.Row(
            dbc.Spinner(
                html.Div(id="bp-papers-results"),
                color="primary",
                type="border",
                size="lg",
            )
        ),
        html.Br(),
        html.H5("Deposits"),
        dbc.Row(
            dbc.Spinner(
                html.Div(id="bp-deposits-results"),
                color="primary",
                type="border",
                size="lg",
            )
        ),
        html.Br(),
        html.H5("Grade Summary"),
        dbc.Row(
            dbc.Spinner(
                html.Div(id="bp-summary-results"),
                color="primary",
                type="border",
                size="lg",
            )
        ),
        html.Br(),
        # The switch lives outside bp-samples-results so it keeps its state when
        # the grid is rebuilt on each deposit click.
        dbc.Row(
            [
                dbc.Col(html.H5("Samples"), width="auto"),
                dbc.Col(
                    dbc.Switch(
                        id="bp-include-bdl",
                        label="Include below-detection readings",
                        value=True,
                    ),
                    className="d-flex justify-content-end",
                ),
            ],
            align="center",
        ),
        dbc.Row(
            dbc.Spinner(
                html.Div(id="bp-samples-results"),
                color="primary",
                type="border",
                size="lg",
            )
        ),
    ],
    style={"margin": "20px"},
)


def _no_results_alert():
    return dbc.Alert("No results found.", color="danger")


def _error_alert(exc):
    """Distinct from _no_results_alert: "the query could not run" must not
    read as "this commodity has no data"."""
    return dbc.Alert(
        [html.Strong("GeoChem data unavailable. "), str(exc)], color="danger"
    )


def _build_papers_grid(papers):
    rows = []
    for p in papers:
        row = dict(p)
        row["doi_link"] = f"[{p['doi']}](https://doi.org/{p['doi']})" if p.get("doi") else None
        rows.append(row)

    column_defs = [
        {"headerName": "Title", "field": "title"},
        {"headerName": "Journal", "field": "journal"},
        {"headerName": "Year", "field": "year"},
        {
            "headerName": "DOI",
            "field": "doi_link",
            "cellRenderer": "markdown",
            "cellRendererParams": {"linkTarget": "_blank"},
        },
    ]
    return AgGrid(
        id="bp-papers-grid",
        style=GRID_STYLE,
        columnDefs=column_defs,
        rowData=rows,
        columnSize="responsiveSizeToFit",
        defaultColDef=DEFAULT_COL_DEF,
        dashGridOptions={
            "rowSelection": "single",
            "pagination": True,
            "paginationPageSize": 20,
            "suppressFieldDotNotation": True,
            "enableCellTextSelection": True,
            "getRowId": {"function": "params.data.paper_id"},
        },
    )


def _build_deposits_grid(deposits):
    column_defs = [
        {"headerName": "Deposit Name", "field": "deposit_name"},
        {"headerName": "Country", "field": "country"},
        {"headerName": "State", "field": "state"},
        {"headerName": "Deposit Type", "field": "deposit_type_text"},
        {"headerName": "Confidence", "field": "deposit_type_confidence"},
    ]
    return AgGrid(
        id="bp-deposits-grid",
        style=GRID_STYLE,
        columnDefs=column_defs,
        rowData=deposits,
        columnSize="responsiveSizeToFit",
        defaultColDef=DEFAULT_COL_DEF,
        dashGridOptions={
            "rowSelection": "single",
            "pagination": True,
            "paginationPageSize": 20,
            "suppressFieldDotNotation": True,
            "enableCellTextSelection": True,
            "getRowId": {"function": "params.data.site_id"},
        },
    )


def _build_samples_grid(samples):
    column_defs = [
        {"headerName": "Sample ID", "field": "sample_id"},
        {"headerName": "Sample Name", "field": "sample_name"},
        {"headerName": "Sample Mineral", "field": "mineral"},
        {"headerName": "Analysis ID", "field": "analysis_id"},
        {"headerName": "Grade(ppm)", "field": "grade"},
        {"headerName": "Method", "field": "analytical_method"},
    ]
    return AgGrid(
        id="bp-samples-grid",
        style=GRID_STYLE,
        columnDefs=column_defs,
        rowData=samples,
        columnSize="responsiveSizeToFit",
        defaultColDef=DEFAULT_COL_DEF,
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 20,
            "suppressFieldDotNotation": True,
            "enableCellTextSelection": True,
            "getRowId": {"function": "params.data.measurement_id"},
        },
    )


def _build_grade_summary(stats, deposit_name=None):
    commodity = api.element_name(stats["commodity"])
    # A site's name is optional in the API, so it can be missing.
    heading = f"{commodity} — {deposit_name}" if deposit_name else commodity

    if stats["count"] == 0:
        return html.Div(
            [
                html.H5(heading),
                dbc.Alert(
                    f"No numeric grade data available for {commodity} at this deposit.",
                    color="danger",
                ),
            ]
        )

    return html.Div(
        [
            html.H5(heading),
            dbc.Row(
                [
                    dbc.Col(stats_card("Min", round(stats["min"], 3)), width=3),
                    dbc.Col(stats_card("Max", round(stats["max"], 3)), width=3),
                    dbc.Col(stats_card("Avg", round(stats["avg"], 3)), width=3),
                    dbc.Col(stats_card("Median", round(stats["median"], 3)), width=3),
                ]
            ),
        ]
    )


@callback(
    Output("bp-commodity", "options"),
    Input("url-byproduct", "pathname"),
)
def bp_load_commodities(pathname):
    # Must degrade rather than raise: if this throws, the page renders
    # nothing at all, not even the layout.
    try:
        return api.get_commodities()
    except api.GeochemAPIError:
        logger.exception("Could not load GeoChem commodities")
        return []


@callback(
    Output("bp-country", "options"),
    Output("bp-papers-results", "children"),
    Output("bp-deposits-results", "children"),
    Output("bp-samples-results", "children"),
    Output("bp-summary-results", "children"),
    Output("bp-selected-deposit", "data", allow_duplicate=True),
    Input("bp-commodity", "value"),
    Input("bp-country", "value"),
    prevent_initial_call=True,
)
def bp_update_papers(commodity, country):
    if not commodity:
        return [], html.Div(), html.Div(), html.Div(), html.Div(), None

    # One try around both calls -- either failing means the same thing to
    # the user.
    try:
        country_options = api.get_countries(commodity)
        papers = api.get_papers(commodity, country)
    except api.GeochemAPIError as exc:
        logger.exception("Could not load GeoChem papers for %s", commodity)
        return [], _error_alert(exc), html.Div(), html.Div(), html.Div(), None

    papers_grid = _build_papers_grid(papers) if papers else _no_results_alert()

    # A new commodity/country selection invalidates the old paper-level
    # summary and deposit selection, same as Deposits and Samples.
    return country_options, papers_grid, html.Div(), html.Div(), html.Div(), None


@callback(
    Output("bp-deposits-results", "children", allow_duplicate=True),
    Output("bp-samples-results", "children", allow_duplicate=True),
    Output("bp-summary-results", "children", allow_duplicate=True),
    Output("bp-selected-deposit", "data", allow_duplicate=True),
    Input("bp-papers-grid", "selectedRows"),
    State("bp-commodity", "value"),
    prevent_initial_call=True,
)
def bp_update_deposits(selected_rows, commodity):
    if not selected_rows or not commodity:
        return html.Div(), html.Div(), html.Div(), None

    paper_id = selected_rows[0]["paper_id"]
    try:
        deposits = api.get_deposits(paper_id, commodity)
    except api.GeochemAPIError as exc:
        logger.exception("Could not load GeoChem deposits for %s", paper_id)
        return _error_alert(exc), html.Div(), html.Div(), None

    deposits_grid = _build_deposits_grid(deposits) if deposits else _no_results_alert()

    # The summary describes one deposit, and selecting a new paper leaves none
    # selected -- so it clears here and is filled by bp_update_samples.
    return deposits_grid, html.Div(), html.Div(), None


@callback(
    Output("bp-selected-deposit", "data"),
    Input("bp-deposits-grid", "selectedRows"),
    prevent_initial_call=True,
)
def bp_select_deposit(selected_rows):
    return selected_rows[0] if selected_rows else None


@callback(
    Output("bp-samples-results", "children", allow_duplicate=True),
    Output("bp-summary-results", "children", allow_duplicate=True),
    Input("bp-selected-deposit", "data"),
    Input("bp-include-bdl", "value"),
    State("bp-commodity", "value"),
    prevent_initial_call=True,
)
def bp_update_samples(deposit, include_bdl, commodity):
    if not deposit or not commodity:
        return html.Div(), html.Div()

    paper_id = deposit["paper_id"]
    site_id = deposit["site_id"]
    deposit_name = deposit.get("deposit_name")
    try:
        samples = api.get_samples(paper_id, site_id, commodity)
    except api.GeochemAPIError as exc:
        logger.exception("Could not load GeoChem samples for %s", site_id)
        return _error_alert(exc), html.Div()

    # Switch on: positive, below-detection (negative) and zero grades.
    # Switch off: detected (positive) grades only. Blanks never reach here.
    if not include_bdl:
        samples = api.detected_only(samples)

    samples_grid = _build_samples_grid(samples) if samples else _no_results_alert()
    # Derived from the rows just fetched, so the summary cannot disagree with
    # the grid below it.
    summary = _build_grade_summary(
        api.summarize_grades(samples, commodity), deposit_name
    )

    return samples_grid, summary
