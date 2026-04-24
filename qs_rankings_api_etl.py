"""
ETL: QS World University Rankings 2026
Extrae 7 rankings desde la API interna de topuniversities.com,
genera un CSV por ranking y un archivo JS con la constante QS_DATA_2026.

API descubierta inspeccionando tráfico XHR de la página:
  GET https://www.topuniversities.com/rankings/endpoint
      ?nid={nid}&page={page}&items_per_page={n}&tab=indicators&sort_by=rank&order_by=asc

Respuesta JSON:
  { "total_record": N, "total_pages": P, "score_nodes": [...] }

Cada score_node incluye:
  title, path, region, country, city, overall_score, rank_display, rank,
  scores: { "categoria": [{ indicator_name, rank, score }, ...] }
"""

import json
import re
import time

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

BASE_URL = "https://www.topuniversities.com"
API_ENDPOINT = f"{BASE_URL}/rankings/endpoint"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": f"{BASE_URL}/world-university-rankings",
}

# nid = Drupal node ID de cada ranking (descubierto inspeccionando el HTML de cada página)
RANKINGS = {
    "global": {
        "nombre": "QS World University Rankings 2026",
        "nid": "4061771",
        "categoria": "global",
        "archivo_salida": "qs_world_ranking_2026.csv",
    },
    "latam_caribbean": {
        "nombre": "QS Latin America & Caribbean University Rankings 2025",
        "nid": "4070255",
        "categoria": "region",
        "archivo_salida": "qs_latam_caribbean_2025.csv",
    },
    "latam_south_america": {
        "nombre": "QS Latin America – South America Rankings 2025",
        "nid": "4070900",
        "categoria": "region",
        "archivo_salida": "qs_latam_south_america_2025.csv",
    },
    "social_sciences": {
        "nombre": "QS World University Rankings by Subject 2025 – Social Sciences & Management",
        "nid": "4114617",
        "categoria": "subject",
        "archivo_salida": "qs_subject_social_sciences_2025.csv",
    },
    "economics": {
        "nombre": "QS World University Rankings by Subject 2025 – Economics & Econometrics",
        "nid": "4114640",
        "categoria": "subject",
        "archivo_salida": "qs_subject_economics_2025.csv",
    },
    "accounting_finance": {
        "nombre": "QS World University Rankings by Subject 2025 – Accounting & Finance",
        "nid": "4114616",
        "categoria": "subject",
        "archivo_salida": "qs_subject_accounting_finance_2025.csv",
    },
    "business_management": {
        "nombre": "QS World University Rankings by Subject 2025 – Business & Management Studies",
        "nid": "4114625",
        "categoria": "subject",
        "archivo_salida": "qs_subject_business_management_2025.csv",
    },
}

# ---------------------------------------------------------------------------
# Extracción
# ---------------------------------------------------------------------------

# Sesión global para mantener cookies entre peticiones (ayuda con Cloudflare)
_session = requests.Session()
_session.headers.update(HEADERS)

ITEMS_PER_PAGE = 50  # tamaño de página que acepta el servidor sin 403


def _get_page(nid: str, page: int, retries: int = 5) -> dict:
    url = (
        f"{API_ENDPOINT}?nid={nid}&page={page}"
        f"&items_per_page={ITEMS_PER_PAGE}&tab=indicators&sort_by=rank&order_by=asc"
    )
    for intento in range(retries):
        try:
            r = _session.get(url, timeout=30)
            if r.status_code == 403:
                espera = 3 * (2 ** intento)
                print(f"      403 en pagina {page}, reintento {intento + 1}/{retries} en {espera}s...")
                time.sleep(espera)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if intento < retries - 1:
                time.sleep(2 ** intento)
            else:
                raise
    raise RuntimeError(f"No se pudo obtener pagina {page} del nid {nid} tras {retries} intentos")


def _aplanar_scores(scores: dict) -> dict:
    """Convierte el dict anidado de scores en columnas planas snake_case."""
    plano = {}
    for categoria, indicadores in scores.items():
        for ind in indicadores:
            nombre = re.sub(r"[^a-z0-9]+", "_", ind["indicator_name"].lower()).strip("_")
            plano[nombre + "_score"] = ind.get("score")
            plano[nombre + "_rank"] = ind.get("rank")
    return plano


def obtener_ranking(nid: str, nombre: str) -> pd.DataFrame:
    primera = _get_page(nid, 0)
    total = primera.get("total_record", 0)
    total_pages = primera.get("total_pages", 1)
    print(f"    {total} universidades, {total_pages} paginas (items_per_page={ITEMS_PER_PAGE})")

    nodos = list(primera.get("score_nodes", []))

    for page in range(1, total_pages):
        datos = _get_page(nid, page)
        nodos.extend(datos.get("score_nodes", []))
        if page % 5 == 0 or page == total_pages - 1:
            print(f"      pagina {page + 1}/{total_pages} | acumulado {len(nodos)}/{total}")
        time.sleep(0.5)

    registros = []
    for n in nodos:
        base = {
            "rank_display":  n.get("rank_display"),
            "rank":          n.get("rank"),
            "name":          n.get("title"),
            "country":       n.get("country"),
            "city":          n.get("city"),
            "region":        n.get("region"),
            "overall_score": n.get("overall_score"),
            "url":           BASE_URL + (n.get("path") or ""),
            "logo":          n.get("logo"),
        }
        scores_plano = _aplanar_scores(n.get("scores") or {})
        registros.append({**base, **scores_plano})

    return pd.DataFrame(registros)

# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------

def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["rank"] = (
        df["rank"].astype(str)
        .str.replace(r"[=+]", "", regex=True)
        .str.replace(r"[^\d].*", "", regex=True)
        .str.strip()
    )
    df = df.replace({"": None, "None": None, "nan": None})
    return df

# ---------------------------------------------------------------------------
# Salida JavaScript
# ---------------------------------------------------------------------------

def _df_a_lista(df: pd.DataFrame) -> list:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def generar_js(resultados: dict, ruta: str = "qs_data_2026.js"):
    estructura = {
        "global": [],
        "region": {},
        "subjects": {},
    }
    for clave, df in resultados.items():
        cfg = RANKINGS[clave]
        categoria = cfg["categoria"]
        datos = _df_a_lista(df)
        if categoria == "global":
            estructura["global"] = datos
        elif categoria == "region":
            estructura["region"][clave] = datos
        elif categoria == "subject":
            estructura["subjects"][clave] = datos

    js = "const QS_DATA_2026 = " + json.dumps(estructura, ensure_ascii=False, indent=2) + ";\n"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"[OK] {ruta}")

# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def main():
    resultados = {}

    for clave, cfg in RANKINGS.items():
        print(f"\n=== {cfg['nombre']} (nid={cfg['nid']}) ===")
        df_raw = obtener_ranking(cfg["nid"], cfg["nombre"])
        df = limpiar(df_raw)
        resultados[clave] = df
        print(f"    -> {len(df)} filas, {len(df.columns)} columnas")

    print("\n--- Guardando CSV ---")
    for clave, cfg in RANKINGS.items():
        df = resultados.get(clave)
        if df is None or df.empty:
            print(f"! {clave} sin datos")
            continue
        df.to_csv(cfg["archivo_salida"], index=False, encoding="utf-8-sig")
        print(f"[OK] {cfg['archivo_salida']}  ({len(df)} filas)")

    print("\n--- Generando JS ---")
    generar_js(resultados, "qs_data_2026.js")

    return resultados


if __name__ == "__main__":
    main()
