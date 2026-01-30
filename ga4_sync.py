import os
import json
import pandas as pd
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest
)
import gspread
from gspread_dataframe import set_with_dataframe

# --- CONFIGURAZIONE ---
# IMPORTANTE: Sostituisci con il tuo ID numerico se non usi le variabili d'ambiente
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "INSERISCI_QUI_IL_TUO_NUMERO_PROPERTY") 
GOOGLE_CREDENTIALS = os.environ.get("GCP_SA_KEY")
SHEET_URL = "https://docs.google.com/spreadsheets/d/1eIojQyXLuC1FO89ZGcswy4s8AgFX3xc1UuheFFgM6Kk/edit"

def get_ga4_data():
    print(f"📡 Connessione a GA4 (Property: {GA4_PROPERTY_ID})...")
    
    if not GOOGLE_CREDENTIALS:
        print("❌ Errore: Manca la variabile d'ambiente GCP_SA_KEY")
        return pd.DataFrame()

    try:
        info_chiave = json.loads(GOOGLE_CREDENTIALS)
        client = BetaAnalyticsDataClient.from_service_account_info(info_chiave)

        # Richiesta API
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            dimensions=[Dimension(name="itemId")], # itemId = SKU
            metrics=[
                Metric(name="itemsPurchased"), 
                Metric(name="itemRevenue")
            ],
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
        )

        response = client.run_report(request)

        # Parsing Risposta
        data = []
        for row in response.rows:
            # Gestione sicura dei valori (evita crash su valori nulli)
            sku = row.dimension_values[0].value
            vendite = int(row.metric_values[0].value) if row.metric_values[0].value else 0
            entrate = float(row.metric_values[1].value) if row.metric_values[1].value else 0.0
            
            data.append({
                "Sku": sku,
                "Vendite": vendite,
                "Entrate": entrate
            })

        df = pd.DataFrame(data)
        
        if df.empty:
            print("⚠️ GA4 ha risposto con successo, ma non ci sono dati per questo periodo (0 righe).")
        else:
            print(f"✅ Scaricati {len(df)} SKU da GA4.")
            
        return df

    except Exception as e:
        print(f"❌ Errore API GA4: {e}")
        return pd.DataFrame()

def sync_ga4_to_sheet():
    # 1. Ottieni Dati
    df_ga4 = get_ga4_data()
    
    if df_ga4.empty:
        print("⏹️ Nessun dato da sincronizzare. Stop.")
        return

    print("📝 Preparazione scrittura su Google Sheets...")

    try:
        # 2. Auth Sheets
        info_chiave = json.loads(GOOGLE_CREDENTIALS)
        gc = gspread.service_account_from_dict(info_chiave)
        
        # 3. Apertura Foglio
        sh = gc.open_by_url(SHEET_URL)
        
        # Gestione Tab "Entrate"
        try:
            worksheet = sh.worksheet("Entrate")
            print("🧹 Pulizia foglio esistente...")
            worksheet.clear()
        except gspread.exceptions.WorksheetNotFound:
            print("✨ Creazione nuovo foglio 'Entrate'...")
            worksheet = sh.add_worksheet(title="Entrate", rows="1000", cols="10")

        # 4. Scrittura
        set_with_dataframe(worksheet, df_ga4)
        
        # Formattazione opzionale (Aggiusta larghezza colonne)
        worksheet.columns_auto_resize(0, 3)
        
        print(f"🚀 Sync completato con successo! Dati aggiornati in 'Entrate'.")

    except Exception as e:
        print(f"❌ Errore durante la scrittura su Sheets: {e}")

if __name__ == "__main__":
    sync_ga4_to_sheet()
