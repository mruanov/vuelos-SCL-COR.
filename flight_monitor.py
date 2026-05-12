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
MAX_DURACION_MINUTOS = 360

# Credenciales
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_alerta(mensaje):
    print(f"Enviando reporte a Telegram...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram no configurado.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"📋 REPORTE DE VUELOS 📋\n\n{mensaje}", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

def parse_price_robust(text):
    if not text: return 999999
    nums = re.findall(r'\d+', text.replace('.', '').replace(',', ''))
    if nums: return int(nums[0])
    return 999999

def get_durations(text):
    """Extrae todas las duraciones lógicas (> 1h) del texto"""
    found = []
    # Buscar formato Xh Ym
    matches = re.findall(r'(\d+)\s*h(?:our|ora|r)?\s*(?:(\d+)\s*m(?:in|inuto)?)?', text.lower())
    for h, m in matches:
        mins = int(h) * 60 + (int(m) if m else 0)
        if mins > 60: found.append(mins) # Ignoramos cosas de menos de 1h (escalas)
            
    # Buscar formato 00:00
    hm_matches = re.findall(r'(\d{1,2}):(\d{2})', text)
    for h, m in hm_matches:
        mins = int(h) * 60 + int(m)
        if 60 < mins < 1440: found.append(mins)
        
    return found

def scrape_platform(name, url, item_selector, locale="es-CL"):
    print(f"Buscando en {name}...")
    cheapest_flight = None
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0", locale=locale)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(15)
            
            items = page.query_selector_all(item_selector)
            for item in items:
                text = item.inner_text()
                if not text or not any(s in text.lower() for s in ["$", "clp", "usd", "pesos"]): continue
                
                # Extraer precio
                p_match = re.search(r'(\d+[\.\,]\d{3})|(\d{5,})', text)
                precio_val = parse_price_robust(p_match.group(0)) if p_match else 999999
                
                duraciones = get_durations(text)
                cumple_filtro = len(duraciones) > 0 and all(d <= MAX_DURACION_MINUTOS for d in duraciones)
                
                flight_data = {
                    "plataforma": name,
                    "precio": p_match.group(0) if p_match else "Ver link",
                    "precio_val": precio_val,
                    "duraciones_str": ", ".join([f"{d//60}h {d%60}m" for d in duraciones]),
                    "cumple": cumple_filtro,
                    "url": url
                }
                
                if not cheapest_flight or flight_data["precio_val"] < cheapest_flight["precio_val"]:
                    cheapest_flight = flight_data
            
            browser.close()
        except Exception as e: print(f"  ❌ Error en {name}: {e}")
    return cheapest_flight

def monitor():
    platforms = [
        ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
        ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, .resultInner"),
        ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[class*='FlightItem']"),
        ("SKY", f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0", ".flight-item, [class*='FlightCard']"),
        ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']"),
    ]

    reporte = ""
    for name, url, selector in platforms:
        res = scrape_platform(name, url, selector)
        if res:
            marca = "✅" if res["cumple"] else "⏳"
            reporte += f"{marca} *{name}*: ${res['precio']}\n"
            reporte += f"⏱️ Duración: {res['duraciones_str']}\n"
            reporte += f"🔗 [Ver Vuelo]({res['url']})\n\n"
        else:
            reporte += f"❌ *{name}*: No se detectaron resultados.\n\n"

    enviar_alerta(reporte + "Leyenda: ✅ < 6h cada tramo | ⏳ > 6h o escala larga")

if __name__ == "__main__":
    monitor()
