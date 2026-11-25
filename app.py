from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.data_processing import (
    exportable_inventory,
    exportable_sales,
    filter_sales,
    load_datasets,
    product_performance,
    catalog_reconciliation,
    compare_equal_periods,
    validation_summary,
)
from utils.reports import build_pdf_report


st.set_page_config(
    page_title="Product Sales Dashboard",
    page_icon=":material/monitoring:",
    layout="wide",
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"


@st.cache_data(show_spinner="Loading sales and inventory data...")
def load_dashboard_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_datasets(DATA_DIR)


def find_optional_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    columns_by_lower = {str(column).casefold(): str(column) for column in frame.columns}
    for candidate in candidates:
        if candidate.casefold() in columns_by_lower:
            return columns_by_lower[candidate.casefold()]
    return None


def currency(value: float) -> str:
    return f"PHP {value:,.2f}"


def style_figure(figure: go.Figure) -> go.Figure:
    figure.update_layout(
        template="plotly_white",
        margin={"l": 12, "r": 12, "t": 58, "b": 12},
        legend_title_text="",
    )
    return figure


def show_figure(figure: go.Figure, alt: str) -> None:
    st.plotly_chart(style_figure(figure), width="stretch", alt=alt)


def sales_summaries(sales: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if sales.empty:
        empty = pd.DataFrame()
        return empty, empty, empty

    monthly = (
        sales.assign(Month=sales["Transaction_Date"].dt.to_period("M").astype(str))
        .groupby("Month", as_index=False)
        .agg(
            Revenue_PHP=("Revenue_PHP", "sum"),
            Orders=("Transaction_ID", "nunique"),
            Units_Sold=("Quantity_Sold", "sum"),
        )
        .sort_values("Month", ignore_index=True)
    )
    categories = (
        sales.groupby("Category", as_index=False)
        .agg(
            Revenue_PHP=("Revenue_PHP", "sum"),
            Units_Sold=("Quantity_Sold", "sum"),
            Orders=("Transaction_ID", "nunique"),
        )
        .sort_values("Revenue_PHP", ascending=False, ignore_index=True)
    )
    daily = (
        sales.assign(Date=sales["Transaction_Date"].dt.date)
        .groupby("Date", as_index=False)
        .agg(
            Revenue_PHP=("Revenue_PHP", "sum"),
            Orders=("Transaction_ID", "nunique"),
        )
        .sort_values("Date", ignore_index=True)
    )
    return monthly, categories, daily


def make_insights(
    sales: pd.DataFrame,
    products: pd.DataFrame,
    categories: pd.DataFrame,
    monthly: pd.DataFrame,
    start_date: Any,
    end_date: Any,
) -> tuple[list[str], pd.DataFrame | None, str | None, str | None]:
    if sales.empty:
        return (
            ["No valid sales records match the selected filters; no sales-based recommendation can be calculated."],
            None,
            None,
            None,
        )

    insights: list[str] = []
    if not monthly.empty:
        best_month = monthly.loc[monthly["Revenue_PHP"].idxmax()]
        insights.append(
            f"{best_month['Month']} had the highest revenue in the selected data "
            f"({currency(float(best_month['Revenue_PHP']))})."
        )
    if not products.empty:
        best_quantity = products.sort_values(
            ["Units_Sold", "Product_Name"], ascending=[False, True]
        ).iloc[0]
        best_revenue = products.sort_values(
            ["Revenue_PHP", "Product_Name"], ascending=[False, True]
        ).iloc[0]
        lowest_revenue = products.sort_values(
            ["Revenue_PHP", "Product_Name"], ascending=[True, True]
        ).iloc[0]
        revenue_total = float(sales["Revenue_PHP"].sum())
        share = (
            float(best_revenue["Revenue_PHP"]) / revenue_total * 100
            if revenue_total
            else 0.0
        )
        insights.append(
            f"{best_quantity['Product_Name']} sold the most units "
            f"({best_quantity['Units_Sold']:,.0f})."
        )
        insights.append(
            f"{best_revenue['Product_Name']} led revenue at "
            f"{currency(float(best_revenue['Revenue_PHP']))} "
            f"({share:.1f}% of selected revenue); prioritize it when reviewing "
            "promotion and replenishment plans."
        )
        insights.append(
            f"{lowest_revenue['Product_Name']} had the lowest recorded product revenue "
            f"({currency(float(lowest_revenue['Revenue_PHP']))}); review its demand "
            "and assortment before changing stock or pricing."
        )
    if not categories.empty:
        top_category = categories.iloc[0]
        insights.append(
            f"{top_category['Category']} was the leading category by revenue "
            f"({currency(float(top_category['Revenue_PHP']))}); use this as a "
            "starting point for category-level inventory planning."
        )

    period_result = compare_equal_periods(sales, start_date, end_date)
    previous_label: str | None = None
    current_label: str | None = None
    if period_result is not None:
        comparison, previous_label, current_label = period_result
        period_days = ((end_date - start_date).days + 1) // 2
        current_start = end_date - timedelta(days=period_days - 1)
        previous_end = current_start - timedelta(days=1)
        previous_sales = sales.loc[
            sales["Transaction_Date"].dt.date.between(
                previous_end - timedelta(days=period_days - 1), previous_end
            )
        ]
        current_sales = sales.loc[
            sales["Transaction_Date"].dt.date.between(current_start, end_date)
        ]
        previous_revenue = float(previous_sales["Revenue_PHP"].sum())
        current_revenue = float(current_sales["Revenue_PHP"].sum())
        if previous_revenue:
            change = (current_revenue - previous_revenue) / previous_revenue * 100
            direction = "increased" if change > 0 else "declined" if change < 0 else "was unchanged"
            insights.append(
                f"Revenue {direction} by {abs(change):.1f}% from the previous "
                f"{period_days}-day period to the latest equal-length period "
                f"({currency(previous_revenue)} to {currency(current_revenue)})."
            )
            previous_orders = int(previous_sales["Transaction_ID"].nunique())
            current_orders = int(current_sales["Transaction_ID"].nunique())
            previous_aov = previous_revenue / previous_orders if previous_orders else 0
            current_aov = current_revenue / current_orders if current_orders else 0
            if previous_aov:
                aov_change = (current_aov - previous_aov) / previous_aov * 100
                aov_direction = (
                    "increased"
                    if aov_change > 0
                    else "declined"
                    if aov_change < 0
                    else "was unchanged"
                )
                insights.append(
                    f"Average order value {aov_direction} by {abs(aov_change):.1f}% "
                    f"between those periods."
                )
        increasing = comparison.loc[comparison["Trend"].eq("Increasing")]
        declining = comparison.loc[comparison["Trend"].eq("Declining")]
        if not increasing.empty:
            names = ", ".join(increasing["Product_Name"].head(3).tolist())
            insights.append(
                f"Units sold increased in the latest equal-length period for: {names}."
            )
        if not declining.empty:
            names = ", ".join(declining["Product_Name"].head(3).tolist())
            insights.append(
                f"Units sold declined in the latest equal-length period for: {names}; "
                "check whether the change is seasonal or requires follow-up."
            )
    else:
        insights.append(
            "The selected date range is too short to compare two equal-length periods."
        )
    return insights, period_result[0] if period_result else None, previous_label, current_label


try:
    sales, inventory = load_dashboard_data()
except (FileNotFoundError, pd.errors.EmptyDataError, pd.errors.ParserError, ValueError) as error:
    st.title("Product Sales Dashboard")
    st.error(f"Unable to load the project datasets: {error}", icon=":material/error:")
    st.stop()

valid_sales = sales.loc[sales["_is_valid_record"]].copy()
valid_inventory = inventory.loc[inventory["_is_valid_record"]].copy()
if valid_sales.empty:
    st.title("Product Sales Dashboard")
    st.error("No valid sales records are available for analysis. Review System Information and the source CSV.")
    st.stop()

minimum_date = valid_sales["Transaction_Date"].min().date()
maximum_date = valid_sales["Transaction_Date"].max().date()
product_options = sorted(valid_sales["Product_Name"].dropna().astype(str).unique())
category_options = sorted(valid_sales["Category"].dropna().astype(str).unique())
payment_options = sorted(valid_sales["Payment_Method"].dropna().astype(str).unique())
region_column = find_optional_column(sales, ("Sales_Region", "Region"))
status_column = find_optional_column(sales, ("Order_Status", "Status"))
region_options = (
    sorted(valid_sales[region_column].dropna().astype(str).unique())
    if region_column
    else []
)
status_options = (
    sorted(valid_sales[status_column].dropna().astype(str).unique())
    if status_column
    else []
)
filter_defaults: dict[str, Any] = {
    "filter_date_range": (minimum_date, maximum_date),
    "filter_products": product_options,
    "filter_categories": category_options,
    "filter_payments": payment_options,
}
if region_column:
    filter_defaults["filter_regions"] = region_options
if status_column:
    filter_defaults["filter_statuses"] = status_options
for filter_key, default_value in filter_defaults.items():
    if filter_key not in st.session_state:
        st.session_state[filter_key] = default_value

st.title("Product sales dashboard")
st.caption("Sales performance, product demand, and inventory signals from the supplied project data.")

with st.sidebar:
    st.header("Navigation")
    page = st.radio(
        "Dashboard section",
        [
            "Dashboard Overview",
            "Product Management",
            "Sales Records",
            "Sales Analytics",
            "Product Performance",
            "Reports and Downloads",
            "System Information",
        ],
        label_visibility="collapsed",
        key="navigation_section",
    )
    st.divider()
    st.subheader("Global filters")
    if st.button(
        "Reset filters",
        icon=":material/filter_alt_off:",
        width="stretch",
        key="reset_filters",
    ):
        st.session_state["filter_date_range"] = (minimum_date, maximum_date)
        st.session_state["filter_products"] = product_options
        st.session_state["filter_categories"] = category_options
        st.session_state["filter_payments"] = payment_options
        if region_column:
            st.session_state["filter_regions"] = region_options
        if status_column:
            st.session_state["filter_statuses"] = status_options
        st.rerun()

    selected_date_range = st.date_input(
        "Date range",
        min_value=minimum_date,
        max_value=maximum_date,
        key="filter_date_range",
    )
    if isinstance(selected_date_range, (tuple, list)):
        if len(selected_date_range) == 2:
            start_date, end_date = selected_date_range
        elif len(selected_date_range) == 1:
            start_date = end_date = selected_date_range[0]
        else:
            start_date, end_date = minimum_date, maximum_date
    else:
        start_date = end_date = selected_date_range
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    selected_products = st.multiselect(
        "Product name",
        product_options,
        key="filter_products",
    )
    selected_categories = st.multiselect(
        "Product category",
        category_options,
        key="filter_categories",
    )
    selected_payments = st.multiselect(
        "Payment method",
        payment_options,
        key="filter_payments",
    )
    selected_regions: list[str] | None = None
    selected_statuses: list[str] | None = None
    if region_column:
        selected_regions = st.multiselect(
            "Sales region",
            region_options,
            key="filter_regions",
        )
    else:
        st.caption("Sales region filter unavailable: no region field in the dataset.")
    if status_column:
        selected_statuses = st.multiselect(
            "Order status",
            status_options,
            key="filter_statuses",
        )
    else:
        st.caption("Order status filter unavailable: no status field in the dataset.")
    st.divider()
    st.caption("Project 3 · Product Sales")

filtered_sales = filter_sales(
    sales,
    start_date,
    end_date,
    selected_products,
    selected_categories,
    selected_payments,
    region_column=region_column,
    regions=selected_regions,
    status_column=status_column,
    statuses=selected_statuses,
)
filtered_inventory = inventory.loc[inventory["_is_valid_record"]].copy()
monthly_summary, category_summary, daily_summary = sales_summaries(filtered_sales)
product_summary = product_performance(filtered_sales)
insights, trend_summary, previous_period_label, current_period_label = make_insights(
    filtered_sales,
    product_summary,
    category_summary,
    monthly_summary,
    start_date,
    end_date,
)

if filtered_sales.empty:
    st.warning("No valid sales records match the selected filters.")
else:
    st.caption(
        f"Showing {len(filtered_sales):,} transaction records from "
        f"{start_date:%b %d, %Y} to {end_date:%b %d, %Y}."
    )


if page == "Dashboard Overview":
    st.header("Business performance overview")

    if filtered_sales.empty:
        st.info("Adjust the global filters to view dashboard metrics.")
    else:
        total_revenue = float(filtered_sales["Revenue_PHP"].sum())
        total_orders = int(filtered_sales["Transaction_ID"].nunique())
        total_units = float(filtered_sales["Quantity_Sold"].sum())
        average_order_value = total_revenue / total_orders if total_orders else 0.0
        average_selling_price = total_revenue / total_units if total_units else 0.0
        top_quantity = product_summary.sort_values(
            ["Units_Sold", "Product_Name"], ascending=[False, True]
        ).iloc[0]
        top_revenue = product_summary.sort_values(
            ["Revenue_PHP", "Product_Name"], ascending=[False, True]
        ).iloc[0]
        low_revenue = product_summary.sort_values(
            ["Revenue_PHP", "Product_Name"], ascending=[True, True]
        ).iloc[0]
        metric_columns = st.columns(4)
        metric_columns[0].metric("Total sales revenue", currency(total_revenue), border=True)
        metric_columns[1].metric("Total orders", f"{total_orders:,}", border=True)
        metric_columns[2].metric("Products sold", f"{total_units:,.0f} units", border=True)
        metric_columns[3].metric(
            "Products in inventory",
            f"{len(valid_inventory):,}",
            border=True,
        )

        metric_columns = st.columns(4)
        metric_columns[0].metric(
            "Average order value", currency(average_order_value), border=True
        )
        metric_columns[1].metric(
            "Average selling price", currency(average_selling_price), border=True
        )
        metric_columns[2].metric(
            "Best-selling product",
            str(top_quantity["Product_Name"]),
            f"{top_quantity['Units_Sold']:,.0f} units",
            border=True,
        )
        metric_columns[3].metric(
            "Highest revenue product",
            str(top_revenue["Product_Name"]),
            currency(float(top_revenue["Revenue_PHP"])),
            border=True,
        )

        metric_columns = st.columns(3)
        metric_columns[0].metric(
            "Lowest revenue product",
            str(low_revenue["Product_Name"]),
            currency(float(low_revenue["Revenue_PHP"])),
            border=True,
        )
        metric_columns[1].metric(
            "Products with sales",
            f"{product_summary['Product_ID'].nunique():,}",
            border=True,
        )
        metric_columns[2].metric(
            "Inventory items to reorder",
            f"{int(filtered_inventory['Stock_Status'].eq('Reorder').sum()):,}",
            border=True,
        )

        st.info(
            "Profit and profit margin are not shown because neither dataset contains "
            "a cost-price or total-cost field."
        )
        st.subheader("Sales at a glance")
        chart_columns = st.columns(2)
        with chart_columns[0]:
            if not monthly_summary.empty:
                figure = px.line(
                    monthly_summary,
                    x="Month",
                    y="Revenue_PHP",
                    markers=True,
                    title="Monthly sales revenue",
                    labels={"Month": "Month", "Revenue_PHP": "Revenue (PHP)"},
                    hover_data={"Revenue_PHP": ":,.2f"},
                )
                show_figure(figure, "Monthly recorded sales revenue")
        with chart_columns[1]:
            if not product_summary.empty:
                best_products = product_summary.sort_values(
                    "Revenue_PHP", ascending=True
                ).tail(10)
                figure = px.bar(
                    best_products,
                    x="Revenue_PHP",
                    y="Product_Name",
                    orientation="h",
                    title="Top products by revenue",
                    labels={"Product_Name": "Product", "Revenue_PHP": "Revenue (PHP)"},
                    hover_data={"Product_ID": True, "Revenue_PHP": ":,.2f"},
                )
                show_figure(figure, "Top product revenue, highest at the top")

        st.subheader("Sales insights")
        for insight in insights:
            st.markdown(f"- {insight}")

elif page == "Product Management":
    st.header("Product management")
    st.caption("Product records are read from the separate inventory snapshot.")

    inventory_search = st.text_input(
        "Search products by name or ID",
        type="search",
        placeholder="Enter a product name or ID",
        key="inventory_search",
    )
    inventory_categories = sorted(
        filtered_inventory["Category"].dropna().astype(str).unique()
    )
    selected_inventory_categories = st.multiselect(
        "Filter inventory by category",
        inventory_categories,
        default=inventory_categories,
        key="inventory_categories",
    )
    shown_inventory = filtered_inventory.loc[
        filtered_inventory["Category"].astype(str).isin(selected_inventory_categories)
    ].copy()
    if inventory_search.strip():
        term = inventory_search.strip()
        matches = shown_inventory["Product_ID"].astype(str).str.contains(
            term, case=False, regex=False, na=False
        ) | shown_inventory["Product_Name"].astype(str).str.contains(
            term, case=False, regex=False, na=False
        )
        shown_inventory = shown_inventory.loc[matches]

    inventory_export = exportable_inventory(shown_inventory)
    st.dataframe(
        inventory_export,
        hide_index=True,
        alt="Inventory product records with current stock and supplier details",
    )
    st.download_button(
        "Download product records",
        inventory_export.to_csv(index=False).encode("utf-8"),
        "product_records.csv",
        "text/csv",
        icon=":material/download:",
    )

    if not shown_inventory.empty:
        product_labels = {
            f"{row.Product_ID} — {row.Product_Name}": row.Product_ID
            for row in shown_inventory.itertuples(index=False)
        }
        selected_product_label = st.selectbox(
            "View product information",
            options=list(product_labels),
            index=None,
            placeholder="Choose a product",
            key="inventory_detail",
        )
        if selected_product_label:
            selected_product = shown_inventory.loc[
                shown_inventory["Product_ID"].astype(str)
                == product_labels[selected_product_label]
            ]
            st.dataframe(
                exportable_inventory(selected_product),
                hide_index=True,
                alt="Selected inventory product details",
            )

    st.info(
        "Adding, editing, and deleting products are not enabled: this project reads "
        "a CSV snapshot and has no persistent product CRUD/database layer."
    )
    st.warning(
        "The inventory CSV is independent of the sales transaction file. Product IDs "
        "and names conflict in several records, so inventory is not treated as an "
        "authoritative sales product catalog."
    )

elif page == "Sales Records":
    st.header("Sales records")
    transaction_search = st.text_input(
        "Search by order ID or product",
        type="search",
        placeholder="Enter a transaction ID, product name, or product ID",
        key="transaction_search",
    )
    shown_sales = filtered_sales.copy()
    if transaction_search.strip():
        term = transaction_search.strip()
        matches = (
            shown_sales["Transaction_ID"].astype(str).str.contains(
                term, case=False, regex=False, na=False
            )
            | shown_sales["Product_Name"].astype(str).str.contains(
                term, case=False, regex=False, na=False
            )
            | shown_sales["Product_ID"].astype(str).str.contains(
                term, case=False, regex=False, na=False
            )
        )
        shown_sales = shown_sales.loc[matches]

    sales_export = exportable_sales(shown_sales)
    st.dataframe(
        sales_export,
        hide_index=True,
        alt="Filtered sales transaction records",
    )
    st.download_button(
        "Download filtered sales records",
        sales_export.to_csv(index=False).encode("utf-8"),
        "filtered_sales_records.csv",
        "text/csv",
        icon=":material/download:",
    )
    if not shown_sales.empty:
        transaction_labels = {
            f"{row.Transaction_ID} — {row.Product_Name}": row.Transaction_ID
            for row in shown_sales.itertuples(index=False)
        }
        selected_transaction = st.selectbox(
            "View transaction details",
            options=list(transaction_labels),
            index=None,
            placeholder="Choose a transaction",
            key="transaction_detail",
        )
        if selected_transaction:
            selected_id = transaction_labels[selected_transaction]
            details = shown_sales.loc[
                shown_sales["Transaction_ID"].astype(str).eq(str(selected_id))
            ]
            st.dataframe(
                exportable_sales(details),
                hide_index=True,
                alt="Selected transaction details",
            )
    st.caption(
        "Sales records are read-only. This CSV-backed project does not support "
        "persistent transaction edits."
    )

elif page == "Sales Analytics":
    st.header("Sales analytics")
    if filtered_sales.empty:
        st.info("No charts can be calculated until the filters include valid sales records.")
    else:
        units_by_product = (
            product_summary.sort_values("Units_Sold", ascending=True).tail(10)
        )
        revenue_by_product = (
            product_summary.sort_values("Revenue_PHP", ascending=True).tail(10)
        )
        category_chart = category_summary.sort_values("Revenue_PHP", ascending=False)

        chart_columns = st.columns(2)
        with chart_columns[0]:
            figure = px.line(
                monthly_summary,
                x="Month",
                y="Revenue_PHP",
                markers=True,
                title="Monthly sales revenue",
                labels={"Month": "Month", "Revenue_PHP": "Revenue (PHP)"},
                hover_data={"Revenue_PHP": ":,.2f"},
            )
            show_figure(figure, "Monthly sales revenue")
        with chart_columns[1]:
            figure = px.line(
                daily_summary,
                x="Date",
                y="Revenue_PHP",
                markers=True,
                title="Daily sales trends",
                labels={"Date": "Order date", "Revenue_PHP": "Revenue (PHP)"},
                hover_data={"Revenue_PHP": ":,.2f", "Orders": True},
            )
            show_figure(figure, "Daily recorded sales revenue")

        chart_columns = st.columns(2)
        with chart_columns[0]:
            figure = px.bar(
                units_by_product,
                x="Units_Sold",
                y="Product_Name",
                orientation="h",
                title="Top 10 best-selling products",
                labels={"Product_Name": "Product", "Units_Sold": "Units sold"},
                hover_data={"Product_ID": True, "Revenue_PHP": ":,.2f"},
            )
            show_figure(figure, "Top products ranked by recorded quantity sold")
        with chart_columns[1]:
            figure = px.bar(
                category_chart,
                x="Category",
                y="Revenue_PHP",
                color="Category",
                title="Revenue by product category",
                labels={"Category": "Category", "Revenue_PHP": "Revenue (PHP)"},
                hover_data={"Units_Sold": True, "Orders": True},
            )
            show_figure(figure, "Recorded revenue by product category")

        chart_columns = st.columns(2)
        with chart_columns[0]:
            figure = px.bar(
                units_by_product,
                x="Product_Name",
                y="Units_Sold",
                color="Category",
                title="Quantity sold by product",
                labels={"Product_Name": "Product", "Units_Sold": "Units sold"},
                hover_data={"Product_ID": True},
            )
            figure.update_xaxes(tickangle=-35)
            show_figure(figure, "Quantity sold by product")
        with chart_columns[1]:
            figure = px.bar(
                revenue_by_product,
                x="Product_Name",
                y="Revenue_PHP",
                color="Category",
                title="Revenue comparison by product",
                labels={"Product_Name": "Product", "Revenue_PHP": "Revenue (PHP)"},
                hover_data={"Product_ID": True, "Units_Sold": True},
            )
            figure.update_xaxes(tickangle=-35)
            show_figure(figure, "Revenue comparison across the top ten products")

        chart_columns = st.columns(2)
        with chart_columns[0]:
            if not daily_summary.empty:
                trend = daily_summary.copy()
                trend["Revenue_7_Day_Average_PHP"] = (
                    trend["Revenue_PHP"].rolling(7, min_periods=1).mean()
                )
                figure = px.line(
                    trend,
                    x="Date",
                    y=["Revenue_PHP", "Revenue_7_Day_Average_PHP"],
                    title="Sales performance over time",
                    labels={
                        "Date": "Order date",
                        "value": "Revenue (PHP)",
                        "variable": "Measure",
                    },
                )
                show_figure(figure, "Daily revenue and seven-day average")
        with chart_columns[1]:
            payment_orders = (
                filtered_sales.groupby("Payment_Method", as_index=False)
                .agg(Orders=("Transaction_ID", "nunique"))
                .sort_values("Orders", ascending=False)
            )
            figure = px.pie(
                payment_orders,
                names="Payment_Method",
                values="Orders",
                hole=0.45,
                title="Order distribution by payment method",
                labels={"Payment_Method": "Payment method", "Orders": "Orders"},
            )
            show_figure(figure, "Share of recorded orders by payment method")

        if region_column:
            regional = (
                filtered_sales.groupby(region_column, as_index=False)
                .agg(Revenue_PHP=("Revenue_PHP", "sum"))
                .sort_values("Revenue_PHP", ascending=False)
            )
            figure = px.bar(
                regional,
                x=region_column,
                y="Revenue_PHP",
                title="Sales by region",
                labels={region_column: "Region", "Revenue_PHP": "Revenue (PHP)"},
            )
            show_figure(figure, "Recorded sales revenue by region")
        else:
            st.info("Sales by region is unavailable because the sales dataset has no region field.")

        cost_column = find_optional_column(
            sales, ("Unit_Cost_PHP", "Cost_Price_PHP", "Total_Cost_PHP")
        )
        if cost_column:
            st.info(
                f"Cost data field {cost_column!r} exists, but profit calculations require "
                "validated numeric cost values. Review System Information before using profit metrics."
            )
        else:
            st.info("Profit analysis is unavailable because the supplied data has no cost field.")

        st.subheader("Product sales summary")
        st.dataframe(
            product_summary.round(2),
            hide_index=True,
            alt="Product quantity, revenue, orders, and average selling price",
        )

elif page == "Product Performance":
    st.header("Product performance")
    if filtered_sales.empty:
        st.info("No product performance can be calculated for the selected filters.")
    else:
        st.subheader("Performance by product")
        st.dataframe(
            product_summary.round(2),
            hide_index=True,
            alt="Product performance ranked by recorded revenue",
        )
        st.download_button(
            "Download product performance CSV",
            product_summary.to_csv(index=False).encode("utf-8"),
            "product_performance.csv",
            "text/csv",
            icon=":material/download:",
        )

        st.subheader("Products increasing or declining")
        if trend_summary is None:
            st.info("Choose at least two days to compare equal-length sales periods.")
        else:
            st.caption(
                f"Quantity comparison: {previous_period_label} vs "
                f"{current_period_label}. These are the latest two equal-length "
                "periods within the selected date range."
            )
            st.dataframe(
                trend_summary,
                hide_index=True,
                alt="Product unit sales change across two equal-length date periods",
            )

        st.subheader("Inventory-to-sales catalog reconciliation")
        reconciliation = catalog_reconciliation(inventory, valid_sales)
        st.dataframe(
            reconciliation,
            hide_index=True,
            alt="Inventory products matched against sales IDs and names",
        )
        unmatched = reconciliation.loc[
            reconciliation["Catalog_Match_Status"].eq("No sales record")
        ]
        if not unmatched.empty:
            st.info(
                f"{len(unmatched)} inventory product(s) have no matching sales record "
                "by product ID."
            )
        conflicts = reconciliation.loc[
            reconciliation["Catalog_Match_Status"].eq("ID conflict")
        ]
        if not conflicts.empty:
            st.warning(
                f"{len(conflicts)} inventory product ID(s) are linked to a different "
                "product name in sales; these cannot safely be classified as unsold."
            )
        category_conflicts = reconciliation.loc[
            reconciliation["Catalog_Match_Status"].eq("Category conflict")
        ]
        if not category_conflicts.empty:
            st.warning(
                f"{len(category_conflicts)} inventory product(s) match sales by ID "
                "and name but have a different category."
            )

        st.subheader("Business insights and recommendations")
        for insight in insights:
            st.markdown(f"- {insight}")

        st.info(
            "Profitability cannot be ranked because the source files do not contain "
            "cost data. Inventory products with conflicting IDs are shown as catalog "
            "conflicts, not as confirmed zero-sales products."
        )

elif page == "Reports and Downloads":
    st.header("Reports and downloads")
    st.write(
        "Downloads use the current dashboard filters. Revenue is taken from the "
        "recorded Total_Sales_PHP values."
    )

    sales_export = exportable_sales(filtered_sales)
    inventory_export = exportable_inventory(filtered_inventory)
    st.download_button(
        "Download filtered sales records",
        sales_export.to_csv(index=False).encode("utf-8"),
        "filtered_sales_records.csv",
        "text/csv",
        icon=":material/download:",
    )
    st.download_button(
        "Download product records",
        inventory_export.to_csv(index=False).encode("utf-8"),
        "product_records.csv",
        "text/csv",
        icon=":material/download:",
    )
    st.download_button(
        "Download product performance summary",
        product_summary.to_csv(index=False).encode("utf-8"),
        "product_performance.csv",
        "text/csv",
        icon=":material/download:",
    )

    pdf_report = build_pdf_report(
        filtered_sales,
        product_summary,
        category_summary,
        monthly_summary,
        insights,
    )
    st.download_button(
        "Download PDF sales report",
        pdf_report,
        "product_sales_dashboard_report.pdf",
        "application/pdf",
        icon=":material/picture_as_pdf:",
        width="stretch",
    )
    st.subheader("Included in the PDF")
    st.markdown(
        "- Report generation date and filtered sales KPIs\n"
        "- Best-selling products, category revenue, and monthly sales\n"
        "- Calculated insights and data-based recommendations"
    )
    if filtered_sales.empty:
        st.warning(
            "The PDF can still be downloaded, but no valid sales records match the filters."
        )

elif page == "System Information":
    st.header("System information")
    st.subheader("Data sources")
    st.markdown(
        f"- Sales records: `data/sales_transactions.csv` ({len(sales):,} rows)\n"
        f"- Inventory snapshot: `data/inventory.csv` ({len(inventory):,} rows)\n"
        "- Paths are resolved relative to this application file."
    )
    st.subheader("Available sales fields")
    st.write(", ".join(str(column) for column in exportable_sales(sales).columns))
    st.subheader("Available inventory fields")
    st.write(", ".join(str(column) for column in exportable_inventory(inventory).columns))

    quality = validation_summary(sales, inventory)
    st.subheader("Data validation")
    st.dataframe(
        pd.DataFrame(
            [
                {"Check": "Sales records", "Result": quality["sales_rows"]},
                {"Check": "Valid sales records", "Result": quality["valid_sales_rows"]},
                {"Check": "Invalid sales records", "Result": quality["invalid_sales_rows"]},
                {"Check": "Exact duplicate sales rows", "Result": quality["duplicate_sales_rows"]},
                {
                    "Check": "Revenue/quantity-price mismatches (tolerance PHP 0.01)",
                    "Result": quality["sales_amount_mismatches"],
                },
                {"Check": "Inventory records", "Result": quality["inventory_rows"]},
                {
                    "Check": "Invalid inventory records",
                    "Result": quality["invalid_inventory_rows"],
                },
                {
                    "Check": "Exact duplicate inventory rows",
                    "Result": quality["duplicate_inventory_rows"],
                },
            ]
        ),
        hide_index=True,
        alt="Dataset row counts and validation results",
    )
    if quality["invalid_sales_rows"] or quality["invalid_inventory_rows"]:
        st.warning(
            "Invalid source rows are retained and listed in the data files, but excluded "
            "from analytical calculations. Missing values are not replaced with estimates."
        )
    if quality["duplicate_sales_rows"] or quality["duplicate_inventory_rows"]:
        st.warning(
            "Exact duplicate rows were detected. They are reported, not silently deleted."
        )
    if quality["sales_amount_mismatches"]:
        st.warning(
            "Some recorded totals differ from quantity multiplied by unit price. "
            "Dashboard revenue uses the supplied Total_Sales_PHP values and flags the difference."
        )
    else:
        st.success(
            "All supplied sales rows have valid required fields, and recorded totals "
            "agree with quantity multiplied by unit price within PHP 0.01."
        )

    st.subheader("Known dataset limitations")
    st.markdown(
        "- No unit cost or total cost field exists; profit and profit margin are unavailable.\n"
        "- No region, customer, or order-status field exists; related filters and analyses are unavailable.\n"
        "- Inventory is a separate stock snapshot and is not reduced by sales transactions.\n"
        "- Inventory IDs P001, P002, P004, and P005 map to different sales product names. "
        "P003 matches by ID and name but has a different category; catalog matches compare ID, name, and category.\n"
        "- Product and sales records are read-only because the project has no persistent database or CRUD layer."
    )

st.divider()
st.caption(
    "Product Sales Dashboard · Revenue is based on recorded transaction totals; "
    "inventory remains an independent snapshot."
)
