# Context Continuity Memory

## Current State
- Upgraded flight monitor [flight_monitor.py](file:///Users/mruanov/Documents/Claude_Projects/flight_monitor.py) to support four platforms: Google Flights, Kayak, Skyscanner, and Hopper.
- Formatted all pricing representations to Chilean Pesos (CLP) using rate conversion.
- Shortened the Telegram alert message to only show the Top 4 cheapest flights (Airline, source search engine, CLP price, and short-formatted dates).
- Implemented randomized flexible date range generation: on each execution, it generates 4 randomized date pairs starting from November 2026 up to the airline schedule limit (~330 days in advance) on any day of the week with a stay duration between 15 and 30 days.
- Successfully verified execution and date generation.
- Staged, committed, and pushed changes successfully (with rebase) to the remote GitHub repository.

## Scrapers and Selectors
- **Google Flights:** URL with `&curr=CLP`. Selector `[role='listitem'], .mzYp9c, .yR1fYc`.
- **Kayak.cl:** Selector `.nrc6, [class*='resultWrapper'], .Base-Results-ResultCard`.
- **Skyscanner.cl:** URL with `&curr=CLP`. Selector `[class*='Ticket_wrapper'], [data-testid*='ticket'], [class*='TicketContainer'], .FlightsTicket_container__`.
- **Hopper:** Selector `[class*='FlightResult'], [class*='ResultCard'], [data-testid*='result-card'], .search-result`.

## Database and Analytics
- CSV database file: [flight_price_history.csv](file:///Users/mruanov/Documents/Claude_Projects/flight_price_history.csv).
- Commits are pushed back from GitHub Actions on each successful execution to persist historical values.
