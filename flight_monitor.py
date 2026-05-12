import time
import requests
import os
import re
import random
from playwright.sync_api import sync_playwright

# --- CONFIGURACIÓN ESTRICTA ---
ORIGEN = "SCL"
DESTINO = "COR"
FECHA_IDA = "2026-10-09"
FECHA_VUELTA = "2026-10-12"
MAX_DURACION_MINUTOS = 360 # 6 Horas

# --- TELEGRAM ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    requests.post(url, json=payload, timeout=20)

def get_minutes_robust(text):
    if not text: return 9999
    text = text.lower().replace(',', '')
    h, m = 0, 0
    h_match = re.search(r'(\d+)\s*(?:h|hour|hora|hr)', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*(?:m|min|minuto)', text)
    if m_match: m = int(m_match.group(1))
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2}):(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
    total = h * 60 + m
    return total if total > 30 else 9999

def scrape_direct(p, name, url, item_selector):
    print(f"✈️ Entrando directamente a {name}...")
    valid_flights = []
    try:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            locale="es-CL"
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        
        # Espera paciente para carga de precios internos
        time.sleep(25)
        page.evaluate("window.scrollTo(0, 600)")
        
        items = page.query_selector_all(item_selector)
        print(f"   -> {name}: {len(items)} elementos detectados.")

        for item in items:
            inner = item.inner_text()
            if not any(s in inner.lower() for s in ["$", "clp", "usd", "pesos", "desde"]): continue
            
            # Extraer duraciones del bloque
            dur_matches = re.findall(r'(\d+\s*h\s*\d+\s*min|\d+\s*h|\d+\s*m|\d{1,2}:\d{2})', inner.lower())
            mins = [get_minutes_robust(d) for d in dur_matches if get_minutes_robust(d) < 1440]
            
            # Extraer precio
            p_match = re.search(r'(?:\$|CLP|USD|pesos)?\s?(\d+[\.\,]\d{3})', inner)
            if not p_match: p_match = re.search(r'(\d{5,})', inner)
            
            if p_match and mins:
                p_str = p_match.group(0).strip()
                p_val_raw = int(re.sub(r'[^\d]', '', p_str))
                p_val_usd = p_val_raw / 950 if p_val_raw > 5000 else p_val_raw
                
                # Filtro Estricto: Todos los tramos < 6h
                if all(m <= MAX_DURACION_MINUTOS for m in mins):
                    valid_flights.append({
                        "airline": name,
                        "price_str": p_str,
                        "price_val": p_val_usd,
                        "dur": " / ".join([f"{m//60}h {m%60}m" for m in mins]),
                        "url": url
                    })
        
        browser.close()
    except Exception as e:
        print(f"   ⚠️ Error en {name}: {str(e)[:50]}")
    
    return min(valid_flights, key=lambda x: x["price_val"]) if valid_flights else None

def monitor():
    with sync_playwright() as p:
        # Búsquedas Directas en cada portal
        targets = [
            ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[class*='FlightItem'], .sc-fLcnxK"),
            ("SKY", f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0", ".flight-item, [class*='FlightCard']"),
            ("Aerolíneas Arg.", f"https://www.aerolineas.com.ar/search/vuelos/SCL/COR?date1=09-10-2026&date2=12-10-2026&adults=1&children=0&infants=0", ".flight-card, [class*='result']"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']"),
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper']"),
            ("Hopper (Web)", f"https://www.hopper.com/search/flights/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "div[class*='ResultCard']")
        ]

        results = []
        for name, url, sel in targets:
            res = scrape_direct(p, name, url, sel)
            if res: results.append(res)

        if not results:
            enviar_telegram("🔄 *Monitor Individual*: No se detectaron vuelos de menos de 6 horas entrando directamente a las aerolíneas. Seguiré re-intentando. 🫡")
            return

        results.sort(key=lambda x: x["price_val"])
        
        mensaje = "✈️ *REPORTE DE BÚSQUEDA DIRECTA* ✈️\n\n"
        for r in results:
            mensaje += f"✅ *{r['airline']}*\n"
            mensaje += f"💰 Precio: *{r['price_str']}*\n"
            mensaje += f"⏱️ Duración: {r['dur']}\n"
            mensaje += f"🔗 [Link Directo]({r['url']})\n\n"

        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
