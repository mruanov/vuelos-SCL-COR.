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
MAX_DURACION_MINUTOS = 360  # 6 horas

# --- CREDENCIALES ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"DEBUG: {mensaje}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try: requests.post(url, json=payload, timeout=15)
    except: pass

def get_minutes(text):
    """Extrae minutos de formatos variados: '1h 30m', '01:30', '90 min'"""
    if not text: return 9999
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
    return (h * 60 + m) if (h > 0 or m > 0) else 9999

def extract_flight_data(block_text):
    """Analiza un bloque de texto de un solo vuelo para extraer precio y duraciones"""
    # 1. Encontrar todas las duraciones en el bloque
    dur_matches = re.findall(r'(\d+h\s*\d+m|\d+h|\d+m|\d{1,2}:\d{2})', block_text.lower())
    durations = [get_minutes(d) for d in dur_matches if get_minutes(d) > 45]
    
    # 2. Encontrar el precio (buscamos números con formato de miles o $ inicial)
    # Ejemplo: $180.000, 250.300, CLP 150000
    price_match = re.search(r'(?:\$|CLP|USD)?\s?(\d+[\.\,]\d{3})', block_text)
    if not price_match:
        price_match = re.search(r'(\d{5,})', block_text) # Fallback para números largos sin puntos
    
    if price_match and durations:
        price_str = price_match.group(0).strip()
        # Limpiar valor numérico para comparaciones
        price_val = int(re.sub(r'[^\d]', '', price_str))
        if price_val > 5000: price_val = price_val / 950 # Normalizar CLP a USD aprox
        
        return {
            "price": price_str,
            "price_val": price_val,
            "durations": durations,
            "is_fast": all(d <= MAX_DURACION_MINUTOS for d in durations) and len(durations) >= 2
        }
    return None

def scrape_with_agent(p, name, url, container_selector):
    print(f"🕵️ Agente Auditado buscando en {name}...")
    best_option = None
    
    try:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            locale="es-CL"
        )
        page = context.new_page()
        
        # Evitar detección: mover mouse a posición aleatoria
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        time.sleep(random.uniform(15, 25)) # Espera humana aleatoria
        
        # Intentar cerrar popups comunes
        try:
            page.click("button:has-text('Aceptar'), button:has-text('Accept'), .canvas-close", timeout=5000)
        except: pass

        # Obtener todos los bloques de vuelos
        containers = page.query_selector_all(container_selector)
        print(f"   -> {name}: {len(containers)} bloques encontrados.")
        
        valid_flights = []
        for c in containers:
            data = extract_flight_data(c.inner_text())
            if data:
                # Guardamos todos los encontrados para auditoría
                data["plataforma"] = name
                data["url"] = url
                valid_flights.append(data)

        if valid_flights:
            # Primero intentamos los que cumplen el filtro de 6h
            fast_flights = [f for f in valid_flights if f["is_fast"]]
            if fast_flights:
                best_option = min(fast_flights, key=lambda x: x["price_val"])
                best_option["status"] = "✅"
            else:
                # Si ninguno cumple, tomamos el más barato pero con aviso
                best_option = min(valid_flights, key=lambda x: x["price_val"])
                best_option["status"] = "⏳"
        
        browser.close()
    except Exception as e:
        print(f"   ⚠️ Error en {name}: {str(e)[:50]}")
        
    return best_option

def monitor():
    with sync_playwright() as p:
        # Selectores de bloques de vuelo probados en 2026
        sources = [
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper']"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']")
        ]
        
        final_results = []
        for name, url, selector in sources:
            res = scrape_with_agent(p, name, url, selector)
            if res: final_results.append(res)
        
        if not final_results:
            enviar_telegram("⚠️ *Alerta Auditoría*: Las webs están bloqueando el acceso o no hay vuelos disponibles para estas fechas. Revisaré la conexión. 🫡")
            return

        # Generar Reporte
        final_results.sort(key=lambda x: x["price_val"])
        mejor = final_results[0]
        
        reporte = "✈️ *REPORTE DE VUELOS AUDITADO* ✈️\n\n"
        reporte += f"La mejor opción encontrada es de *{mejor['plataforma']}* por *{mejor['price']}*.\n\n"
        
        reporte += "📋 *Resumen por plataforma:*\n"
        for r in final_results:
            durs = ", ".join([f"{d//60}h {d%60}m" for d in r['durations']])
            reporte += f"{r['status']} *{r['plataforma']}*: {r['price']} (Dur: {durs})\n"
            reporte += f"🔗 [Ver Vuelo]({r['url']})\n\n"
        
        reporte += "\n_Leyenda: ✅ < 6h cada tramo | ⏳ > 6h o escala_"
        enviar_telegram(reporte)

if __name__ == "__main__":
    monitor()
