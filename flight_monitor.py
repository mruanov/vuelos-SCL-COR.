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
        # Usamos un contexto con idioma español y ventana grande para forzar una interfaz consistente
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            locale="es-CL"
        )
        page = context.new_page()
        print(f"Buscando en Google Flights: {url}")
        
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            time.sleep(10) # Espera generosa para carga de precios dinámicos
            
            # Intentar múltiples selectores conocidos de Google Flights
            selectors = [
                ".MJ7yc .JMc5Xc",  # Precio en lista principal
                ".YMlS1e",         # Precio destacado
                "span[role='text']", # Respaldo de accesibilidad
                "div[aria-label*='pesos']",
                ".pI9Wbc"          # Selector antiguo
            ]
            
            for selector in selectors:
                precios = page.query_selector_all(selector)
                for p_elem in precios:
                    texto = p_elem.inner_text()
                    if any(c in texto for c in ["$", "CLP", "USD"]):
                        print(f"Precio detectado con {selector}: {texto}")
                        browser.close()
                        return {"plataforma": "Google Flights", "precio": texto, "url": url}
            
            # Si llegamos aquí, falló la extracción
            page.screenshot(path="error_capture.png")
            print("No se encontró ningún formato de precio. Screenshot guardado.")
            enviar_alerta("⚠️ El bot no pudo extraer el precio en esta vuelta. Es posible que Google haya cambiado el diseño o esté bloqueando la visualización. Revisaré el código.")
            
        except Exception as e:
            print(f"Error crítico en Google Flights: {e}")
            enviar_alerta(f"❌ Error técnico en el bot: {str(e)[:100]}")
        
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
