import time
import requests
import os
import re
import random
import csv
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# --- CONFIGURACION POR DEFECTO ---
ORIGEN = "SCL"
DESTINO = "BKK"
FECHA_IDA = "2026-11-06"
FECHA_VUELTA = "2026-11-21"
MAX_DURACION_MINUTOS = 2700 # 45 Horas

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
        print("Telegram not configured. Message content:")
        print(mensaje)
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
                time.sleep(random.uniform(2, 4))
            except: pass

        page.goto(url, wait_until="domcontentloaded", timeout=95000)
        time.sleep(random.uniform(10, 15))
        
        # BYPASS CONSENTIMIENTO
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
        if len(items) == 0:
            screenshot_path = f"screenshot_{name.lower().replace(' ', '_')}.png"
            page.screenshot(path=screenshot_path)
            print(f"   Saved failure screenshot for {name} to {screenshot_path}")

        for i, item in enumerate(items):
            try:
                inner = item.inner_text()
                if not inner or len(inner) < 30: continue
                
                airline_detected = "Otras"
                known = [
                    "LATAM", "JetSMART", "SKY", "Aerolíneas Argentinas", "Iberia", "Copa",
                    "Flybondi", "Avianca", "Emirates", "Qatar", "Qantas", "American Airlines",
                    "Delta", "United", "Air France", "KLM", "British Airways", "Lufthansa",
                    "Ethiopian", "Turkish Airlines", "Singapore Airlines", "ANA", "JAL", "Thai"
                ]
                for k in known:
                    if k.lower() in inner.lower():
                        airline_detected = k
                        break

                dur_regex = r'(\d+\s*(?:horas?|hours?|hrs?|h)\s*\d*\s*(?:minutos?|mins?|m)?|\d+\s*(?:minutos?|mins?|m))'
                dur_matches = re.findall(dur_regex, inner.lower())
                if not dur_matches: dur_matches = re.findall(r'(\d{1,2}[h:]\d{2})', inner.lower())
                
                mins = [get_minutes_robust(d) for d in dur_matches]
                mins = [m for m in mins if 20 < m < 3000]
                
                p_match = re.search(r'(?:\$|CLP|USD|pesos)?\s?(\d+[\.\,]\d{3})', inner, re.IGNORECASE)
                if not p_match: p_match = re.search(r'(\d{5,})', inner)
                
                if p_match and mins:
                    p_str = p_match.group(0).strip()
                    p_val_raw = int(re.sub(r'[^\d]', '', p_str))
                    p_val_norm = p_val_raw / 950 if p_val_raw > 10000 else p_val_raw
                    
                    if all(m <= MAX_DURACION_MINUTOS for m in mins):
                        found_flights.append({
                            "source": name,
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

def monitor(date_combinations):
    all_found = []
    
    with sync_playwright() as p:
        for idx, (ida, vuelta) in enumerate(date_combinations):
            print(f"\n[{idx+1}/{len(date_combinations)}] Buscando combinación: Ida {ida} | Vuelta {vuelta}...")
            
            targets = [
                ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{ida}%20through%20{vuelta}&curr=CLP", "[role='listitem'], .mzYp9c, .yR1fYc"),
                ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{ida}/{vuelta}?sort=price_a", ".nrc6, [class*='resultWrapper'], .Base-Results-ResultCard", "https://www.kayak.cl"),
                ("Skyscanner", f"https://www.skyscanner.cl/transporte/vuelos/{ORIGEN}/{DESTINO}/{ida}/{vuelta}/?rtn=1&preferdirects=false&outboundaltsenabled=false&inboundaltsenabled=false&ref=home&curr=CLP", "[class*='Ticket_wrapper'], [data-testid*='ticket'], [class*='TicketContainer'], .FlightsTicket_container__", "https://www.skyscanner.cl"),
                ("Hopper", f"https://hopper.com/search/flights/{ORIGEN}/{DESTINO}/{ida}/{vuelta}", "[class*='FlightResult'], [class*='ResultCard'], [data-testid*='result-card'], .search-result", "https://hopper.com")
            ]
            
            for name, url, sel, *extra in targets:
                root = extra[0] if extra else None
                res = scrape_direct(p, name, url, sel, root_url=root)
                if res:
                    for r in res:
                        r["fecha_ida"] = ida
                        r["fecha_vuelta"] = vuelta
                    all_found.extend(res)
                    
            # Breve pausa entre búsquedas para parecer humano
            if idx < len(date_combinations) - 1:
                time.sleep(random.uniform(3, 7))

    if not all_found:
        enviar_telegram(f"<b>Monitor de Vuelos:</b> No se detectaron vuelos en esta pasada para ninguna combinación de fecha. 🫡")
        return

    # Guardar en el historial de precios local
    guardar_en_historial(all_found)

    # 1. Filtrar duplicados exactos y armar Top 5 vuelos más baratos
    seen = set()
    unique_flights = []
    for f in all_found:
        key = (f["airline"], f["price_val"], f.get("fecha_ida"), f.get("fecha_vuelta"), f["source"])
        if key not in seen:
            seen.add(key)
            unique_flights.append(f)
            
    sorted_all = sorted(unique_flights, key=lambda x: x["price_val"])[:5]
    
    mensaje = f"✈️ <b>TOP 5 VUELOS MÁS BARATOS ({ORIGEN} ➔ {DESTINO})</b> ✈️\n\n"
    for i, r in enumerate(sorted_all):
        clp_val = int(r["price_val"] * 950)
        clp_str = f"${clp_val:,}".replace(",", ".")
        mensaje += f"<b>{i+1}. {r['airline']}</b>\n"
        mensaje += f"   📅 Fechas: <b>{r.get('fecha_ida')}</b> al <b>{r.get('fecha_vuelta')}</b>\n"
        mensaje += f"   💰 Precio: <b>{clp_str} CLP</b> (~USD {int(r['price_val'])})\n"
        mensaje += f"   🌐 Encontrado en: <b>{r['source']}</b>\n"
        mensaje += f"   ⏱️ Duración: {r['dur']}\n"
        mensaje += f"   🔗 <a href='{r['url']}'>Link Directo</a>\n\n"

    # 2. Agrupar los mejores precios por aerolínea e incluir las fechas correspondientes
    best_per_airline = {}
    for f in unique_flights:
        air = f["airline"]
        if air not in best_per_airline or f["price_val"] < best_per_airline[air]["price_val"]:
            best_per_airline[air] = f

    sorted_results = sorted(best_per_airline.values(), key=lambda x: x["price_val"])
    
    mensaje += "---\n✈️ <b>MEJORES PRECIOS POR AEROLÍNEA</b> ✈️\n\n"
    for r in sorted_results:
        clp_val = int(r["price_val"] * 950)
        clp_str = f"${clp_val:,}".replace(",", ".")
        mensaje += f"✅ <b>{r['airline']}</b>\n"
        mensaje += f"   📅 Fechas: <b>{r.get('fecha_ida')}</b> al <b>{r.get('fecha_vuelta')}</b>\n"
        mensaje += f"   💰 Precio: <b>{clp_str} CLP</b> (~USD {int(r['price_val'])})\n"
        mensaje += f"   🌐 Encontrado en: <b>{r['source']}</b>\n"
        mensaje += f"   ⏱️ Duración: {r['dur']}\n"
        mensaje += f"   🔗 <a href='{r['url']}'>Link Directo</a>\n\n"

    # Agregar el análisis de tendencias e histórico
    try:
        reporte_tendencias = analizar_tendencias(all_found)
        mensaje += "---\n" + reporte_tendencias
    except Exception as e:
        mensaje += f"\nError en análisis de tendencias: {e}"

    enviar_telegram(mensaje)

HISTORIAL_FILE = "flight_price_history.csv"

def guardar_en_historial(flights):
    file_exists = os.path.exists(HISTORIAL_FILE)
    with open(HISTORIAL_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "origen", "destino", "fecha_ida", "fecha_vuelta", "aerolinea", "precio_raw", "precio_usd", "duracion", "source"])
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for fl in flights:
            writer.writerow([
                timestamp,
                ORIGEN,
                DESTINO,
                fl.get("fecha_ida", FECHA_IDA),
                fl.get("fecha_vuelta", FECHA_VUELTA),
                fl["airline"],
                fl["price_str"],
                int(fl["price_val"]),
                fl["dur"],
                fl["source"]
            ])

def analizar_tendencias(current_flights):
    if not os.path.exists(HISTORIAL_FILE):
        return "⚠️ <b>Historial de precios:</b> No hay suficiente historial de precios para estimar tendencias todavía. Guardando primeros datos."
    
    history = []
    try:
        with open(HISTORIAL_FILE, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                history.append(row)
    except Exception as e:
        return f"⚠️ <b>Error leyendo historial:</b> {e}"
        
    if not history:
        return "⚠️ <b>Historial de precios:</b> Historial vacío. Guardando primeros datos."

    report = "📈 <b>ANÁLISIS DE TENDENCIAS Y RECOMENDACIÓN</b> 📈\n\n"
    
    if not current_flights:
        return "No hay vuelos actuales para analizar."
        
    best_current = min(current_flights, key=lambda x: x["price_val"])
    best_current_price = best_current["price_val"]
    best_current_date_key = (best_current.get("fecha_ida", FECHA_IDA), best_current.get("fecha_vuelta", FECHA_VUELTA))
    
    all_past_prices = [int(row["precio_usd"]) for row in history if row["origen"] == ORIGEN and row["destino"] == DESTINO]
    
    if all_past_prices:
        min_past = min(all_past_prices)
        avg_past = sum(all_past_prices) / len(all_past_prices)
        
        report += f"📊 <b>Precio actual más bajo:</b> USD {int(best_current_price)} ({best_current['price_str']}) de {best_current['airline']} ({best_current_date_key[0]} al {best_current_date_key[1]})\n"
        report += f"📉 <b>Historial de la ruta {ORIGEN} ➔ {DESTINO}:</b>\n"
        report += f"   • Mínimo histórico registrado: USD {min_past}\n"
        report += f"   • Promedio histórico registrado: USD {int(avg_past)}\n\n"
        
        # Recommendation
        if best_current_price <= min_past * 1.05:
            report += "🚨 <b>RECOMENDACIÓN: ¡COMPRA AHORA!</b> El precio actual está en el mínimo histórico o muy cerca de él (dentro del 5%). Es poco probable que baje significativamente más.\n"
        elif best_current_price < avg_past:
            report += "✅ <b>RECOMENDACIÓN: BUEN MOMENTO.</b> El precio está por debajo del promedio histórico. Es una opción razonable si tienes fechas fijas.\n"
        else:
            report += "⏳ <b>RECOMENDACIÓN: ESPERA.</b> El precio actual está por encima del promedio histórico. Te sugerimos esperar si tienes flexibilidad, ya que suele haber mejores ofertas.\n"
    
    # Check trend over time (last N queries)
    timestamps = sorted(list(set(row["timestamp"][:10] for row in history))) # group by date
    if len(timestamps) >= 2:
        avg_per_day = {}
        for t in timestamps:
            prices_for_day = [int(row["precio_usd"]) for row in history if row["timestamp"].startswith(t)]
            if prices_for_day:
                avg_per_day[t] = sum(prices_for_day) / len(prices_for_day)
                
        sorted_days = sorted(avg_per_day.keys())
        if len(sorted_days) >= 2:
            first_avg = avg_per_day[sorted_days[0]]
            last_avg = avg_per_day[sorted_days[-1]]
            change_pct = ((last_avg - first_avg) / first_avg) * 100
            
            report += f"\n📈 <b>Evolución del mercado:</b>\n"
            if change_pct < -2:
                report += f"   • Los precios promedio de esta ruta han <b>bajado {abs(change_pct):.1f}%</b> desde el {sorted_days[0]} al {sorted_days[-1]}."
            elif change_pct > 2:
                report += f"   • Los precios promedio de esta ruta han <b>subido {change_pct:.1f}%</b> desde el {sorted_days[0]} al {sorted_days[-1]}. Recomendamos comprar antes de que sigan subiendo."
            else:
                report += f"   • Los precios se mantienen estables (variación del {change_pct:.1f}%)."
                
    return report

def generar_combinaciones_fechas(fecha_inicio_str, cantidad_meses=3, duracion_min=15, duracion_max=30):
    try:
        start_date = datetime.strptime(fecha_inicio_str, "%Y-%m-%d")
    except Exception:
        start_date = datetime.now() + timedelta(days=30)
        
    # Si la fecha de inicio es anterior a noviembre de 2026, forzamos a que empiece en noviembre
    if start_date < datetime(2026, 11, 1):
        start_date = datetime(2026, 11, 1)
        
    date_list = []
    current = start_date
    end_date = start_date + timedelta(days=cantidad_meses * 30)
    
    # Buscamos viernes (4) o sábados (5) para las salidas
    while current < end_date:
        if current.weekday() in (4, 5):
            ida = current.strftime("%Y-%m-%d")
            # Agregamos estadías corta (min) y larga (max)
            vuelta_min = (current + timedelta(days=duracion_min)).strftime("%Y-%m-%d")
            vuelta_max = (current + timedelta(days=duracion_max)).strftime("%Y-%m-%d")
            
            date_list.append((ida, vuelta_min))
            date_list.append((ida, vuelta_max))
            
            current += timedelta(days=14) # Avanzar dos semanas para muestrear
        else:
            current += timedelta(days=1)
            
    # Para evitar bloqueos, seleccionamos un máximo de 8 combinaciones bien distribuidas
    if len(date_list) > 8:
        step = len(date_list) // 8
        date_list = date_list[::step][:8]
        
    return date_list

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor de Vuelos con Playwright y Análisis de Tendencias")
    parser.add_argument("--origen", default=ORIGEN, help=f"Aeropuerto de origen (default: {ORIGEN})")
    parser.add_argument("--destino", default=DESTINO, help=f"Aeropuerto de destino (default: {DESTINO})")
    parser.add_argument("--fecha-ida", default=FECHA_IDA, help=f"Fecha de ida base o de inicio para flexible AAAA-MM-DD (default: {FECHA_IDA})")
    parser.add_argument("--fecha-vuelta", default=FECHA_VUELTA, help=f"Fecha de vuelta AAAA-MM-DD (default: {FECHA_VUELTA})")
    parser.add_argument("--max-duracion", type=int, default=MAX_DURACION_MINUTOS, help=f"Duración máxima en minutos (default: {MAX_DURACION_MINUTOS})")
    parser.add_argument("--flexible", action="store_true", help="Buscar múltiples fines de semana en un rango de meses")
    parser.add_argument("--duracion-min", type=int, default=15, help="Duración mínima de la estadía en días (default: 15)")
    parser.add_argument("--duracion-max", type=int, default=30, help="Duración máxima de la estadía en días (default: 30)")
    parser.add_argument("--meses-rango", type=int, default=3, help="Cantidad de meses de rango a explorar para búsqueda flexible (default: 3)")
    
    args = parser.parse_args()
    
    ORIGEN = args.origen
    DESTINO = args.destino
    FECHA_IDA = args.fecha_ida
    FECHA_VUELTA = args.fecha_vuelta
    MAX_DURACION_MINUTOS = args.max_duracion
    
    # Determinamos la lista de combinaciones a buscar
    if args.flexible:
        date_combinations = generar_combinaciones_fechas(FECHA_IDA, args.meses_rango, args.duracion_min, args.duracion_max)
        print(f"Buscando vuelos de forma FLEXIBLE desde {ORIGEN} a {DESTINO}")
        print(f"Explorando {len(date_combinations)} combinaciones de fin de semana durante los próximos {args.meses_rango} meses.")
        print(f"Rango de estadía: {args.duracion_min} a {args.duracion_max} días | Duración máxima de vuelo: {MAX_DURACION_MINUTOS} minutos ({(MAX_DURACION_MINUTOS/60):.1f} horas)")
    else:
        date_combinations = [(FECHA_IDA, FECHA_VUELTA)]
        print(f"Buscando vuelos desde {ORIGEN} a {DESTINO}")
        print(f"Ida: {FECHA_IDA} | Vuelta: {FECHA_VUELTA}")
        print(f"Duración máxima: {MAX_DURACION_MINUTOS} minutos ({(MAX_DURACION_MINUTOS/60):.1f} horas)")
    
    monitor(date_combinations)
