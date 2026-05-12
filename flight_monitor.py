import time
import requests
import os
import re
from playwright.sync_api import sync_playwright

# Configuración de búsqueda
ORIGEN = "SCL"
DESTINO = "COR"
FECHA_IDA = "2026-10-09"
FECHA_VUELTA = "2026-10-12"
MAX_DURACION_MINUTOS = 360  # 6 horas por tramo

# Credenciales Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram no configurado.\n{mensaje}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
    except: pass

def parse_price(text):
    """Extrae el primer número grande de un texto (precio)"""
    nums = re.findall(r'\d+', text.replace('.', '').replace(',', ''))
    if nums:
        val = int(nums[0])
        return val / 950 if val > 5000 else val # Convertir CLP a USD aprox
    return 999999

def get_minutes(text):
    """Extrae minutos totales de un texto tipo '5h 30m'"""
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

def agent_scrape(p, name, url, selector):
    print(f"🤖 Agente buscando en {name}...")
    try:
        browser = p.chromium.launch(headless=True)
        # Headers de alta calidad para evitar bloqueos
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            locale="es-CL"
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        time.sleep(15) # Espera real para carga de precios

        # Scroll para activar carga dinámica
        page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
        time.sleep(5)

        cards = page.query_selector_all(selector)
        print(f"   -> {name}: {len(cards)} vuelos detectados.")
        
        valid_flights = []
        for card in cards:
            inner_text = card.inner_text()
            if not any(s in inner_text.lower() for s in ["$", "clp", "usd", "pesos"]): continue
            
            # Detectar duraciones (buscamos todos los patrones de tiempo)
            dur_matches = re.findall(r'(\d+\s*h\s*\d+\s*m|\d+\s*h|\d+\s*m|\d{1,2}:\d{2})', inner_text.lower())
            durations = [get_minutes(d) for d in dur_matches if get_minutes(d) > 40]
            
            if durations and all(d <= MAX_DURACION_MINUTOS for d in durations):
                price_match = re.search(r'(\d+[\.\,]\d{3})|(\d{5,})|(\d{2,3})', inner_text)
                if price_match:
                    valid_flights.append({
                        "plataforma": name,
                        "precio_str": price_match.group(0),
                        "precio_val": parse_price(price_match.group(0)),
                        "duracion": ", ".join([f"{d//60}h {d%60}m" for d in durations]),
                        "url": url
                    })
        
        browser.close()
        if valid_flights:
            return min(valid_flights, key=lambda x: x["precio_val"])
    except Exception as e:
        print(f"   ❌ Error en {name}: {str(e)[:50]}")
    return None

def monitor():
    with sync_playwright() as p:
        # Fuentes principales (estas cubren a SKY, JetSMART y LATAM)
        sources = [
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", "[class*='resultWrapper'], .nrc6"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']")
        ]
        
        results = []
        for name, url, sel in sources:
            res = agent_scrape(p, name, url, sel)
            if res:
                results.append(res)
                print(f"   ✅ {name} encontró opción válida!")

        if not results:
            enviar_telegram("🔄 *Monitor Activo*: No se encontraron vuelos de < 6h en esta vuelta. Seguiré vigilando las 24hs. 🫡")
            return

        # Ordenar por precio y enviar reporte
        results.sort(key=lambda x: x["precio_val"])
        mejor = results[0]
        
        detalle = ""
        for r in results:
            detalle += f"📍 *{r['plataforma']}*: ${r['precio_str']} ({r['duracion']})\n🔗 [Ver Vuelo]({r['url']})\n\n"

        mensaje = f"✈️ *OFERTA ENCONTRADA* ✈️\n\n"
        mensaje += f"La mejor opción es de *{mejor['plataforma']}* por un valor aproximado de *${mejor['precio_str']}*.\n\n"
        mensaje += f"📋 *Detalle de opciones validas (<6h):*\n{detalle}"
        
        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
