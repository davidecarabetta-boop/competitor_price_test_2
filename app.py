import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread

# --- 1. CONFIGURAZIONE UI & LOGO ---
LOGO_PATH = "logosensation.png" 
st.set_page_config(page_title="Sensation Profumerie", layout="wide", page_icon=LOGO_PATH)

# --- 2. CARICAMENTO DATI ---
@st.cache_data(ttl=600)
def load_data():
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(st.secrets["google_sheets"]["sheet_url"]).sheet1
        raw_data = sheet.get_all_values()
        
        if not raw_data: return pd.DataFrame()
        
        df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
        df.columns = df.columns.str.strip()

        # PULIZIA PREZZI (Correzione Virgola -> Punto per evitare cifre astronomiche)
        price_cols = ['Sensation_Prezzo', 'Comp_1_Prezzo', 'Comp_2_prezzo']
        for col in price_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace('€', '', regex=False)
                           .str.replace('.', '', regex=False)
                           .str.replace(',', '.', regex=False).str.strip(), 
                    errors='coerce'
                ).fillna(0)
        
        # [cite_start]PULIZIA POSIZIONE (Rank su Trovaprezzi) [cite: 74]
        if 'Sensation_Posizione' in df.columns:
            df['Sensation_Posizione'] = pd.to_numeric(df['Sensation_Posizione'], errors='coerce').fillna(0).astype(int)

        # CONVERSIONE DATA per ordinamento cronologico
        df['Data_dt'] = pd.to_datetime(df['Data'], dayfirst=True, errors='coerce')
        return df
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. SIDEBAR (FILTRI) ---
with st.sidebar:
    try: st.image(LOGO_PATH, use_container_width=True)
    except: st.info("Logo Sensation")
    
    st.header("🛒 Filtri Catalogo")
    full_brand_list = sorted(df_raw['Product'].str.split().str[0].unique()) if not df_raw.empty else []
    selected_brands = st.multiselect("Seleziona Brand", full_brand_list)
    
    if st.button("🔄 Aggiorna Dati"):
        st.cache_data.clear()
        st.rerun()

# --- 4. LOGICA SNAPSHOT (ULTIMO DATO PER SKU) ---
if not df_raw.empty:
    # Teniamo solo l'ultima rilevazione per ogni SKU per i KPI globali
    df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()
    
    # Filtro Brand
    df = df_latest.copy()
    if selected_brands:
        df = df[df['Product'].str.startswith(tuple(selected_brands))]
else:
    st.stop()

# --- 5. DASHBOARD ---
tab1, tab2 = st.tabs(["📊 Overview Mercato", "🔍 Focus Prodotto"])

# --- TAB 1: OVERVIEW ---
with tab1:
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    
    c1.metric("Buy Box Win Rate", f"{win_rate:.1f}%")
    c2.metric("Posizione Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Sensation Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("Prodotti Visualizzati", len(df))

    st.divider()
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.subheader("Confronto Prezzi: Noi vs Miglior Competitor")
        fig = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
                     barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'})
        st.plotly_chart(fig, use_container_width=True)
    
    with col_r:
        st.subheader("Distribuzione Posizioni (Rank)")
        fig_pie = px.pie(df, names='Sensation_Posizione', hole=0.5)
        st.plotly_chart(fig_pie, use_container_width=True)

    st.subheader("📋 Tabella Riepilogativa Attuale")
    st.dataframe(df[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Comp_1_Prezzo']], use_container_width=True, hide_index=True)

# Calcolo Indice di Competitività (PI)
# 100 = Allineato al minimo, >100 = Più caro del minimo
df_display['Price_Index'] = (df_display['Sensation_Prezzo'] / df_display['Comp_1_Prezzo']) * 100

# Formattazione per la tabella
st.dataframe(
    df_display[['Sku', 'Product', 'Sensation_Posizione', 'Price_Index', 'Analisi AI']],
    column_config={
        "Price_Index": st.column_config.ProgressColumn(
            "Indice Competitività",
            help="100% significa che sei il primo prezzo",
            format="%.1f",
            min_value=80,
            max_value=150,
        )
    }
)

# --- TAB 2: FOCUS PRODOTTO (REINTEGRATA) ---
with tab2:
    st.subheader("🔍 Analisi Storica e Dettaglio Competitor")
    
    if not df.empty:
        # Selezione prodotto filtrata per quanto scelto nella sidebar
        lista_prodotti = sorted(df['Product'].unique())
        product_selected = st.selectbox("Seleziona un profumo per l'analisi:", lista_prodotti)
        
        # Dati correnti (Snapshot) e Storici (Full DB)
        p_data = df[df['Product'] == product_selected].iloc[0]
        hist_data = df_raw[df_raw['Product'] == product_selected].sort_values('Data_dt')

        col_card, col_chart = st.columns([1, 2])
        
        with col_card:
            st.markdown(f"""
                <div style="background-color: white; padding: 20px; border-radius: 10px; border-left: 5px solid #0056b3; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <h4 style="margin-top:0;">{product_selected}</h4>
                    <p style="color: #666;">SKU: {p_data['Sku']}</p>
                    <hr>
                    <p><b>Posizione Attuale:</b> {p_data['Sensation_Posizione']:.0f}°</p>
                    <h2 style="color: #0056b3;">{p_data['Sensation_Prezzo']:.2f} €</h2>
                    <p style="color: green;">✔ Disponibile</p>
                </div>
            """, unsafe_allow_html=True)
            
        with col_chart:
            # Grafico a linee per il trend temporale
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Sensation_Prezzo'], name='Sensation (Noi)', line=dict(color='#0056b3', width=4)))
            
            # Aggiungiamo il competitor 1 se presente
            if p_data['Comp_1_Prezzo'] > 0:
                fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_1_Prezzo'], name=str(p_data['Comp_rank_1']), line=dict(dash='dash', color='#ffa500')))
            
            fig_trend.update_layout(title="Andamento Prezzi nel Tempo", hovermode="x unified")
            st.plotly_chart(fig_trend, use_container_width=True)

        # Tabella di Benchmark basso
        st.subheader("🏁 Posizionamento Rispetto ai Competitor")
        bench_df = pd.DataFrame({
            "Competitor": [p_data['Comp_rank_1'], p_data['Comp_rank_2']],
            "Prezzo": [f"{p_data['Comp_1_Prezzo']:.2f} €", f"{p_data['Comp_2_prezzo']:.2f} €"],
            "Gap da Sensation": [
                f"{p_data['Sensation_Prezzo'] - p_data['Comp_1_Prezzo']:.2f} €",
                f"{p_data['Sensation_Prezzo'] - p_data['Comp_2_prezzo']:.2f} €"
            ]
        })
        st.table(bench_df)
    else:
        st.info("Seleziona un brand nella sidebar per attivare l'analisi del prodotto.")
