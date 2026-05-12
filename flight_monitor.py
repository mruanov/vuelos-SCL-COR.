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
MAX_DURACION_MINUTOS = 360  # 6 horas

# Credenciales
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_alerta(mensaje):
    print(f"Enviando alerta a Telegram...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ No hay Telegram. Mensaje:\n{mensaje}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"✈️ MONITOR DE VUELOS ✈️\n\n{mensaje}"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

def parse_price(text):
    if not text: return float('inf')
    # Extraer números y limpiar
    nums = "".join(re.findall(r'\d+', text.replace('.', '').replace(',', '')))
    if nums:
        val = int(nums)
        return val / 950 if val > 5000 else val
    return float('inf')

def extract_minutes(text):
    """Convierte '2 h 30 min' o '5h 2m' a minutos"""
    if not text: return 9999
    text = text.lower()
    h = 0
    m = 0
    # Buscar horas
    h_match = re.search(r'(\d+)\s*(h|hour|hora)', text)
    if h_match: h = int(h_match.group(1))
    # Buscar minutos
    m_match = re.search(r'(\d+)\s*(m|min)', text)
    if m_match: m = int(m_match.group(1))
    
    if h == 0 and m == 0:
        # Intentar formato 00:00
        hm = re.search(r'(\d+):(\d+)', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
        return 9999
    return h * 60 + m

def scrape_google_flights():
    url = f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="es-CL")
        print(f"Buscando en Google Flights...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(8)
            items = page.query_selector_all("[role='listitem']")
            for item in items:
                text = item.inner_text()
                if not any(kw in text.lower() for kw in ["$", "clp", "usd", "pesos", "precio"]): continue
                
                dur = extract_minutes(text)
                if dur <= MAX_DURACION_MINUTOS:
                    # Encontrar el precio (el número más grande usualmente)
                    prices = re.findall(r'[\d\.\,]{4,}', text)
                    if prices:
                        browser.close()
                        return {"plataforma": "Google Flights", "precio": f"${prices[0]}", "duracion": f"{dur//60}h {dur%60}m", "url": url}
            print("Google Flights: Ningún vuelo cumplió el filtro de 6h.")
        except Exception as e: print(f"Error Google: {e}")
        browser.close()
    return None

def scrape_kayak():
    url = f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="es-CL")
        print(f"Buscando en Kayak...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(12)
            cards = page.query_selector_all(".nrc6, .resultInner, [class*='resultWrapper']")
            for card in cards:
                text = card.inner_text()
                dur = extract_minutes(text)
                if dur <= MAX_DURACION_MINUTOS:
                    p_elem = card.query_selector("[class*='price'], .f8F1-price")
                    if p_elem:
                        browser.close()
                        return {"plataforma": "Kayak", "precio": p_elem.inner_text(), "duracion": f"{dur//60}h {dur%60}m", "url": url}
        except Exception as e: print(f"Error Kayak: {e}")
        browser.close()
    return None

def scrape_latam():
    url = f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="es-CL")
        print(f"Buscando en LATAM...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(12)
            flights = page.query_selector_all("li[class*='FlightItem'], [class*='FlightCard']")
            for f in flights:
                text = f.inner_text()
                dur = extract_minutes(text)
                if dur <= MAX_DURACION_MINUTOS:
                    price = f.query_selector("span[class*='CurrencyAmount']")
                    if price:
                        browser.close()
                        return {"plataforma": "LATAM", "precio": price.inner_text(), "duracion": f"{dur//60}h {dur%60}m", "url": url}
        except Exception as e: print(f"Error LATAM: {e}")
        browser.close()
    return None

def scrape_sky():
    url = f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="es-CL")
        print(f"Buscando en SKY...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(15)
            items = page.query_selector_all(".flight-item, [class*='FlightCard']")
            for item in items:
                text = item.inner_text()
                dur = extract_minutes(text)
                if dur <= MAX_DURACION_MINUTOS:
                    price = item.query_selector(".price-amount, .amount, [class*='Price']")
                    if price:
                        browser.close()
                        return {"plataforma": "SKY", "precio": price.inner_text(), "duracion": f"{dur//60}h {dur%60}m", "url": url}
        except Exception as e: print(f"Error SKY: {e}")
        browser.close()
    return None

def scrape_kiwi():
    url = f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="en-US")
        print(f"Buscando en Kiwi.com...")
        try:
            page.goto(url, wait_until="networkidle", timeout=90000)
            time.sleep(10)
            cards = page.query_selector_all("[data-test='ResultCardWrapper']")
            for card in cards:
                text = card.inner_text().lower()
                durations = re.findall(r'(\d+h\s*\d+m|\d+h|\d+m)', text)
                mins = [extract_minutes(d) for d in durations]
                if mins and all(m <= MAX_DURACION_MINUTOS for m in mins):
                    price = card.query_selector("[data-test='ResultCardPrice']")
                    if price:
                        browser.close()
                        return {"plataforma": "Kiwi.com", "precio": price.inner_text(), "duracion": "Filtro OK", "url": url}
        except Exception as e: print(f"Error Kiwi: {e}")
        browser.close()
    return None

def monitor():
    scrapers = [scrape_google_flights, scrape_kayak, scrape_latam, scrape_sky, scrape_kiwi]
    resultados = []
    for s in scrapers:
        res = s()
        if res:
            res['precio_usd'] = parse_price(res['precio'])
            resultados.append(res)
            print(f"✅ {res['plataforma']}: {res['precio']} ({res['duracion']})")
        else:
            print(f"❌ {s.__name__} sin resultados válidos (<6h).")

    if not resultados:
        enviar_alerta("No se encontraron vuelos de menos de 6 horas en esta vuelta. Seguiré buscando. 🫡")
        return

    mejor = min(resultados, key=lambda x: x['precio_usd'])
    detalle = "\n".join([f"- {r['plataforma']}: {r['precio']} ({r['duracion']})" for r in resultados])
    msg = f"🌟 MEJOR OPCIÓN (<6h): {mejor['plataforma']} 🌟\n💰 Precio: {mejor['precio']} (~{mejor['precio_usd']:.2f} USD)\n🕒 Duración: {mejor['duracion']}\n🔗 Link: {mejor['url']}\n\n📋 Otros resultados válidos:\n{detalle}"
    enviar_alerta(msg)

if __name__ == "__main__":
    monitor()
