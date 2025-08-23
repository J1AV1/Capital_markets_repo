import pandas as pd
import dash
from dash import dcc, html, dash_table
import plotly.express as px
import plotly.figure_factory as ff
import datetime
from Analitic_functions.Util_functions import calculate_ewma_std, calculate_returns, calculate_correlation_returns_all_instruments_csv
from data.update_data import update_ibkr_csvs_and_consolidate

# ===================== ACTUALIZACION DE DATOS ===================== #
update_ibkr_csvs_and_consolidate(
    csv_dir="Portfolio_stuff/data",
    host="127.0.0.1",
    port=7496,
    client_id=43,
    min_days_fetch=30,
    bar_size="1 day",
    what_to_show="TRADES",
    use_rth=True,
    sleep_between=3.0,
)

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

all_data["Symbol"] = all_data["Symbol"].astype(str).str.strip().str.upper()
all_data["Date"] = pd.to_datetime(all_data["Date"], errors="coerce")
all_data["Close"] = pd.to_numeric(all_data["Close"], errors="coerce")
clean_data = all_data.dropna(subset=["Date", "Close"])

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
holdings["Start Value YTD"] = holdings["Quantity"] * holdings.index.map(first_closes)
holdings["\u0394 USD YTD"] = holdings["Market Value"] - holdings["Start Value YTD"]
holdings["\u0394 % YTD"] = (holdings["\u0394 USD YTD"] / holdings["Start Value YTD"]) * 100

initial_equity = holdings["Start Value YTD"].sum()
current_equity = holdings["Market Value"].sum()
portfolio_ytd = ((current_equity - initial_equity) / initial_equity) * 100

# ===================== BENCHMARK: SPY ===================== #
spy_data = pd.read_csv(spy_file_path, usecols=[0, 4], header=None, names=["Date", "Close"], low_memory=False)
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

# ===================== CÁLCULO TOTALES Y VOLATILIDAD PONDERADA ===================== #
total_market_value = holdings["Market Value"].sum()
holdings["Weight"] = holdings["Market Value"] / total_market_value
holdings["Weighted Volatility"] = holdings["Weight"] * holdings["Volatility (%)"]
portfolio_volatility = holdings["Weighted Volatility"].sum()

# ===================== SHARPE RATIO ===================== #
rf_annual = 0.04
excess_return_annual = portfolio_ytd - (rf_annual * 100)
sharpe_ratio = excess_return_annual / portfolio_volatility if portfolio_volatility else None

# ===================== VOLATILIDAD SPY ===================== #
spy_returns = spy_data["Close"].pct_change().dropna().values
spy_volatility = None
if len(spy_returns) > 32:
    spy_vol_ewma = calculate_ewma_std(spy_returns, periods=32)
    spy_volatility = spy_vol_ewma[-1] * 16 * 100

# ===================== GRÁFICO DE COMPARACIÓN YTD ===================== #
fig_ytd = px.bar(
    x=["Portafolio", "SPY"],
    y=[portfolio_ytd, spy_ytd] if spy_ytd is not None else [portfolio_ytd, 0],
    labels={"x": "Activo", "y": "Rendimiento YTD (%)"},
    title="Comparación de Rendimiento YTD (%)",
    color=["Portafolio", "SPY"],
    text=[f"{portfolio_ytd:.2f}%", f"{spy_ytd:.2f}%" if spy_ytd is not None else "N/A"]
)


# ===================== MATRIZ DE CORRELACIÓN ===================== #
correlation_matrix = calculate_correlation_returns_all_instruments_csv(clean_data.set_index(["Symbol", "Date"]))
fig_corr = ff.create_annotated_heatmap(
    z=correlation_matrix.values.round(2),
    x=correlation_matrix.columns.tolist(),
    y=correlation_matrix.index.tolist(),
    colorscale="RdBu",
    zmin=-1,
    zmax=1,
    showscale=True
)
fig_corr.update_layout(title="Matriz de Correlación de Retornos", autosize=True)

# ===================== TOTALES ===================== #
total_row = pd.Series({
    "Symbol": "TOTAL",
    "Quantity": holdings["Quantity"].sum(),
    "Total Cost": holdings["Total Cost"].sum(),
    "Market Value": holdings["Market Value"].sum(),
    "G/P": holdings["G/P"].sum(),
    "% G/P": (holdings["G/P"].sum() / holdings["Total Cost"].sum()) * 100,
    "Start Value YTD": holdings["Start Value YTD"].sum(),
    "Δ USD YTD": holdings["Δ USD YTD"].sum(),
    "Δ % YTD": (holdings["Δ USD YTD"].sum() / holdings["Start Value YTD"].sum()) * 100,
    "Weight": holdings["Weight"].sum(),
    "Weighted Volatility": holdings["Weighted Volatility"].sum()
})

dashboard_data = pd.concat([holdings.reset_index(), pd.DataFrame([total_row])], ignore_index=True)

# ===================== DASHBOARD ===================== #
dashboard = dash.Dash(__name__)
dashboard.layout = html.Div([
    html.H1("Dashboard de Portafolio"),

    html.H3("Holdings con Métricas YTD"),
    dash_table.DataTable(
        columns=[
            {"name": col, "id": col, "type": "numeric" if col not in ["Symbol", "Last Price Date"] else "text", "format": {"specifier": "$,.2f"} if "Price" in col or "Cost" in col or "Value" in col or col == "G/P" else {"specifier": ".2f"} if "%" in col else None}
            for col in dashboard_data.columns
        ],
        data=dashboard_data.to_dict("records"),
        style_table={"overflowX": "auto"},
    ),

    html.H3("Métricas del Portafolio"),
    html.P(f"Total Open: ${total_gp:,.2f}"),
    html.P(f"Rendimiento YTD del Portafolio: {portfolio_ytd:.2f}%"),
    html.P(f"Volatilidad Ponderada del Portafolio: {portfolio_volatility:.2f}%"),
    html.P(f"Volatilidad del SPY: {spy_volatility:.2f}%" if spy_volatility is not None else "Volatilidad del SPY no disponible"),
    html.P(f"Sharpe Ratio del Portafolio (YTD): {sharpe_ratio:.2f}" if sharpe_ratio is not None else "Sharpe Ratio no disponible"),

    dcc.Graph(figure=fig_ytd),
    dcc.Graph(figure=fig_corr)
])

if __name__ == "__main__":
    dashboard.run_server(debug=True)
