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
        print(f"⚠️ Sin Telegram.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"📋 REPORTE DE VUELOS 📋\n\n{mensaje}", "disable_web_page_preview": True, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)

def parse_price(text):
    nums = re.findall(r'\d+', text.replace('.', '').replace(',', ''))
    return int(nums[0]) if nums else 999999

def get_minutes(text):
    """Extrae minutos de formatos como '1h 30m', '1:30', '90 min'"""
    text = text.lower()
    h = 0
    m = 0
    h_match = re.search(r'(\d+)\s*h', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*m', text)
    if m_match: m = int(m_match.group(1))
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2}):(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
    return h * 60 + m

def scrape_site(name, url, card_selector):
    print(f"Buscando en {name}...")
    best_flight = None
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=60000)
            
            # Simular scroll para cargar contenido dinámico
            for _ in range(3):
                page.mouse.wheel(0, 500)
                time.sleep(2)
            
            time.sleep(10)
            cards = page.query_selector_all(card_selector)
            
            flights_found = []
            for card in cards:
                text = card.inner_text()
                if not any(s in text.lower() for s in ["$", "clp", "usd", "pesos"]): continue
                
                # Extraer precio (limpiando formatos comunes)
                price_match = re.search(r'[\d\.\,]{4,}', text)
                if not price_match: continue
                
                price_str = price_match.group(0)
                price_val = parse_price(price_str)
                
                # Extraer duraciones
                dur_matches = re.findall(r'(\d+\s*h\s*\d+\s*m|\d+\s*h|\d+\s*m|\d{1,2}:\d{2})', text.lower())
                durations = [get_minutes(d) for d in dur_matches if get_minutes(d) > 30]
                
                is_valid = len(durations) > 0 and all(d <= MAX_DURACION_MINUTOS for d in durations)
                
                flights_found.append({
                    "price": price_str,
                    "price_val": price_val,
                    "dur": ", ".join([f"{d//60}h {d%60}m" for d in durations]) if durations else "N/A",
                    "valid": is_valid
                })

            if flights_found:
                # El más barato de los encontrados
                flights_found.sort(key=lambda x: x["price_val"])
                best_flight = flights_found[0]
            
            browser.close()
        except Exception as e: print(f"  ❌ Error {name}: {e}")
    return best_flight

def monitor():
    configs = [
        ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
        ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", "[class*='resultWrapper']"),
        ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[class*='FlightItem']"),
        ("SKY", f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0", ".flight-item, [class*='FlightCard']"),
        ("Kiwi", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']")
    ]

    reporte = ""
    for name, url, selector in configs:
        res = scrape_site(name, url, selector)
        if res:
            emoji = "✅" if res["valid"] else "⏳"
            reporte += f"{emoji} *{name}*: ${res['price']}\n"
            reporte += f"⏱️ Duración: {res['dur']}\n"
            reporte += f"🔗 [Link al vuelo]({url})\n\n"
        else:
            reporte += f"❌ *{name}*: Sin resultados en esta vuelta.\n\n"

    enviar_alerta(reporte + "Leyenda: ✅ < 6h cada tramo | ⏳ > 6h o escala")

if __name__ == "__main__":
    monitor()
