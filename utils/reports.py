from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pandas as pd
from fpdf import FPDF


def _write_paragraph(pdf: FPDF, text: str, line_height: float = 6) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, line_height, text)


def build_pdf_report(
    sales: pd.DataFrame,
    product_summary: pd.DataFrame,
    category_summary: pd.DataFrame,
    monthly_summary: pd.DataFrame,
    insights: list[str],
    generated_at: datetime | None = None,
) -> bytes:
    """Create a compact PDF summary from the currently filtered dataset."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_title("Product Sales Dashboard Report")
    pdf.set_author("Product Sales Dashboard")
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 12, "Product Sales Dashboard", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    timestamp = generated_at or datetime.now()
    pdf.cell(
        0,
        7,
        f"Report generated: {timestamp:%Y-%m-%d %H:%M}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    total_revenue = float(sales["Revenue_PHP"].sum()) if not sales.empty else 0.0
    total_orders = int(sales["Transaction_ID"].nunique()) if not sales.empty else 0
    total_units = float(sales["Quantity_Sold"].sum()) if not sales.empty else 0.0
    average_order_value = total_revenue / total_orders if total_orders else 0.0

    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Filtered sales summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    summary_lines = (
        f"Total revenue: PHP {total_revenue:,.2f}",
        f"Total orders: {total_orders:,}",
        f"Products sold (units): {total_units:,.0f}",
        f"Average order value: PHP {average_order_value:,.2f}",
    )
    for line in summary_lines:
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Best-selling products", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    if product_summary.empty:
        pdf.cell(0, 6, "No valid sales records match the selected filters.", new_x="LMARGIN", new_y="NEXT")
    else:
        best_sellers = product_summary.sort_values(
            ["Units_Sold", "Product_Name"], ascending=[False, True]
        ).head(5)
        for row in best_sellers.itertuples(index=False):
            _write_paragraph(
                pdf,
                f"{row.Product_Name} ({row.Product_ID}): "
                f"{row.Units_Sold:,.0f} units; PHP {row.Revenue_PHP:,.2f}",
            )

    pdf.ln(2)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Product category performance", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    if category_summary.empty:
        pdf.cell(0, 6, "No category sales are available.", new_x="LMARGIN", new_y="NEXT")
    else:
        for row in category_summary.sort_values(
            "Revenue_PHP", ascending=False
        ).itertuples(index=False):
            _write_paragraph(
                pdf,
                f"{row.Category}: PHP {row.Revenue_PHP:,.2f} "
                f"({row.Units_Sold:,.0f} units)",
            )

    pdf.ln(2)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Monthly sales analysis", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    if monthly_summary.empty:
        pdf.cell(0, 6, "No monthly sales are available.", new_x="LMARGIN", new_y="NEXT")
    else:
        for row in monthly_summary.sort_values("Month").itertuples(index=False):
            pdf.cell(
                0,
                6,
                f"{row.Month}: PHP {row.Revenue_PHP:,.2f}",
                new_x="LMARGIN",
                new_y="NEXT",
            )

    pdf.ln(2)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Business insights and recommendations", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    for insight in insights:
        _write_paragraph(pdf, f"- {insight}")

    output = pdf.output()
    if isinstance(output, bytearray):
        return bytes(output)
    if isinstance(output, bytes):
        return output
    if isinstance(output, BytesIO):
        return output.getvalue()
    raise TypeError(f"Unexpected PDF output type: {type(output).__name__}")
