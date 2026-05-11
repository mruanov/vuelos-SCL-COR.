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
    print(f"Intentando enviar alerta a Telegram...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ ERROR: No hay credenciales de Telegram configuradas en las variables de entorno.")
        print(f"Contenido del mensaje que no se envió: {mensaje}")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"✈️ ¡ALERTA DE VUELO! ✈️\n\n{mensaje}"}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Mensaje enviado exitosamente a Telegram.")
        else:
            print(f"❌ Error de Telegram (Status {response.status_code}): {response.text}")
    except Exception as e:
        print(f"❌ Error de red al contactar a Telegram: {e}")

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

def scrape_kayak():
    url = f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-CL"
        )
        page = context.new_page()
        print(f"Buscando en Kayak: {url}")
        
        try:
            # Kayak puede ser lento, esperamos a que cargue el contenido principal
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(15)
            
            # Intentar varios selectores de precio comunes en Kayak
            kayak_selectors = [".f8F1-price", ".price-text", "div[class*='price-text']", ".O3uT-price-text"]
            
            for selector in kayak_selectors:
                precio_elem = page.query_selector(selector)
                if precio_elem:
                    texto = precio_elem.inner_text()
                    if "$" in texto or "CLP" in texto:
                        print(f"Precio detectado en Kayak con {selector}: {texto}")
                        browser.close()
                        return {"plataforma": "Kayak", "precio": texto, "url": url}
            
            print("No se encontró el precio en Kayak tras varios intentos.")
        except Exception as e:
            print(f"Error en Kayak: {e}")
        
        browser.close()
    return None

def scrape_skyscanner():
    url = f"https://www.skyscanner.cl/transport/vuelos/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}/?adultsv2=1&sortby=price"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Usamos un contexto más "humano" para Skyscanner
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            locale="es-CL"
        )
        page = context.new_page()
        print(f"Buscando en Skyscanner: {url}")
        
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            # Intentar mover el mouse o hacer scroll para parecer humano
            page.mouse.move(100, 100)
            time.sleep(25) # Espera larga para que Skyscanner procese
            
            # Selector más profundo para el precio de Skyscanner
            # Buscamos el texto que contiene "$" o "CLP" dentro de las tarjetas de resultados
            price_elements = page.query_selector_all("span[class*='Price_mainPrice']")
            if not price_elements:
                price_elements = page.query_selector_all("div[class*='price-container'] span")

            if price_elements:
                texto = price_elements[0].inner_text()
                print(f"Precio detectado en Skyscanner: {texto}")
                browser.close()
                return {"plataforma": "Skyscanner", "precio": texto, "url": url}
            
            print("No se encontraron resultados en Skyscanner.")
        except Exception as e:
            print(f"Error en Skyscanner: {e}")
        
        browser.close()
    return None

def scrape_latam():
    # URL directa de búsqueda en LATAM
    url = f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-CL"
        )
        page = context.new_page()
        print(f"Buscando en LATAM: {url}")
        
        try:
            page.goto(url, wait_until="networkidle", timeout=90000)
            time.sleep(15)
            
            # LATAM usa selectores específicos para sus precios en la grilla
            precio_elem = page.query_selector(".display-currencystyle__CurrencyAmount-sc__sc-19mloyt-2")
            if not precio_elem:
                precio_elem = page.query_selector("span[class*='CurrencyAmount']")

            if precio_elem:
                texto = precio_elem.inner_text()
                print(f"Precio detectado en LATAM: {texto}")
                browser.close()
                return {"plataforma": "LATAM", "precio": texto, "url": url}
        except Exception as e:
            print(f"Error en LATAM: {e}")
        
        browser.close()
    return None

def scrape_sky():
    # URL directa de búsqueda en SKY
    url = f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            locale="es-CL"
        )
        page = context.new_page()
        print(f"Buscando en SKY: {url}")
        
        try:
            page.goto(url, wait_until="networkidle", timeout=90000)
            time.sleep(15)
            
            # Selector de precio en SKY (clases de precio final)
            precio_elem = page.query_selector(".price-amount")
            if not precio_elem:
                precio_elem = page.query_selector("span[class*='amount']")

            if precio_elem:
                texto = precio_elem.inner_text()
                print(f"Precio detectado en SKY: {texto}")
                browser.close()
                return {"plataforma": "SKY Airline", "precio": texto, "url": url}
        except Exception as e:
            print(f"Error en SKY: {e}")
        
        browser.close()
    return None

def monitor():
    resultados = []
    
    # 1. Google Flights
    res_google = scrape_google_flights()
    if res_google:
        res_google['precio_usd'] = parse_price(res_google['precio'])
        resultados.append(res_google)
    
    # 2. Kayak
    res_kayak = scrape_kayak()
    if res_kayak:
        res_kayak['precio_usd'] = parse_price(res_kayak['precio'])
        resultados.append(res_kayak)
        
    # 3. Skyscanner
    res_skyscanner = scrape_skyscanner()
    if res_skyscanner:
        res_skyscanner['precio_usd'] = parse_price(res_skyscanner['precio'])
        resultados.append(res_skyscanner)
        
    # 4. LATAM
    res_latam = scrape_latam()
    if res_latam:
        res_latam['precio_usd'] = parse_price(res_latam['precio'])
        resultados.append(res_latam)
        
    # 5. SKY Airline
    res_sky = scrape_sky()
    if res_sky:
        res_sky['precio_usd'] = parse_price(res_sky['precio'])
        resultados.append(res_sky)

    if not resultados:
        enviar_alerta("⚠️ No se pudieron obtener precios de ninguna plataforma en esta vuelta.")
        return

    # Encontrar el mejor resultado
    mejor_opcion = min(resultados, key=lambda x: x['precio_usd'])
    
    print(f"Mejor opción encontrada: {mejor_opcion['plataforma']} a ~{mejor_opcion['precio_usd']:.2f} USD")
    
    # Detalle de todas las plataformas para el log (opcional enviarlo por Telegram si quieres)
    detalle = "\n".join([f"- {r['plataforma']}: {r['precio']}" for r in resultados])
    
    if mejor_opcion['precio_usd'] <= META_PRECIO:
        enviar_alerta(f"🔥 ¡OFERTA ENCONTRADA EN {mejor_opcion['plataforma'].upper()}! 🔥\n\nPrecio: {mejor_opcion['precio']} (~{mejor_opcion['precio_usd']:.2f} USD)\n\nLink: {mejor_opcion['url']}\n\nResumen:\n{detalle}")
    else:
        enviar_alerta(f"📊 La mejor opción es en {mejor_opcion['plataforma']}: {mejor_opcion['precio']} (~{mejor_opcion['precio_usd']:.2f} USD).\n\nSeguiré monitoreando las 5 plataformas por ti. 🫡\n\nPrecios actuales:\n{detalle}")

if __name__ == "__main__":
    monitor()
