import pandas as pd
import dash
from dash import dcc, html, dash_table
import plotly.express as px
import datetime
from Analitic_functions.Util_functions import calculate_ewma_std, calculate_returns

# ===================== VARIABLES PRINCIPALES ===================== #
holdings_data = {
    "Symbol": ["AXP", "EQR", "GOOG", "IWM", "JPM", "KO", "NDAQ", "NVDA", "TQQQ", "UBER", "WMT"],
    "Quantity": [4, 3, 3, 4, 2, 10, 3, 3, 31, 7, 7],
    "Average Price": [258.61, 60.00, 102.10, 234.71, 226.71, 62.23, 50.46, 111.60, 42.75, 72.49, 61.31]
}
file_path = r"C:\Users\jalpi\git_repos\Capital_markets\Portfolio_stuff\data\all_historical_data.csv"
spy_file_path = r"C:\Users\jalpi\git_repos\Capital_markets\Portfolio_stuff\data\SPY_historical_data.csv"

# ===================== DATOS DEL PORTAFOLIO ===================== #
holdings = pd.DataFrame(holdings_data).set_index("Symbol")
holdings["Total Cost"] = holdings["Quantity"] * holdings["Average Price"]

all_data = pd.read_csv(
    file_path,
    usecols=[0, 1, 2],
    header=None,
    names=["Symbol", "Date", "Close"],
    low_memory=False
)

# ✅ Normaliza símbolos
all_data["Symbol"] = all_data["Symbol"].astype(str).str.strip().str.upper()

# ✅ Convierte fechas sin formato forzado
all_data["Date"] = pd.to_datetime(all_data["Date"], errors="coerce")
all_data["Close"] = pd.to_numeric(all_data["Close"], errors="coerce")

# ✅ Filtrar valores válidos
clean_data = all_data.dropna(subset=["Date", "Close"])

# ✅ Obtener último precio y fecha por símbolo
latest_prices = clean_data.sort_values(["Symbol", "Date"]).groupby("Symbol")["Close"].last()
latest_dates = clean_data.sort_values(["Symbol", "Date"]).groupby("Symbol")["Date"].last().dt.strftime("%d %b %Y")

holdings["Last Close"] = holdings.index.map(latest_prices)
holdings["Last Price Date"] = holdings.index.map(latest_dates)
holdings["Market Value"] = holdings["Quantity"] * holdings["Last Close"]
holdings["G/P"] = holdings["Market Value"] - holdings["Total Cost"]
holdings["% G/P"] = (holdings["G/P"] / holdings["Total Cost"]) * 100
total_gp = holdings["G/P"].sum()

# ===================== VALORES AL INICIO DEL AÑO ===================== #
start_of_year = pd.Timestamp(datetime.datetime.now().year, 1, 1)
first_prices = all_data[all_data["Date"] >= start_of_year].sort_values("Date").dropna()
first_closes = first_prices.groupby("Symbol")["Close"].first()
holdings["Start Value"] = holdings["Quantity"] * holdings.index.map(first_closes)
holdings["Δ USD"] = holdings["Market Value"] - holdings["Start Value"]
holdings["Δ %"] = (holdings["Δ USD"] / holdings["Start Value"]) * 100

initial_equity = holdings["Start Value"].sum()
current_equity = holdings["Market Value"].sum()
portfolio_ytd = ((current_equity - initial_equity) / initial_equity) * 100

# ===================== BENCHMARK: SPY ===================== #
spy_data = pd.read_csv(spy_file_path, usecols=[0, 1], header=None, names=["Date", "Close"], low_memory=False)
spy_data["Date"] = spy_data["Date"].astype(str).str.strip().str[:10]
spy_data["Date"] = pd.to_datetime(spy_data["Date"], format="%Y-%m-%d", errors="coerce")
spy_data["Close"] = pd.to_numeric(spy_data["Close"], errors="coerce")

current_year = datetime.datetime.now().year
spy_data_current_year = spy_data[spy_data["Date"].dt.year == current_year]
spy_start_price = spy_data_current_year.sort_values("Date")["Close"].iloc[0] if not spy_data_current_year.empty else None
spy_end_price = spy_data["Close"].iloc[-1] if not spy_data.empty else None
spy_ytd = ((spy_end_price - spy_start_price) / spy_start_price) * 100 if spy_start_price else None

# ===================== VOLATILIDAD ANUALIZADA ===================== #
data_by_symbol = {
    symbol: group.sort_values("Date")[["Date", "Close"]].reset_index(drop=True)
    for symbol, group in all_data.groupby("Symbol")
}

returns_df = calculate_returns(data_by_symbol)
volatilities = {}

for symbol in returns_df.columns:
    ret_series = returns_df[symbol].dropna().values
    if len(ret_series) > 32:
        ewma_std = calculate_ewma_std(ret_series, periods=32)
        vol_annualized = ewma_std[-1] * 16 * 100
        volatilities[symbol] = vol_annualized
    else:
        volatilities[symbol] = None

holdings["Volatility (%)"] = holdings.index.map(volatilities)

# ===================== GRÁFICO DE COMPARACIÓN YTD ===================== #
fig_ytd = px.bar(
    x=["Portafolio", "SPY"],
    y=[portfolio_ytd, spy_ytd] if spy_ytd is not None else [portfolio_ytd, 0],
    labels={"x": "Activo", "y": "Rendimiento YTD (%)"},
    title="Comparación de Rendimiento YTD (%)",
    color=["Portafolio", "SPY"],
    text=[f"{portfolio_ytd:.2f}%", f"{spy_ytd:.2f}%" if spy_ytd is not None else "N/A"]
)

# ===================== DASHBOARD ===================== #
dashboard = dash.Dash(__name__)
dashboard.layout = html.Div([
    html.H1("Dashboard de Portafolio"),

    html.H3("Holdings con Métricas YTD"),
    dash_table.DataTable(
        columns=[
            {"name": "Symbol", "id": "Symbol"},
            {"name": "Quantity", "id": "Quantity"},
            {"name": "Average Price", "id": "Average Price", "type": "numeric", "format": {"specifier": "$,.2f"}},
            {"name": "Total Cost", "id": "Total Cost", "type": "numeric", "format": {"specifier": "$,.2f"}},
            {"name": "Last Close", "id": "Last Close", "type": "numeric", "format": {"specifier": "$,.2f"}},
            {"name": "Market Value", "id": "Market Value", "type": "numeric", "format": {"specifier": "$,.2f"}},
            {"name": "G/P", "id": "G/P", "type": "numeric", "format": {"specifier": "$,.2f"}},
            {"name": "% G/P", "id": "% G/P", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Start Value", "id": "Start Value", "type": "numeric", "format": {"specifier": "$,.2f"}},
            {"name": "Δ USD", "id": "Δ USD", "type": "numeric", "format": {"specifier": "$,.2f"}},
            {"name": "Δ %", "id": "Δ %", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Volatility (%)", "id": "Volatility (%)", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Last Price Date", "id": "Last Price Date"},
        ],
        data=holdings.reset_index().to_dict("records"),
        style_table={"overflowX": "auto"},
    ),

    html.H3("Métricas del Portafolio"),
    html.P(f"Total Open: ${total_gp:,.2f}"),
    html.P(f"Rendimiento YTD del Portafolio: {portfolio_ytd:.2f}%"),

    dcc.Graph(figure=fig_ytd)
])

if __name__ == "__main__":
    dashboard.run_server(debug=True)
