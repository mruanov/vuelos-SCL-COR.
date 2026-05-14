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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        print(f"Telegram not configured. Message: {mensaje[:100]}...")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code != 200:
            print(f"Error Telegram: {r.text}")
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

def get_minutes_robust(text):
    if not text: return 9999
    text = text.lower().replace(',', '').replace('.', '')
    h, m = 0, 0
    h_match = re.search(r'(\d+)\s*(?:hour|hora|hr|h)', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*(?:minuto|min|m)', text)
    if m_match: m = int(m_match.group(1))
    
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2}):(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
        
    total = h * 60 + m
    return total if total > 10 else 9999 

def scrape_direct(p, name, url, item_selector):
    print(f"✈️ Entrando a {name}...")
    valid_flights = []
    browser = None
    try:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            locale="es-CL"
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        time.sleep(25)
        page.evaluate("window.scrollTo(0, 800)")
        time.sleep(5)
        
        items = page.query_selector_all(item_selector)
        print(f"   -> {name}: {len(items)} elementos detectados.")

        for item in items:
            try:
                inner = item.inner_text()
                if not inner: continue
                if not any(s in inner.lower() for s in ["$", "clp", "usd", "pesos", "desde", "total", "ida y vuelta"]): continue
                
                dur_regex = r'(\d+\s*(?:hour|hora|hr|h|s)\s*\d*\s*(?:minuto|min|m|s)?|\d+\s*(?:minuto|min|m|s)|\d{1,2}:\d{2})'
                dur_matches = re.findall(dur_regex, inner.lower())
                mins = [get_minutes_robust(d) for d in dur_matches]
                mins = [m for m in mins if m < 1440]
                
                p_match = re.search(r'(?:\$|CLP|USD|pesos)?\s?(\d+[\.\,]\d{3})', inner)
                if not p_match: p_match = re.search(r'(\d{5,})', inner)
                
                if p_match and mins:
                    p_str = p_match.group(0).strip()
                    p_val_raw = int(re.sub(r'[^\d]', '', p_str))
                    p_val_usd = p_val_raw / 950 if p_val_raw > 10000 else p_val_raw
                    
                    if all(m <= MAX_DURACION_MINUTOS for m in mins):
                        valid_flights.append({
                            "airline": name,
                            "price_str": p_str,
                            "price_val": p_val_usd,
                            "dur": " / ".join([f"{m//60}h {m%60}m" for m in mins]),
                            "url": url
                        })
            except Exception:
                continue
    except Exception as e:
        print(f"   ⚠️ Error en {name}: {str(e)[:100]}")
    finally:
        if browser:
            browser.close()
    
    if not valid_flights:
        print(f"   ❌ {name}: No se encontraron vuelos rápidos.")
        return None
        
    best = min(valid_flights, key=lambda x: x["price_val"])
    print(f"   ✅ {name}: Mejor precio {best['price_str']}")
    return best

def monitor():
    with sync_playwright() as p:
        targets = [
            ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[role='listitem'], .sc-fLcnxK, [class*='FlightItem']"),
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem'], .mzYp9c"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper'], .Base-Results-ResultCard"),
            ("SKY", f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0", ".flight-item, [class*='FlightCard']"),
            ("Aerolíneas Arg.", f"https://www.aerolineas.com.ar/search/vuelos/SCL/COR?date1=09-10-2026&date2=12-10-2026&adults=1&children=0&infants=0", ".flight-card, [class*='result']"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']"),
        ]

        results = []
        for name, url, sel in targets:
            res = scrape_direct(p, name, url, sel)
            if res: results.append(res)

        if not results:
            enviar_telegram("🔄 *Monitor de Vuelos*: No se detectaron vuelos rápidos en esta pasada. 🫡")
            return

        results.sort(key=lambda x: x["price_val"])
        
        mensaje = "✈️ *REPORTE DE VUELOS ENCONTRADOS* ✈️\n\n"
        for r in results:
            mensaje += f"✅ *{r['airline']}*\n"
            mensaje += f"💰 Precio: *{r['price_str']}*\n"
            mensaje += f"⏱️ Duración: {r['dur']}\n"
            mensaje += f"🔗 [Link Directo]({r['url']})\n\n"

        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
