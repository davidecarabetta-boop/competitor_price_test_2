# --- 3. CARICAMENTO DATI (VERSIONE FIX DEFINITIVA) ---
@st.cache_data(ttl=600)
def load_data():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        client = gspread.service_account_from_dict(creds_dict)
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # 1. Carichiamo tutto lo storico prezzi (Foglio 1)
        df_p = pd.DataFrame(sh.sheet1.get_all_records())
        if df_p.empty: return pd.DataFrame()

        # 2. Carichiamo le entrate (Foglio Entrate)
        try: 
            df_r = pd.DataFrame(sh.worksheet("Entrate").get_all_records())
        except: 
            df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite', 'Data'])

        # Mapping Colonne Prezzi
        rename_map = {
            'Sensation_Prezzo': 'Price',
            'Sensation_Posizione': 'Rank',
            'Codice': 'Sku', 'id': 'Sku'
        }
        df_p.rename(columns=rename_map, inplace=True)

        # Pulizia SKU e Colonne
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip()
                if 'Sku' in df.columns: df['Sku'] = df['Sku'].astype(str).str.strip()

        # Pulizia Valute
        for col in ['Price', 'Comp_1_Prezzo']: 
            if col in df_p.columns: df_p[col] = df_p[col].apply(clean_currency)
        
        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns: df_r[col] = df_r[col].apply(clean_currency)

        # 3. GESTIONE DATE (Il cuore del problema)
        # Normalizziamo le date in entrambi i DF per poterli unire per Giorno + SKU
        for df, col_name in [(df_p, 'Data'), (df_r, 'Data')]:
            if col_name in df.columns:
                df['Data_dt'] = pd.to_datetime(df[col_name], dayfirst=True, errors='coerce').dt.normalize()
            else:
                # Se manca la data nei prezzi, proviamo Data_esecuzione
                fallback = 'Data_esecuzione' if 'Data_esecuzione' in df.columns else None
                if fallback:
                    df['Data_dt'] = pd.to_datetime(df[fallback], dayfirst=True, errors='coerce').dt.normalize()
                else:
                    df['Data_dt'] = pd.Timestamp.now().normalize()

        # 4. MERGE CRONOLOGICO
        # Uniamo per SKU e per DATA, così le entrate del 16 vanno sui prezzi del 16
        df_final = df_p.merge(df_r, on=['Sku', 'Data_dt'], how='left', suffixes=('', '_r')).fillna(0)
        
        # Gestione Categoria
        if 'Categoria' not in df_final.columns:
            df_final['Categoria'] = df_final.get('Category', 'Generale')

        return df_final.dropna(subset=['Data_dt'])
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()
