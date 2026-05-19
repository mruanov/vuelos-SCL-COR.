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
MAX_DURACION_MINUTOS = 420 # 7 Horas

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15"
]

# --- TELEGRAM ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        print(f"Telegram not configured. Message: {mensaje[:100]}...")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code != 200:
            print(f"Error Telegram: {r.text}")
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

def get_minutes_robust(text):
    if not text: return 9999
    text = text.lower().replace(',', '').replace('.', '').replace('\xa0', ' ')
    h, m = 0, 0
    h_match = re.search(r'(\d+)\s*(?:hour|hora|hr|h)', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*(?:minuto|min|m)', text)
    if m_match: m = int(m_match.group(1))
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2})[h:]\s*(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
    total = h * 60 + m
    return total if total > 20 else 9999 

def apply_stealth_robust(context, page):
    try:
        import playwright_stealth
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(context)
            return True
        except: pass
        try:
            from playwright_stealth import stealth_sync
            stealth_sync(page)
            return True
        except: pass
        try:
            from playwright_stealth import stealth
            if hasattr(stealth, 'stealth'):
                stealth.stealth(page)
                return True
            elif callable(stealth):
                stealth(page)
                return True
        except: pass
    except ImportError: pass
    try:
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['es-CL', 'es', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)
    except: pass
    return False

def scrape_direct(p, name, url, item_selector, root_url=None):
    print(f"Entrando a {name}...")
    found_flights = []
    browser = None
    try:
        browser = p.chromium.launch(headless=True)
        w, h = random.randint(1250, 1350), random.randint(850, 950)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': w, 'height': h},
            locale="es-CL",
            timezone_id="America/Santiago"
        )
        page = context.new_page()
        apply_stealth_robust(context, page)

        if root_url:
            try:
                page.goto(root_url, wait_until="domcontentloaded", timeout=40000)
                time.sleep(random.uniform(3, 5))
                try: page.mouse.move(random.randint(100, 500), random.randint(100, 500))
                except: pass
            except: pass

        page.goto(url, wait_until="domcontentloaded", timeout=95000)
        time.sleep(random.uniform(5, 8))
        
        selectors = ["button:has-text('Aceptar')", "button:has-text('Accept')", "button:has-text('Agree')", "button:has-text('Entendido')", ".VfPpkd-LgbsSe", "[id*='cookie'] button", "[class*='cookie'] button"]
        for sel in selectors:
            try:
                if page.locator(sel).first.is_visible():
                    page.locator(sel).first.click()
                    time.sleep(2)
            except: pass

        try: page.wait_for_selector(item_selector, timeout=35000)
        except: pass
        time.sleep(random.uniform(5, 10))
        
        items = page.query_selector_all(item_selector)
        print(f"   -> {name}: {len(items)} elementos detectados.")

        for i, item in enumerate(items):
            try:
                inner = item.inner_text()
                if not inner or len(inner) < 30: continue
                
                # Detección de aerolínea
                airline_detected = name
                known = ["LATAM", "JetSMART", "SKY", "Aerolíneas Argentinas", "Iberia", "Copa", "Flybondi", "Avianca"]
                for k in known:
                    if k.lower() in inner.lower():
                        airline_detected = k
                        break

                dur_regex = r'(\d+\s*(?:horas?|hours?|hrs?|h)\s*\d*\s*(?:minutos?|mins?|m)?|\d+\s*(?:minutos?|mins?|m))'
                dur_matches = re.findall(dur_regex, inner.lower())
                if not dur_matches: dur_matches = re.findall(r'(\d{1,2}[h:]\d{2})', inner.lower())
                
                mins = [get_minutes_robust(d) for d in dur_matches]
                mins = [m for m in mins if 20 < m < 1440]
                
                p_match = re.search(r'(?:\$|CLP|USD|pesos)?\s?(\d+[\.\,]\d{3})', inner, re.IGNORECASE)
                if not p_match: p_match = re.search(r'(\d{5,})', inner)
                
                if p_match and mins:
                    p_str = p_match.group(0).strip()
                    p_val_raw = int(re.sub(r'[^\d]', '', p_str))
                    p_val_norm = p_val_raw / 950 if p_val_raw > 10000 else p_val_raw
                    
                    if all(m <= MAX_DURACION_MINUTOS for m in mins):
                        found_flights.append({
                            "airline": airline_detected,
                            "price_str": p_str,
                            "price_val": p_val_norm,
                            "dur": " / ".join([f"{m//60}h {m%60}m" for m in mins]),
                            "url": url
                        })
            except Exception: continue
    except Exception as e: print(f"   Error en {name}: {str(e)[:100]}")
    finally:
        if browser: browser.close()
    
    return found_flights

def monitor():
    with sync_playwright() as p:
        targets = [
            ("LATAM", f"https://www.latamairlines.com/cl/es/ofertas-vuelos?origin={ORIGEN}&outbound={FECHA_IDA}T12%3A00%3A00.000Z&destination={DESTINO}&inbound={FECHA_VUELTA}T12%3A00%3A00.000Z&adt=1&chd=0&inf=0&trip=RT&cabin=Economy&redemption=false", "li[role='listitem'], [class*='FlightItem'], .sc-fLcnxK", "https://www.latamairlines.com"),
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}&curr=CLP", "[role='listitem'], .mzYp9c, .yR1fYc"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a", ".nrc6, [class*='resultWrapper'], .Base-Results-ResultCard", "https://www.kayak.cl"),
            ("SKY", f"https://www.skyairline.com/es-cl/flujo-compra/busqueda-vuelos?origin={ORIGEN}&destination={DESTINO}&departure={FECHA_IDA}&return={FECHA_VUELTA}&adults=1&children=0&infants=0", ".flight-item, [class*='FlightCard'], [class*='flightItem']", "https://www.skyairline.com"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results?origin={ORIGEN.lower()}&destination={DESTINO.lower()}&outboundDate={FECHA_IDA}&returnDate={FECHA_VUELTA}", "[data-test='ResultCardWrapper']", "https://www.kiwi.com")
        ]
        
        all_found = []
        for name, url, sel, *extra in targets:
            root = extra[0] if extra else None
            res = scrape_direct(p, name, url, sel, root_url=root)
            if res: all_found.extend(res)

        if not all_found:
            enviar_telegram("<b>Monitor de Vuelos:</b> No se detectaron vuelos rápidos en esta pasada. 🫡")
            return

        # Agrupar por aerolínea y quedarnos con el mejor de cada una
        best_per_airline = {}
        for f in all_found:
            air = f["airline"]
            if air not in best_per_airline or f["price_val"] < best_per_airline[air]["price_val"]:
                best_per_airline[air] = f

        # Ordenar por precio
        sorted_results = sorted(best_per_airline.values(), key=lambda x: x["price_val"])
        
        mensaje = "✈️ <b>MEJORES PRECIOS POR AEROLÍNEA</b> ✈️\n\n"
        for r in sorted_results:
            mensaje += f"✅ <b>{r['airline']}</b>\n"
            mensaje += f"💰 Precio: <b>{r['price_str']}</b>\n"
            mensaje += f"⏱️ Duración: {r['dur']}\n"
            mensaje += f"🔗 <a href='{r['url']}'>Link Directo</a>\n\n"

        enviar_telegram(mensaje)

if __name__ == "__main__":
    monitor()
