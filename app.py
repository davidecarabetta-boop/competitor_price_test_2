import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
import json
import re

# --- 1. CONFIGURAZIONE INIZIALE (DEVE ESSERE LA PRIMA ISTRUZIONE STREAMLIT) ---
st.set_page_config(
    page_title="Sensation AI Pricing Tower",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# Verifica configurazione Secrets
if "gcp_service_account" not in st.secrets or "gemini_api_key" not in st.secrets:
    st.error("⛔ Manca la configurazione in `.streamlit/secrets.toml`. Controlla le chiavi 'gcp_service_account' e 'gemini_api_key'.")
    st.stop()

# Configurazione AI
genai.configure(api_key=st.secrets["gemini_api_key"])
MODEL_NAME = 'gemini-1.5-flash'

# --- 2. FUNZIONI DI UTILITÀ (PULIZIA DATI) ---

def clean_currency(value):
    """
    Converte stringhe come '1.200,50 €', '1.200,50' o '1,200.50' in float puri.
    """
    if pd.isna(value) or value == '':
        return 0.0
    
    if isinstance(value, (int, float)):
        return float(value)
    
    # Rimuovi simboli di valuta e spazi
    s = str(value).replace('€', '').replace('$', '').replace('£', '').strip()
    
    try:
        # Caso Italiano: 1.000,00 (punto migliaia, virgola decimali)
        if ',' in s and '.' in s:
            if s.find('.') < s.find(','): # Formato EU: 1.000,50 -> togli punto, cambia virgola in punto
                s = s.replace('.', '').replace(',', '.')
            else: # Formato US errato ma possibile: 1,000.50 -> togli virgola
                s = s.replace(',', '')
        elif ',' in s: # Solo virgola (presumibilmente decimale in IT)
            s = s.replace(',', '.')
            
        return float(s)
    except:
        return 0.0

def clean_json_response(text):
    """Pulisce la risposta dell'AI dai tag Markdown per estrarre il JSON puro."""
    text = text.strip()
    if "```" in text:
        pattern = r"```(?:json)?(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    return text

# --- 3. CARICAMENTO DATI ---

@st.cache_data(ttl=600)
def load_data():
    try:
        # Autenticazione Google Sheets
        scope = ['[https://www.googleapis.com/auth/spreadsheets](https://www.googleapis.com/auth/spreadsheets)', '[https://www.googleapis.com/auth/drive](https://www.googleapis.com/auth/drive)']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # 1. Dati Prezzi (Foglio1)
        data_p = sh.sheet1.get_all_records()
        df_p = pd.DataFrame(data_p)
        
        if df_p.empty:
            # Ritorna DF vuoto strutturato se il foglio è vuoto
            return pd.DataFrame(columns=['Sku', 'Product', 'Data_dt', 'Entrate'])

        # 2. Dati Entrate (Foglio "Entrate")
        try:
            data_r = sh.worksheet("Entrate").get_all_records()
            df_r = pd.DataFrame(data_r)
        except:
            # Se la tab non esiste, crea DF vuoto
            df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        # Standardizzazione Nomi Colonne (toglie spazi)
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip()
                if 'Sku' in df.columns:
                    df['Sku'] = df['Sku'].astype(str).str.strip()

        # Pulizia Prezzi
        cols_to_clean = [c for c in df_p.columns if any(x in c.lower() for x in ['prezzo', 'price', 'costo'])]
        for col in cols_to_clean:
            df_p[col] = df_p[col].apply(clean_currency)
            
        if 'Rank' in df_p.columns:
            df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        # Pulizia Entrate
        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns:
                    df_r[col] = df_r[col].apply(clean_currency)

        # MERGE: Uniamo i dati storici con i dati di vendita
        df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        
        # --- FIX DATA (Corregge il KeyError) ---
        # Cerca 'Data' o 'Data_Esecuzione'
        col_data_trovata = None
        if 'Data' in df_final.columns:
            col_data_trovata = 'Data'
        elif 'Data_Esecuzione' in df_final.columns:
            col_data_trovata = 'Data_Esecuzione'
            
        if col_data_trovata:
            # Converte la stringa data in oggetto datetime
            df_final['Data_dt'] = pd.to_datetime(df_final[col_data_trovata], dayfirst=True, errors='coerce')
        else:
            # Se manca la colonna data, usa la data odierna per non crashare
            # st.warning("Colonna Data non trovata, uso data odierna.")
            df_final['Data_dt'] = pd.Timestamp.now()
        
        # Rimuove righe con data non valida (NaT)
        df_final = df_final.dropna(subset=['Data_dt'])

        return df_final

    except Exception as e:
        st.error(f"❌ Errore critico nel caricamento dati: {str(e)}")
        return pd.DataFrame()

# --- 4. LOGICA AI ---

def analyze_strategy(df_input):
    """Chiama Gemini per analizzare la strategia di prezzo."""
    # Limitiamo ai top 20 prodotti per revenue o importanza per non saturare l'API
    df_subset = df_input.sort_values(by='Entrate', ascending=False).head(20)
    
    # Prepariamo i dati minimi per l'AI
    data_for_ai = df_subset[['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate']].to_dict(orient='records')
    
    prompt = f"""
    Sei un Senior Pricing Analyst. Analizza questi dati JSON: {json.dumps(data_for_ai)}.
    Per ogni prodotto, decidi l'azione migliore tra: "Aumentare Margine", "Attacco", "Monitorare", "Liquidare".
    
    Regole:
    - Attacco: Se Rank > 1 e il prezzo competitor è vicino.
    - Aumentare Margine: Se Rank = 1 e siamo molto più economici del competitor.
    
    Restituisci ESCLUSIVAMENTE un array JSON valido:
    [{{"Sku": "...", "Azione": "...", "Motivazione": "breve testo"}}]
    """
    
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)
        cleaned_text = clean_json_response(response.text)
        return pd.DataFrame(json.loads(cleaned_text))
    except Exception as e:
        st.warning(f"⚠️ Analisi AI fallita: {str(e)}")
        return pd.DataFrame()

# --- 5. INTERFACCIA UTENTE ---

# 1. Caricamento Dati
df_raw = load_data()

if df_raw.empty:
    st.warning("⚠️ Nessun dato disponibile. Controlla il Foglio Google e assicurati che contenga dati.")
    st.stop()

# 2. Creazione Snapshot Ultima Rilevazione (per la Dashboard)
# Ordina per data e tiene l'ultima occorrenza di ogni SKU
df_latest = df_raw.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()

# Sidebar
with st.sidebar:
    st.title("Sensation AI")
    st.caption("Pricing Intelligence Suite")
    
    # Filtro Brand
    all_brands = sorted(list(set([str(p).split()[0] for p in df_latest['Product'] if p])))
    sel_brand = st.selectbox("Filtra Brand", ["Tutti"] + all_brands)
    
    st.divider()
    
    # Gestione AI (Session State per non perdere i risultati al refresh)
    if "ai_results" not in st.session_state:
        st.session_state.ai_results = pd.DataFrame()
        
    if st.button("✨ Genera Strategia AI"):
        with st.spinner("L'AI sta analizzando i margini..."):
            df_ai_input = df_latest if sel_brand == "Tutti" else df_latest[df_latest['Product'].str.startswith(sel_brand)]
            st.session_state.ai_results = analyze_strategy(df_ai_input)
            
    if st.button("🔄 Aggiorna Dati"):
        st.cache_data.clear()
        st.rerun()

# Filtraggio Dati Dashboard
df_view = df_latest.copy()
if sel_brand != "Tutti":
    df_view = df_view[df_view['Product'].str.startswith(sel_brand)]

# Calcolo KPI
# Price Index: 100 = Parità. <100 = Siamo economici. >100 = Siamo cari.
df_view['Price_Index'] = df_view.apply(lambda x: (x['Price'] / x['Comp_1_Prezzo'] * 100) if x['Comp_1_Prezzo'] > 0 else 0, axis=1)

win_rate = (df_view['Rank'] == 1).mean()
total_rev = df_view['Entrate'].sum()

# Layout Dashboard
st.title("📊 Control Tower")
col1, col2, col3 = st.columns(3)
col1.metric("Win Rate (Pos. 1)", f"{win_rate:.1%}")
col2.metric("Price Index Medio", f"{df_view[df_view['Price_Index']>0]['Price_Index'].mean():.1f}%")
col3.metric("Fatturato Monitorato (30gg)", f"€ {total_rev:,.0f}")

st.divider()

# Tabs
tab1, tab2, tab3 = st.tabs(["📈 Analisi Mercato", "🤖 Strategia AI", "📋 Dati Dettaglio"])

with tab1:
    st.subheader("Posizionamento Prezzo vs Fatturato")
    # Grafico a bolle: Asse X=Indice Prezzo, Asse Y=Fatturato, Dimensione=Vendite
    fig = px.scatter(
        df_view[df_view['Price'] > 0], 
        x="Price_Index", 
        y="Entrate", 
        size="Vendite", 
        color="Rank",
        hover_name="Product", 
        range_x=[80, 120], # Focus sull'area +/- 20% dal competitor
        color_continuous_scale="RdYlGn_r", 
        title="Distribuzione Competitiva"
    )
    fig.add_vline(x=100, line_dash="dash", annotation_text="Parità")
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Suggerimenti Strategici AI")
    if not st.session_state.ai_results.empty:
        # Uniamo i risultati AI con i dati prodotto per mostrare il contesto
        res_display = st.session_state.ai_results
        st.dataframe(res_display, use_container_width=True, hide_index=True)
    else:
        st.info("👈 Clicca su 'Genera Strategia AI' nella barra laterale per avviare l'analisi.")

with tab3:
    st.subheader("Database Prodotti")
    st.dataframe(
        df_view[['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate', 'Data_dt']], 
        use_container_width=True,
        hide_index=True
    )
