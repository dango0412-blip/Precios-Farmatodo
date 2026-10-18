"""Recolector diario de precios: Farmatodo > Higiene del Hogar (Caracas).

Uso:    python recolector.py
Prueba: python recolector.py --muestra descubrimiento.json --tasa 880,12
"""
import asyncio
import datetime as dt
import json
import sqlite3
import struct
import sys
import urllib.request
import zlib
from collections import Counter
from pathlib import Path

import normalizar as nz

AQUI = Path(__file__).parent
URL_CATEGORIA = (
    "https://www.farmatodo.com.ve/categorias/"
    "hogar-mascota-y-otros/higiene-del-hogar"
)
URL_TASA = "https://ve.dolarapi.com/v1/dolares/oficial"
CLAVE_API = "getProductsFromCategoryAlgolia"
MAX_PAGINAS = 60
PAUSA = 1.5


async def descargar():
    """Abre la página y pulsa 'Cargar más' hasta que se acaben."""
    from playwright.async_api import async_playwright

    vistos, items, tareas = set(), [], []

    async def al_responder(r):
        if CLAVE_API not in r.url or not r.ok:
            return
        try:
            lote = (await r.json()).get("items", [])
        except Exception:
            return
        for it in lote:
            if it.get("id") not in vistos:
                vistos.add(it.get("id"))
                items.append(it)

    def al_recibir(r):
        tareas.append(asyncio.create_task(al_responder(r)))

    async with async_playwright() as p:
        nav = await p.chromium.launch(headless=True)
        ctx = await nav.new_context(
            locale="es-VE", viewport={"width": 1366, "height": 900}
        )
        pag = await ctx.new_page()
        pag.on("response", al_recibir)
        await pag.goto(URL_CATEGORIA, wait_until="networkidle", timeout=90000)
        await pag.wait_for_timeout(4000)
        await asyncio.gather(*tareas)
        print(f"carga inicial: {len(items)} productos")
        boton = pag.locator("button:has-text('Cargar más')")
        for n in range(1, MAX_PAGINAS + 1):
            if not await boton.count() or not await boton.first.is_enabled():
                print("El botón 'Cargar más' ya no está activo: fin.")
                break
            antes = len(items)
            try:
                await boton.first.scroll_into_view_if_needed(timeout=5000)
                await boton.first.click(timeout=10000)
            except Exception as e:
                print("No se pudo pulsar 'Cargar más':", type(e).__name__)
                break
            await pag.wait_for_timeout(2500)
            await asyncio.gather(*tareas)
            nuevos = len(items) - antes
            print(f"clic {n}: {nuevos} productos nuevos (total {len(items)})")
            if nuevos == 0:
                break
            await asyncio.sleep(PAUSA)
        await nav.close()
    return items


def obtener_tasa():
    """Tasa oficial BCV (Bs por US$) vía ve.dolarapi.com."""
    try:
        req = urllib.request.Request(
            URL_TASA, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        fecha = (d.get("fechaActualizacion") or "")[:10]
        return float(d["promedio"]), fecha, "dolarapi (BCV oficial)"
    except Exception as e:
        print("No se pudo obtener la tasa BCV:", type(e).__name__)
        return None


MANIFEST = {
    "name": "Precios Farmatodo · Colgate vs competencia",
    "short_name": "Precios",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#f4f6f8",
    "theme_color": "#c8102e",
    "lang": "es",
    "icons": [
        {"src": f"icon-{n}.png", "sizes": f"{n}x{n}",
         "type": "image/png", "purpose": "any maskable"}
        for n in (192, 512)
    ],
}

SW = """// Versión nueva si hay internet; si no, la última guardada.
const C = "precios-v1";
const BASE = ["./", "index.html", "manifest.webmanifest",
  "icon-192.png", "icon-512.png"];
self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(C).then(c => c.addAll(BASE)));
});
self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(k => Promise.all(
        k.filter(x => x !== C).map(x => caches.delete(x))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request, { cache: "no-cache" })
      .then(r => {
        const copia = r.clone();
        caches.open(C).then(c => c.put(e.request, copia));
        return r;
      })
      .catch(() => caches.match(e.request)
        .then(m => m || caches.match("index.html")))
  );
});
"""


def _trozo(tipo, datos):
    cuerpo = tipo + datos
    crc = zlib.crc32(cuerpo) & 0xFFFFFFFF
    return struct.pack(">I", len(datos)) + cuerpo + struct.pack(">I", crc)


def _icono(n):
    u = n / 512
    barras = []
    for x, h in ((130, 120), (226, 200), (322, 290)):
        barras.append(
            (int(x * u), int((x + 60) * u), int((400 - h) * u), int(400 * u))
        )
    filas = []
    for y in range(n):
        fila = bytearray([0])
        for x in range(n):
            blanco = any(a <= x < b and c <= y < d for a, b, c, d in barras)
            fila += b"\xff\xff\xff" if blanco else b"\xc8\x10\x2e"
        filas.append(bytes(fila))
    cabecera = struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _trozo(b"IHDR", cabecera)
        + _trozo(b"IDAT", zlib.compress(b"".join(filas)))
        + _trozo(b"IEND", b"")
    )


def escribir_app(carpeta):
    """Crea manifest, service worker e íconos para instalar la app."""
    carpeta.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(MANIFEST, ensure_ascii=False, indent=2)
    (carpeta / "manifest.webmanifest").write_text(texto, encoding="utf-8")
    (carpeta / "sw.js").write_text(SW, encoding="utf-8")
    for n in (192, 512):
        (carpeta / f"icon-{n}.png").write_bytes(_icono(n))


def desde_muestra(ruta):
    d = json.load(open(ruta, encoding="utf-8"))
    h = next(x for x in d if "calculate-best-deal" in x["url"])
    datos = json.loads(h["datos_enviados"])
    its = datos["bestDealItems"]["sellers"][0]["items"]
    salida = []
    for i in its:
        salida.append(dict(
            id=i["itemId"], mediaDescription=i["name"], marca=i["marca"],
            fullPrice=i["unitPrice"], offerPrice=i["offerPrice"],
            offerText=i["offerText"],
            offerDescription=i["offerDescription"],
            subCategory=i["subCategory"],
        ))
    return salida


def fila(it, fecha):
    nombre = (it.get("mediaDescription") or "").strip()
    marca = (it.get("marca") or "").strip()
    regular = it.get("fullPrice") or it.get("offerPrice") or 0
    promo = it.get("offerPrice") or regular
    desc = it.get("offerDescription") or ""
    cond = int(any(k in desc.lower() for k in ("1era compra", "delivery")))
    cant, unidad = nz.parse_capacidad(nombre) or (None, None)
    fotos = it.get("listUrlImages") or [None]
    img = it.get("mediaImageUrl") or fotos[0]
    return (
        fecha, str(it["id"]), nombre, marca, nz.clasificar(nombre),
        cant, unidad, regular, promo, it.get("offerText"), desc, cond,
        it.get("totalStock"), it.get("subCategory"), img,
    )


CREAR = """CREATE TABLE IF NOT EXISTS precios(
    fecha TEXT, id TEXT, nombre TEXT, marca TEXT, categoria TEXT,
    cantidad REAL, unidad TEXT, precio_regular REAL, precio_promo REAL,
    promo_texto TEXT, promo_desc TEXT, promo_cond INTEGER, stock INTEGER,
    subcategoria TEXT, imagen TEXT, PRIMARY KEY(fecha, id))"""
CREAR_TASAS = """CREATE TABLE IF NOT EXISTS tasas(
    fecha TEXT PRIMARY KEY, bs_por_usd REAL, fecha_valor TEXT, fuente TEXT)"""
CONSULTA = """SELECT fecha, id, nombre, marca, categoria, cantidad, unidad,
    precio_regular, precio_promo, promo_cond, imagen
    FROM precios WHERE categoria IS NOT NULL ORDER BY fecha"""


def guardar(db, filas):
    con = sqlite3.connect(db)
    con.execute(CREAR)
    cols = [c[1] for c in con.execute("PRAGMA table_info(precios)")]
    if "imagen" not in cols:
        con.execute("ALTER TABLE precios ADD COLUMN imagen TEXT")
    con.execute(CREAR_TASAS)
    ph = ",".join("?" * 15)
    con.executemany(f"INSERT OR REPLACE INTO precios VALUES({ph})", filas)
    con.commit()
    return con


def generar_panel(con, salida):
    rows = con.execute(CONSULTA).fetchall()
    prods = {}
    fechas = sorted({r[0] for r in rows})
    for f, i, n, m, c, q, u, r, p, cond, img in rows:
        d = prods.setdefault(i, dict(
            id=i, nombre=n, marca=m.lower(), categoria=c, cantidad=q,
            unidad=u, rol=nz.rol(m, c), h={},
        ))
        if img:
            d["img"] = img
        # [precio regular, precio efectivo sin promos condicionales]
        d["h"][f] = [round(r, 2), round(r if cond else p, 2)]
    cats = [c for c in nz.CATEGORIAS
            if any(p["categoria"] == c for p in prods.values())]
    tasas = dict(con.execute("SELECT fecha, bs_por_usd FROM tasas"))
    datos = json.dumps(
        dict(fechas=fechas, categorias=cats,
             productos=list(prods.values()), tasas=tasas),
        ensure_ascii=False,
    )
    plantilla = (AQUI / "plantilla_panel.html").read_text(encoding="utf-8")
    Path(salida).write_text(
        plantilla.replace("__DATOS__", datos), encoding="utf-8"
    )


def argumento(nombre):
    if nombre in sys.argv:
        return sys.argv[sys.argv.index(nombre) + 1]
    return None


def decidir_tasa(con, hoy):
    manual = argumento("--tasa")
    if manual:
        return float(manual.replace(",", ".")), hoy, "manual"
    t = obtener_tasa()
    if t:
        return t
    ult = con.execute(
        "SELECT bs_por_usd, fecha FROM tasas ORDER BY fecha DESC LIMIT 1"
    ).fetchone()
    if ult:
        print(f"AVISO: se usó la última tasa guardada ({ult[1]}).")
        print("Puedes indicarla tú: python recolector.py --tasa 880,12")
        return ult[0], ult[1], "última conocida"
    print("AVISO: sin tasa BCV; solo se mostrarán bolívares.")
    print("Indícala así: python recolector.py --tasa 880,12")
    return None


def resumen(items):
    cuenta = Counter(
        nz.clasificar(i.get("mediaDescription") or "") for i in items
    )
    ok = ", ".join(f"{k}: {v}" for k, v in cuenta.items() if k)
    print("En tus categorías ->", ok or "ninguno",
          f"| sin categoría: {cuenta.get(None, 0)}")
    con_foto = sum(
        1 for i in items if i.get("mediaImageUrl") or i.get("listUrlImages")
    )
    print(f"Productos con enlace de foto: {con_foto} de {len(items)}")
    vistas = {(i.get("marca") or "").strip().lower() for i in items}
    esperadas = nz.COLGATE - {"acción", "accion"}
    esperadas = esperadas | set().union(*nz.COMPETENCIA.values())
    faltan = sorted(esperadas - vistas)
    if faltan:
        print("AVISO - marcas de tu lista que no aparecieron:",
              ", ".join(faltan))


def main():
    muestra = argumento("--muestra")
    salida = argumento("--salida")
    items = desde_muestra(muestra) if muestra else asyncio.run(descargar())
    hoy = dt.date.today().isoformat()
    db = AQUI / ("precios_muestra.db" if muestra else "precios.db")
    con = guardar(db, [fila(i, hoy) for i in items])
    t = decidir_tasa(con, hoy)
    if t:
        con.execute("INSERT OR REPLACE INTO tasas VALUES(?,?,?,?)", (hoy, *t))
        con.commit()
        print(f"Tasa BCV del día: Bs {t[0]:,.4f} por US$ ({t[2]})")
    if salida:
        destino = Path(salida)
    else:
        destino = AQUI / ("panel_muestra.html" if muestra else "panel.html")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if salida:
        escribir_app(destino.parent)
    generar_panel(con, destino)
    print(f"Listo: {len(items)} productos guardados ({hoy}).")
    resumen(items)


if __name__ == "__main__":
    main()
