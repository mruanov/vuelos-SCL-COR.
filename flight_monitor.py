import time
import requests
import os
import re
from playwright.sync_api import sync_playwright

# Configuración
ORIGEN = "SCL"
DESTINO = "COR"
FECHA_IDA = "2026-10-09"
FECHA_VUELTA = "2026-10-12"
META_PRECIO = 200
MAX_DURACION_MINUTOS = 360  # 6 horas máximo por tramo

# Credenciales
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_alerta(mensaje):
    print(f"Intentando enviar alerta a Telegram...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ ERROR: No hay credenciales de Telegram configuradas.")
        print(f"Contenido: {mensaje}")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"✈️ ¡MONITOR DE VUELOS! ✈️\n\n{mensaje}"}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Mensaje enviado exitosamente a Telegram.")
        else:
            print(f"❌ Error de Telegram (Status {response.status_code}): {response.text}")
    except Exception as e:
        print(f"❌ Error de red: {e}")

def parse_price(text):
    if not text: return float('inf')
    clean_text = text.replace('.', '').replace(',', '').replace('$', '').replace('CLP', '').strip()
    numbers = re.findall(r'\d+', clean_text)
    if numbers:
        val = int(numbers[0])
        if val > 5000: # Asumimos CLP
            return val / 950
        return val
    return float('inf')

def parse_duration(text):
    if not text: return 9999
    text = text.lower().replace(' ', '')
    hours = 0
    minutes = 0
    h_match = re.search(r'(\d+)h', text)
    m_match = re.search(r'(\d+)m', text)
    hm_match = re.search(r'(\d+):(\d+)', text)
    
    if h_match:
        hours = int(h_match.group(1))
    if m_match:
        minutes = int(m_match.group(1))
    if not h_match and not m_match and hm_match:
        hours = int(hm_match.group(1))
        minutes = int(hm_match.group(2))
        
    if hours == 0 and minutes == 0:
        return 9999
    return hours * 60 + minutes

def scrape_google_flights():
    url = f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36", locale="es-CL")
        page = context.new_page()
        print(f"Buscando en Google Flights: {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            time.sleep(5)
            flights = page.query_selector_all("[role='listitem']")
            for flight in flights:
                text = flight.inner_text()
                if not text or ("$" not in text and "CLP" not in text): continue
                dur_match = re.search(r'(\d+ h \d+ min|\d+ h|\d+ min)', text)
                duracion_str = dur_match.group(0) if dur_match else ""
                if parse_duration(duracion_str) <= MAX_DURACION_MINUTOS:
                    precio_match = re.search(r'(CLP|USD|\$)\s*[\d\.\,]+', text)
                    if precio_match:
                        browser.close()
                        return {"plataforma": "Google Flights", "precio": precio_match.group(0), "duracion": duracion_str, "url": url}
        except Exception as e:
            print(f"Error Google Flights: {e}")
        browser.close()
    return None

def scrape_kayak():
    url = f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36", locale="es-CL")
        page = context.new_page()
        print(f"Buscando en Kayak: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(10)
            results = page.query_selector_all(".nrc6, .resultInner, [class*='resultWrapper']") 
            for res in results:
                text = res.inner_text()
                dur_match = re.search(r'(\d+h\s*\d+m|\d+h|\d+m)', text)
                duracion_str = dur_match.group(0) if dur_match else ""
                if parse_duration(duracion_str) <= MAX_DURACION_MINUTOS:
                    precio_elem = res.query_selector(".f8F1-price, .price-text, .O3uT-price-text")
                    if precio_elem:
                        browser.close()
                        return {"plataforma": "Kayak", "precio": precio_elem.inner_text(), "duracion": duracion_str, "url": url}
        except Exception as e:
            print(f"Error Kayak: {e}")
        browser.close()
    return None

def scrape_latam():
    url = f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36", locale="es-CL")
        page = context.new_page()
        print(f"Buscando en LATAM: {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=90000)
            time.sleep(10)
            items = page.query_selector_all("li[class*='FlightItem'], [class*='sc-fLcnxK']")
            for item in items:
                text = item.inner_text()
                dur_match = re.search(r'(\d+ h \d+ min|\d+ h|\d+ min)', text)
                duracion_str = dur_match.group(0) if dur_match else ""
                if parse_duration(duracion_str) <= MAX_DURACION_MINUTOS:
                    precio_elem = item.query_selector("span[class*='CurrencyAmount']")
                    if precio_elem:
                        browser.close()
                        return {"plataforma": "LATAM", "precio": precio_elem.inner_text(), "duracion": duracion_str, "url": url}
        except Exception as e:
            print(f"Error LATAM: {e}")
        browser.close()
    return None

def scrape_sky():
    url = f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36", locale="es-CL")
        page = context.new_page()
        print(f"Buscando en SKY: {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=90000)
            time.sleep(10)
            flights = page.query_selector_all(".flight-item, .card-vuelo, [class*='FlightCard']")
            for f in flights:
                text = f.inner_text()
                dur_match = re.search(r'(\d+h\s*\d+m|\d+h|\d+m)', text)
                duracion_str = dur_match.group(0) if dur_match else ""
                if parse_duration(duracion_str) <= MAX_DURACION_MINUTOS:
                    precio_elem = f.query_selector(".price-amount, .amount, [class*='Price']")
                    if precio_elem:
                        browser.close()
                        return {"plataforma": "SKY Airline", "precio": precio_elem.inner_text(), "duracion": duracion_str, "url": url}
        except Exception as e:
            print(f"Error SKY: {e}")
        browser.close()
    return None

def scrape_kiwi():
    url = f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36", locale="en-US")
        page = context.new_page()
        print(f"Buscando en Kiwi.com: {url}")
        try:
            page.goto(url, wait_until="networkidle", timeout=90000)
            try:
                page.click("button:has-text('Accept')", timeout=5000)
            except: pass
            time.sleep(10)
            results = page.query_selector_all("[data-test='ResultCardWrapper']")
            for res in results:
                text = res.inner_text()
                durations = re.findall(r'(\d+h\s*\d+m|\d+h|\d+m)', text)
                if durations and all(parse_duration(d) <= MAX_DURACION_MINUTOS for d in durations):
                    precio_elem = res.query_selector("[data-test='ResultCardPrice']")
                    if precio_elem:
                        browser.close()
                        return {"plataforma": "Kiwi.com", "precio": precio_elem.inner_text(), "duracion": ", ".join(durations), "url": url}
        except Exception as e:
            print(f"Error Kiwi: {e}")
        browser.close()
    return None

def scrape_skyscanner():
    url = f"https://www.skyscanner.cl/transport/vuelos/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}/?adultsv2=1&sortby=price"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36", locale="es-CL")
        page = context.new_page()
        print(f"Buscando en Skyscanner: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            time.sleep(20)
            cards = page.query_selector_all("div[class*='Ticket_wrapper'], [class*='FlightsTicket']")
            for card in cards:
                text = card.inner_text()
                durations = re.findall(r'(\d+\s*h\s*\d+\s*min|\d+\s*h|\d+\s*min)', text)
                if durations and all(parse_duration(d) <= MAX_DURACION_MINUTOS for d in durations):
                    precio_elem = card.query_selector("span[class*='Price_mainPrice'], [class*='PriceText']")
                    if precio_elem:
                        browser.close()
                        return {"plataforma": "Skyscanner", "precio": precio_elem.inner_text(), "duracion": ", ".join(durations), "url": url}
        except Exception as e:
            print(f"Error Skyscanner: {e}")
        browser.close()
    return None

def monitor():
    scrapers = [scrape_google_flights, scrape_kayak, scrape_latam, scrape_sky, scrape_kiwi, scrape_skyscanner]
    resultados = []
    for scraper in scrapers:
        try:
            res = scraper()
            if res:
                res['precio_usd'] = parse_price(res['precio'])
                if res['precio_usd'] != float('inf'):
                    resultados.append(res)
                    print(f"✅ {res['plataforma']}: {res['precio']} ({res['duracion']})")
            else:
                print(f"❌ {scraper.__name__} sin resultados.")
        except Exception as e:
            print(f"Error {scraper.__name__}: {e}")

    if not resultados:
        enviar_alerta("⚠️ No se encontraron vuelos de < 6h en esta vuelta.")
        return

    mejor = min(resultados, key=lambda x: x['precio_usd'])
    detalle = "\n".join([f"- {r['plataforma']}: {r['precio']} ({r['duracion']})" for r in resultados])
    msg = f"🌟 MEJOR OPCIÓN: {mejor['plataforma']} 🌟\n💰 Precio: {mejor['precio']} (~{mejor['precio_usd']:.2f} USD)\n🕒 Duración: {mejor['duracion']}\n🔗 Link: {mejor['url']}\n\n📋 Otros resultados (< 6h):\n{detalle}"
    enviar_alerta(msg)

if __name__ == "__main__":
    monitor()
