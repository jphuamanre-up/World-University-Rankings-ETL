"""
ETL: Times Higher Education Rankings 2026
Extrae los tres rankings directamente desde la API JSON interna de THE,
enriquece con direcciones estructuradas por perfil y guarda en CSV.
"""

import json
import re

import pandas as pd
import requests
from bs4 import BeautifulSoup as soup

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

BASE_URL = "https://www.timeshighereducation.com"

HEADERS_API = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

RANKINGS = {
    "world_2026": {
        "nombre": "World University Rankings 2026",
        "api_url": "https://www.timeshighereducation.com/json/ranking_tables/world_university_rankings/2026",
        "archivo_salida": "the_world_ranking_2026.csv",
    },
    "business_economics_2026": {
        "nombre": "Subject Ranking 2026 – Business & Economics",
        "api_url": "https://www.timeshighereducation.com/json/ranking_tables/business_economics_rankings/2026",
        "archivo_salida": "the_subject_business_economics_2026.csv",
    },
    "latam_2026": {
        "nombre": "Latin America University Rankings 2026",
        "api_url": "https://www.timeshighereducation.com/json/ranking_tables/latin_america_rankings/2026",
        "archivo_salida": "the_latam_ranking_2026.csv",
    },
}

COLUMNAS_FINALES = [
    "rank_raw", "rank", "name", "country",
    "overall_score", "teaching_score", "research_env_score",
    "research_quality_score", "industry_score", "international_score",
    "url",
    "street_address", "locality", "region", "postal_code", "country_address",
]

# ---------------------------------------------------------------------------
# Extracción desde la API
# ---------------------------------------------------------------------------

def obtener_ranking_api(api_url: str) -> pd.DataFrame:
    print(f"  -> GET {api_url}")
    r = requests.get(api_url, headers=HEADERS_API, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", [])
    print(f"    {len(data)} registros recibidos")
    registros = []
    for item in data:
        url_rel = item.get("url") or ""
        registros.append({
            "rank":                   str(item.get("rank") or ""),
            "name":                   item.get("name"),
            "country":                item.get("location"),
            "url":                    f"{BASE_URL}{url_rel}" if url_rel else None,
            "overall_score":          item.get("scores_overall"),
            "teaching_score":         item.get("scores_teaching"),
            "research_env_score":     item.get("scores_research"),
            "research_quality_score": item.get("scores_citations"),
            "industry_score":         item.get("scores_industry_income"),
            "international_score":    item.get("scores_international_outlook"),
        })
    return pd.DataFrame(registros)

# ---------------------------------------------------------------------------
# Enriquecimiento de direcciones (JSON-LD en cada perfil)
# ---------------------------------------------------------------------------

def _buscar_en_json(obj, clave):
    if isinstance(obj, dict):
        if clave in obj:
            return obj[clave]
        for v in obj.values():
            r = _buscar_en_json(v, clave)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _buscar_en_json(v, clave)
            if r is not None:
                return r
    return None


def obtener_direccion(url_perfil: str, timeout: int = 15) -> dict:
    vacio = {
        "street_address": None, "locality": None, "region": None,
        "postal_code": None, "country_address": None,
    }
    if not url_perfil:
        return vacio
    try:
        r = requests.get(url_perfil, headers=HEADERS_API, timeout=timeout)
        r.raise_for_status()
        pagina = soup(r.text, "html.parser")
        jsonld = None
        for tag in pagina.find_all("script", {"type": "application/ld+json"}):
            try:
                jsonld = json.loads(tag.string or "{}")
                if _buscar_en_json(jsonld, "address") is not None:
                    break
            except Exception:
                jsonld = None
        direccion = _buscar_en_json(jsonld or {}, "address") or {}
        if not isinstance(direccion, dict):
            direccion = {}
        return {
            "street_address":  direccion.get("streetAddress"),
            "locality":        direccion.get("addressLocality"),
            "region":          direccion.get("addressRegion"),
            "postal_code":     direccion.get("postalCode"),
            "country_address": direccion.get("addressCountry"),
        }
    except Exception as e:
        print(f"    ! {url_perfil} -> {e}")
        return vacio


def enriquecer_direcciones(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "url" not in df.columns:
        return df
    print(f"    Enriqueciendo {len(df)} perfiles de universidad...")
    direcciones = []
    for i, url in enumerate(df["url"].tolist(), 1):
        direcciones.append(obtener_direccion(url))
        if i % 25 == 0:
            print(f"      {i}/{len(df)} listos")
    df_addr = pd.DataFrame(direcciones)
    return pd.concat([df.reset_index(drop=True), df_addr.reset_index(drop=True)], axis=1)

# ---------------------------------------------------------------------------
# Limpieza y normalización
# ---------------------------------------------------------------------------

def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["rank_raw"] = df["rank"]
    df["rank"] = (
        df["rank"].astype(str)
        .str.replace(r"[=+]", "", regex=True)
        .str.replace(r"[–—-]\d+", "", regex=True)
        .str.strip()
    )
    if "overall_score" in df.columns:
        df["overall_score"] = (
            df["overall_score"].astype(str)
            .str.replace(r".*[–—-]", "", regex=True)
        )
    df = df.replace({"n/a": None, "N/A": None, "": None, "None": None})
    presentes = [c for c in COLUMNAS_FINALES if c in df.columns]
    return df[presentes]

# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def main(obtener_direcciones: bool = True):
    resultados = {}

    # 1. Extracción
    for clave, cfg in RANKINGS.items():
        print(f"\n=== {cfg['nombre']} ===")
        resultados[clave] = obtener_ranking_api(cfg["api_url"])

    # 2. Enriquecimiento (opcional)
    if obtener_direcciones:
        for clave, df in resultados.items():
            print(f"\n=== Direcciones: {RANKINGS[clave]['nombre']} ===")
            resultados[clave] = enriquecer_direcciones(df)

    # 3. Limpieza
    resultados = {k: limpiar(v) for k, v in resultados.items()}

    # 4. Guardar
    print()
    for clave, cfg in RANKINGS.items():
        df = resultados.get(clave)
        if df is None or df.empty:
            print(f"! {clave} sin datos, se omite")
            continue
        df.to_csv(cfg["archivo_salida"], index=False, encoding="utf-8-sig")
        print(f"[OK] {cfg['archivo_salida']}  ({len(df)} filas, {len(df.columns)} columnas)")

    return resultados


if __name__ == "__main__":
    main(obtener_direcciones=True)
