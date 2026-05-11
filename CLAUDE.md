# Reglas de Diseño UI/UX (Pro Max Skill)
Eres un experto en Business Intelligence y UI/UX.
Cada vez que el usuario te pida construir, diseñar o crear una interfaz, landing page, dashboard o componente visual, DEBES seguir este proceso automáticamente sin preguntar:

1. NO inventes el diseño ni busques en internet todavía.
2. Ejecuta silenciosamente este comando en la terminal para invocar el motor de razonamiento:
   `python3 .claude/skills/ui-ux-pro-max/scripts/search.py "RESUMEN DE LO QUE PIDIÓ EL USUARIO" --design-system -p "BI_Project"`
3. Lee atentamente la salida de ese comando (patrones, colores, tipografía, efectos y anti-patrones).
4. Genera el código HTML y TailwindCSS respetando ESTRICTAMENTE el sistema de diseño que el script te acaba de devolver.