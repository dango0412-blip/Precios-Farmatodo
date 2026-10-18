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
        pag.on("response", lambda r: tareas.append(asyncio.create_task(al_responder(r))))
        await pag.goto(URL_CATEGORIA, wait_until="networkidle", timeout=90000)
        await pag.wait_for_timeout(4000)
        await asyncio.gather(*tareas)
        print(f"carga inicial: {len(items)} productos")
        for n in range(1, MAX_PAGINAS + 1):
            boton = pag.locator("button:has-text('Cargar más')")
            if not await boton.count() or not await boton.first.is_enabled():
                print("El botón 'Cargar más' ya no está activo: se llegó al final.")
                break
            antes = len(items)
            try:
                await boton.first.scroll_into_view_if_needed(timeout=5000)
                await boton.first.click(timeout=10000)
            except Exception as e:
                print("No se pudo pulsar 'Cargar más' (", type(e).__name__, "): se sigue con lo descargado.")
                break
            await pag.wait_for_timeout(2500)
            await asyncio.gather(*tareas)
            print(f"clic {n}: {len(items) - antes} productos nuevos (total {len(items)})")
            if len(items) == antes:
                break
            await asyncio.sleep(PAUSA)
        await nav.close()
    return items

def obtener_tasa():
    """Tasa oficial BCV (Bs por US$) desde ve.dolarapi.com, que republica el dólar oficial del BCV."""
    try:
        req = urllib.request.Request("https://ve.dolarapi.com/v1/dolares/oficial", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        return float(d["promedio"]), (d.get("fechaActualizacion") or "")[:10], "dolarapi (BCV oficial)"
    except Exception as e:
        print("No se pudo obtener la tasa BCV automáticamente:", type(e).__name__)
        return None

def desde_muestra(ruta):
    d = json.load(open(ruta, encoding="utf-8"))
    h = next(x for x in d if "calculate-best-deal" in x["url"])
    its = json.loads(h["datos_enviados"])["bestDealItems"]["sellers"][0]["items"]
    return [dict(id=i["itemId"], mediaDescription=i["name"], marca=i["marca"], fullPrice=i["unitPrice"],
                 offerPrice=i["offerPrice"], offerText=i["offerText"], offerDescription=i["offerDescription"],
                 subCategory=i["subCategory"]) for i in its]

def fila(it, fecha):
    nombre, marca = (it.get("mediaDescription") or "").strip(), (it.get("marca") or "").strip()
    regular = it.get("fullPrice") or it.get("offerPrice") or 0
    promo = it.get("offerPrice") or regular
    desc = it.get("offerDescription") or ""
    cond = int(any(k in desc.lower() for k in ("1era compra", "delivery")))  # promo condicional
    cant, unidad = nz.parse_capacidad(nombre) or (None, None)
    img = it.get("mediaImageUrl") or (it.get("listUrlImages") or [None])[0]
    return (fecha, str(it["id"]), nombre, marca, nz.clasificar(nombre), cant, unidad, regular, promo,
            it.get("offerText"), desc, cond, it.get("totalStock"), it.get("subCategory"), img)

def guardar(db, filas):
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE IF NOT EXISTS precios(fecha TEXT, id TEXT, nombre TEXT, marca TEXT, categoria TEXT,
        cantidad REAL, unidad TEXT, precio_regular REAL, precio_promo REAL, promo_texto TEXT, promo_desc TEXT,
        promo_cond INTEGER, stock INTEGER, subcategoria TEXT, imagen TEXT, PRIMARY KEY(fecha, id))""")
    if "imagen" not in [c[1] for c in con.execute("PRAGMA table_info(precios)")]:
        con.execute("ALTER TABLE precios ADD COLUMN imagen TEXT")  # bases creadas con la versión anterior
    con.execute("CREATE TABLE IF NOT EXISTS tasas(fecha TEXT PRIMARY KEY, bs_por_usd REAL, fecha_valor TEXT, fuente TEXT)")
    con.executemany("INSERT OR REPLACE INTO precios VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", filas)
    con.commit()
    return con

def generar_panel(con, salida):
    rows = con.execute("""SELECT fecha,id,nombre,marca,categoria,cantidad,unidad,precio_regular,precio_promo,promo_cond,imagen
                          FROM precios WHERE categoria IS NOT NULL ORDER BY fecha""").fetchall()
    prods, fechas = {}, sorted({r[0] for r in rows})
    for f, i, n, m, c, q, u, r, p, cond, img in rows:
        d = prods.setdefault(i, dict(id=i, nombre=n, marca=m.lower(), categoria=c, cantidad=q, unidad=u,
                                     rol=nz.rol(m, c), h={}))
        if img:
            d["img"] = img
        d["h"][f] = [round(r, 2), round(r if cond else p, 2)]  # [regular, efectivo sin promos condicionales]
    cats = [c for c in nz.CATEGORIAS if any(p["categoria"] == c for p in prods.values())]
    datos = json.dumps(dict(fechas=fechas, categorias=cats, productos=list(prods.values()),
                            tasas=dict(con.execute("SELECT fecha, bs_por_usd FROM tasas"))), ensure_ascii=False)
    html = (AQUI / "plantilla_panel.html").read_text(encoding="utf-8").replace("__DATOS__", datos)
    Path(salida).write_text(html, encoding="utf-8")

if __name__ == "__main__":
    muestra = sys.argv[sys.argv.index("--muestra") + 1] if "--muestra" in sys.argv else None
    items = desde_muestra(muestra) if muestra else asyncio.run(descargar())
    hoy = dt.date.today().isoformat()
    con = guardar(AQUI / ("precios_muestra.db" if muestra else "precios.db"), [fila(i, hoy) for i in items])
    manual = sys.argv[sys.argv.index("--tasa") + 1] if "--tasa" in sys.argv else None
    t = (float(manual.replace(",", ".")), hoy, "manual") if manual else obtener_tasa()
    if not t:
        ult = con.execute("SELECT bs_por_usd, fecha FROM tasas ORDER BY fecha DESC LIMIT 1").fetchone()
        if ult:
            t = (ult[0], ult[1], "última conocida")
            print(f"AVISO: se usó la última tasa guardada ({ult[1]}). Puedes indicarla tú: python recolector.py --tasa 880,12")
        else:
            print("AVISO: sin tasa BCV; el panel solo mostrará bolívares. Indícala así: python recolector.py --tasa 880,12")
    if t:
        con.execute("INSERT OR REPLACE INTO tasas VALUES(?,?,?,?)", (hoy, *t))
        con.commit()
        print(f"Tasa BCV del día: Bs {t[0]:,.4f} por US$ ({t[2]})")
    salida = sys.argv[sys.argv.index("--salida") + 1] if "--salida" in sys.argv else None
    destino = Path(salida) if salida else AQUI / ("panel_muestra.html" if muestra else "panel.html")
    destino.parent.mkdir(parents=True, exist_ok=True)
    generar_panel(con, destino)
    print(f"Listo: {len(items)} productos guardados ({hoy}). Abre el panel .html en tu navegador.")
    from collections import Counter
    cuenta = Counter(nz.clasificar((i.get("mediaDescription") or "")) for i in items)
    print("En tus categorías ->", ", ".join(f"{k}: {v}" for k, v in cuenta.items() if k) or "ninguno",
          f"| sin categoría: {cuenta.get(None, 0)}")
    con_foto = sum(1 for i in items if i.get("mediaImageUrl") or i.get("listUrlImages"))
    print(f"Productos con enlace de foto: {con_foto} de {len(items)}")
    vistas = {(i.get("marca") or "").strip().lower() for i in items}
    esperadas = (nz.COLGATE - {"acción", "accion"}) | set().union(*nz.COMPETENCIA.values())
    faltan = sorted(esperadas - vistas)
    if faltan:
        print("AVISO - marcas de tu lista que no aparecieron en esta categoría:", ", ".join(faltan))
