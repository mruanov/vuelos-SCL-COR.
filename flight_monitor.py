import time
import requests
import os
import re
import random
from playwright.sync_api import sync_playwright

# --- CONFIGURACIÓN DE BÚSQUEDA ---
ORIGEN = "SCL"
DESTINO = "COR"
FECHA_IDA = "2026-10-09"
FECHA_VUELTA = "2026-10-12"
MAX_DURACION_MINUTOS = 360  # 6 Horas

# --- CREDENCIALES ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"DEBUG:\n{mensaje}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=15)
    except: pass

def parse_price(text):
    """Extrae el valor numérico de un precio"""
    if not text: return 9999999
    nums = re.findall(r'\d+', text.replace('.', '').replace(',', ''))
    if nums:
        val = int(nums[0])
        return val / 950 if val > 5000 else val # Normalizar a USD para comparar
    return 9999999

def get_minutes(text):
    """Convierte texto de tiempo a minutos totales"""
    text = text.lower()
    h = 0
    m = 0
    h_match = re.search(r'(\d+)\s*(h|hora|hr)', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*(m|min)', text)
    if m_match: m = int(m_match.group(1))
    # Caso formato 00:00
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2}):(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
    return h * 60 + m

def scrape_platform(p, name, url, item_selector):
    print(f"🚀 Buscando en {name}...")
    best_flight = None
    
    try:
        browser = p.chromium.launch(headless=True)
        # Identidad humana premium
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            locale="es-CL"
        )
        page = context.new_page()
        page.goto(url, wait_until="load", timeout=60000)
        
        # Simular carga humana
        time.sleep(10)
        page.evaluate("window.scrollTo(0, 500)")
        time.sleep(5)

        items = page.query_selector_all(item_selector)
        print(f"   {name}: {len(items)} vuelos encontrados.")

        flights_found = []
        for item in items:
            inner = item.inner_text()
            if not any(s in inner.lower() for s in ["$", "clp", "usd", "pesos"]): continue
            
            # 1. Extraer duraciones (buscamos ida y vuelta por separado)
            # Buscamos patrones de duración que no sean horas de reloj
            dur_raw = re.findall(r'(\d+h\s*\d+m|\d+h|\d+m|\d+ h \d+ min)', inner.lower())
            durations = [get_minutes(d) for d in dur_raw if get_minutes(d) > 40]
            
            # 2. Extraer precio
            price_match = re.search(r'(?:\$|CLP|USD)?\s?(\d+[\.\,]\d{3})', inner)
            if not price_match: price_match = re.search(r'(\d{5,})', inner)
            
            if price_match and len(durations) >= 2:
                price_str = price_match.group(0).strip()
                # Verificar que los dos primeros tramos sean < 6h
                if all(d <= MAX_DURACION_MINUTOS for d in durations[:2]):
                    flights_found.append({
                        "name": name,
                        "price": price_str,
                        "price_val": parse_price(price_str),
                        "dur": f"Ida: {durations[0]//60}h {durations[0]%60}m | Vta: {durations[1]//60}h {durations[1]%60}m",
                        "url": url,
                        "status": "✅"
                    })
                else:
                    # Guardamos el más barato aunque sea largo para el reporte
                    flights_found.append({
                        "name": name,
                        "price": price_str,
                        "price_val": parse_price(price_str),
                        "dur": f"Excede 6h ({max(durations)//60}h)",
                        "url": url,
                        "status": "⏳"
                    })

        if flights_found:
            # Priorizar los rápidos, si no hay, el más barato
            fast = [f for f in flights_found if f["status"] == "✅"]
            if fast:
                best_flight = min(fast, key=lambda x: x["price_val"])
            else:
                best_flight = min(flights_found, key=lambda x: x["price_val"])

        browser.close()
    except Exception as e:
        print(f"   ❌ Error en {name}: {str(e)[:50]}")
    
    return best_flight

def monitor():
    with sync_playwright() as p:
        platforms = [
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper']"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']")
        ]

        results = []
        for name, url, selector in platforms:
            res = scrape_platform(p, name, url, selector)
            if res: results.append(res)

        if not results:
            enviar_telegram("❌ *Monitor*: No se pudieron obtener precios en esta vuelta. Posible bloqueo de las aerolíneas. Re-intentando luego. 🫡")
            return

        # Ordenar reporte por precio
        results.sort(key=lambda x: x["price_val"])
        
        mensaje = "✈️ *LISTADO DE VUELOS MÁS BARATOS* ✈️\n\n"
        for r in results:
            mensaje += f"{r['status']} *{r['name']}*: {r['price']}\n"
            mensaje += f"⏱️ {r['dur']}\n"
            mensaje += f"🔗 [Ver Vuelo]({r['url']})\n\n"
        
        mensaje += "_Leyenda: ✅ < 6h cada tramo | ⏳ > 6h o escala larga_"
        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
