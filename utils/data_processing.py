from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

SALES_REQUIRED_COLUMNS = (
    "Transaction_ID",
    "Transaction_Date",
    "Product_ID",
    "Product_Name",
    "Category",
    "Quantity_Sold",
    "Unit_Price_PHP",
    "Total_Sales_PHP",
    "Payment_Method",
)

INVENTORY_REQUIRED_COLUMNS = (
    "Product_ID",
    "Product_Name",
    "Category",
    "Stock_Quantity",
    "Unit_Price",
    "Reorder_Level",
    "Supplier",
)

SALES_INTERNAL_COLUMNS = (
    "Revenue_PHP",
    "_is_valid_record",
    "_validation_issues",
)

INVENTORY_INTERNAL_COLUMNS = (
    "_is_valid_record",
    "_validation_issues",
    "Stock_Status",
)


def _find_dataset_path(data_dir: Path, dataset_name: str) -> Path:
    for suffix in (".csv", ".xlsx"):
        candidate = data_dir / f"{dataset_name}{suffix}"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Dataset not found: expected {dataset_name}.csv or {dataset_name}.xlsx in {data_dir}"
    )


def _read_dataset(path: Path) -> pd.DataFrame:
    if path.suffix.casefold() == ".csv":
        return pd.read_csv(path)
    if path.suffix.casefold() == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    raise ValueError(f"Unsupported dataset format: {path.suffix}")


def load_datasets(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and validate supported source schemas without discarding rows."""
    sales_path = _find_dataset_path(data_dir, "sales_transactions")
    inventory_path = _find_dataset_path(data_dir, "inventory")

    sales_raw = _read_dataset(sales_path)
    inventory_raw = _read_dataset(inventory_path)
    missing_sales = sorted(set(SALES_REQUIRED_COLUMNS) - set(sales_raw.columns))
    missing_inventory = sorted(
        set(INVENTORY_REQUIRED_COLUMNS) - set(inventory_raw.columns)
    )
    if missing_sales or missing_inventory:
        details = []
        if missing_sales:
            details.append(f"sales_transactions.csv is missing: {', '.join(missing_sales)}")
        if missing_inventory:
            details.append(f"inventory.csv is missing: {', '.join(missing_inventory)}")
        raise ValueError("; ".join(details))

    return prepare_sales(sales_raw), prepare_inventory(inventory_raw)


def prepare_sales(sales: pd.DataFrame) -> pd.DataFrame:
    """Parse source fields and flag invalid rows while retaining every record."""
    prepared = sales.copy()
    prepared["Transaction_Date"] = pd.to_datetime(
        prepared["Transaction_Date"], errors="coerce"
    )

    numeric_columns = (
        "Quantity_Sold",
        "Unit_Price_PHP",
        "Total_Sales_PHP",
    )
    for column in numeric_columns:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    issues = pd.Series("", index=prepared.index, dtype="object")

    def add_issue(mask: pd.Series, message: str) -> None:
        nonlocal issues
        issues.loc[mask] = issues.loc[mask].map(
            lambda current: f"{current}; {message}" if current else message
        )

    add_issue(prepared["Transaction_Date"].isna(), "invalid or missing date")
    for column in ("Transaction_ID", "Product_ID", "Product_Name", "Category"):
        add_issue(
            prepared[column].isna() | prepared[column].astype(str).str.strip().eq(""),
            f"missing {column}",
        )
    for column in numeric_columns:
        add_issue(prepared[column].isna(), f"invalid or missing {column}")
        add_issue(
            prepared[column].lt(0).fillna(False),
            f"negative {column}",
        )

    prepared["Revenue_PHP"] = prepared["Total_Sales_PHP"]
    prepared["_validation_issues"] = issues
    prepared["_is_valid_record"] = issues.eq("")
    return prepared


def prepare_inventory(inventory: pd.DataFrame) -> pd.DataFrame:
    """Parse inventory fields and flag invalid rows while retaining all records."""
    prepared = inventory.copy()
    for column in ("Stock_Quantity", "Unit_Price", "Reorder_Level"):
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    issues = pd.Series("", index=prepared.index, dtype="object")

    def add_issue(mask: pd.Series, message: str) -> None:
        nonlocal issues
        issues.loc[mask] = issues.loc[mask].map(
            lambda current: f"{current}; {message}" if current else message
        )

    for column in ("Product_ID", "Product_Name", "Category"):
        add_issue(
            prepared[column].isna() | prepared[column].astype(str).str.strip().eq(""),
            f"missing {column}",
        )
    for column in ("Stock_Quantity", "Unit_Price", "Reorder_Level"):
        add_issue(prepared[column].isna(), f"invalid or missing {column}")
        add_issue(
            prepared[column].lt(0).fillna(False),
            f"negative {column}",
        )

    prepared["_validation_issues"] = issues
    prepared["_is_valid_record"] = issues.eq("")
    prepared["Stock_Status"] = "Unknown"
    valid = prepared["_is_valid_record"]
    prepared.loc[valid, "Stock_Status"] = "Sufficient"
    needs_reorder = valid & prepared["Stock_Quantity"].le(prepared["Reorder_Level"])
    prepared.loc[needs_reorder, "Stock_Status"] = "Reorder"
    return prepared


def validation_summary(
    sales: pd.DataFrame, inventory: pd.DataFrame
) -> dict[str, Any]:
    """Summarize data quality issues without altering source records."""
    amount_mismatch = (
        sales["Total_Sales_PHP"].notna()
        & sales["Quantity_Sold"].notna()
        & sales["Unit_Price_PHP"].notna()
        & (
            sales["Total_Sales_PHP"]
            - sales["Quantity_Sold"] * sales["Unit_Price_PHP"]
        ).abs().gt(0.01)
    )
    return {
        "sales_rows": len(sales),
        "valid_sales_rows": int(sales["_is_valid_record"].sum()),
        "invalid_sales_rows": int((~sales["_is_valid_record"]).sum()),
        "duplicate_sales_rows": int(sales.duplicated().sum()),
        "sales_amount_mismatches": int(amount_mismatch.sum()),
        "inventory_rows": len(inventory),
        "valid_inventory_rows": int(inventory["_is_valid_record"].sum()),
        "invalid_inventory_rows": int((~inventory["_is_valid_record"]).sum()),
        "duplicate_inventory_rows": int(inventory.duplicated().sum()),
    }


def filter_sales(
    sales: pd.DataFrame,
    start_date: Any,
    end_date: Any,
    products: list[str],
    categories: list[str],
    payment_methods: list[str],
    region_column: str | None = None,
    regions: list[str] | None = None,
    status_column: str | None = None,
    statuses: list[str] | None = None,
) -> pd.DataFrame:
    """Apply dashboard filters to valid records without changing the source."""
    filtered = sales.loc[sales["_is_valid_record"]].copy()
    filtered = filtered.loc[
        filtered["Transaction_Date"].dt.date.between(start_date, end_date)
    ]

    dimensions = (
        ("Product_Name", products),
        ("Category", categories),
        ("Payment_Method", payment_methods),
        (region_column, regions),
        (status_column, statuses),
    )
    for column, selected in dimensions:
        if column and selected is not None:
            filtered = filtered.loc[filtered[column].isin(selected)]
    return filtered


def product_performance(sales: pd.DataFrame) -> pd.DataFrame:
    """Aggregate actual recorded product quantities and revenue."""
    if sales.empty:
        return pd.DataFrame(
            columns=[
                "Product_ID",
                "Product_Name",
                "Category",
                "Units_Sold",
                "Revenue_PHP",
                "Orders",
                "Average_Selling_Price_PHP",
            ]
        )
    summary = (
        sales.groupby(
            ["Product_ID", "Product_Name", "Category"], as_index=False, dropna=False
        )
        .agg(
            Units_Sold=("Quantity_Sold", "sum"),
            Revenue_PHP=("Revenue_PHP", "sum"),
            Orders=("Transaction_ID", "nunique"),
        )
    )
    summary["Average_Selling_Price_PHP"] = (
        summary["Revenue_PHP"]
        .div(summary["Units_Sold"].where(summary["Units_Sold"].ne(0)))
    )
    return summary.sort_values(
        ["Revenue_PHP", "Units_Sold", "Product_Name"],
        ascending=[False, False, True],
        ignore_index=True,
    )


def catalog_reconciliation(
    inventory: pd.DataFrame, sales: pd.DataFrame
) -> pd.DataFrame:
    """Compare inventory products to sales by ID, name, and category."""
    sales_products: dict[str, set[tuple[str, str]]] = {}
    for product_id, product_name, category in sales[
        ["Product_ID", "Product_Name", "Category"]
    ].dropna().itertuples(index=False, name=None):
        sales_products.setdefault(str(product_id), set()).add(
            (str(product_name), str(category))
        )

    records: list[dict[str, Any]] = []
    for row in inventory.itertuples(index=False):
        product_id = str(row.Product_ID)
        product_name = str(row.Product_Name)
        category = str(row.Category)
        products_for_id = sales_products.get(product_id, set())
        matching_identity = {
            sales_category
            for sales_name, sales_category in products_for_id
            if sales_name == product_name
        }
        if category in matching_identity:
            status = "Matched"
        elif matching_identity:
            status = "Category conflict"
        elif products_for_id:
            status = "ID conflict"
        else:
            status = "No sales record"
        records.append(
            {
                "Product_ID": product_id,
                "Inventory_Product": product_name,
                "Inventory_Category": category,
                "Sales_Product_Names": ", ".join(
                    sorted({name for name, _ in products_for_id})
                ),
                "Sales_Categories": ", ".join(
                    sorted({sales_category for _, sales_category in products_for_id})
                ),
                "Catalog_Match_Status": status,
                "Stock_Quantity": row.Stock_Quantity,
            }
        )
    return pd.DataFrame.from_records(records)


def compare_equal_periods(
    sales: pd.DataFrame, start_date: Any, end_date: Any
) -> tuple[pd.DataFrame, str, str] | None:
    """Compare product performance across the two latest equal-length periods."""
    total_days = (end_date - start_date).days + 1
    period_days = total_days // 2
    if period_days < 1:
        return None

    current_start = end_date - timedelta(days=period_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)

    previous = sales.loc[sales["Transaction_Date"].dt.date.between(
        previous_start, previous_end
    )]
    current = sales.loc[sales["Transaction_Date"].dt.date.between(
        current_start, end_date
    )]
    product_keys = sales[["Product_ID", "Product_Name"]].drop_duplicates()
    previous_units = (
        previous.groupby(["Product_ID", "Product_Name"])["Quantity_Sold"].sum()
    )
    current_units = current.groupby(["Product_ID", "Product_Name"])["Quantity_Sold"].sum()
    comparison = product_keys.copy()
    comparison["Previous_Units"] = [
        previous_units.get((row.Product_ID, row.Product_Name), 0)
        for row in comparison.itertuples(index=False)
    ]
    comparison["Current_Units"] = [
        current_units.get((row.Product_ID, row.Product_Name), 0)
        for row in comparison.itertuples(index=False)
    ]
    comparison["Change_Units"] = (
        comparison["Current_Units"] - comparison["Previous_Units"]
    )
    comparison["Trend"] = comparison.apply(
        lambda row: (
            "Increasing"
            if row["Current_Units"] > row["Previous_Units"]
            else "Declining"
            if row["Current_Units"] < row["Previous_Units"]
            else "Unchanged"
        ),
        axis=1,
    )
    comparison = comparison.sort_values(
        ["Change_Units", "Product_Name"], ascending=[False, True], ignore_index=True
    )
    return (
        comparison,
        f"{previous_start:%b %d}–{previous_end:%b %d, %Y}",
        f"{current_start:%b %d}–{end_date:%b %d, %Y}",
    )


def exportable_sales(sales: pd.DataFrame) -> pd.DataFrame:
    """Return original dataset columns, excluding dashboard-only helper fields."""
    return sales.drop(
        columns=[column for column in SALES_INTERNAL_COLUMNS if column in sales.columns],
        errors="ignore",
    )


def exportable_inventory(inventory: pd.DataFrame) -> pd.DataFrame:
    """Return original inventory columns, excluding dashboard-only helper fields."""
    return inventory.drop(
        columns=[
            column
            for column in INVENTORY_INTERNAL_COLUMNS
            if column in inventory.columns
        ],
        errors="ignore",
    )
