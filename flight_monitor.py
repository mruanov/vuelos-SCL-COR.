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
MAX_DURACION_MINUTOS = 360  # 6 horas por tramo

# Credenciales
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_alerta(mensaje):
    print(f"Enviando alerta a Telegram...")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram no configurado.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": f"✈️ MONITOR DE VUELOS ✈️\n\n{mensaje}"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

def parse_price_robust(text):
    if not text: return float('inf')
    nums = re.findall(r'\d+', text.replace('.', '').replace(',', ''))
    if nums:
        val = int(nums[0])
        return val / 950 if val > 5000 else val
    return float('inf')

def check_all_durations_under_limit(text):
    """Verifica que TODAS las duraciones mencionadas sean <= 6h"""
    # Buscar patrones como "5h 30m", "5 h 30 min", "5:30"
    # Evitamos confundir con horas de salida como "17:53" buscando el contexto de 'h' o 'min'
    found_durations = []
    
    # 1. Buscar "Xh Ym"
    matches = re.findall(r'(\d+)\s*h(?:our|ora|r)?\s*(?:(\d+)\s*m(?:in|inuto)?)?', text.lower())
    for h, m in matches:
        mins = int(h) * 60 + (int(m) if m else 0)
        if mins > 10: # Evitar falsos positivos de números sueltos
            found_durations.append(mins)
            
    # 2. Buscar formato "05:30" que no sea hora de reloj (normalmente duraciones no tienen AM/PM cerca)
    if not found_durations:
        hm_matches = re.findall(r'(\d{1,2}):(\d{2})', text)
        for h, m in hm_matches:
            mins = int(h) * 60 + int(m)
            if 30 < mins < 1000: # Rango razonable para duración de vuelo
                found_durations.append(mins)

    if not found_durations: return False
    
    # Debug log en consola
    print(f"    Duraciones detectadas: {[f'{d//60}h {d%60}m' for d in found_durations]}")
    
    return all(d <= MAX_DURACION_MINUTOS for d in found_durations)

def scrape_platform(name, url, item_selector, locale="es-CL"):
    print(f"Buscando en {name}...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale=locale
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(15)
            
            try: page.click("button:has-text('Aceptar'), button:has-text('Accept')", timeout=5000)
            except: pass

            items = page.query_selector_all(item_selector)
            for item in items:
                text = item.inner_text()
                if not text or not any(s in text.lower() for s in ["$", "clp", "usd", "pesos", "desde"]): continue
                
                if check_all_durations_under_limit(text):
                    # Extraer precio: el primer número con formato de miles o > 4 dígitos
                    p_match = re.search(r'(\d+[\.\,]\d{3})|(\d{5,})', text)
                    precio_str = p_match.group(0) if p_match else "N/A"
                    
                    browser.close()
                    return {
                        "plataforma": name,
                        "precio": precio_str,
                        "precio_usd": parse_price_robust(precio_str),
                        "url": url
                    }
            browser.close()
        except Exception as e: print(f"  ❌ Error en {name}: {e}")
    return None

def monitor():
    platforms = [
        ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}", "[role='listitem']"),
        ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, .resultInner"),
        ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[class*='FlightItem']"),
        ("SKY", f"https://www.skyairline.com/chile/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0", ".flight-item, [class*='FlightCard']"),
        ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}", "[data-test='ResultCardWrapper']"),
        ("Skyscanner", f"https://www.skyscanner.cl/transport/vuelos/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}/?adultsv2=1&sortby=price", "div[class*='Ticket_wrapper']")
    ]

    final_results = []
    for name, url, selector in platforms:
        res = scrape_platform(name, url, selector, locale="en-US" if name == "Kiwi.com" else "es-CL")
        if res:
            final_results.append(res)
            print(f"✅ {name} encontró un vuelo válido!")
        else:
            print(f"❌ {name} sin vuelos que cumplan 6h cada tramo.")

    if not final_results:
        enviar_alerta("No encontré vuelos de menos de 6 horas en esta vuelta. 🫡")
        return

    mejor = min(final_results, key=lambda x: x['precio_usd'])
    detalle = "\n".join([f"- {r['plataforma']}: {r['precio']}" for r in final_results])
    
    mensaje = f"🌟 MEJOR VUELO (IDA Y VUELTA < 6h): {mejor['plataforma']} 🌟\n"
    mensaje += f"💰 Precio: {mejor['precio']} (~{mejor['precio_usd']:.2f} USD)\n"
    mensaje += f"🔗 Link: {mejor['url']}\n\n"
    mensaje += f"📋 Otras opciones válidas:\n{detalle}"
    
    enviar_alerta(mensaje)

if __name__ == "__main__":
    monitor()
