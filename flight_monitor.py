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
MAX_DURACION_MINUTOS = 360 

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown", "disable_web_page_preview": True}
    requests.post(url, json=payload, timeout=10)

def extract_minutes(text):
    text = text.lower()
    h = 0
    m = 0
    h_match = re.search(r'(\d+)\s*(h|hora|hour)', text)
    if h_match: h = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*(m|min)', text)
    if m_match: m = int(m_match.group(1))
    if h == 0 and m == 0:
        hm = re.search(r'(\d{1,2}):(\d{2})', text)
        if hm: return int(hm.group(1)) * 60 + int(hm.group(2))
    return h * 60 + m

def find_flights_in_text(name, page_text, url):
    """Busca vuelos analizando bloques de texto plano"""
    # Buscamos bloques que contengan precios y tiempos
    # Un bloque suele ser algo como: "1h 30m ... $180.000"
    found = []
    
    # Expresión regular para encontrar precios (números grandes)
    prices = re.findall(r'(\d+[\.\,]\d{3})|(\d{5,})', page_text)
    # Expresión regular para encontrar duraciones
    durations = re.findall(r'(\d+h\s*\d+m|\d+h|\d+m|\d{1,2}:\d{2})', page_text.lower())
    
    if prices and durations:
        # Si encontramos datos, intentamos parsear el primero (más barato usualmente)
        price_str = prices[0][0] or prices[0][1]
        
        # Limpiar precio para convertir a valor numerico
        val = int(re.sub(r'[^\d]', '', price_str))
        price_usd = val / 950 if val > 5000 else val
        
        # Verificar duraciones (tomamos las 2 primeras: ida y vuelta)
        valid = True
        for d in durations[:2]:
            if extract_minutes(d) > MAX_DURACION_MINUTOS:
                valid = False
        
        if valid:
            return {
                "plataforma": name,
                "precio": price_str,
                "val": price_usd,
                "dur": ", ".join(durations[:2]),
                "url": url
            }
    return None

def monitor():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Identidad humana completa
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        
        sources = [
            ("Google Flights", f"https://www.google.com/travel/flights?q=Flights%20to%20{DESTINO}%20from%20{ORIGEN}%20on%20{FECHA_IDA}%20through%20{FECHA_VUELTA}"),
            ("Kayak", f"https://www.kayak.cl/flights/{ORIGEN}-{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}?sort=price_a"),
            ("Kiwi.com", f"https://www.kiwi.com/en/search/results/{ORIGEN}/{DESTINO}/{FECHA_IDA}/{FECHA_VUELTA}")
        ]
        
        results = []
        for name, url in sources:
            print(f"🕵️ Agente analizando {name}...")
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                time.sleep(20) # Espera real para que cargue la data
                
                # Extraemos TODO el texto de la página
                page_content = page.content()
                # Limpiamos el HTML para quedarnos solo con el texto visible
                clean_text = re.sub(r'<[^>]*>', ' ', page_content)
                
                flight = find_flights_in_text(name, clean_text, url)
                if flight:
                    results.append(flight)
                    print(f"   ✅ ¡Vuelo detectado!")
                else:
                    print(f"   ❌ Sin vuelos válidos en el texto.")
                page.close()
            except Exception as e:
                print(f"   ⚠️ Error de carga en {name}")

        if not results:
            enviar_telegram("🔄 *Monitor*: Sin vuelos < 6h detectados. Re-intentando en la próxima vuelta. 🫡")
        else:
            results.sort(key=lambda x: x["val"])
            mejor = results[0]
            detalle = "\n".join([f"📍 *{r['plataforma']}*: ${r['precio']} ({r['dur']})" for r in results])
            mensaje = f"✈️ *VUELO ENCONTRADO (<6h)* ✈️\n\nEl mejor precio es *${mejor['precio']}* en {mejor['plataforma']}.\n\n{detalle}\n\n🔗 [Ver en la web]({mejor['url']})"
            enviar_telegram(mensaje)
        
        browser.close()

if __name__ == "__main__":
    monitor()
