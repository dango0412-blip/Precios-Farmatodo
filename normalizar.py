"""Reglas de clasificación y normalización (editables)."""
import re

COLGATE = {"brisol", "ajax", "axion", "acción", "accion", "suavitel", "fabuloso", "belrosita"}

COMPETENCIA = {  # marcas competidoras a seguir por categoría (en minúsculas)
    "Lavaplatos líquido": {"vale"},
    "Suavizantes": {"alive", "downy"},
    "Lavaplatos en crema": {"las llaves"},
    "Detergente líquido": {"ariel"},
    "Limpiador antibacterial / multiusos": {"las llaves"},
    "Cloro": {"lavansan"},
}
CATEGORIAS = list(COMPETENCIA)

def clasificar(nombre):
    n = nombre.lower().strip()
    if "suavizante" in n:
        return "Suavizantes"
    if "lavaplatos" in n or "lavavajilla" in n:
        return "Lavaplatos en crema" if "crema" in n else "Lavaplatos líquido"
    if "detergente" in n and ("líquido" in n or "liquido" in n):
        return "Detergente líquido"
    primera = n.split()[0] if n else ""
    if primera in ("cloro", "blanqueador", "lejia", "lejía"):
        return "Cloro"
    if primera == "limpiador" and not any(x in n for x in ("poceta", "tanque", "pastilla")):
        return "Limpiador antibacterial / multiusos"
    return None

def rol(marca, categoria):
    m = marca.lower()
    if m in COLGATE:
        return "colgate"
    return "competidor" if m in COMPETENCIA.get(categoria, ()) else "otra"

def parse_capacidad(nombre):
    """'x 700 ml' -> (700, 'ml'); '1Lt' -> (1000, 'ml'); '2 Kg' -> (2000, 'g'); '800Cc' -> (800, 'ml')."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|mililitros?|cc|lts?|litros?|l|kg|kilos?|gr?|gramos?)\b", nombre.lower())
    if not m:
        return None
    num, u = m.group(1), m.group(2)
    if re.fullmatch(r"\d{1,3}\.\d{3}", num):
        num = num.replace(".", "")
    v = float(num.replace(",", "."))
    if u[0] in "mc":
        return v, "ml"
    if u[0] == "l":
        return v * 1000, "ml"
    return (v * 1000, "g") if u[0] == "k" else (v, "g")
