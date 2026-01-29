import os
import json
import pandas as pd
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest
)
import gspread
from gspread_dataframe import set_with_dataframe

# --- CONFIGURAZIONE GA4 ---
PROPERTY_ID = "IL_TUO_PROPERTY_ID" # Inseriscilo nei Secrets
GOOGLE_CREDENTIALS = os.environ.get("GCP_SA_KEY")
SHEET_URL = "https://docs.google.com/spreadsheets/d/1eIojQyXLuC1FO89ZGcswy4s8AgFX3xc1UuheFFgM6Kk/edit?gid=1248846582#gid=1248846582"

def get_ga4_report():
    print("⏳ Estrazione dati da GA4...")
    info_chiave = json.loads(GOOGLE_CREDENTIALS)
    client = BetaAnalyticsDataClient.from_service_account_info(info_chiave)

    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name="itemId")],
        metrics=[Metric(name="itemRevenue"), Metric(name="itemsPurchased")],
        date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
    )

    response = client.run_report(request)
    
    data = []
    for row in response.rows:
        data.append({
            "Sku": row.dimension_values[0].value,
            "Entrate": float(row.metric_values[0].value),
            "Vendite": int(row.metric_values[1].value)
        })
    
    return pd.DataFrame(data)

def sync_ga4_to_sheet():
    df_ga4 = get_ga4_report()
    if df_ga4.empty: return

    # Auth Google Sheets
    info_chiave = json.loads(GOOGLE_CREDENTIALS)
    gc = gspread.service_account_from_dict(info_chiave)
    sh = gc.open_by_url(SHEET_URL)
    
    # Crea o pulisce il foglio "Entrate"
    try:
        worksheet = sh.worksheet("Entrate")
        worksheet.clear()
    except:
        worksheet = sh.add_worksheet(title="Entrate", rows="1000", cols="5")

    set_with_dataframe(worksheet, df_ga4)
    print(f"✅ GA4 Sync completato: {len(df_ga4)} SKU aggiornati.")

if __name__ == "__main__":
    sync_ga4_to_sheet()
