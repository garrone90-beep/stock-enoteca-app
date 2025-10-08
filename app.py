
# (same content as canvas update above)
import os
import io
import json
import requests
import pandas as pd
import numpy as np
import streamlit as st

DEFAULT_URL = os.getenv("STOCK_CSV_URL", "")
COL_MAP_ENV = os.getenv("COL_MAP", "")

st.set_page_config(page_title="Stock Enoteca", page_icon="🍷", layout="wide")

st.markdown(
    """
    <style>
      .badge {display:inline-block;padding:4px 8px;border-radius:10px;font-size:12px;font-weight:600}
      .ok {background:#e8f7ed;border:1px solid #bfe7cd;color:#1a7f37}
      .warn {background:#fff7e6;border:1px solid #ffe1a3;color:#8a5b00}
      .no {background:#ffecec;border:1px solid #ffb3b3;color:#b00020}
      .pill {background:#edf2ff;color:#1f3a93;border:1px solid #c7d2fe}
      .sticky {position:sticky; top:0; z-index:999; backdrop-filter: blur(6px); background:rgba(255,255,255,0.8); padding:8px 0 2px 0; margin-bottom:8px; border-bottom: 1px solid #eee}
      .card {border:1px solid #eee;border-radius:14px;padding:12px;margin-bottom:10px}
      .muted{color:#6b7280}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🍷 Stock Enoteca")
st.caption("Ricerca rapida disponibilità – CSV da Dropbox")

with st.sidebar:
    st.header("Sorgente dati")
    csv_url = st.text_input(
        "URL CSV Dropbox (termina con ?dl=1 / raw=1)", value=DEFAULT_URL,
        placeholder="https://www.dropbox.com/s/.../stock_latest.csv?dl=1",
    )
    st.caption("Consigliato: sovrascrivere ogni giorno lo stesso file CSV.")
    col_map_text = st.text_area(
        "Mappatura colonne (JSON o tabella TOML)", value=COL_MAP_ENV, height=140,
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
        return df\n    except Exception as e:\n        st.error(f\"Errore nel caricamento CSV: {e}\")\n        return pd.DataFrame()\n\ndef normalize_columns(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:\n    if df.empty:\n        return df\n    df = df.copy()\n    cols_originali = list(df.columns)\n    lower_map = {c.lower(): c for c in cols_originali}\n    for src, dst in (col_map or {}).items():\n        if src in df.columns:\n            df.rename(columns={src: dst}, inplace=True)\n        elif src.lower() in lower_map:\n            df.rename(columns={lower_map[src.lower()]: dst}, inplace=True)\n    def maybe_rename(candidates, dst):\n        for c in candidates:\n            if c in df.columns:\n                df.rename(columns={c: dst}, inplace=True); return\n            if c.lower() in lower_map and lower_map[c.lower()] in df.columns:\n                df.rename(columns={lower_map[c.lower()]: dst}, inplace=True); return\n    maybe_rename(["ID", "Codice", "SKU", "Barcode"], "codice_prodotto")\n    maybe_rename(["DENOMINAZIONE", "Descrizione", "Nome", "Prodotto", "Titolo"], "descrizione")\n    maybe_rename(["PRODUTTORE", "Cantina", "Azienda"], "produttore")\n    maybe_rename(["FORNITORE", "Distributore", "Dealer"], "fornitore")\n    maybe_rename(["ANNATA", "Vintage", "Anno"], "annata")\n    maybe_rename(["QTA", "Quantita", "Quantità", "Qty", "Giacenza", "Stock"], "stock_attuale")\n    maybe_rename(["PREZZO DETT", "Prezzo", "Listino", "PV"], "prezzo_vendita")\n    maybe_rename(["PREZZO ING", "Prezzo Ingrosso"], "prezzo_ingrosso")\n    for c in [\"codice_prodotto\", \"descrizione\", \"produttore\", \"fornitore\", \"annata\"]:\n        if c in df.columns:\n            df[c] = df[c].astype(str).fillna(\"\").str.strip()\n    if \"stock_attuale\" in df.columns:\n        df[\"stock_attuale\"] = pd.to_numeric(df[\"stock_attuale\"], errors=\"coerce\").fillna(0).astype(int)\n    else:\n        df[\"stock_attuale\"] = 0\n    for price_col in [\"prezzo_vendita\", \"prezzo_ingrosso\"]:\n        if price_col in df.columns:\n            df[price_col] = (\n                df[price_col]\n                .astype(str)\n                .str.replace(\".\", \"\", regex=False)\n                .str.replace(\",\", \".\", regex=False)\n            )\n            df[price_col] = pd.to_numeric(df[price_col], errors=\"coerce\")\n    df[\"disponibile\"] = df[\"stock_attuale\"] > 0\n    df.sort_values(by=[\"disponibile\", \"descrizione\"], ascending=[False, True], inplace=True)\n    cols_out = [c for c in [\n        \"descrizione\", \"codice_prodotto\", \"annata\", \"produttore\", \"fornitore\",\n        \"stock_attuale\", \"prezzo_vendita\", \"prezzo_ingrosso\", \"disponibile\"\n    ] if c in df.columns]\n    return df[cols_out]\n\ndef apply_filters(df: pd.DataFrame, q: str, only_avail: bool, low_stock: bool, forn: list, prod: list, ann: list) -> pd.DataFrame:\n    if df.empty:\n        return df\n    res = df\n    if q:\n        ql = q.lower().strip()\n        mask = (\n            res.get(\"descrizione\", \"\").str.lower().str.contains(ql, na=False)\n            | res.get(\"codice_prodotto\", \"\").str.lower().str.contains(ql, na=False)\n            | res.get(\"fornitore\", \"\").str.lower().str.contains(ql, na=False)\n            | res.get(\"produttore\", \"\").str.lower().str.contains(ql, na=False)\n        )\n        res = res[mask]\n    if only_avail and \"disponibile\" in res.columns:\n        res = res[res[\"disponibile\"]]\n    if low_stock and \"stock_attuale\" in res.columns:\n        res = res[res[\"stock_attuale\"] <= 2]\n    if forn and \"fornitore\" in res.columns:\n        res = res[res[\"fornitore\"].isin(forn)]\n    if prod and \"produttore\" in res.columns:\n        res = res[res[\"produttore\"].isin(prod)]\n    if ann and \"annata\" in res.columns:\n        res = res[res[\"annata\"].isin(ann)]\n    return res\n\ncol_map = {}\nif col_map_text.strip():\n    try:\n        if isinstance(st.secrets.get(\"COL_MAP\", \"\"), dict):\n            col_map = st.secrets[\"COL_MAP\"]\n        else:\n            col_map = json.loads(col_map_text)\n    except Exception:\n        st.warning(\"JSON mappatura colonne non valido: ignorato.\")\n        col_map = {}\n\nif refresh:\n    load_csv.clear()\n\ndf_raw = load_csv(csv_url)\ndf = normalize_columns(df_raw, col_map)\n\nif df.empty:\n    st.info(\"Carica un URL CSV valido per iniziare.\")\n    st.stop()\n\nst.markdown('<div class=\"sticky\">', unsafe_allow_html=True)\ncol_a, col_b, col_c, col_d = st.columns([4, 2, 2, 2])\nwith col_a:\n    q = st.text_input(\"🔎 Cerca (nome, codice, fornitore, produttore)\", placeholder=\"Es. Barolo 2019 o Cavalleri\")\nwith col_b:\n    only_avail = st.toggle(\"Solo disponibili\", value=False)\nwith col_c:\n    low_stock = st.toggle(\"Sottoscorta (≤2)\", value=False)\nwith col_d:\n    view_mode = st.radio(\"Vista\", [\"Cards\", \"Tabella\"], horizontal=True, label_visibility=\"visible\")\nst.markdown('</div>', unsafe_allow_html=True)\n\ncols = st.columns(3)\nwith cols[0]:\n    forn_opts = sorted([f for f in df.get(\"fornitore\", pd.Series(dtype=str)).dropna().unique() if str(f).strip()])\n    forn_sel = st.multiselect(\"Fornitore\", forn_opts)\nwith cols[1]:\n    prod_opts = sorted([p for p in df.get(\"produttore\", pd.Series(dtype=str)).dropna().unique() if str(p).strip()])\n    prod_sel = st.multiselect(\"Produttore\", prod_opts)\nwith cols[2]:\n    ann_opts = [a for a in df.get(\"annata\", pd.Series(dtype=str)).dropna().unique() if str(a).strip()]\n    try:\n        ann_opts = sorted(ann_opts, key=lambda x: int(str(x)))\n    except Exception:\n        ann_opts = sorted(ann_opts)\n    ann_sel = st.multiselect(\"Annata\", ann_opts)\n\nfiltered = apply_filters(df, q, only_avail, low_stock, forn_sel, prod_sel, ann_sel)\n\ncolk = st.columns(3)\ncolk[0].metric(\"Articoli trovati\", f\"{len(filtered):,}\".replace(\",\", \".\"))\ncolk[1].metric(\"Disponibili\", f\"{filtered['disponibile'].sum():,}\".replace(\",\", \".\"))\nif \"stock_attuale\" in filtered.columns:\n    colk[2].metric(\"Pezzi totali (filtro)\", f\"{int(filtered['stock_attuale'].sum()):,}\".replace(\",\", \".\"))\n\nif view_mode == \"Cards\":\n    for _, r in filtered.iterrows():\n        disp = \"✅ Disponibile\" if r.get(\"disponibile\", False) else \"❌ Esaurito\"\n        badge_class = \"ok\" if r.get(\"disponibile\", False) else \"no\"\n        if \"stock_attuale\" in r and r[\"stock_attuale\"] <= 2 and r.get(\"disponibile\", False):\n            disp = \"⚠️ Sottoscorta\"\n            badge_class = \"warn\"\n        prezzo = r.get(\"prezzo_vendita\", None)\n        prezzo_txt = f\" – {prezzo:.2f}€\" if pd.notna(prezzo) else \"\"\n        st.markdown(\n            f\"\"\"\n            <div class='card'>\n              <div style='display:flex;justify-content:space-between;align-items:center;'>\n                <div>\n                  <strong>{r.get('descrizione','')}</strong><span class='muted'>{prezzo_txt}</span><br>\n                  <span class='muted'>Cod: {r.get('codice_prodotto','')} · Annata: {r.get('annata','')}</span><br>\n                  <span class='muted'>Produttore: {r.get('produttore','')} · Fornitore: {r.get('fornitore','')}</span>\n                </div>\n                <div><span class='badge {badge_class}'>{disp}</span></div>\n              </div>\n              <div class='muted' style='margin-top:6px;'>Qta: <strong>{int(r.get('stock_attuale',0))}</strong></div>\n            </div>\n            \"\"\",\n            unsafe_allow_html=True,\n        )\nelse:\n    show_df = filtered.copy()\n    if \"disponibile\" in show_df.columns:\n        show_df[\"disponibile\"] = show_df[\"disponibile\"].map({True: \"✅ sì\", False: \"❌ no\"})\n\n    def highlight_qta(val):\n        try:\n            v = int(val)\n        except Exception:\n            return \"\"\n        if v == 0:\n            return \"background-color:#ffe6e6;\"\n        elif v <= 2:\n            return \"background-color:#fff5cc;\"\n        return \"\"\n\n    if \"stock_attuale\" in show_df.columns:\n        styler = show_df.style.applymap(highlight_qta, subset=[\"stock_attuale\"])  # type: ignore\n    else:\n        styler = show_df.style  # type: ignore\n\n    st.dataframe(styler, use_container_width=True, hide_index=True)\n\ncsv_bytes = filtered.to_csv(index=False).encode(\"utf-8\")\nst.download_button(\"⬇️ Scarica risultato (CSV)\", data=csv_bytes, file_name=\"stock_filtrato.csv\", mime=\"text/csv\")\n\nif auto_refresh:\n    st.caption(\"Auto‑refresh attivo (5 min)\")\n