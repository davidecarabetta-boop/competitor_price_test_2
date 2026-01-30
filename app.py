import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import gspread
import json
import re
from datetime import date

# --- 1. CONFIGURAZIONE ---
st.set_page_config(page_title="Sensation AI Pricing Tower", layout="wide", page_icon="📈")

if "gcp_service_account" not in st.secrets or "gemini_api_key" not in st.secrets:
    st.error("⛔ Configurazione mancante in secrets.toml")
    st.stop()

genai.configure(api_key=st.secrets["gemini_api_key"])
MODEL_NAME = 'gemini-1.5-flash'

# --- 2. FUNZIONI UTILITÀ ---
def clean_currency(value):
    if pd.isna(value) or str(value).strip() == '': return 0.0
    if isinstance(value, (int, float)): return float(value)
    s = str(value).replace('€', '').replace('$', '').strip()
    try:
        if ',' in s and '.' in s:
            if s.find('.') < s.find(','): s = s.replace('.', '').replace(',', '.')
            else: s = s.replace(',', '')
        elif ',' in s: s = s.replace(',', '.')
        return float(s)
    except: return 0.0

def clean_json_response(text):
    text = text.strip()
    if "```" in text:
        pattern = r"```(?:json)?(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match: text = match.group(1).strip()
    return text

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=600)
def load_data():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        client = gspread.service_account_from_dict(creds_dict)
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # Carica Prezzi
        df_p = pd.DataFrame(sh.sheet1.get_all_records())
        if df_p.empty: return pd.DataFrame()

        # Carica Entrate
        try: df_r = pd.DataFrame(sh.worksheet("Entrate").get_all_records())
        except: df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        # Mapping Colonne
        rename_map = {
            'Sensation_Prezzo': 'Price',
            'Sensation_Posizione': 'Rank',
            'Codice': 'Sku', 'id': 'Sku'
        }
        df_p.rename(columns=rename_map, inplace=True)

        # Standardizza
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip()
                if 'Sku' in df.columns: df['Sku'] = df['Sku'].astype(str).str.strip()

        # Check e Pulizia
        if 'Price' not in df_p.columns: df_p['Price'] = 0.0
        if 'Rank' not in df_p.columns: df_p['Rank'] = 99
        if 'Comp_1_Prezzo' not in df_p.columns: df_p['Comp_1_Prezzo'] = 0.0
        
        for col in ['Price', 'Comp_1_Prezzo']: df_p[col] = df_p[col].apply(clean_currency)
        df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns: df_r[col] = df_r[col].apply(clean_currency)

        # Merge
        df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        
        # --- GESTIONE DATA E ORARIO (FIX RICHIESTO) ---
        col_data = 'Data' if 'Data' in df_final.columns else ('Data_esecuzione' if 'Data_esecuzione' in df_final.columns else None)
        
        if col_data: 
            # 1. Converte in datetime
            df_final['Data_dt'] = pd.to_datetime(df_final[col_data], dayfirst=True, errors='coerce')
            # 2. Rimuove l'orario (normalizza a mezzanotte) per evitare problemi nei grafici
            df_final['Data_dt'] = df_final['Data_dt'].dt.normalize()
        else: 
            df_final['Data_dt'] = pd.Timestamp.now().normalize()
            
        # Gestione Categoria (se manca la colonna, ne creiamo una fittizia o usiamo una logica)
        if 'Categoria' not in df_final.columns:
            # Fallback: Se c'è una colonna 'Category' la usa, altrimenti mette 'N/D'
            df_final['Categoria'] = df_final.get('Category', 'Generale')

        return df_final.dropna(subset=['Data_dt'])
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

# --- 4. FUNZIONI AI ---
def ai_clustering_bulk(df_input):
    if df_input.empty: return pd.DataFrame()
    df_subset = df_input.sort_values(by='Entrate', ascending=False).head(20)
    cols = ['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate']
    for c in cols: 
        if c not in df_subset.columns: df_subset[c] = 0
    
    data_json = df_subset[cols].to_dict(orient='records')
    prompt = f"""
    Analizza: {json.dumps(data_json)}.
    Definisci Categoria Strategica: "Attacco", "Margine", "Monitorare", "Liquidare".
    Output JSON: [{{ "Sku": "...", "Categoria": "..." }}]
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        clean = clean_json_response(res.text)
        return pd.DataFrame(json.loads(clean))
    except: return pd.DataFrame()

def ai_predictive_strategy(hist_data, current_data):
    trend = "Stabile"
    if len(hist_data) > 1:
        start, end = hist_data.iloc[0]['Price'], hist_data.iloc[-1]['Price']
        if end < start: trend = "In discesa"
        elif end > start: trend = "In salita"

    prompt = f"""
    Prodotto: {current_data['Product']}
    Prezzo: {current_data['Price']}€ (Pos: {current_data['Rank']})
    Competitor: {current_data['Comp_1_Prezzo']}€
    Trend: {trend}
    Consiglia strategia breve (3 righe).
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        return res.text
    except Exception as e: return f"Errore AI: {e}"

# --- 5. INTERFACCIA E FILTRI ---

df_raw = load_data()
if df_raw.empty: st.stop()

# Sidebar: Immagine e Titolo
with st.sidebar:
    st.image("logosensation.png") if "logosensation.png" in st.secrets else st.title("Sensation AI")
    st.divider()
    st.header("🔍 Pannello Filtri")

    # --- 1. FILTRO DATA (Range) ---
    min_date = df_raw['Data_dt'].min().date()
    max_date = df_raw['Data_dt'].max().date()
    
    # Se c'è un solo giorno, non mostrare il range che confonde
    if min_date == max_date:
        st.info(f"📅 Dati del: {min_date}")
        start_date, end_date = min_date, max_date
    else:
        date_range = st.date_input("Seleziona Periodo", [min_date, max_date])
        if len(date_range) == 2:
            start_date, end_date = date_range
        else:
            start_date, end_date = min_date, max_date

    # Applicazione Filtro Data al Raw Data
    mask_date = (df_raw['Data_dt'].dt.date >= start_date) & (df_raw['Data_dt'].dt.date <= end_date)
    df_period = df_raw[mask_date].copy()

    # Creiamo lo snapshot (ultima rilevazione nel periodo selezionato) per le tabelle
    df_latest = df_period.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()

    # --- 2. ALTRI FILTRI (Brand, Categoria, Prezzo, Entrate, Vendite) ---
    
    # A. Brand
    all_brands = sorted(list(set([str(p).split()[0] for p in df_latest['Product'] if p])))
    sel_brands = st.multiselect("Brand", all_brands, default=[])
    
    # B. Categoria (Se presente)
    all_cats = sorted(df_latest['Categoria'].astype(str).unique())
    sel_cats = st.multiselect("Categoria", all_cats, default=[])

    # C. Fascia di Prezzo
    min_p, max_p = int(df_latest['Price'].min()), int(df_latest['Price'].max())
    # Gestione caso prezzo unico
    if min_p == max_p: 
        price_range = (min_p, max_p)
        st.caption(f"Prezzo fisso: {min_p}€")
    else:
        price_range = st.slider("Fascia di Prezzo (€)", min_p, max_p, (min_p, max_p))

    # D. Entrate Generate
    min_r, max_r = int(df_latest['Entrate'].min()), int(df_latest['Entrate'].max())
    if min_r == max_r: revenue_range = (min_r, max_r)
    else: revenue_range = st.slider("Entrate Generate (€)", min_r, max_r, (min_r, max_r))

    # E. Numero Vendite
    min_v, max_v = int(df_latest['Vendite'].min()), int(df_latest['Vendite'].max())
    if min_v == max_v: sales_range = (min_v, max_v)
    else: sales_range = st.slider("Numero Vendite", min_v, max_v, (min_v, max_v))

    st.divider()
    
    # AI Buttons
    if "ai_clusters" not in st.session_state: st.session_state.ai_clusters = pd.DataFrame()
    if st.button("✨ Clustering AI"):
        with st.spinner("Analisi..."): st.session_state.ai_clusters = ai_clustering_bulk(df_latest)
    
    if st.button("🔄 Reset Cache"):
        st.cache_data.clear()
        st.rerun()

# --- APPLICAZIONE FILTRI ---
df_filtered = df_latest.copy()

# Filtro Brand
if sel_brands:
    # Filtra se il prodotto inizia con uno dei brand selezionati
    pattern = '|'.join(sel_brands)
    df_filtered = df_filtered[df_filtered['Product'].str.contains(pattern, case=False, na=False)]

# Filtro Categoria
if sel_cats:
    df_filtered = df_filtered[df_filtered['Categoria'].isin(sel_cats)]

# Filtri Numerici
df_filtered = df_filtered[
    (df_filtered['Price'] >= price_range[0]) & (df_filtered['Price'] <= price_range[1]) &
    (df_filtered['Entrate'] >= revenue_range[0]) & (df_filtered['Entrate'] <= revenue_range[1]) &
    (df_filtered['Vendite'] >= sales_range[0]) & (df_filtered['Vendite'] <= sales_range[1])
]

# --- DASHBOARD ---
st.title("🚀 Control Tower Sensation")
st.markdown(f"**Prodotti visualizzati:** {len(df_filtered)} su {len(df_latest)}")

tab1, tab2 = st.tabs(["📊 Market Intelligence", "🔍 Focus & AI Prediction"])

with tab1:
    # KPI
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df_filtered['Rank'] == 1).mean() if not df_filtered.empty else 0
    c1.metric("Win Rate", f"{win_rate:.1%}")
    c2.metric("Pos. Media", f"{df_filtered['Rank'].mean():.1f}" if not df_filtered.empty else "0")
    c3.metric("Prezzo Medio", f"{df_filtered['Price'].mean():.2f} €" if not df_filtered.empty else "0 €")
    c4.metric("Entrate Totali (Filtrate)", f"€ {df_filtered['Entrate'].sum():,.0f}")

    st.divider()

    # Grafico Bar
    st.subheader("Confronto Prezzi (Top 15 Filtri)")
    df_chart = df_filtered.sort_values('Entrate', ascending=False).head(15).rename(columns={'Price': 'Sensation_Prezzo'})
    if not df_chart.empty:
        fig_bar = px.bar(
            df_chart, 
            x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
            barmode='group',
            color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'}
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.warning("Nessun dato corrisponde ai filtri selezionati.")

    # Tabella
    st.subheader("📋 Lista Prodotti")
    df_display = df_filtered.copy()
    if not st.session_state.ai_clusters.empty:
        df_display = df_display.merge(st.session_state.ai_clusters, on='Sku', how='left')
        df_display['Classificazione AI'] = df_display['Categoria'].fillna("-")
    else:
        df_display['Classificazione AI'] = "-"

    cols_show = ['Sku', 'Product', 'Rank', 'Price', 'Comp_1_Prezzo', 'Entrate', 'Vendite', 'Classificazione AI']
    df_show = df_display[cols_show].rename(columns={'Rank': 'Posizione', 'Price': 'Nostro Prezzo'})
    st.dataframe(df_show, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("🔍 Analisi Storica e Predittiva")
    
    # Qui usiamo i prodotti filtrati per popolare la selectbox
    prods = df_filtered['Product'].unique()
    
    if len(prods) > 0:
        selected_prod = st.selectbox("Seleziona Prodotto (tra quelli filtrati):", prods)
        
        # Recuperiamo i dati puntuali e lo storico COMPLETO (filtrato solo per data)
        p_data = df_filtered[df_filtered['Product'] == selected_prod].iloc[0]
        
        # Storico: prendiamo dal df_period (filtrato per data) ma SOLO per questo prodotto
        h_data = df_period[df_period['Product'] == selected_prod].sort_values('Data_dt')

        c_info, c_ai = st.columns([1, 1])
        with c_info:
            st.info(f"**{selected_prod}**\n\n💰 Prezzo: {p_data['Price']}€\n\n🏆 Posizione: {p_data['Rank']}°")
        
        with c_ai:
            if st.button("🚀 Analizza SKU"):
                with st.spinner("AI al lavoro..."):
                    an = ai_predictive_strategy(h_data, p_data)
                    st.success(an)

        # Grafico Trend con asse X formattato
        if not h_data.empty:
            df_plot = h_data.rename(columns={'Price': 'Sensation_Prezzo'})
            
            # Creazione Grafico
            fig_line = px.line(
                df_plot, 
                x='Data_dt', 
                y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
                markers=True, 
                title="Andamento nel Periodo"
            )
            
            # --- FIX ASSE X (SOLO DATA, NO ORE) ---
            fig_line.update_xaxes(
                tickformat="%d-%m-%Y",  # Formato Giorno-Mese-Anno
                dtick="D1" # Forza un tick ogni giorno (opzionale, utile se hai pochi dati)
            )
            
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.warning("Storico insufficiente per il periodo selezionato.")
            
    else:
        st.warning("Nessun prodotto disponibile con i filtri attuali.")
