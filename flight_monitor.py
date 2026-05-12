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
    print(f"Enviando alerta a Telegram...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Sin Telegram. Mensaje: {mensaje}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"✈️ ¡MONITOR DE VUELOS! ✈️\n\n{mensaje}"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

def parse_price(text):
    if not text: return float('inf')
    clean = "".join(re.findall(r'\d+', text.replace('.', '').replace(',', '')))
    if clean:
        val = int(clean)
        return val / 950 if val > 5000 else val
    return float('inf')

def extract_duration_minutes(text):
    if not text: return None
    text = text.lower()
    hm = re.search(r'(\d+):(\d+)', text)
    if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
    h = 0
    m = 0
    h_match = re.search(r'(\d+)\s*(h|hour|hora|hr)', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*(m|min|minuto)', text)
    if m_match: m = int(m_match.group(1))
    if h == 0 and m == 0: return None
    return h * 60 + m

def scrape_google_flights():
    url = f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="es-CL")
        print(f"Buscando en Google Flights...")
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            time.sleep(5)
            items = page.query_selector_all("[role='listitem']")
            for item in items:
                text = item.inner_text()
                if not any(c in text for c in ["$", "CLP", "USD"]): continue
                dur = extract_duration_minutes(text)
                if dur and dur <= MAX_DURACION_MINUTOS:
                    precio = re.search(r'[\d\.\,]{3,}', text.replace('$', '').replace('CLP', ''))
                    if precio:
                        browser.close()
                        return {"plataforma": "Google Flights", "precio": precio.group(0), "duracion": f"{dur//60}h {dur%60}m", "url": url}
            print("Google Flights: Sin vuelos < 6h.")
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
            time.sleep(10)
            cards = page.query_selector_all(".nrc6, .resultInner, [role='listitem']")
            for card in cards:
                text = card.inner_text()
                dur = extract_duration_minutes(text)
                if dur and dur <= MAX_DURACION_MINUTOS:
                    price_elem = card.query_selector(".f8F1-price, .price-text, .O3uT-price-text")
                    if price_elem:
                        browser.close()
                        return {"plataforma": "Kayak", "precio": price_elem.inner_text(), "duracion": f"{dur//60}h {dur%60}m", "url": url}
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
            page.goto(url, wait_until="networkidle", timeout=90000)
            time.sleep(10)
            flights = page.query_selector_all("li[class*='FlightItem'], [class*='FlightCard']")
            for f in flights:
                text = f.inner_text()
                dur = extract_duration_minutes(text)
                if dur and dur <= MAX_DURACION_MINUTOS:
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
            page.goto(url, wait_until="networkidle", timeout=90000)
            time.sleep(10)
            cards = page.query_selector_all(".flight-item, .card-vuelo, [class*='FlightCard']")
            for c in cards:
                text = c.inner_text()
                dur = extract_duration_minutes(text)
                if dur and dur <= MAX_DURACION_MINUTOS:
                    price = c.query_selector(".price-amount, .amount, [class*='Price']")
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
            try: page.click("button:has-text('Accept')", timeout=5000)
            except: pass
            time.sleep(10)
            results = page.query_selector_all("[data-test='ResultCardWrapper']")
            for res in results:
                text = res.inner_text()
                durations = re.findall(r'(\d+h\s*\d+m|\d+h|\d+m|\d+\s*hour|\d+\s*min)', text.lower())
                minutes = [extract_duration_minutes(d) for d in durations if extract_duration_minutes(d)]
                if minutes and all(m <= MAX_DURACION_MINUTOS for m in minutes):
                    price = res.query_selector("[data-test='ResultCardPrice']")
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
            print(f"❌ {s.__name__} sin resultados.")

    if not resultados:
        enviar_alerta("⚠️ No se encontraron vuelos de < 6h en ninguna plataforma.")
        return

    mejor = min(resultados, key=lambda x: x['precio_usd'])
    detalle = "\n".join([f"- {r['plataforma']}: {r['precio']} ({r['duracion']})" for r in resultados])
    msg = f"🌟 MEJOR OPCIÓN: {mejor['plataforma']} 🌟\n💰 Precio: {mejor['precio']} (~{mejor['precio_usd']:.2f} USD)\n🕒 Duración: {mejor['duracion']}\n🔗 Link: {mejor['url']}\n\n📋 Otros resultados (< 6h):\n{detalle}"
    enviar_alerta(msg)

if __name__ == "__main__":
    monitor()
