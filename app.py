
import os
import io
import json
import requests
import pandas as pd
import numpy as np
import streamlit as st

@st.cache_data(ttl=60 * 30)  # 30 minuti di cache (l'access token dura ore)
def get_dropbox_access_token() -> str:
    url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": st.secrets["DROPBOX_REFRESH_TOKEN"],
        "client_id": st.secrets["DROPBOX_APP_KEY"],
        "client_secret": st.secrets["DROPBOX_APP_SECRET"],
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def download_from_dropbox(path: str) -> bytes:
    url = "https://content.dropboxapi.com/2/files/download"
    access_token = get_dropbox_access_token()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": json.dumps({"path": path.strip()}),
    }
    r = requests.post(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.content


# =========================
# CONFIG
# =========================
DEFAULT_URL = os.getenv("STOCK_CSV_URL", "")
COL_MAP_ENV = os.getenv("COL_MAP", "")

st.set_page_config(page_title="Stock Enoteca", page_icon="🍷", layout="wide")

# ---- CSS (badges, sticky, cards, grid per valori incolonnati) ----
st.markdown(
    """
    <style>
      .badge {display:inline-block;padding:4px 8px;border-radius:10px;font-size:12px;font-weight:600}
      .ok {background:#e8f7ed;border:1px solid #bfe7cd;color:#1a7f37}
      .warn {background:#fff7e6;border:1px solid #ffe1a3;color:#8a5b00}
      .no {background:#ffecec;border:1px solid #ffb3b3;color:#b00020}
      .sticky {position:sticky; top:0; z-index:999; backdrop-filter: blur(6px); background:rgba(255,255,255,0.8); padding:8px 0 2px 0; margin-bottom:8px; border-bottom: 1px solid #eee}
      .card {border:1px solid #eee;border-radius:14px;padding:12px;margin-bottom:10px}
      .muted{color:#6b7280}
      .kv {display:grid; grid-template-columns: 140px 1fr; column-gap: 8px; row-gap: 6px; margin-top:6px}
      .k {color:#6b7280}
      .v {font-weight:600}
      .card-head {display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
      .price {font-variant-numeric: tabular-nums;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🍷 Stock Enoteca")
st.caption("Ricerca rapida disponibilità – CSV da Dropbox")

# =========================
# SIDEBAR (data source)
# =========================
with st.sidebar:
    st.header("Sorgente dati")
    csv_url = st.text_input(
        "URL CSV Dropbox (termina con ?dl=1 / raw=1)",
        value=DEFAULT_URL,
        placeholder="https://www.dropbox.com/s/.../stock_latest.csv?dl=1",
    )
    st.caption("Consigliato: sovrascrivere ogni giorno lo stesso file CSV.")

    col_map_text = st.text_area(
        "Mappatura colonne (JSON o tabella TOML)", value=COL_MAP_ENV, height=140,
        placeholder='{"ID":"codice_prodotto","DENOMINAZIONE":"descrizione","PRODUTTORE":"produttore","FORNITORE":"fornitore","ANNATA":"annata","PREZZO DETT":"prezzo_vendita","PREZZO ING":"prezzo_ingrosso","QTA":"stock_attuale"}'
    )
    auto_refresh = st.checkbox("Auto-refresh ogni 5 min", value=True)
    refresh = st.button("🔄 Aggiorna ora")

# =========================
# FUNZIONI
# =========================
@st.cache_data(ttl=300)
def load_csv(_ignored_url: str) -> pd.DataFrame:
    dropbox_path = st.secrets.get("DROPBOX_STOCK_PATH", "")
    if not dropbox_path:
        st.error("Config mancante: aggiungi DROPBOX_STOCK_PATH nei secrets di Streamlit.")
        return pd.DataFrame()

    content = download_from_dropbox(dropbox_path)

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin1")

    try:
        df = pd.read_csv(io.StringIO(text), sep=";", decimal=",")
    except Exception:
        df = pd.read_csv(io.StringIO(text))
    return df


def _to_price_eu(series: pd.Series) -> pd.Series:
    import pandas.api.types as ptypes
    s = series
    if ptypes.is_numeric_dtype(s):
        return s
    s = s.astype(str).str.strip()
    s = (s
         .str.replace('€', '', regex=False)
         .str.replace('EUR', '', regex=False)
         .str.replace(' ', '', regex=False)
    )
    s = s.str.replace(r'\.(?=\d{3}(\D|$))', '', regex=True)
    s = s.str.replace(',', '.', regex=False)
    return pd.to_numeric(s, errors='coerce')

def _fmt_eur(v) -> str:
    if pd.isna(v):
        return ""
    try:
        return f"{float(v):.2f}".replace('.', ',') + "€"
    except Exception:
        return ""

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
                df.rename(columns={c: dst}, inplace=True)
                return
            if c.lower() in lower_map and lower_map[c.lower()] in df.columns:
                df.rename(columns={lower_map[c.lower()]: dst}, inplace=True)
                return

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

    # Prezzi robusti EU
    for price_col in ["prezzo_vendita", "prezzo_ingrosso"]:
        if price_col in df.columns:
            df[price_col] = _to_price_eu(df[price_col])

    df["disponibile"] = df["stock_attuale"] > 0
    df.sort_values(by=["disponibile", "descrizione"], ascending=[False, True], inplace=True)

    cols_out = [c for c in [
        "descrizione", "codice_prodotto", "annata", "produttore", "fornitore",
        "stock_attuale", "prezzo_vendita", "prezzo_ingrosso", "disponibile"
    ] if c in df.columns]
    return df[cols_out]

def apply_filters(df: pd.DataFrame, q: str, only_avail: bool, low_stock: bool,
                  forn: list, prod: list, ann: list) -> pd.DataFrame:
    if df.empty:
        return df
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
    if only_avail and "disponibile" in res.columns:
        res = res[res["disponibile"]]
    if low_stock and "stock_attuale" in res.columns:
        res = res[res["stock_attuale"] <= 2]
    if forn and "fornitore" in res.columns:
        res = res[res["fornitore"].isin(forn)]
    if prod and "produttore" in res.columns:
        res = res[res["produttore"].isin(prod)]
    if ann and "annata" in res.columns:
        res = res[res["annata"].isin(ann)]
    return res

# =========================
# LOAD DATA
# =========================
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

# =========================
# STICKY BAR: Ricerca + Quick filters
# =========================
st.markdown('<div class="sticky">', unsafe_allow_html=True)
col_a, col_b, col_c, col_d = st.columns([4, 2, 2, 2])
with col_a:
    q = st.text_input("🔎 Cerca (nome, codice, fornitore, produttore)", placeholder="Es. Barolo 2019 o Cavalleri")
with col_b:
    only_avail = st.toggle("Solo disponibili", value=False)
with col_c:
    low_stock = st.toggle("Sottoscorta (≤2)", value=False)
with col_d:
    view_mode = st.radio("Vista", ["Cards", "Tabella"], horizontal=True, label_visibility="visible")
st.markdown('</div>', unsafe_allow_html=True)

# Filtri secondari
cols = st.columns(3)
with cols[0]:
    forn_opts = sorted([f for f in df.get("fornitore", pd.Series(dtype=str)).dropna().unique() if str(f).strip()])
    forn_sel = st.multiselect("Fornitore", forn_opts)
with cols[1]:
    prod_opts = sorted([p for p in df.get("produttore", pd.Series(dtype=str)).dropna().unique() if str(p).strip()])
    prod_sel = st.multiselect("Produttore", prod_opts)
with cols[2]:
    ann_opts = [a for a in df.get("annata", pd.Series(dtype=str)).dropna().unique() if str(a).strip()]
    try:
        ann_opts = sorted(ann_opts, key=lambda x: int(str(x)))
    except Exception:
        ann_opts = sorted(ann_opts)
    ann_sel = st.multiselect("Annata", ann_opts)

filtered = apply_filters(df, q, only_avail, low_stock, forn_sel, prod_sel, ann_sel)

# =========================
# KPI
# =========================
colk = st.columns(3)
colk[0].metric("Articoli trovati", f"{len(filtered):,}".replace(",", "."))
colk[1].metric("Disponibili", f"{filtered['disponibile'].sum():,}".replace(",", "."))
if "stock_attuale" in filtered.columns:
    colk[2].metric("Pezzi totali (filtro)", f"{int(filtered['stock_attuale'].sum()):,}".replace(",", "."))

# =========================
# RENDER: Cards o Tabella
# =========================
if view_mode == "Cards":
    for _, r in filtered.iterrows():
        disp = "✅ Disponibile" if r.get("disponibile", False) else "❌ Esaurito"
        badge_class = "ok" if r.get("disponibile", False) else "no"
        if "stock_attuale" in r and r["stock_attuale"] <= 2 and r.get("disponibile", False):
            disp = "⚠️ Sottoscorta"
            badge_class = "warn"

        prezzo_v = r.get("prezzo_vendita", None)
        prezzo_i = r.get("prezzo_ingrosso", None)
        prezzo_v_txt = _fmt_eur(prezzo_v)
        prezzo_i_txt = _fmt_eur(prezzo_i)

        st.markdown(
            f"""
            <div class='card'>
              <div class='card-head'>
                <div>
                  <strong>{r.get('descrizione','')}</strong>
                </div>
                <div><span class='badge {badge_class}'>{disp}</span></div>
              </div>

              <div class='kv'>
                <div class='k'>Prezzo dettaglio</div><div class='v price'>{prezzo_v_txt}</div>
                <div class='k'>Prezzo ingrosso</div><div class='v price'>{prezzo_i_txt}</div>
                <div class='k'>Codice</div><div class='v'>{r.get('codice_prodotto','')}</div>
                <div class='k'>Annata</div><div class='v'>{r.get('annata','')}</div>
                <div class='k'>Produttore</div><div class='v'>{r.get('produttore','')}</div>
                <div class='k'>Fornitore</div><div class='v'>{r.get('fornitore','')}</div>
                <div class='k'>Quantità</div><div class='v'>{int(r.get('stock_attuale',0))}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    show_df = filtered.copy()
    if "disponibile" in show_df.columns:
        show_df["disponibile"] = show_df["disponibile"].map({True: "✅ sì", False: "❌ no"})

    def highlight_qta(val):
        try:
            v = int(val)
        except Exception:
            return ""
        if v == 0:
            return "background-color:#ffe6e6;"
        elif v <= 2:
            return "background-color:#fff5cc;"
        return ""

    if "stock_attuale" in show_df.columns:
        styler = show_df.style.applymap(highlight_qta, subset=["stock_attuale"])  # type: ignore
    else:
        styler = show_df.style  # type: ignore

    st.dataframe(styler, use_container_width=True, hide_index=True)

# =========================
# DOWNLOAD filtrato
# =========================
csv_bytes = filtered.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Scarica risultato (CSV)", data=csv_bytes, file_name="stock_filtrato.csv", mime="text/csv")

# =========================
# AUTO REFRESH
# =========================
if auto_refresh:
    st.caption("Auto-refresh attivo (5 min)")
