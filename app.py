import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread

# --- CONFIGURAZIONE UI ---
st.set_page_config(page_title="Sensation Perfume Intelligence", layout="wide", page_icon="🧪")

# Custom CSS per un look "Premium"
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stMetric { background-color: #ffffff; border-radius: 10px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .css-1r6slb0 { border: 1px solid #e0e0e0; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- CONNESSIONE GOOGLE SHEETS ---
@st.cache_data(ttl=3600) # Aggiorna la cache ogni ora
def load_data():
    # Carica le credenziali dai "Secrets" di Streamlit/GitHub
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    
    # Sostituisci con l'ID del tuo foglio
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1eIojQyXLuC1FO89ZGcswy4s8AgFX3xc1UuheFFgM6Kk/edit#gid=0").sheet1
    data = sheet.get_all_records()
    return pd.DataFrame(data)

# --- LOGICA AI & NORMALIZZAZIONE ---
def apply_ai_insights(df):
    # Rilevamento Anomalie: se il prezzo è > 20% rispetto al minimo
    df['Anomaly'] = df.apply(lambda x: "⚠️ Overpriced" if float(x['Sensation_Prezzo']) > (float(x['Comp_1_Prezzo']) * 1.2) else "✅ Ok", axis=1)
    
    # Ottimizzazione Prezzo: suggerisce il prezzo per essere Rank 1 [cite: 74]
    df['AI_Suggested_Price'] = df.apply(lambda x: float(x['Comp_1_Prezzo']) - 0.10 if float(x['Sensation_Posizione']) > 1 else x['Sensation_Prezzo'], axis=1)
    
    # Delta Profitto (semplificato)
    df['Potential_Gain'] = df['Sensation_Prezzo'] - df['AI_Suggested_Price']
    return df

# --- MAIN APP ---
try:
    df_raw = load_data()
    df = apply_ai_insights(df_raw)

    st.title("🧪 Sensation Perfume Pricing Intelligence")
    st.markdown("Analisi competitiva basata sui dati Alphaposition Premium [cite: 13, 14]")

    # --- ROW 1: KPI CARDS ---
    col1, col2, col3, col4 = st.columns(4)
    
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / df.shape[0]) * 100
    avg_pos = df['Sensation_Posizione'].mean()
    critical_items = df[df['Anomaly'] == "⚠️ Overpriced"].shape[0]

    col1.metric("Buy Box Win Rate", f"{win_rate:.1f}%", help="Percentuale di prodotti dove sei il primo prezzo")
    col2.metric("Posizione Media", f"{avg_pos:.1f}", delta_color="inverse")
    col3.metric("Prodotti Critici", critical_items, delta="-5", delta_color="normal")
    col4.metric("Catalogo Monitorato", df.shape[0])

    st.divider()

    # --- ROW 2: VISUAL ANALYTICS ---
    c1, c2 = st.columns([2, 1])

    with c1:
        st.subheader("Analisi Prezzo: Sensation vs Miglior Competitor")
        fig = px.bar(df.head(20), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'],
                     barmode='group', labels={'value': 'Prezzo (€)', 'variable': 'Venditore'},
                     color_discrete_sequence=['#1f77b4', '#ff7f0e'])
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Distribuzione Posizionamento")
        # Visualizza quante volte sei in Rank 1, 2, 3... [cite: 74]
        fig_pie = px.pie(df, names='Sensation_Posizione', hole=.4, color_discrete_sequence=px.colors.sequential.RdBu)
        st.plotly_chart(fig_pie, use_container_width=True)

    # --- ROW 3: ACTIONABLE DATA TABLE ---
    st.subheader("📋 Piano d'Azione AI & Dettaglio Prodotti")
    
    # Selettore per filtrare i critici
    filter_choice = st.multiselect("Filtra per stato:", ["⚠️ Overpriced", "✅ Ok"], default=["⚠️ Overpriced", "✅ Ok"])
    df_filtered = df[df['Anomaly'].isin(filter_choice)]

    st.dataframe(df_filtered[['Product', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Sensation_Posizione', 'Anomaly', 'AI_Suggested_Price']], 
                 use_container_width=True,
                 column_config={
                     "Sensation_Prezzo": st.column_config.NumberColumn(format="%.2f €"),
                     "Comp_1_Prezzo": st.column_config.NumberColumn(format="%.2f €"),
                     "AI_Suggested_Price": st.column_config.NumberColumn("Prezzo Suggerito AI", format="%.2f €"),
                     "Anomaly": st.column_config.TextColumn("Status")
                 })

except Exception as e:
    st.error(f"Configura le credenziali di Google Sheets nei Secret! Errore: {e}")
