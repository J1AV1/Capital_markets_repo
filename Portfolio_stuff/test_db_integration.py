"""
Script de prueba rápida para verificar que la BD centralizada funciona correctamente.
Ejecutar: python test_db_integration.py
"""
import sys
from pathlib import Path

# Agregar carpeta al path para imports
sys.path.insert(0, str(Path(__file__).parent))

from data.db import get_consolidated_data, get_price_data, get_all_symbols, get_latest_close
import pandas as pd


def test_db():
    print("=" * 60)
    print("🧪 TEST: Integración de BD Centralizada")
    print("=" * 60)
    
    # Test 1: Símbolos en BD
    print("\n1️⃣  Símbolos en BD:")
    symbols = get_all_symbols()
    symbols_clean = [s for s in symbols if s != "ALL"]
    print(f"   ✅ {len(symbols_clean)} símbolos encontrados: {', '.join(symbols_clean[:5])}...")
    
    # Test 2: Datos consolidados
    print("\n2️⃣  Datos consolidados (Symbol, Date, Close):")
    consolidated = get_consolidated_data()
    print(f"   ✅ {len(consolidated)} filas totales")
    print(f"   Rango de fechas: {consolidated['Date'].min()} a {consolidated['Date'].max()}")
    print(f"   Primeras filas:\n{consolidated.head(3)}")
    
    # Test 3: Datos por símbolo
    print("\n3️⃣  Lectura específica (NVDA):")
    nvda = get_price_data(symbol="NVDA")
    print(f"   ✅ {len(nvda)} filas para NVDA")
    print(f"   Últimas 3 filas:\n{nvda.tail(3)[['symbol', 'date', 'close']]}")
    
    # Test 4: Último cierre
    print("\n4️⃣  Último cierre (SPY):")
    spy_last = get_latest_close("SPY")
    if spy_last:
        date, close = spy_last
        print(f"   ✅ SPY: ${close:.2f} ({date})")
    else:
        print("   ⚠️  SPY no encontrado")
    
    # Test 5: Rango de fechas
    print("\n5️⃣  Datos en rango (2026-01-01 a 2026-03-31):")
    range_data = get_price_data(start_date="2026-01-01", end_date="2026-03-31")
    print(f"   ✅ {len(range_data)} filas en Q1 2026")
    
    print("\n" + "=" * 60)
    print("✅ Todos los tests pasaron. BD centralizada funcionando.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        test_db()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
