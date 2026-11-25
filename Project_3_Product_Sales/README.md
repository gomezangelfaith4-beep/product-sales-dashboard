# Product Sales Dashboard

A Streamlit business dashboard for the supplied sales transaction and inventory CSV files. It provides filtered KPIs, product and transaction lookup, interactive sales charts, product performance comparisons, validation information, CSV downloads, and a PDF summary.

## Project structure

```text
Project_3_Product_Sales/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/
│   └── config.toml
├── data/
│   ├── inventory.csv
│   └── sales_transactions.csv
├── tests/
│   └── test_dashboard_logic.py
└── utils/
    ├── __init__.py
    ├── data_processing.py
    └── reports.py
```

## Install and run locally

Python 3.12 is recommended. From this project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

If PowerShell blocks environment activation, run the environment's executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\streamlit.exe run app.py
```

The app loads data through paths relative to `app.py`; it accepts CSV or `.xlsx` files named `sales_transactions` and `inventory`. If both formats exist for a dataset, CSV is used. No local machine-specific paths or secrets are required.

## Test

Run the focused processing, filtering, product analysis, and report tests:

```powershell
python -m unittest discover -s tests -v
```

## GitHub upload

Create a GitHub repository, then run these commands from this project directory (replace the URL with your repository):

```powershell
git init
git add app.py README.md requirements.txt .streamlit data utils tests
git commit -m "Build product sales dashboard"
git branch -M main
git remote add origin https://github.com/<account>/<repository>.git
git push -u origin main
```

Do not upload a virtual environment. Keep the two CSV files in the repository if they do not contain private business data.

## Streamlit Community Cloud

1. Push the project to GitHub.
2. In Streamlit Community Cloud, choose **Create app** and connect the repository and branch.
3. Set the app file path to `app.py` if this project is the repository root, or `Project_3_Product_Sales/app.py` if the parent workspace is the repository.
4. Deploy. The dependencies are installed from `requirements.txt`, and the committed CSVs are loaded using relative paths.
5. After deployment, verify the dashboard overview, filters, charts, and PDF/CSV download buttons.

Deployment has not been performed from this workspace.

## Data and calculation notes

- Sales revenue uses the supplied `Total_Sales_PHP` column. The app also checks it against `Quantity_Sold * Unit_Price_PHP`; it does not add both values together.
- Orders are counted by unique `Transaction_ID`. Products sold are the sum of `Quantity_Sold`. Average selling price is revenue divided by units sold; average order value is revenue divided by unique order IDs.
- The provided sales data contains product, category, quantity, unit price, sales total, date, and payment method. It has no cost, region, customer, or order-status field; dependent metrics and filters are therefore unavailable.
- Inventory is a separate stock snapshot and does not change as sales are recorded. Some inventory IDs and names conflict with sales, and one matching product has a category mismatch; the app flags these rather than assuming a clean catalog link.
- Product and sales records are read-only. Adding, editing, and deleting records would require a persistent CRUD/database layer that this project does not currently have.
- Invalid rows are retained in the source files and reported in System Information. They are excluded from calculations rather than being silently filled or rewritten.
