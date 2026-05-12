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
MAX_DURACION_MINUTOS = 360  # 6 horas exactas

# --- TELEGRAM ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=20)
    except: pass

def get_minutes(text):
    """Extrae minutos totales. Ejemplo: '1h 30m' -> 90"""
    if not text: return 9999
    text = text.lower().replace(' ', '')
    h = 0
    m = 0
    h_match = re.search(r'(\d+)h', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)m', text)
    if m_match: m = int(m_match.group(1))
    # Soporte para formato 01:30
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2}):(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
    return (h * 60 + m) if (h > 0 or m > 0) else 9999

def scrape_agent(p, name, url, item_selector):
    print(f"🕵️ Agente buscando en {name}...")
    valid_flights = []
    try:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            locale="es-CL"
        )
        page = context.new_page()
        
        # Navegación con tiempo de espera humano
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        time.sleep(25) # Espera crítica para que carguen los precios dinámicos
        
        # Hacer scroll para "despertar" la página
        page.mouse.wheel(0, 800)
        time.sleep(5)

        # Capturar todos los bloques que parecen vuelos
        items = page.query_selector_all(item_selector)
        if not items and name == "Google Flights":
            items = page.query_selector_all("[role='listitem']")

        for item in items:
            inner = item.inner_text()
            if not any(s in inner.lower() for s in ["$", "clp", "usd", "pesos"]): continue
            
            # Extraer todas las duraciones del bloque
            dur_raw = re.findall(r'(\d+\s*h\s*\d+\s*m|\d+\s*h|\d+\s*m|\d{1,2}:\d{2})', inner.lower())
            minutes_list = [get_minutes(d) for d in dur_raw if get_minutes(d) > 40]
            
            # REGLA DE ORO: Solo vuelos donde CADA tramo sea < 6h
            if minutes_list and all(m <= MAX_DURACION_MINUTOS for m in minutes_list):
                # Extraer precio
                price_match = re.search(r'(?:\$|CLP|USD)?\s?(\d+[\.\,]\d{3})', inner)
                if not price_match: price_match = re.search(r'(\d{5,})', inner)
                
                if price_match:
                    p_str = price_match.group(0).strip()
                    p_val = int(re.sub(r'[^\d]', '', p_str))
                    valid_flights.append({
                        "plataforma": name,
                        "precio_str": p_str,
                        "precio_val": p_val / 950 if p_val > 5000 else p_val,
                        "dur": " / ".join([f"{m//60}h {m%60}m" for m in minutes_list]),
                        "url": url
                    })
        
        browser.close()
    except Exception as e:
        print(f"   ⚠️ Error en {name}: {str(e)[:50]}")
    
    return valid_flights

def monitor():
    with sync_playwright() as p:
        # Definición de búsquedas (incluyendo Hopper y Aerolíneas Argentinas vía Kayak/Google por estabilidad)
        search_configs = [
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
            ("Kayak (incl. Hopper/AR)", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper']"),
            ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[class*='FlightItem']"),
            ("SKY", f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0", ".flight-item, [class*='FlightCard']"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']")
        ]

        all_valid_flights = []
        for name, url, sel in search_configs:
            res = scrape_agent(p, name, url, sel)
            if res: all_valid_flights.extend(res)

        if not all_valid_flights:
            enviar_telegram("🔄 *Monitor de Vuelo*: No se encontraron vuelos de menos de 6 horas en ninguna plataforma. Seguiré buscando opciones rápidas. 🫡")
            return

        # Filtrar el mejor por plataforma para no repetir
        final_report = {}
        for f in all_valid_flights:
            if f['plataforma'] not in final_report or f['precio_val'] < final_report[f['plataforma']]['precio_val']:
                final_report[f['plataforma']] = f

        # Construir mensaje
        mensaje = "✈️ *VUELOS ENCONTRADOS (< 6 HORAS)* ✈️\n\n"
        # Ordenar por precio
        sorted_flights = sorted(final_report.values(), key=lambda x: x['precio_val'])
        
        for f in sorted_flights:
            mensaje += f"✅ *{f['plataforma']}*: ${f['precio_str']}\n"
            mensaje += f"⏱️ Duración: {f['dur']}\n"
            mensaje += f"🔗 [Ver Vuelo]({f['url']})\n\n"

        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
