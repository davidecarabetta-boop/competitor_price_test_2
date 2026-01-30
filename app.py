import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
import json
import re

# --- 1. CONFIGURAZIONE INIZIALE ---
st.set_page_config(
    page_title="Sensation AI Pricing Tower",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# Verifica Secrets
if "gcp_service_account" not in st.secrets or "gemini_api_key" not in st.secrets:
    st.error("⛔ Manca la configurazione in `.streamlit/secrets.toml`.")
    st.stop()

# Configurazione AI
genai.configure(api_key=st.secrets["gemini_api_key"])
MODEL_NAME = 'gemini-1.5-flash' # Usa 1.5 Flash (veloce ed economico) o 2.0-flash-exp se disponibile

# --- 2. FUNZIONI DI UTILITÀ (CLEANING) ---

def clean_currency(value):
    """
    Converte stringhe come '1.200,50 €' o '1,200.50' in float puri.
    Gestisce formattazione italiana e anglosassone.
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
            if s.find('.') < s.find(','): # Formato EU: 1.000,50
                s = s.replace('.', '').replace(',', '.')
            else: # Formato US errato ma possibile: 1,000.50
                s = s.replace(',', '')
        elif ',' in s: # Solo virgola (presumibilmente decimale in IT)
            s = s.replace(',', '.')
            
        return float(s)
    except:
        return 0.0

def clean_json_response(text):
    """Pulisce la risposta dell'AI dai tag Markdown per estrarre il JSON puro."""
    text = text.strip()
    # Rimuove ```json all'inizio e ``` alla fine
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
        # Autenticazione
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # 1. Dati Prezzi (Foglio1)
        data_p = sh.sheet1.get_all_records()
        df_p = pd.DataFrame(data_p)
        
        # 2. Dati Entrate (Entrate) - Gestione se non esiste
        try:
            data_r = sh.worksheet("Entrate").get_all_records()
            df_r = pd.DataFrame(data_r)
        except:
            df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        # Standardizzazione Colonne
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip()
                # Rinomina colonne critiche se necessario
                col_map = {c: c for c in df.columns} # Identità per default
                # Esempio: se hai 'Codice' invece di 'Sku', aggiungi qui il mapping
                # col_map['Codice'] = 'Sku' 
                df.rename(columns=col_map, inplace=True)
                
                if 'Sku' in df.columns:
                    df['Sku'] = df['Sku'].astype(str).str.strip()

        # Pulizia Prezzi nel DataFrame principale
        cols_to_clean = [c for c in df_p.columns if any(x in c.lower() for x in ['prezzo', 'price', 'costo'])]
        for col in cols_to_clean:
            df_p[col] = df_p[col].apply(clean_currency)
            
        # Pulizia Rank
        if 'Rank' in df_p.columns:
            df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        # Pulizia Entrate/Vendite nel DataFrame Revenue
        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns:
                    df_r[col] = df_r[col].apply(clean_currency)

        # MERGE
        df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        
        # Data Handling
        if 'Data_Esecuzione' in df_final.columns:
            df_final['Data_dt'] = pd.to_datetime(df_final['Data_Esecuzione'], dayfirst=True, errors='coerce')
        
        return df_final

    except Exception as e:
        st.error(f"❌ Errore critico nel caricamento dati: {str(e)}")
        return pd.DataFrame()

# --- 4. LOGICA AI ---

def analyze_strategy(df_input):
    """
    Analizza i prodotti per suggerire azioni di prezzo.
    """
    # Prendiamo i top 20 prodotti per fatturato o criticità per non saturare l'API
    df_subset = df_input.sort_values(by='Entrate', ascending=False).head(20)
    
    # Prepariamo un dizionario leggero
    data_for_ai = df_subset[['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate']].to_dict(orient='records')
    
    prompt = f"""
    Sei un Senior Pricing Analyst. Analizza questi dati di e-commerce:
    {json.dumps(data_for_ai)}
    
    Per ogni prodotto, determina la "Azione Consigliata" tra:
    1. "Aumentare Margine" (Se Rank=1 e siamo molto più economici del competitor)
    2. "Attacco" (Se Rank > 1 e il prezzo competitor è vicino)
    3. "Monitorare" (Situazione stabile)
    4. "Liquidare" (Prezzo alto, zero vendite)
    
    Restituisci ESCLUSIVAMENTE un JSON array valido in questo formato:
    [
        {{"Sku": "sku_prodotto", "Azione": "Azione scelta", "Motivazione": "Breve spiegazione (max 10 parole)"}}
    ]
    Non aggiungere testo introduttivo.
    """
    
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)
        cleaned_text = clean_json_response(response.text)
        return pd.DataFrame(json.loads(cleaned_text))
    except Exception as e:
        st.warning(f"⚠️ Analisi AI fallita: {str(e)}")
        return pd.DataFrame()

# --- 5. INTERFACCIA UTENTE (DASHBOARD) ---

# Caricamento
df_raw = load_data()

if df_raw.empty:
    st.warning("Nessun dato disponibile. Controlla il foglio Google o lo script di sync.")
    st.stop()

# Prendiamo solo l'ultima rilevazione temporale per ogni SKU
df_latest = df_raw.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()

# SIDEBAR
with st.sidebar:
    st.title("Sensation AI")
    st.caption("Pricing Intelligence Suite")
    st.divider()
    
    # Filtri
    brands = sorted(list(set([str(p).split()[0] for p in df_latest['Product'] if p])))
    sel_brand = st.selectbox("Filtra Brand", ["Tutti"] + brands)
    
    st.divider()
    
    # AI Control con Session State
    if "ai_results" not in st.session_state:
        st.session_state.ai_results = pd.DataFrame()
        
    if st.button("✨ Genera Strategia AI"):
        with st.spinner("L'AI sta analizzando i margini..."):
            # Filtriamo i dati attuali prima di mandarli all'AI
            if sel_brand != "Tutti":
                df_ai_input = df_latest[df_latest['Product'].str.startswith(sel_brand)]
            else:
                df_ai_input = df_latest
            
            st.session_state.ai_results = analyze_strategy(df_ai_input)
            
    if st.button("🔄 Aggiorna Dati"):
        st.cache_data.clear()
        st.rerun()

# FILTRAGGIO MAIN
if sel_brand != "Tutti":
    df_view = df_latest[df_latest['Product'].str.startswith(sel_brand)].copy()
else:
    df_view = df_latest.copy()

# CALCOLO KPI
# Price Index: (Nostro Prezzo / Prezzo Competitor) * 100
df_view['Price_Index'] = df_view.apply(lambda x: (x['Price'] / x['Comp_1_Prezzo'] * 100) if x['Comp_1_Prezzo'] > 0 else 0, axis=1)

win_rate = (df_view['Rank'] == 1).mean()
total_rev = df_view['Entrate'].sum()
# Opportunity Lost: Fatturato potenziale (20% stimato) su prodotti popolari dove non siamo primi
opp_mask = (df_view['Rank'] > 1) & (df_view['Popularity'] > 0) & (df_view['Popularity'] <= 20)
opp_lost = df_view[opp_mask]['Entrate'].sum() * 0.20 

# LAYOUT DASHBOARD
st.title("📊 Control Tower")
st.markdown(f"**Ultimo Aggiornamento:** {df_view['Data_dt'].max().strftime('%d/%m/%Y') if not pd.isnull(df_view['Data_dt'].max()) else 'N/D'}")

# KPI CARDS
col1, col2, col3, col4 = st.columns(4)
col1.metric("Win Rate (Pos. 1)", f"{win_rate:.1%}", delta="vs Competitor")
col2.metric("Price Index Medio", f"{df_view[df_view['Price_Index']>0]['Price_Index'].mean():.1f}", help="< 100: Più economici dei competitor")
col3.metric("Fatturato (Mensile)", f"€ {total_rev:,.0f}")
col4.metric("Opportunity Lost", f"€ {opp_lost:,.0f}", delta="Recuperabile", delta_color="inverse")

st.divider()

# TABS
tab1, tab2, tab3 = st.tabs(["📈 Analisi Mercato", "🤖 Strategia AI", "📋 Dettaglio Dati"])

# TAB 1: GRAFICI
with tab1:
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("Matrice Competitiva")
        # Scatter Plot
        fig = px.scatter(
            df_view[df_view['Price'] > 0],
            x="Price_Index",
            y="Entrate",
            size="Vendite",
            color="Rank",
            hover_name="Product",
            hover_data=["Price", "Comp_1_Prezzo"],
            range_x=[80, 120], # Focus sull'area critica +/- 20%
            color_continuous_scale="RdYlGn_r", # Verde=Rank 1, Rosso=Rank Alto
            title="Posizionamento Prezzo vs Fatturato"
        )
        fig.add_vline(x=100, line_dash="dash", annotation_text="Parità Prezzo")
        st.plotly_chart(fig, use_container_width=True)
        
    with c2:
        st.subheader("Top Competitor")
        if 'Comp_1_Nome' in df_view.columns:
            top_comps = df_view['Comp_1_Nome'].value_counts().head(5)
            st.bar_chart(top_comps)
        else:
            st.info("Dati nomi competitor non disponibili")

# TAB 2: AI INSIGHTS
with tab2:
    st.subheader("💡 Suggerimenti Intelligenza Artificiale")
    
    if not st.session_state.ai_results.empty:
        # Merge dei risultati AI con i dati prodotto per mostrare contesto
        res = st.session_state.ai_results
        
        # Colorazione condizionale
        def color_action(val):
            color = 'black'
            if val == 'Attacco': color = 'red'
            elif val == 'Aumentare Margine': color = 'green'
            elif val == 'Liquidare': color = 'orange'
            return f'color: {color}; font-weight: bold'

        st.dataframe(
            res.style.map(color_action, subset=['Azione']),
            use_container_width=True,
            hide_index=True
        )
        
        st.markdown("---")
        st.caption("Nota: L'AI analizza i Top 20 prodotti per impatto sul fatturato.")
    else:
        st.info("👈 Clicca su 'Genera Strategia AI' nella barra laterale per avviare l'analisi.")

# TAB 3: DATA EDITOR
with tab3:
    st.subheader("Esplora Dati Completi")
    
    # Setup colonne per editor
    column_cfg = {
        "Price": st.column_config.NumberColumn("Nostro Prezzo", format="€ %.2f"),
        "Comp_1_Prezzo": st.column_config.NumberColumn("Miglior Competitor", format="€ %.2f"),
        "Entrate": st.column_config.NumberColumn("Revenue", format="€ %.2f"),
        "Url_Prodotto": st.column_config.LinkColumn("Link")
    }
    
    # Filtriamo colonne inutili
    cols_show = ['Product', 'Rank', 'Price', 'Comp_1_Prezzo', 'Entrate', 'Vendite', 'Popularity']
    final_cols = [c for c in cols_show if c in df_view.columns]
    
    st.dataframe(
        df_view[final_cols].sort_values('Entrate', ascending=False),
        column_config=column_cfg,
        use_container_width=True,
        hide_index=True
    )
