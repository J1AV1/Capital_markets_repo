import pandas as pd
import dash
from dash import dcc, html, dash_table
import plotly.express as px
import datetime

# Definir holdings manualmente
holdings_data = {
    "Symbol": ["AXP", "EQR", "GOOG", "IWM", "JPM", "KO", "NDAQ", "NVDA", "TQQQ", "UBER", "WMT"],
    "Quantity": [2, 3, 3, 4, 1, 10, 3, 3, 24, 4, 6],
    "Average Price": [270.85, 60.00, 102.10, 234.71, 187.20, 62.23, 50.46, 111.60, 38.15, 74.94, 57.54]
}
holdings = pd.DataFrame(holdings_data).set_index("Symbol")

# Calcular costo total
holdings["Total Cost"] = holdings["Quantity"] * holdings["Average Price"]

# Leer datos de los activos desde all_historical_data.csv
file_path = r"C:\Users\jalpi\git_repos\Capital_markets\Portfolio_stuff\data\all_historical_data.csv"
use_cols = [0, 1, 5]  # Solo 'Symbol', 'Date', 'Close'

all_data = pd.read_csv(file_path, usecols=use_cols, header=None, names=["Symbol", "Date", "Close"], low_memory=False)

# Asegurar que la columna Date está bien formateada
all_data["Date"] = pd.to_datetime(all_data["Date"].astype(str).str.strip(), format="%Y-%m-%d", errors="coerce")
all_data["Close"] = pd.to_numeric(all_data["Close"], errors="coerce")

# Obtener el último precio de cada símbolo
latest_prices = all_data.sort_values(by=["Symbol", "Date"]).groupby("Symbol")["Close"].last()

# Unir los últimos precios al DataFrame de holdings
holdings["Last Close"] = holdings.index.map(latest_prices)
holdings["Market Value"] = holdings["Quantity"] * holdings["Last Close"]

# Convertir a numérico para evitar errores
holdings["Total Cost"] = pd.to_numeric(holdings["Total Cost"], errors="coerce")
holdings["Market Value"] = pd.to_numeric(holdings["Market Value"], errors="coerce")

# Calcular Ganancia/Pérdida (G/P)
holdings["G/P"] = holdings["Market Value"] - holdings["Total Cost"]

# Calcular % de ganancia por activo
holdings["% G/P"] = (holdings["G/P"] / holdings["Total Cost"]) * 100

# Total G/P
total_gp = holdings["G/P"].sum()

# Calcular YTD del portafolio
initial_equity = 6392.49  # Net equity a inicio de año
current_equity = holdings["Market Value"].sum()
portfolio_ytd = ((current_equity - initial_equity) / initial_equity) * 100

# ===================== BENCHMARK: SPY =====================#
#EL SPY SALE VACIO
spy_file_path = r"C:\Users\jalpi\git_repos\Capital_markets\Portfolio_stuff\data\SPY_historical_data.csv"

# Leer datos del SPY y asegurarnos de que se trata igual que all_historical_data.csv
spy_data = pd.read_csv(spy_file_path, usecols=[0, 4], header=None, names=["Date", "Close"], low_memory=False)

# Asegurar que la columna Date está bien formateada
spy_data["Date"] = pd.to_datetime(spy_data["Date"].astype(str).str.strip(), format="%Y-%m-%d", errors="coerce")
spy_data["Close"] = pd.to_numeric(spy_data["Close"], errors="coerce")

# Filtrar datos del SPY solo para el año actual
current_year = datetime.datetime.now().year
spy_data_current_year = spy_data[spy_data["Date"].dt.year == current_year]

# Obtener el primer precio del año y el último disponible
spy_start_price = spy_data_current_year.sort_values("Date")["Close"].iloc[0] if not spy_data_current_year.empty else None
spy_end_price = spy_data["Close"].iloc[-1] if not spy_data.empty else None

# Calcular rendimiento YTD del SPY solo si hay datos disponibles
spy_ytd = ((spy_end_price - spy_start_price) / spy_start_price) * 100 if spy_start_price else None

# Crear gráfico de YTD
fig_ytd = px.bar(
    x=["Portafolio", "SPY"],
    y=[portfolio_ytd, spy_ytd] if spy_ytd is not None else [portfolio_ytd, 0],
    labels={"x": "Activo", "y": "Rendimiento YTD (%)"},
    title="Comparación de Rendimiento YTD (%)",
    color=["Portafolio", "SPY"],
    text=[f"{portfolio_ytd:.2f}%", f"{spy_ytd:.2f}%" if spy_ytd is not None else "N/A"]
)

# Crear el dashboard con Dash
dashboard = dash.Dash(__name__)

dashboard.layout = html.Div([
    html.H1("Dashboard de Portafolio"),
    
    # Tabla de holdings con G/P
    html.H3("Holdings y Ganancia/Pérdida"),
    dash_table.DataTable(
        columns=[{"name": col, "id": col} for col in holdings.reset_index().columns],
        data=holdings.reset_index().to_dict("records"),
    ),
    
    # Indicador de G/P total
    html.H3("Métricas del Portafolio"),
    html.P(f"Total G/P: {total_gp:.2f} USD"),
    html.P(f"Rendimiento YTD del Portafolio: {portfolio_ytd:.2f}%"),
    
    # Gráfico de comparación con SPY
    dcc.Graph(figure=fig_ytd)
])

if __name__ == "__main__":
    dashboard.run_server(debug=True)
