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
MAX_DURACION_MINUTOS = 360 

# --- TELEGRAM ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    requests.post(url, json=payload, timeout=20)

def get_minutes(text):
    text = text.lower()
    h = 0
    m = 0
    h_match = re.search(r'(\d+)\s*(h|hora|hr)', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*(m|min)', text)
    if m_match: m = int(m_match.group(1))
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2}):(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
    return h * 60 + m

def scrape_platform(p, name, url, selector, wait_time=20):
    print(f"🕵️ Agente buscando en {name}...")
    try:
        browser = p.chromium.launch(headless=True)
        # Identidad aleatoria para evitar bloqueos de Google/LATAM
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ]
        context = browser.new_context(user_agent=random.choice(user_agents), viewport={'width': 1920, 'height': 1080}, locale="es-CL")
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        
        time.sleep(wait_time)
        page.evaluate("window.scrollTo(0, 400)") # Scroll para disparar carga
        time.sleep(5)

        # Si es Google, intentamos un selector más agresivo
        if name == "Google Flights":
            items = page.query_selector_all("[role='listitem'], .pI9Wbc, .yR3e6c")
        else:
            items = page.query_selector_all(selector)

        print(f"   {name}: {len(items)} resultados potenciales.")
        
        flights = []
        for item in items:
            inner = item.inner_text()
            if not any(s in inner.lower() for s in ["$", "clp", "usd", "pesos"]): continue
            
            # Duraciones (Ida y Vuelta)
            dur_raw = re.findall(r'(\d+h\s*\d+m|\d+h|\d+m|\d+ h \d+ min|\d{1,2}:\d{2})', inner.lower())
            mins = [get_minutes(d) for d in dur_raw if get_minutes(d) > 40]
            
            # Precio
            p_match = re.search(r'(?:\$|CLP|USD)?\s?(\d+[\.\,]\d{3})', inner)
            if not p_match: p_match = re.search(r'(\d{5,})', inner)

            if p_match and len(mins) >= 1:
                price_str = p_match.group(0).strip()
                val = int(re.sub(r'[^\d]', '', price_str))
                # Filtro: < 6h en los tramos detectados
                status = "✅" if all(m <= MAX_DURACION_MINUTOS for m in mins) else "⏳"
                
                flights.append({
                    "name": name,
                    "price": price_str,
                    "val": val / 950 if val > 5000 else val,
                    "dur": f"{mins[0]//60}h {mins[0]%60}m" + (f" / {mins[1]//60}h {mins[1]%60}m" if len(mins)>1 else ""),
                    "url": url,
                    "status": status
                })

        browser.close()
        if flights:
            # Retornar el más barato (pero preferir el que cumple <6h si existe)
            validos = [f for f in flights if f["status"] == "✅"]
            return min(validos, key=lambda x: x["val"]) if validos else min(flights, key=lambda x: x["val"])
            
    except Exception as e:
        print(f"   ❌ Error en {name}: {str(e)[:50]}")
    return None

def monitor():
    with sync_playwright() as p:
        sources = [
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", ""),
            ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[class*='FlightItem'], .sc-fLcnxK"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper']"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']")
        ]

        results = []
        for name, url, sel in sources:
            res = scrape_platform(p, name, url, sel)
            if res: results.append(res)

        if not results:
            enviar_telegram("⚠️ *Monitor*: Sin resultados en todas las plataformas. Es posible que los sitios estén bloqueando el acceso desde el servidor. Revisaré el sistema de camuflaje. 🫡")
            return

        results.sort(key=lambda x: x["val"])
        mensaje = "✈️ *LISTADO COMPARATIVO DE VUELOS* ✈️\n\n"
        for r in results:
            mensaje += f"{r['status']} *{r['name']}*: {r['price']}\n"
            mensaje += f"⏱️ {r['dur']}\n"
            mensaje += f"🔗 [Ver en la web]({r['url']})\n\n"
        
        mensaje += "_Leyenda: ✅ < 6h tramos | ⏳ > 6h o escala_"
        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
