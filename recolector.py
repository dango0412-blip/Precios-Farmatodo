"""Recolector diario: Farmatodo > Higiene del Hogar (Caracas) -> precios.db -> panel.html

Uso:   python recolector.py                      (descarga, guarda y genera panel.html)
Prueba: python recolector.py --muestra descubrimiento.json   (sin internet, datos de ejemplo)
"""
import asyncio, datetime as dt, json, sqlite3, sys, urllib.request
from pathlib import Path
import normalizar as nz

AQUI = Path(__file__).parent
URL_CATEGORIA = "https://www.farmatodo.com.ve/categorias/hogar-mascota-y-otros/higiene-del-hogar"
CLAVE_API, MAX_PAGINAS, PAUSA = "getProductsFromCategoryAlgolia", 60, 1.5

async def descargar():
    """Abre la página como una persona y pulsa 'Cargar más' hasta que se acaben los productos."""
    from playwright.async_api import async_playwright
    vistos, items, tareas = set(), [], []

    async def al_responder(r):
        if CLAVE_API in r.url and r.ok:
            try:
                lote = (await r.json()).get("items", [])
            except Exception:
                return
            for it in lote:
                if it.get("id") not in vistos:
                    vistos.add(it.get("id"))
                    items.append(it)

    async with async_playwright() as p:
        nav = await p.chromium.launch(headless=True)
        ctx = await nav.new_context(locale="es-VE", viewport={"width": 1366, "height": 900})
        pag = await ctx.new_page()
        pag.on("response",
