import time
import requests
import os
import re
import random
from playwright.sync_api import sync_playwright

# --- CONFIGURACIÓN ---
ORIGEN = "SCL"
DESTINO = "COR"
FECHA_IDA = "2026-10-09"
FECHA_VUELTA = "2026-10-12"
MAX_DURACION_MINUTOS = 360  # 6 Horas

# --- TELEGRAM ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=20)
    except: pass

def get_minutes_robust(text):
    """Convierte cualquier formato de tiempo a minutos. Ej: '2 h 33 min' -> 153"""
    if not text: return 9999
    text = text.lower().replace(',', '')
    
    h = 0
    m = 0
    # Buscar horas: '2 h', '2h', '2 hora'
    h_match = re.search(r'(\d+)\s*(?:h|hour|hora|hr)', text)
    if h_match: h = int(h_match.group(1))
    
    # Buscar minutos: '33 m', '33m', '33 min'
    m_match = re.search(r'(\d+)\s*(?:m|min|minuto)', text)
    if m_match: m = int(m_match.group(1))
    
    # Formato reloj: '02:33'
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2}):(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
        
    total = h * 60 + m
    return total if total > 0 else 9999

def scrape_agent_v2(p, name, url, item_selector):
    print(f"🕵️ Escaneando {name}...")
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
        
        # Espera dinámica: aguardar a que aparezca algún indicio de vuelos
        time.sleep(20)
        page.mouse.wheel(0, 1000)
        time.sleep(5)

        items = page.query_selector_all(item_selector)
        if not items and name == "Google Flights":
            items = page.query_selector_all("[role='listitem']")

        for item in items:
            inner = item.inner_text()
            if not any(s in inner.lower() for s in ["$", "clp", "usd", "pesos", "desde"]): continue
            
            # 1. Extraer todas las duraciones del bloque de texto
            # Buscamos patrones: '2 h 33 min', '1h 30m', '02:33'
            dur_matches = re.findall(r'(\d+\s*h\s*\d+\s*min|\d+\s*h\s*\d+\s*m|\d+\s*h|\d+\s*m|\d{1,2}:\d{2})', inner.lower())
            minutes_list = [get_minutes_robust(d) for d in dur_matches if get_minutes_robust(d) > 40]
            
            # 2. Extraer precio
            p_match = re.search(r'(?:\$|CLP|USD|pesos)?\s?(\d+[\.\,]\d{3})', inner)
            if not p_match: p_match = re.search(r'(\d{5,})', inner)
            
            if p_match and minutes_list:
                p_str = p_match.group(0).strip()
                p_val_raw = int(re.sub(r'[^\d]', '', p_str))
                p_val_usd = p_val_raw / 950 if p_val_raw > 5000 else p_val_raw
                
                # Identificar aerolínea para el reporte
                airline = "Varias"
                for a in ["LATAM", "SKY", "Aerolíneas Argentinas", "JetSMART", "Hopper"]:
                    if a.lower() in inner.lower():
                        airline = a
                        break

                # Solo vuelos donde TODOS los tramos detectados sean < 6h
                if all(m <= MAX_DURACION_MINUTOS for m in minutes_list):
                    valid_flights.append({
                        "platform": name,
                        "airline": airline,
                        "price_str": p_str,
                        "price_val": p_val_usd,
                        "dur": " / ".join([f"{m//60}h {m%60}m" for m in minutes_list]),
                        "url": url
                    })
        
        browser.close()
    except Exception as e:
        print(f"   ⚠️ Error en {name}: {str(e)[:50]}")
    
    return valid_flights

def monitor():
    with sync_playwright() as p:
        # Fuentes maestras que agrupan a LATAM, SKY, AR, etc.
        configs = [
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper']"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']")
        ]

        all_flights = []
        for name, url, sel in configs:
            res = scrape_agent_v2(p, name, url, sel)
            if res: all_flights.extend(res)

        if not all_flights:
            enviar_telegram("🔄 *Monitor*: Sin vuelos < 6h detectados. Las aerolíneas podrían estar bloqueando el servidor. Re-intentaré con nueva identidad en la próxima vuelta. 🫡")
            return

        # Consolidar: Mejor precio por aerolínea
        report_data = {}
        for f in all_flights:
            key = f"{f['airline']} ({f['platform']})"
            if key not in report_data or f['price_val'] < report_data[key]['price_val']:
                report_data[key] = f

        # Generar mensaje ordenado por precio
        sorted_report = sorted(report_data.values(), key=lambda x: x['price_val'])
        
        mensaje = "✈️ *VUELOS < 6H ENCONTRADOS* ✈️\n\n"
        for f in sorted_report:
            mensaje += f"✅ *{f['airline']}* (${f['platform']})\n"
            mensaje += f"💰 Precio: *{f['price_str']}*\n"
            mensaje += f"⏱️ Duración: {f['dur']}\n"
            mensaje += f"🔗 [Ver Vuelo]({f['url']})\n\n"

        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
