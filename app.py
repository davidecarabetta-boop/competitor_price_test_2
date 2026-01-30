import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import gspread
import json
import re

# --- 1. CONFIGURAZIONE ---
st.set_page_config(
    page_title="Sensation AI Pricing Tower",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# Check Secrets
if "gcp_service_account" not in st.secrets or "gemini_api_key" not in st.secrets:
    st.error("⛔ Configurazione mancante in secrets.toml")
    st.stop()

genai.configure(api_key=st.secrets["gemini_api_key"])
MODEL_NAME = 'gemini-1.5-flash'

# --- 2. FUNZIONI UTILITÀ ---

def clean_currency(value):
    """Pulisce valute (es. '1.200,00 €' -> 1200.00)"""
    if pd.isna(value) or str(value).strip() == '':
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    
    s = str(value).replace('€', '').replace('$', '').strip()
    try:
        # Gestione 1.000,00 vs 1,000.00
        if ',' in s and '.' in s:
            if s.find('.') < s.find(','): # 1.000,00
                s = s.replace('.', '').replace(',', '.')
            else: # 1,000.00
                s = s.replace(',', '')
        elif ',' in s: 
            s = s.replace(',', '.')
        return float(s)
    except:
        return 0.0

def clean_json_response(text):
    text = text.strip()
    if "```" in text:
        pattern = r"```(?:json)?(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    return text

# --- 3. CARICAMENTO DATI (MAPPING CORRETTO) ---

@st.cache_data(ttl=600)
def load_data():
    try:
        # Auth
        creds_dict = dict(st.secrets["gcp_service_account"])
        client = gspread.service_account_from_dict(creds_dict)
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # 1. Carica Prezzi (Foglio1)
        data_p = sh.sheet1.get_all_records()
        df_p = pd.DataFrame(data_p)
        
        if df_p.empty:
            # Crea struttura vuota se manca tutto
            return pd.DataFrame(columns=['Sku', 'Product', 'Data_dt', 'Price', 'Rank', 'Comp_1_Prezzo'])

        # 2. Carica Entrate
        try:
            data_r = sh.worksheet("Entrate").get_all_records()
            df_r = pd.DataFrame(data_r)
        except:
            df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        # --- MAPPING DELLE TUE COLONNE ---
        # Qui rinominiamo le TUE colonne in quelle standard del codice
        # Sensation_Prezzo -> Price
        # Sensation_Posizione -> Rank
        rename_map = {
            'Sensation_Prezzo': 'Price',
            'Sensation_Posizione': 'Rank',
            'Codice': 'Sku',   # Caso mai servisse
            'id': 'Sku'        # Caso mai servisse
        }
        df_p.rename(columns=rename_map, inplace=True)

        # Standardizza nomi (rimuovi spazi)
        df_p.columns = df_p.columns.str.strip()
        if not df_r.empty: df_r.columns = df_r.columns.str.strip()

        # Check colonne critiche mancanti dopo il rinomina
        if 'Price' not in df_p.columns: df_p['Price'] = 0.0
        if 'Rank' not in df_p.columns: df_p['Rank'] = 99
        if 'Comp_1_Prezzo' not in df_p.columns: df_p['Comp_1_Prezzo'] = 0.0
        
        # Pulizia Valori
        for col in ['Price', 'Comp_1_Prezzo']:
            if col in df_p.columns:
                df_p[col] = df_p[col].apply(clean_currency)
        
        df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        # Pulizia Entrate
        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns:
                    df_r[col] = df_r[col].apply(clean_currency)
            if 'Sku' in df_r.columns:
                df_r['Sku'] = df_r['Sku'].astype(str).str.strip()

        if 'Sku' in df_p.columns:
            df_p['Sku'] = df_p['Sku'].astype(str).str.strip()

        # MERGE
        df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        
        # --- GESTIONE DATA ---
        # Tu hai "Data" e "Data_esecuzione". Il codice prova a prenderne una.
        col_data = None
        if 'Data' in df_final.columns:
            col_data = 'Data'
        elif 'Data_esecuzione' in df_final.columns:
            col_data = 'Data_esecuzione'
            
        if col_data:
            df_final['Data_dt'] = pd.to_datetime(df_final[col_data], dayfirst=True, errors='coerce')
        else:
            df_final['Data_dt'] = pd.Timestamp.now()
            
        df_final = df_final.dropna(subset=['Data_dt'])
        
        return df_final

    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

# --- 4. LOGICA AI ---

def analyze_strategy(df_input):
    if df_input.empty: return pd.DataFrame()
    
    # Prepara subset
    df_subset = df_input.sort_values(by='Entrate', ascending=False).head(20)
    
    # Colonne sicure
    cols = ['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate']
    for c in cols:
        if c not in df_subset.columns: df_subset[c] = 0
        
    data_json = df_subset[cols].to_dict(orient='records')
    
    prompt = f"""
    Analizza questi dati: {json.dumps(data_json)}.
    Per ogni prodotto, decidi: "Aumentare Margine", "Attacco", "Monitorare", "Liquidare".
    Regole:
    - Attacco: Rank > 1 e differenza prezzo bassa.
    - Margine: Rank = 1 e prezzo molto inferiore al competitor.
    Output JSON Array: [{{ "Sku": "...", "Azione": "...", "Motivazione": "..." }}]
    """
    
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        clean = clean_json_response(res.text)
        return pd.DataFrame(json.loads(clean))
    except:
        return pd.DataFrame()

# --- 5. UI PRINCIPALE ---

df_raw = load_data()

if df_raw.empty:
    st.warning("⚠️ Database vuoto o errore lettura.")
    st.stop()

# Snapshot ultima data
df_latest = df_raw.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    st.title("Sensation AI")
    
    brands = sorted(list(set([str(p).split()[0] for p in df_latest['Product'] if p])))
    sel_brand = st.selectbox("Brand", ["Tutti"] + brands)
    
    if "ai_results" not in st.session_state:
        st.session_state.ai_results = pd.DataFrame()
        
    if st.button("✨ Analisi AI"):
        with st.spinner("Analisi in corso..."):
            df_in = df_latest if sel_brand == "Tutti" else df_latest[df_latest['Product'].str.startswith(sel_brand)]
            st.session_state.ai_results = analyze_strategy(df_in)
            
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# Filtri Dashboard
df_view = df_latest.copy()
if sel_brand != "Tutti":
    df_view = df_view[df_view['Product'].str.startswith(sel_brand)]

# KPI Calculation (Safe)
try:
    df_view['Price_Index'] = df_view.apply(
        lambda x: (x['Price'] / x['Comp_1_Prezzo'] * 100) if x['Comp_1_Prezzo'] > 0 else 0, 
        axis=1
    )
except:
    df_view['Price_Index'] = 0

win_rate = (df_view['Rank'] == 1).mean()
tot_rev = df_view['Entrate'].sum()

# Visualizzazione
st.title("📊 Control Tower")
c1, c2, c3 = st.columns(3)
c1.metric("Win Rate", f"{win_rate:.1%}")
c2.metric("Price Index", f"{df_view['Price_Index'].mean():.1f}%")
c3.metric("Fatturato (30gg)", f"€ {tot_rev:,.0f}")

t1, t2, t3 = st.tabs(["Performance", "Strategia AI", "Dati"])

with t1:
    
    fig = px.scatter(
        df_view[df_view['Price'] > 0], 
        x="Price_Index", y="Entrate", size="Vendite", color="Rank",
        hover_name="Product", range_x=[80, 120], color_continuous_scale="RdYlGn_r"
    )
    fig.add_vline(x=100, line_dash="dash")
    st.plotly_chart(fig, use_container_width=True)

with t2:
    if not st.session_state.ai_results.empty:
        st.dataframe(st.session_state.ai_results, hide_index=True, use_container_width=True)
    else:
        st.info("Premi 'Analisi AI' nella sidebar.")

with t3:
    cols = ['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate', 'Data_dt']
    # Mostra solo colonne esistenti per evitare errori
    valid_cols = [c for c in cols if c in df_view.columns]
    st.dataframe(df_view[valid_cols], use_container_width=True)
