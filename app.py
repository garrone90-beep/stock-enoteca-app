
import os
import io
import json
import requests
import pandas as pd
import numpy as np
import streamlit as st

DEFAULT_URL = os.getenv("STOCK_CSV_URL", "")
COL_MAP_ENV = os.getenv("COL_MAP", "")

st.set_page_config(page_title="Stock Enoteca", page_icon="🍷", layout="centered")
st.title("🍷 Stock Enoteca")
st.caption("Ricerca rapida disponibilità – legge un CSV da Dropbox")

with st.sidebar:
    st.header("Sorgente dati")
    csv_url = st.text_input(
        "URL CSV Dropbox (termina con ?dl=1)", value=DEFAULT_URL,
        placeholder="https://www.dropbox.com/s/…/stock_latest.csv?dl=1"
    )
    st.caption("Consigliato: sovrascrivere ogni giorno lo stesso file CSV.")
    col_map_text = st.text_area(
        "Mappatura colonne (JSON, opzionale)", value=COL_MAP_ENV, height=140,
        placeholder='{"ID":"codice_prodotto","DENOMINAZIONE":"descrizione","PRODUTTORE":"produttore","FORNITORE":"fornitore","ANNATA":"annata","PREZZO DETT":"prezzo_vendita","PREZZO ING":"prezzo_ingrosso","QTA":"stock_attuale"}'
    )
    auto_refresh = st.checkbox("Auto‑refresh ogni 5 min", value=True)
    refresh = st.button("🔄 Aggiorna ora")

@st.cache_data(ttl=300)
def load_csv(url: str) -> pd.DataFrame:
    if not url:
        return pd.DataFrame()
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        content = r.content
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin1")
        try:
            df = pd.read_csv(io.StringIO(text), sep=";", decimal=",")
        except Exception:
            df = pd.read_csv(io.StringIO(text))
        return df
    except Exception as e:
        st.error(f"Errore nel caricamento CSV: {e}")
        return pd.DataFrame()

def normalize_columns(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    cols_originali = list(df.columns)
    lower_map = {c.lower(): c for c in cols_originali}
    for src, dst in (col_map or {}).items():
        if src in df.columns:
            df.rename(columns={src: dst}, inplace=True)
        elif src.lower() in lower_map:
            df.rename(columns={lower_map[src.lower()]: dst}, inplace=True)
    def maybe_rename(candidates, dst):
        for c in candidates:
            if c in df.columns:
                df.rename(columns={c: dst}, inplace=True); return
            if c.lower() in lower_map and lower_map[c.lower()] in df.columns:
                df.rename(columns={lower_map[c.lower()]: dst}, inplace=True); return
    maybe_rename(["ID", "Codice", "SKU", "Barcode"], "codice_prodotto")
    maybe_rename(["DENOMINAZIONE", "Descrizione", "Nome", "Prodotto", "Titolo"], "descrizione")
    maybe_rename(["PRODUTTORE", "Cantina", "Azienda"], "produttore")
    maybe_rename(["FORNITORE", "Distributore", "Dealer"], "fornitore")
    maybe_rename(["ANNATA", "Vintage", "Anno"], "annata")
    maybe_rename(["QTA", "Quantita", "Quantità", "Qty", "Giacenza", "Stock"], "stock_attuale")
    maybe_rename(["PREZZO DETT", "Prezzo", "Listino", "PV"], "prezzo_vendita")
    maybe_rename(["PREZZO ING", "Prezzo Ingrosso"], "prezzo_ingrosso")
    for c in ["codice_prodotto", "descrizione", "produttore", "fornitore", "annata"]:
        if c in df.columns:
            df[c] = df[c].astype(str).fillna("").str.strip()
    if "stock_attuale" in df.columns:
        df["stock_attuale"] = pd.to_numeric(df["stock_attuale"], errors="coerce").fillna(0).astype(int)
    else:
        df["stock_attuale"] = 0
    for price_col in ["prezzo_vendita", "prezzo_ingrosso"]:
        if price_col in df.columns:
            df[price_col] = (
                df[price_col].astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
            )
            df[price_col] = pd.to_numeric(df[price_col], errors="coerce")
    df["disponibile"] = df["stock_attuale"] > 0
    df.sort_values(by=["disponibile", "descrizione"], ascending=[False, True], inplace=True)
    cols_out = [c for c in [
        "descrizione", "codice_prodotto", "annata", "produttore", "fornitore",
        "stock_attuale", "prezzo_vendita", "prezzo_ingrosso", "disponibile"
    ] if c in df.columns]
    return df[cols_out]

def apply_filters(df: pd.DataFrame, q: str, cat: list, forn: list, prod: list, ann: list) -> pd.DataFrame:
    if df.empty: return df
    res = df
    if q:
        ql = q.lower().strip()
        mask = (
            res.get("descrizione", "").str.lower().str.contains(ql, na=False)
            | res.get("codice_prodotto", "").str.lower().str.contains(ql, na=False)
            | res.get("fornitore", "").str.lower().str.contains(ql, na=False)
            | res.get("produttore", "").str.lower().str.contains(ql, na=False)
        )
        res = res[mask]
    if cat and "categoria" in res.columns:
        res = res[res["categoria"].isin(cat)]
    if forn and "fornitore" in res.columns:
        res = res[res["fornitore"].isin(forn)]
    if prod and "produttore" in res.columns:
        res = res[res["produttore"].isin(prod)]
    if ann and "annata" in res.columns:
        res = res[res["annata"].isin(ann)]
    return res

col_map = {}
if col_map_text.strip():
    try:
        if isinstance(st.secrets.get("COL_MAP", ""), dict):
            col_map = st.secrets["COL_MAP"]
        else:
            col_map = json.loads(col_map_text)
    except Exception:
        st.warning("JSON mappatura colonne non valido: ignorato.")
        col_map = {}

if refresh:
    load_csv.clear()

df_raw = load_csv(csv_url)
df = normalize_columns(df_raw, col_map)

if df.empty:
    st.info("Carica un URL CSV valido per iniziare.")
    st.stop()

st.subheader("Ricerca")
q = st.text_input("Cerca per nome, codice, fornitore o produttore", placeholder="Es. Barolo 2019 o Cavalleri")

cols = st.columns(4)
with cols[0]:
    cat_opts = sorted([c for c in df.get("categoria", pd.Series(dtype=str)).dropna().unique() if str(c).strip()])
    cat_sel = st.multiselect("Categoria", cat_opts)
with cols[1]:
    forn_opts = sorted([f for f in df.get("fornitore", pd.Series(dtype=str)).dropna().unique() if str(f).strip()])
    forn_sel = st.multiselect("Fornitore", forn_opts)
with cols[2]:
    prod_opts = sorted([p for p in df.get("produttore", pd.Series(dtype=str)).dropna().unique() if str(p).strip()])
    prod_sel = st.multiselect("Produttore", prod_opts)
with cols[3]:
    ann_opts = [a for a in df.get("annata", pd.Series(dtype=str)).dropna().unique() if str(a).strip()]
    try:
        ann_opts = sorted(ann_opts, key=lambda x: int(str(x)))
    except Exception:
        ann_opts = sorted(ann_opts)
    ann_sel = st.multiselect("Annata", ann_opts)

filtered = apply_filters(df, q, cat_sel, forn_sel, prod_sel, ann_sel)

colk = st.columns(3)
colk[0].metric("Articoli trovati", f"{len(filtered):,}".replace(",", "."))
colk[1].metric("Disponibili", f"{filtered['disponibile'].sum():,}".replace(",", "."))
if "stock_attuale" in filtered.columns:
    colk[2].metric("Pezzi totali (filtro)", f"{int(filtered['stock_attuale'].sum()):,}".replace(",", "."))

show_df = filtered.copy()
if "disponibile" in show_df.columns:
    show_df["disponibile"] = show_df["disponibile"].map({True: "✅ sì", False: "❌ no"})

def highlight_qta(val):
    try: v = int(val)
    except Exception: return ""
    if v == 0: return "background-color:#ffe6e6;"
    elif v <= 2: return "background-color:#fff5cc;"
    return ""

if "stock_attuale" in show_df.columns:
    styler = show_df.style.applymap(highlight_qta, subset=["stock_attuale"])  # type: ignore
else:
    styler = show_df.style  # type: ignore

st.dataframe(styler, use_container_width=True, hide_index=True)

csv_bytes = filtered.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Scarica risultato (CSV)", data=csv_bytes, file_name="stock_filtrato.csv", mime="text/csv")

if auto_refresh:
    st.caption("Auto‑refresh attivo (5 min)")
