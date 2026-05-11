import pandas as pd
import dash
from dash import dcc, html, dash_table
import plotly.express as px
import plotly.figure_factory as ff
import datetime

from Analitic_functions.Util_functions import (
    calculate_ewma_std,
    calculate_returns,
    calculate_correlation_returns_all_instruments_csv
)
from data.update_data import update_ibkr_prices_to_db
from data.db import get_price_data, get_consolidated_data, needs_data_update

# ===================== CONFIG ===================== #
ANALYSIS_YEAR = 2026        # <<< CAMBIA AQUÍ EL AÑO
RISK_FREE_RATE = 0.025

# ===================== ACTUALIZACION DE DATOS ===================== #
print("📊 Comprobando necesidad de actualización de BD...")
try:
    if needs_data_update():
        print("🔄 La BD está desactualizada. Iniciando actualización desde IBKR...")
        result = update_ibkr_prices_to_db()
        if result != 0:
            print("⚠️ La actualización no terminó correctamente. Continuando con los datos disponibles.")
        else:
            print("✅ Actualización completada.")
    else:
        print("✅ La BD ya está actualizada.")
except Exception as e:
    print(f"⚠️ Error al comprobar/actualizar la BD: {e}")

print("📊 Leyendo datos desde BD centralizada...")

# ===================== HOLDINGS ===================== #
holdings_data = {
    "Symbol": ["ACWX","AXP","EQR","GOOG","IWM","JPM","KO","NDAQ","NVDA","TQQQ","UBER","WMT"],
    "Quantity": [5,6,3,7,4,7,10,3,1,68,7,8],
    "Average Price": [62.65,293.58,60,216.69,234.71,279.34,62.23,50.46,111.60,23.44,72.49,67.85]
}

holdings = pd.DataFrame(holdings_data).set_index("Symbol")
holdings["Total Cost"] = holdings["Quantity"] * holdings["Average Price"]

# ===================== HISTORICOS (DESDE BD) ===================== #
all_data = get_consolidated_data()

all_data["Symbol"] = all_data["Symbol"].str.strip().str.upper()
all_data["Date"] = pd.to_datetime(all_data["Date"], errors="coerce")
all_data["Close"] = pd.to_numeric(all_data["Close"], errors="coerce")
clean_data = all_data.dropna()

# ===================== FILTROS DE FECHA ===================== #
start_year = pd.Timestamp(ANALYSIS_YEAR, 1, 1)
end_year   = pd.Timestamp(ANALYSIS_YEAR, 12, 31)

data_year = clean_data[(clean_data["Date"] >= start_year) &
                        (clean_data["Date"] <= end_year)]

data_prev_year = clean_data[clean_data["Date"] < start_year]

# ===================== LAST CLOSE (DEL AÑO) ===================== #
last_prices = data_year.sort_values("Date").groupby("Symbol").last()
holdings["Last Close"] = holdings.index.map(last_prices["Close"])
holdings["Last Price Date"] = holdings.index.map(
    last_prices["Date"].dt.strftime("%d %b %Y")
)

holdings["Market Value"] = holdings["Quantity"] * holdings["Last Close"]
holdings["G/P"] = holdings["Market Value"] - holdings["Total Cost"]
holdings["% G/P"] = (holdings["G/P"] / holdings["Total Cost"]) * 100

# ===================== START VALUE YTD ===================== #
start_prices = data_prev_year.sort_values("Date").groupby("Symbol").last()
holdings["Start Value YTD"] = holdings["Quantity"] * holdings.index.map(start_prices["Close"])

holdings["Δ USD YTD"] = holdings["Market Value"] - holdings["Start Value YTD"]
holdings["Δ % YTD"] = (holdings["Δ USD YTD"] / holdings["Start Value YTD"]) * 100

portfolio_ytd = (
    holdings["Market Value"].sum() -
    holdings["Start Value YTD"].sum()
) / holdings["Start Value YTD"].sum() * 100

# ===================== VOLATILIDADES ===================== #
returns_df = calculate_returns({
    s: g.sort_values("Date")[["Date","Close"]].reset_index(drop=True)
    for s,g in data_year.groupby("Symbol")
})

vols = {}
for s in returns_df:
    r = returns_df[s].dropna().values
    if len(r) > 32:
        vols[s] = calculate_ewma_std(r,32)[-1]*16*100

holdings["Volatility (%)"] = holdings.index.map(vols)

holdings["Weight"] = holdings["Market Value"] / holdings["Market Value"].sum()
holdings["Weighted Volatility"] = holdings["Weight"] * holdings["Volatility (%)"]
portfolio_volatility = holdings["Weighted Volatility"].sum()

# ===================== SPY (DESDE BD) ===================== #
spy_data = get_price_data(symbol="SPY")
if spy_data.empty:
    print("⚠️ SPY no encontrado en BD. Usando datos vacíos.")
    spy = pd.DataFrame(columns=["Date", "Close"])
else:
    spy = spy_data[["date", "close"]].rename(columns={"date": "Date", "close": "Close"})
    spy["Date"] = pd.to_datetime(spy["Date"])
    spy["Close"] = pd.to_numeric(spy["Close"], errors="coerce")
    spy = spy.dropna()

if not spy.empty:
    spy_start = spy[spy["Date"] < start_year].sort_values("Date").iloc[-1]["Close"]
    spy_end   = spy[spy["Date"] <= end_year].sort_values("Date").iloc[-1]["Close"]
    spy_ytd = (spy_end - spy_start) / spy_start * 100
    spy_ret = spy["Close"].pct_change().dropna().values
    spy_vol = calculate_ewma_std(spy_ret,32)[-1]*16*100 if len(spy_ret) > 32 else 0
else:
    spy_ytd = 0
    spy_vol = 0
    print("⚠️ SPY sin datos para el año.")

# ===================== SHARPE ===================== #
sharpe = ((portfolio_ytd/100 - RISK_FREE_RATE) /
          (portfolio_volatility/100))

# ===================== CORRELACIÓN ===================== #
corr = calculate_correlation_returns_all_instruments_csv(
    data_year.set_index(["Symbol","Date"])
).round(2)

fig_corr = ff.create_annotated_heatmap(
    z=corr.values,
    x=list(corr.columns),
    y=list(corr.index),
    colorscale="RdBu",
    zmin=-1,
    zmax=1
)

# ===================== BAR YTD ===================== #
fig_ytd = px.bar(
    x=["Portafolio","SPY"],
    y=[portfolio_ytd, spy_ytd],
    text=[f"{portfolio_ytd:.2f}%", f"{spy_ytd:.2f}%"],
    title=f"Rendimiento YTD {ANALYSIS_YEAR}"
)

# ===================== TOTAL ROW ===================== #
total = pd.Series({
    "Symbol":"TOTAL",
    "Quantity":holdings["Quantity"].sum(),
    "Total Cost":holdings["Total Cost"].sum(),
    "Market Value":holdings["Market Value"].sum(),
    "G/P":holdings["G/P"].sum(),
    "% G/P":holdings["G/P"].sum()/holdings["Total Cost"].sum()*100,
    "Start Value YTD":holdings["Start Value YTD"].sum(),
    "Δ USD YTD":holdings["Δ USD YTD"].sum(),
    "Δ % YTD":holdings["Δ USD YTD"].sum()/holdings["Start Value YTD"].sum()*100,
    "Weight":1,
    "Weighted Volatility":holdings["Weighted Volatility"].sum()
})

dashboard_data = pd.concat(
    [holdings.reset_index(), pd.DataFrame([total])],
    ignore_index=True
).round(2)

# ===================== DASH ===================== #
app = dash.Dash(__name__)
app.layout = html.Div([
    html.H1(f"Dashboard de Portafolio – YTD {ANALYSIS_YEAR}"),

    dash_table.DataTable(
        data=dashboard_data.to_dict("records"),
        columns=[{"name":c,"id":c} for c in dashboard_data.columns],
        style_table={"overflowX":"auto"}
    ),

    html.H3("Métricas del Portafolio"),
    html.P(f"Total Open: ${total['G/P']:.2f}"),
    html.P(f"Rendimiento YTD: {portfolio_ytd:.2f}%"),
    html.P(f"Volatilidad Portafolio: {portfolio_volatility:.2f}%"),
    html.P(f"Volatilidad SPY: {spy_vol:.2f}%"),
    html.P(f"Sharpe Ratio: {sharpe:.2f}"),

    dcc.Graph(figure=fig_ytd),
    dcc.Graph(figure=fig_corr)
])

if __name__ == "__main__":
    app.run(debug=True)
