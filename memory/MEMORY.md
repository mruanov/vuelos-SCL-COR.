# Context Continuity Memory

## Current State
- Updated the flight monitor agent [flight_monitor.py](file:///Users/mruanov/Documents/Claude_Projects/flight_monitor.py) to support flexible weekend-based date searches, local price persistence, and a trend analysis recommendation engine.
- Configured dependencies (Playwright, playwright-stealth, requests) inside `.venv`.
- Verified a full execution of the SCL to BKK search and verified historical data logger.

## Database & Persistence
- File: [flight_price_history.csv](file:///Users/mruanov/Documents/Claude_Projects/flight_price_history.csv) in the project workspace.
- Columns: `timestamp, origen, destino, fecha_ida, fecha_vuelta, aerolinea, precio_raw, precio_usd, duracion, source`

## Prediction Engine Logic
- Rules:
  - BUY recommendation if current price is <= 1.05 * historical minimum.
  - GOOD MOMENT recommendation if current price is < average historical price.
  - WAIT recommendation if current price is >= average historical price.
- Velocity: Calculates the percentage change in average prices between the first and last run dates to state if the market is trending up or down.

## Scraping & Anti-Bot Strategies
- Uses Playwright headless Chromium.
- Custom stealth configurations via `apply_stealth_robust`.
- User agent randomization.
- Respects robots rules by adding random sleeps between date checks.
