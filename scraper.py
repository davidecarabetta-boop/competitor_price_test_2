import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import gspread
import os
import json
from gspread_dataframe import set_with_dataframe

# --- 1. CONFIGURAZIONE ---
XML_FEED_URL = "https://feeds.datafeedwatch.com/62653/5de2db28bf341d54bffbab7e2af0711a40c1d189.xml"
MERCHANT_ID = "sensationprofumerie"
API_KEY = os.environ.get("TP_API_KEY") 
SHEET_URL = "https://docs.google.com/spreadsheets/d/1eIojQyXLuC1FO89ZGcswy4s8AgFX3xc1UuheFFgM6Kk/edit#gid=0"
GOOGLE_CREDENTIALS = os.environ.get("GCP_SA_KEY")
BASE_URL = "https://services.7pixel.it/api/v1/"

LIMITE_PRODOTTI = 500  # <--- SETTATO A 500 COME RICHIESTO
LIMITE_COMPETITOR = 5

# --- 2. FUNZIONE LETTURA XML CON LIMITE ---
def get_xml_products(url, limit):
    print(f"Lettura feed XML (limite {limit} prodotti)...")
    try:
        response = requests.get(url)
        root = ET.fromstring(response.content)
        products_info = []
        items = root.findall('.//item') or root.findall('.//product')

        for product in items:
            p_id = (product.findtext('id') or 
                    product.findtext('{http://base.google.com/ns/1.0}id'))
            p_title = (product.findtext('title') or 
                       product.findtext('{http://base.google.com/ns/1.0}title'))

            if p_id or p_title:
                products_info.append({
                    'id': str(p_id).strip() if p_id else None,
                    'title': str(p_title).strip() if p_title else None
                })
            
            if len(products_info) >= limit:
                break
                
        print(f"Presi {len(products_info)} prodotti dal feed.")
        return products_info
    except Exception as e:
        print(f"Errore XML: {e}")
        return []

# --- 3. ESPANSIONE COMPETITOR ---
def espandi_competitor(df, num_comp):
    rows = []
    for _, row in df.iterrows():
        dati = row.to_dict()
        dati['Sensation_Prezzo'] = dati.get('Price', 0)
        dati['Sensation_Posizione'] = dati.get('Position', '-')
        dati['Rank'] = dati.get('Rank', '-')
        
        offers = dati.pop('BestOffers', [])

        for i in range(1, num_comp + 1):
            if isinstance(offers, list) and len(offers) >= i:
                dati[f'Comp_{i}_Nome'] = offers[i-1].get('Merchant', '-')
                dati[f'Comp_{i}_Prezzo'] = offers[i-1].get('Price', 0)
            else:
                dati[f'Comp_{i}_Nome'] = "-"
                dati[f'Comp_{i}_Prezzo'] = "-"

        col_ordine = ['Data_Esecuzione', 'Product', 'Sku', 'Rank', 'Sensation_Prezzo', 'Sensation_Posizione'] + \
                     [c for c in dati.keys() if 'Comp_' in c]
        
        rows.append({k: dati.get(k, "-") for k in col_ordine})
    
    return pd.DataFrame(rows)

# --- 4. LOGICA DI SINCRONIZZAZIONE ---
def sync_data():
    if not GOOGLE_CREDENTIALS or not API_KEY:
        print("Errore: Credenziali mancanti nei Secrets di GitHub!")
        return

    # Autenticazione Google
    info_chiave = json.loads(GOOGLE_CREDENTIALS)
    gc = gspread.service_account_from_dict(info_chiave)
    sheet = gc.open_by_url(SHEET_URL).sheet1

    # Caricamento Prodotti
    prodotti_xml = get_xml_products(XML_FEED_URL, LIMITE_PRODOTTI)
    if not prodotti_xml: return
    
    lista_id_xml = [p['id'] for p in prodotti_xml if p['id']]
    lista_titoli_xml = [p['title'] for p in prodotti_xml if p['title']]

    # API Trovaprezzi: Token
    url_token = f"{BASE_URL}TemporaryToken?merchantid={MERCHANT_ID.lower()}&merchantkey={API_KEY}"
    token_resp = requests.get(url_token).json()
    token = token_resp.get("Token")
    
    # API Trovaprezzi: Dati
    url_data = f"{BASE_URL}OffersRanking?merchantid={MERCHANT_ID.lower()}&token={token}&format=json"
    df_tp = pd.DataFrame(requests.get(url_data).json())

    # Matching
    mask_id = df_tp['Sku'].astype(str).isin(lista_id_xml)
    mask_titolo = df_tp['Product'].astype(str).isin(lista_titoli_xml)
    df_filtrato = df_tp[mask_id | mask_titolo].drop_duplicates(subset=['Product']).copy()

    if df_filtrato.empty:
        print("Nessun match trovato.")
        return

    ora_attuale = datetime.now().strftime("%d/%m/%Y %H:%M")
    df_filtrato.insert(0, 'Data_Esecuzione', ora_attuale)
    df_finale = espandi_competitor(df_filtrato, LIMITE_COMPETITOR)

    # Scrittura su Google Sheets (Append)
    esistenti = sheet.get_all_values()
    riga_inizio = len(esistenti) + 1
    # Se il foglio è vuoto o ha solo l'intestazione, decidi se metterla
    includi_header = True if riga_inizio <= 1 else False
    
    set_with_dataframe(sheet, df_finale, row=riga_inizio, include_column_header=includi_header)
    print(f"Operazione completata. Salvati {len(df_finale)} prodotti.")

if __name__ == "__main__":
    sync_data()
