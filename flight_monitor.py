import time
import requests
import os
from playwright.sync_api import sync_playwright

# Configuración
ORIGEN = "SCL"
DESTINO = "COR"
FECHA_IDA = "2026-10-09"
FECHA_VUELTA = "2026-10-12"
META_PRECIO = 200

# Credenciales (Se pueden pasar como variables de entorno)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_alerta(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ No hay credenciales de Telegram configuradas.")
        print(f"ALERTA: {mensaje}")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"✈️ ¡ALERTA DE VUELO! ✈️\n\n{mensaje}"}
    requests.post(url, json=payload)

def scrape_google_flights():
    url = f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"Buscando en Google Flights: {url}")
        page.goto(url)
        
        # Esperar a que carguen los resultados
        try:
            # Esperar a que aparezca al menos un resultado de vuelo
            page.wait_for_selector("li", timeout=30000) 
            time.sleep(5) 
            
            # Tomar screenshot para debug
            page.screenshot(path="debug_flights.png")
            print("Screenshot guardado como debug_flights.png")
            
            # Buscar el primer precio dentro de los resultados
            precios = page.query_selector_all(".YMlS1e")
            if not precios:
                precios = page.query_selector_all("[aria-label*='Chilean pesos']")
            
            if precios:
                texto_precio = precios[0].inner_text()
                print(f"Precio detectado en Google Flights: {texto_precio}")
                return {"plataforma": "Google Flights", "precio": texto_precio, "url": url}
            else:
                print("No se encontraron elementos de precio.")
        except Exception as e:
            page.screenshot(path="error_flights.png")
            print(f"Error en Google Flights: {e}. Screenshot de error guardado.")
        
        browser.close()
    return None

import re

def parse_price(text):
    # Eliminar símbolos de moneda y puntos/comas de miles
    # Ejemplo: "$180.000" -> 180000, "US$ 200" -> 200
    # Asumimos que si es mayor a 5000 es CLP, si es menor es USD/EUR
    numbers = re.findall(r'\d+', text.replace('.', '').replace(',', ''))
    if numbers:
        val = int(numbers[0])
        # Conversión simple si detectamos CLP (aprox 950 por 1 USD)
        if val > 5000:
            return val / 950
        return val
    return float('inf')

def monitor():
    resultados = []
    
    res_google = scrape_google_flights()
    if res_google:
        precio_usd = parse_price(res_google['precio'])
        print(f"[Google Flights] Precio parseado: ~{precio_usd:.2f} USD")
        
        if precio_usd <= META_PRECIO:
            enviar_alerta(f"🔥 ¡OFERTA ENCONTRADA! 🔥\n\nPlataforma: Google Flights\nPrecio: {res_google['precio']} (~{precio_usd:.2f} USD)\n\n¡Es un excelente momento para comprar!\n\nLink: {res_google['url']}")
        else:
            enviar_alerta(f"📊 Actualización de Búsqueda\n\nEl precio más bajo encontrado es de {res_google['precio']} (~{precio_usd:.2f} USD).\n\nTodavía está por encima de nuestra meta de {META_PRECIO} USD. Seguiré buscando 3 veces al día para encontrar el mejor precio para ti. 🫡")
    else:
        print("No se pudieron obtener resultados en esta ejecución.")

if __name__ == "__main__":
    monitor()
