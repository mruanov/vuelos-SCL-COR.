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
MAX_DURACION_MINUTOS = 360  # 6 horas (360 min)

# Credenciales
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_alerta(mensaje):
    print(f"Enviando alerta a Telegram...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram no configurado. Mensaje:\n{mensaje}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"✈️ MONITOR DE VUELOS ✈️\n\n{mensaje}"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

def parse_price_robust(text):
    if not text: return float('inf')
    nums = re.findall(r'\d+', text.replace('.', '').replace(',', ''))
    if nums:
        val = int(nums[0])
        if val > 5000:
            return val / 950
        return val
    return float('inf')

def extract_total_minutes(text):
    if not text: return 9999
    text = text.lower()
    h = 0
    m = 0
    h_match = re.search(r'(\d+)\s*(h|hour|hora|hr)', text)
    m_match = re.search(r'(\d+)\s*(m|min|minuto)', text)
    if h_match: h = int(h_match.group(1))
    if m_match: m = int(m_match.group(1))
    if h > 0 or m > 0:
        return h * 60 + m
    hm_match = re.search(r'(\d{1,2}):(\d{2})', text)
    if hm_match:
        return int(hm_match.group(1)) * 60 + int(hm_match.group(2))
    return 9999

def scrape_platform(name, url, item_selector, price_selector=None, locale="es-CL"):
    print(f"Buscando en {name}...")
    results = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 800},
                locale=locale
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(15)
            try: page.click("button:has-text('Aceptar'), button:has-text('Accept')", timeout=3000)
            except: pass
            items = page.query_selector_all(item_selector)
            for item in items:
                text = item.inner_text()
                if not text: continue
                dur_min = extract_total_minutes(text)
                has_price_sign = any(s in text.lower() for s in ["$", "clp", "usd", "pesos", "desde"])
                if dur_min <= MAX_DURACION_MINUTOS and has_price_sign:
                    precio_str = "N/A"
                    if price_selector:
                        p_elem = item.query_selector(price_selector)
                        if p_elem: precio_str = p_elem.inner_text()
                    if precio_str == "N/A":
                        p_match = re.search(r'(\d+[\.\,]\d+)', text)
                        if p_match: precio_str = p_match.group(0)
                        else:
                            p_match = re.search(r'(\d{5,})', text)
                            if p_match: precio_str = p_match.group(0)
                    results.append({
                        "plataforma": name,
                        "precio": precio_str,
                        "precio_usd": parse_price_robust(precio_str),
                        "duracion": f"{dur_min//60}h {dur_min%60}m",
                        "url": url
                    })
                    break
            browser.close()
        except Exception as e:
            print(f"  ❌ Error en {name}: {e}")
    return results[0] if results else None

def monitor():
    google_url = f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}"
    kayak_url = f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a"
    latam_url = f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false"
    sky_url = f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0"
    kiwi_url = f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}"

    final_results = []
    res = scrape_platform("Google Flights", google_url, "[role='listitem'], .pI9Wbc")
    if res: final_results.append(res)
    res = scrape_platform("Kayak", kayak_url, ".nrc6, .resultInner, [class*='resultWrapper']")
    if res: final_results.append(res)
    res = scrape_platform("LATAM", latam_url, "li[class*='FlightItem'], [class*='FlightCard']")
    if res: final_results.append(res)
    res = scrape_platform("SKY", sky_url, ".flight-item, [class*='FlightCard'], .card-vuelo")
    if res: final_results.append(res)
    res = scrape_platform("Kiwi.com", kiwi_url, "[data-test='ResultCardWrapper']", locale="en-US")
    if res: final_results.append(res)

    if not final_results:
        enviar_alerta("No encontré vuelos de menos de 6 horas en esta vuelta. Seguiré buscando. 🫡")
        return

    mejor = min(final_results, key=lambda x: x['precio_usd'])
    detalle = "\n".join([f"- {r['plataforma']}: {r['precio']} ({r['duracion']})" for r in final_results])
    mensaje = f"🌟 MEJOR VUELO (<6h): {mejor['plataforma']} 🌟\n💰 Precio: {mejor['precio']} (~{mejor['precio_usd']:.2f} USD)\n🕒 Duración: {mejor['duracion']}\n🔗 Link: {mejor['url']}\n\n📋 Otras opciones válidas:\n{detalle}"
    enviar_alerta(mensaje)

if __name__ == "__main__":
    monitor()
