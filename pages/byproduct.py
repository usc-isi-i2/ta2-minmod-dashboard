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
HIDDEN = {"display": "none"}

layout = html.Div(
    [
        dcc.Location(id="url-byproduct", refresh=True),
        # selections live in stores because the grids are not always in the layout
        dcc.Store(id="bp-selected-paper"),
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
                        dbc.Label("Deposit Type"),
                        dcc.Dropdown(
                            id="bp-deposit-type",
                            options=[],
                            multi=True,
                            placeholder="Search Deposit Type",
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
        # error when the commodity list can't load
        html.Div(id="bp-commodity-alert", className="mt-2"),
        # sections are hidden, not removed, so the BDL switch keeps its state
        html.Div(
            [
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
            ],
            id="bp-papers-section",
            style=HIDDEN,
        ),
        html.Div(
            [
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
            ],
            id="bp-deposits-section",
            style=HIDDEN,
        ),
        html.Div(
            [
                html.Br(),
                html.H5(
                    [
                        "Grade Summary ",
                        html.I(
                            id="bp-summary-info",
                            className="fas fa-info-circle text-muted",
                            style={"fontSize": "0.8em", "cursor": "help"},
                        ),
                    ]
                ),
                dbc.Tooltip(
                    "Grade summary is always calculated from readings above the "
                    "detection limit.",
                    target="bp-summary-info",
                    placement="right",
                ),
                dbc.Row(
                    dbc.Spinner(
                        html.Div(id="bp-summary-results"),
                        color="primary",
                        type="border",
                        size="lg",
                    )
                ),
                html.Br(),
                # outside the results div so it survives grid rebuilds
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
            id="bp-samples-section",
            style=HIDDEN,
        ),
    ],
    style={"margin": "20px"},
)


def no_results_alert():
    return dbc.Alert("No results found.", color="danger")


def error_alert(exc):
    """Query failed, as opposed to no results."""
    return dbc.Alert(
        [html.Strong("GeoChem data unavailable. "), str(exc)], color="danger"
    )


def element_names(symbols):
    return ", ".join(api.element_name(s) for s in symbols)


def is_group(commodity):
    return len(api.expand(commodity)) > 1


def build_papers_grid(papers, grouped=False):
    rows = []
    for p in papers:
        row = dict(p)
        row["doi_link"] = f"[{p['doi']}](https://doi.org/{p['doi']})" if p.get("doi") else None
        row["elements_text"] = element_names(p["elements"])
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
    # a group matches each paper on some of its elements
    if grouped:
        column_defs.append({"headerName": "Elements", "field": "elements_text"})
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


def build_deposits_grid(deposits, grouped=False):
    rows = [{**d, "elements_text": element_names(d["elements"])} for d in deposits]
    column_defs = [
        {"headerName": "Deposit Name", "field": "deposit_name"},
        {"headerName": "Country", "field": "country"},
        {"headerName": "State", "field": "state"},
        {"headerName": "Deposit Type", "field": "deposit_type"},
        {"headerName": "Confidence", "field": "deposit_type_confidence"},
        {"headerName": "Reported Deposit Type", "field": "reported_deposit_type"},
    ]
    if grouped:
        column_defs.append({"headerName": "Elements", "field": "elements_text"})
    return AgGrid(
        id="bp-deposits-grid",
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
            "getRowId": {"function": "params.data.site_id"},
        },
    )


def build_samples_grid(samples, grouped=False):
    # a shared unit goes in the header, otherwise a Unit column
    unit = api.common_unit(samples)
    has_units = any(s.get("grade_unit") for s in samples)
    grade_columns = [
        {"headerName": f"Grade ({unit})" if unit else "Grade", "field": "grade"}
    ]
    if has_units and not unit:
        grade_columns.append({"headerName": "Unit", "field": "grade_unit"})

    rows = [{**s, "element_name": api.element_name(s["element"])} for s in samples]
    element_columns = [{"headerName": "Element", "field": "element_name"}] if grouped else []
    column_defs = [
        {"headerName": "Sample ID", "field": "sample_id"},
        {"headerName": "Sample Name", "field": "sample_name"},
        {"headerName": "Sample Mineral", "field": "mineral"},
        {"headerName": "Analysis ID", "field": "analysis_id"},
        *element_columns,
        *grade_columns,
        {"headerName": "Method", "field": "analytical_method"},
    ]
    return AgGrid(
        id="bp-samples-grid",
        style=GRID_STYLE,
        columnDefs=column_defs,
        rowData=rows,
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


def build_grade_summary(stats, deposit_name=None, mixed_units=None):
    commodity = api.commodity_label(stats["commodity"])
    heading = f"{commodity} — {deposit_name}" if deposit_name else commodity

    if mixed_units:
        units = ", ".join(sorted(u or "unknown" for u in mixed_units))
        return html.Div(
            [
                html.H5(heading),
                dbc.Alert(
                    f"Grade units differ at this deposit ({units}); summary not calculated.",
                    color="warning",
                ),
            ]
        )

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


def build_group_summary(samples, commodity, deposit_name=None):
    """One summary row per element of the group."""
    heading = f"{commodity} — {deposit_name}" if deposit_name else commodity

    def fmt(value):
        return "—" if value is None else round(value, 3)

    body = []
    mixed = []
    for element in api.expand(commodity):
        element_samples = [s for s in samples if s["element"] == element]
        if not element_samples:
            continue
        units = {s.get("grade_unit") for s in api.detected_only(element_samples)}
        name = api.commodity_label(element)
        if len(units) > 1:
            mixed.append(f"{name}: {', '.join(sorted(u or 'unknown' for u in units))}")
            continue
        stats = api.summarize_grades(element_samples, element)
        body.append(
            html.Tr(
                [html.Td(name), html.Td(stats["count"])]
                + [html.Td(fmt(stats[k])) for k in ("min", "max", "avg", "median")]
            )
        )

    header = html.Thead(
        html.Tr([html.Th(h) for h in ("Element", "Count", "Min", "Max", "Avg", "Median")])
    )
    children = [html.H5(heading)]
    if not body and not mixed:
        children.append(
            dbc.Alert(
                f"No numeric grade data available for {commodity} at this deposit.",
                color="danger",
            )
        )
    if body:
        children.append(dbc.Table([header, html.Tbody(body)], bordered=True, size="sm"))
    if mixed:
        children.append(
            dbc.Alert(
                "Grade units differ at this deposit, so no summary for "
                + "; ".join(mixed) + ".",
                color="warning",
            )
        )
    return html.Div(children)


def section_style(visible):
    return {} if visible else HIDDEN


@callback(
    Output("bp-papers-section", "style"),
    Output("bp-deposits-section", "style"),
    Output("bp-samples-section", "style"),
    Input("bp-commodity", "value"),
    Input("bp-deposit-type", "value"),
    Input("bp-country", "value"),
    Input("bp-selected-paper", "data"),
    Input("bp-selected-deposit", "data"),
)
def bp_show_sections(commodity, deposit_types, country, paper, deposit):
    # hide sections below a changed selection right away; the data
    # callbacks clear the stores later
    trigger = dash.ctx.triggered_id
    if trigger in ("bp-commodity", "bp-deposit-type", "bp-country"):
        paper = deposit = None
    elif trigger == "bp-selected-paper":
        deposit = None
    return (
        section_style(commodity),
        section_style(commodity and paper),
        section_style(commodity and paper and deposit),
    )


@callback(
    Output("bp-commodity", "options"),
    Output("bp-commodity-alert", "children"),
    Input("url-byproduct", "pathname"),
)
def bp_load_commodities(pathname):
    # must not raise, or the whole page fails to render
    try:
        return api.get_commodities(), None
    except api.GeochemAPIError as exc:
        logger.exception("Could not load GeoChem commodities")
        return [], error_alert(exc)


@callback(
    Output("bp-deposit-type", "options"),
    Output("bp-deposit-type", "value"),
    Output("bp-country", "options"),
    Output("bp-country", "value"),
    Output("bp-papers-results", "children"),
    Output("bp-deposits-results", "children"),
    Output("bp-samples-results", "children"),
    Output("bp-summary-results", "children"),
    Output("bp-selected-paper", "data", allow_duplicate=True),
    Output("bp-selected-deposit", "data", allow_duplicate=True),
    Input("bp-commodity", "value"),
    Input("bp-deposit-type", "value"),
    Input("bp-country", "value"),
    prevent_initial_call=True,
)
def bp_update_papers(commodity, deposit_types, country):
    # a new commodity starts unfiltered and rebuilds both filter lists;
    # a deposit type change narrows the country list, like the Mineral Site tab
    trigger = dash.ctx.triggered_id
    new_commodity = trigger == "bp-commodity"
    if new_commodity:
        deposit_types, country = None, None
    deposit_types = tuple(deposit_types or ())
    reset = None if new_commodity else dash.no_update
    empty = (html.Div(), html.Div(), html.Div(), None, None)

    if not commodity:
        return [], reset, [], reset, html.Div(), *empty

    try:
        papers = api.get_papers(commodity, country, deposit_types)
    except api.GeochemAPIError as exc:
        logger.exception("Could not load GeoChem papers for %s", commodity)
        options = [] if new_commodity else dash.no_update
        return options, reset, options, reset, error_alert(exc), *empty

    # options come from the commodity's unfiltered papers; failing them must
    # not hide the papers
    children = []
    type_options = country_options = dash.no_update
    if trigger in ("bp-commodity", "bp-deposit-type"):
        try:
            all_papers = papers if new_commodity else api.get_papers(commodity)
            types, countries = api.get_filter_options(all_papers, deposit_types)
            country_options = countries
            if new_commodity:
                type_options = types
        except api.GeochemAPIError as exc:
            logger.exception("Could not load GeoChem filters for %s", commodity)
            country_options = []
            if new_commodity:
                type_options = []
            children.append(
                dbc.Alert([html.Strong("Filters unavailable. "), str(exc)], color="warning")
            )
    children.append(
        build_papers_grid(papers, is_group(commodity)) if papers else no_results_alert()
    )
    return (
        type_options, reset, country_options, reset, html.Div(children), *empty
    )


@callback(
    Output("bp-deposits-results", "children", allow_duplicate=True),
    Output("bp-samples-results", "children", allow_duplicate=True),
    Output("bp-summary-results", "children", allow_duplicate=True),
    Output("bp-selected-deposit", "data", allow_duplicate=True),
    Input("bp-selected-paper", "data"),
    State("bp-commodity", "value"),
    State("bp-deposit-type", "value"),
    prevent_initial_call=True,
)
def bp_update_deposits(paper, commodity, deposit_types):
    if not paper or not commodity:
        return html.Div(), html.Div(), html.Div(), None

    paper_id = paper["paper_id"]
    try:
        deposits = api.get_deposits(paper_id, paper["elements"], tuple(deposit_types or ()))
    except api.GeochemAPIError as exc:
        logger.exception("Could not load GeoChem deposits for %s", paper_id)
        return error_alert(exc), html.Div(), html.Div(), None

    deposits_grid = (
        build_deposits_grid(deposits, is_group(commodity)) if deposits else no_results_alert()
    )

    # no deposit is selected yet, so the summary is cleared
    return deposits_grid, html.Div(), html.Div(), None


@callback(
    Output("bp-selected-paper", "data"),
    Input("bp-papers-grid", "selectedRows"),
    prevent_initial_call=True,
)
def bp_select_paper(selected_rows):
    return selected_rows[0] if selected_rows else None


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
        samples = api.get_samples(paper_id, site_id, tuple(deposit["elements"]))
    except api.GeochemAPIError as exc:
        logger.exception("Could not load GeoChem samples for %s", site_id)
        return error_alert(exc), html.Div()

    # off: detected (positive) grades only
    if not include_bdl:
        samples = api.detected_only(samples)

    grouped = is_group(commodity)
    samples_grid = build_samples_grid(samples, grouped) if samples else no_results_alert()
    if grouped:
        return samples_grid, build_group_summary(samples, commodity, deposit_name)
    detected_units = {s.get("grade_unit") for s in api.detected_only(samples)}
    summary = build_grade_summary(
        api.summarize_grades(samples, commodity),
        deposit_name,
        mixed_units=detected_units if len(detected_units) > 1 else None,
    )

    return samples_grid, summary
