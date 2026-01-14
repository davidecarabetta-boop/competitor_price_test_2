import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread

# --- 1. CONFIGURAZIONE UI & LOGO ---
LOGO_PATH = "logosensation.png" 
st.set_page_config(page_title="Sensation Profumerie", layout="wide", page_icon=LOGO_PATH)

# CSS per look Premium
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; border-radius: 10px; padding: 15px; border: 1px solid #f0f0f0; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .product-card { background-color: white; padding: 20px; border-radius: 10px; border-left: 5px solid #0056b3; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

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

        # PULIZIA PREZZI (Correzione decimale virgola -> punto)
        price_cols = ['Sensation_Prezzo', 'Comp_1_Prezzo', 'Comp_2_prezzo']
        for col in price_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace('€', '', regex=False)
                           .str.replace('.', '', regex=False)
                           .str.replace(',', '.', regex=False).str.strip(), 
                    errors='coerce'
                ).fillna(0)
        
        # PULIZIA POSIZIONE (Rank)
        if 'Sensation_Posizione' in df.columns:
            df['Sensation_Posizione'] = pd.to_numeric(df['Sensation_Posizione'], errors='coerce').fillna(0).astype(int)

        # CONVERSIONE DATA
        df['Data_dt'] = pd.to_datetime(df['Data'], dayfirst=True, errors='coerce')
        return df
    except Exception as e:
        st.error(f"Errore caricamento database: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. SIDEBAR (FILTRI) ---
with st.sidebar:
    try: st.image(LOGO_PATH, use_container_width=True)
    except: st.info("Sensation Intelligence")
    
    st.header("🛒 Filtri Catalogo")
    full_brand_list = sorted(df_raw['Product'].str.split().str[0].unique()) if not df_raw.empty else []
    selected_brands = st.multiselect("Seleziona Brand", full_brand_list)
    
    if st.button("🔄 Forza Aggiornamento"):
        st.cache_data.clear()
        st.rerun()

# --- 4. LOGICA SNAPSHOT (DATI ATTUALI) ---
if not df_raw.empty:
    # Deduplicazione per SKU: teniamo solo l'ultima rilevazione
    df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()
    
    df = df_latest.copy()
    if selected_brands:
        df = df[df['Product'].str.startswith(tuple(selected_brands))]
else:
    st.stop()

# --- 5. DASHBOARD ---
tab1, tab2 = st.tabs(["📊 Overview Mercato", "🔍 Focus Prodotto"])

# --- TAB 1: OVERVIEW ---
with tab1:
    # Metriche principali
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    
    c1.metric("Buy Box Win Rate", f"{win_rate:.1f}%")
    c2.metric("Posizione Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Sensation Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("Prodotti in Analisi", len(df))

    st.divider()
    
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.subheader("Confronto Prezzi: Noi vs Miglior Competitor")
        fig = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
                     barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'})
        st.plotly_chart(fig, use_container_width=True)
    
    with col_r:
        st.subheader("Distribuzione Posizioni (Rank)")
        fig_pie = px.pie(df, names='Sensation_Posizione', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig_pie, use_container_width=True)

    st.subheader("📋 Riepilogo Strategico Prodotti")
    
    # --- LOGICA TABELLA INTEGRATA (STILE MINDEREST) ---
    df_display = df.copy()
    
    # 1. Calcolo Gap in Euro
    df_display['Gap'] = df_display['Sensation_Prezzo'] - df_display['Comp_1_Prezzo']
    
    # 2. Calcolo Indice di Competitività (Price Index)
    # Evitiamo divisione per zero
    df_display['Price_Index'] = df_display.apply(
        lambda x: (x['Sensation_Prezzo'] / x['Comp_1_Prezzo'] * 100) if x['Comp_1_Prezzo'] > 0 else 100, axis=1
    )
    
    # 3. Analisi AI
    df_display['Analisi AI'] = df_display.apply(
        lambda x: "✅ Leader" if x['Sensation_Posizione'] == 1 else "⚠️ Da Rivedere", axis=1
    )

    # Visualizzazione Super-Tabella
    st.dataframe(
        df_display[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Gap', 'Price_Index', 'Analisi AI']],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Product": st.column_config.TextColumn("Prodotto", width="large"),
            "Sensation_Prezzo": st.column_config.NumberColumn("Tuo Prezzo", format="%.2f €"),
            "Comp_1_Prezzo": st.column_config.NumberColumn("Miglior Competitor", format="%.2f €"),
            "Gap": st.column_config.NumberColumn("Gap (€)", format="%.2f €"),
            "Sensation_Posizione": st.column_config.NumberColumn("Rank"),
            "Price_Index": st.column_config.ProgressColumn(
                "Indice Competitività",
                help="100% significa che sei allineato al primo prezzo. Sopra 100% sei più caro.",
                format="%.0f",
                min_value=80,
                max_value=130,
            ),
            "Analisi AI": st.column_config.TextColumn("Stato")
        }
    )

# --- TAB 2: FOCUS PRODOTTO ---
with tab2:
    st.subheader("🔍 Analisi Storica e Benchmarking")
    
    if not df.empty:
        lista_prodotti = sorted(df['Product'].unique())
        product_selected = st.selectbox("Cerca prodotto:", lista_prodotti)
        
        p_data = df[df['Product'] == product_selected].iloc[0]
        hist_data = df_raw[df_raw['Product'] == product_selected].sort_values('Data_dt')

        col_card, col_chart = st.columns([1, 2])
        
        with col_card:
            st.markdown(f"""
                <div class="product-card">
                    <h4 style="margin:0;">{product_selected}</h4>
                    <p style="color:#666; font-size:0.8em;">SKU: {p_data['Sku']}</p>
                    <hr>
                    <p><b>Posizione Attuale:</b> {p_data['Sensation_Posizione']:.0f}°</p>
                    <h2 style="color:#0056b3; margin:0;">{p_data['Sensation_Prezzo']:.2f} €</h2>
                    <p style="color:green; font-size:0.9em; margin-top:10px;">✔ In Monitoraggio</p>
                </div>
            """, unsafe_allow_html=True)
            
        with col_chart:
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Sensation_Prezzo'], name='Sensation', line=dict(color='#0056b3', width=4)))
            if p_data['Comp_1_Prezzo'] > 0:
                fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_1_Prezzo'], name=str(p_data['Comp_rank_1']), line=dict(dash='dash', color='#ffa500')))
            
            fig_trend.update_layout(title="Andamento Storico Prezzi", hovermode="x unified", margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_trend, use_container_width=True)

        st.subheader("🏁 Distacco dai Competitor")
        bench_df = pd.DataFrame({
            "Competitor": [p_data['Comp_rank_1'], p_data['Comp_rank_2']],
            "Prezzo": [f"{p_data['Comp_1_Prezzo']:.2f} €", f"{p_data['Comp_2_prezzo']:.2f} €"],
            "Gap da Sensation": [
                f"{p_data['Sensation_Prezzo'] - p_data['Comp_1_Prezzo']:.2f} €",
                f"{p_data['Sensation_Prezzo'] - p_data['Comp_2_prezzo']:.2f} €"
            ]
        })
        st.table(bench_df)
