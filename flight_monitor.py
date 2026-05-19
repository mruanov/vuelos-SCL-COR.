import time
import requests
import os
import re
import random
from playwright.sync_api import sync_playwright

# --- CONFIGURACION ESTRICTA ---
ORIGEN = "SCL"
DESTINO = "COR"
FECHA_IDA = "2026-10-09"
FECHA_VUELTA = "2026-10-12"
MAX_DURACION_MINUTOS = 420 # 7 Horas (Flexible para escalas eficientes)

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
    # Limpiar texto de ruidos comunes
    text = text.lower().replace(',', '').replace('.', '').replace('\xa0', ' ')
    
    # Caso especial: "1 h 33 min" o "1 hora 33 minutos"
    h, m = 0, 0
    h_match = re.search(r'(\d+)\s*(?:hour|hora|hr|h)', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*(?:minuto|min|m)', text)
    if m_match: m = int(m_match.group(1))
    
    if h == 0 and m == 0:
        # Intentar formato 10:10 o 10h10
        hm = re.search(r'(\d{1,2})[h:]\s*(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
        
    total = h * 60 + m
    # Si detecto algo muy bajo (como 1 min), probablemente es error de parsing
    return total if total > 20 else 9999 

def scrape_direct(p, name, url, item_selector):
    print(f"Entrando a {name}...")
    valid_flights = []
    browser = None
    try:
        stealth_applied = False
        try:
            from playwright_stealth import stealth
            stealth_applied = True
        except ImportError:
            pass

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800},
            locale="es-CL",
            timezone_id="America/Santiago"
        )
        page = context.new_page()
        
        if stealth_applied:
            stealth(page)
        else:
            page.add_init_script(\"\"\"
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', { get: () => ['es-CL', 'es', 'en-US', 'en'] });
            \"\"\")

        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        
        # BYPASS DE CONSENTIMIENTO/COOKIES
        time.sleep(random.uniform(3, 5))
        selectors = [
            "button:has-text('Aceptar')", "button:has-text('Accept')", 
            "button:has-text('Agree')", "button:has-text('Entendido')",
            ".VfPpkd-LgbsSe", "[id*='cookie'] button", "[class*='cookie'] button"
        ]
        for sel in selectors:
            try:
                if page.locator(sel).first.is_visible():
                    page.locator(sel).first.click()
                    time.sleep(2)
            except: pass

        # Esperar a que carguen los resultados
        try:
            page.wait_for_selector(item_selector, timeout=25000)
        except: pass

        time.sleep(random.uniform(5, 8))
        
        items = page.query_selector_all(item_selector)
        print(f"   -> {name}: {len(items)} elementos detectados.")

        if len(items) == 0:
            bt = page.inner_text("body").strip()[:300]
            print(f"      [DIAGNOSTIC] {name} Body: {bt}...")

        rejected_count = 0
        for i, item in enumerate(items):
            try:
                inner = item.inner_text()
                if not inner or len(inner) < 30: continue
                
                dur_regex_explicit = r'(\d+\s*(?:horas?|hours?|hrs?|h)\s*\d*\s*(?:minutos?|mins?|m)?|\d+\s*(?:minutos?|mins?|m))'
                dur_matches = re.findall(dur_regex_explicit, inner.lower())
                
                if not dur_matches:
                    dur_matches = re.findall(r'(\d{1,2}[h:]\d{2})', inner.lower())
                
                mins = [get_minutes_robust(d) for d in dur_matches]
                mins = [m for m in mins if 20 < m < 1440]
                
                p_match = re.search(r'(?:\$|CLP|USD|pesos)?\s?(\d+[\.\,]\d{3})', inner, re.IGNORECASE)
                if not p_match: p_match = re.search(r'(\d{5,})', inner)
                
                if p_match and mins:
                    p_str = p_match.group(0).strip()
                    p_val_raw = int(re.sub(r'[^\d]', '', p_str))
                    p_val_norm = p_val_raw / 950 if p_val_raw > 10000 else p_val_raw
                    
                    if i < 3:
                        print(f"      [DEBUG] {name} #{i}: Precio={p_str}, Duraciones={mins}")

                    if all(m <= MAX_DURACION_MINUTOS for m in mins):
                        valid_flights.append({
                            "airline": name,
                            "price_str": p_str,
                            "price_val": p_val_norm,
                            "dur": " / ".join([f"{m//60}h {m%60}m" for m in mins]),
                            "url": url
                        })
                    else:
                        rejected_count += 1
                else:
                    rejected_count += 1
            except Exception:
                continue
    except Exception as e:
        print(f"   Error en {name}: {str(e)[:100]}")
    finally:
        if browser:
            browser.close()
    
    if not valid_flights:
        print(f"   Sin vuelos rápidos (Rechazados: {rejected_count}).")
        return None
        
    best = min(valid_flights, key=lambda x: x["price_val"])
    print(f"   Mejor precio {best['price_str']}")
    return best

def monitor():
    with sync_playwright() as p:
        targets = [
            ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[role='listitem'], [class*='FlightItem'], .sc-fLcnxK"),
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}&curr=CLP", "[role='listitem'], .mzYp9c, .yR1fYc"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper'], .Base-Results-ResultCard"),
            ("SKY", f"https://www.skyairline.com/es-cl/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0", ".flight-item, [class*='FlightCard'], [class*='flightItem']"),
        ]

        results = []
        for name, url, sel in targets:
            res = scrape_direct(p, name, url, sel)
            if res: results.append(res)

        if not results:
            enviar_telegram("No se detectaron vuelos rápidos en esta pasada.")
            return

        results.sort(key=lambda x: x["price_val"])
        
        mensaje = "Reporte de Vuelos:\n\n"
        for r in results:
            mensaje += f"{r['airline']}: {r['price_str']} ({r['dur']})\n{r['url']}\n\n"

        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
