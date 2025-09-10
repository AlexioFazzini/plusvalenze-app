# plusvalenze_app.py
# App Streamlit per calcolare il netto incasso dopo imposte su plusvalenze (Italia)
# v1.1 – header con logo + payoff ALLINEA, FIFO lotti, commissioni, compensazione minusvalenze per bucket 12,5%/26%

import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Netto Incasso dopo Plusvalenza – Italia", page_icon="💶", layout="centered")

# ----- Header brand -----
# Mostra il logo se presente (senza PIL, così non servono dipendenze extra)
try:
    st.image("logo.png", width=180)
except Exception:
    pass

st.markdown("### ALLINEA – Il tuo punto fermo nei momenti che contano")
st.caption("by Alexio Fazzini, Consulente Finanziario")

st.title("💶 Netto incasso dopo vendita (Italia)")
st.caption("Calcola quanto **incassi davvero** dalla vendita di un titolo dopo imposte sulle plusvalenze, con compensazione perdite dove applicabile.")

with st.expander("📌 Istruzioni rapide", expanded=True):
    st.markdown("""
    **Come funziona**  
    1) Inserisci i tuoi **lotti di acquisto** nella tabella (puoi aggiungere righe).  
    2) Inserisci i dettagli della **vendita** (quantità, prezzo, commissione).  
    3) Scegli la **categoria fiscale** del titolo venduto:  
       - *Titoli di Stato italiani/UE, white list e sovranazionali UE* → **12,5%**  
       - *Altri strumenti (azioni, ETF/ETC non governativi, obbligazioni corporate, ecc.)* → **26%**  
    4) (Opzionale) Inserisci eventuali **minusvalenze pregresse** disponibili **nello stesso bucket fiscale** della vendita.  
    5) Ottieni **plus/minusvalenza**, **imposta**, **netto incasso** e il residuo di minusvalenze (o la nuova minusvalenza da riportare).

    **Assunzioni principali (v1.1):**
    - Metodo **FIFO** per l'abbinamento tra lotti di acquisto e quantità vendute.  
    - Le **commissioni** di acquisto e vendita sono incluse nel calcolo del costo fiscale (ripartite pro-quota).  
    - Prezzi **clean/dirty** e **ratei** non sono trattati separatamente: inserisci i prezzi coerenti con l'estratto conto fiscale.  
    - La **compensazione** usa solo minusvalenze del **medesimo bucket fiscale** (12,5% o 26%), fino a capienza del realizzo positivo.
    """)

st.subheader("1) Categoria fiscale del titolo venduto")
bucket = st.radio(
    "Scegli la categoria fiscale valida **per questo titolo**",
    options=["12,5% – Titoli di Stato/sovranazionali UE/white list", "26% – Altri strumenti"],
    index=1,
    help="La tassazione standard in Italia è 12,5% per Titoli di Stato italiani/UE (white list) e sovranazionali UE; 26% per la maggior parte degli altri strumenti."
)

tax_rate = 0.125 if bucket.startswith("12,5%") else 0.26

st.subheader("2) Lotti di acquisto (FIFO)")
st.caption("Inserisci uno o più lotti. La quantità venduta verrà imputata ai lotti in ordine cronologico (FIFO). Le commissioni di acquisto vengono ripartite pro-quota sulla quantità venduta.")

default_rows = pd.DataFrame([
    {"Data": "", "Quantità": 100, "Prezzo di acquisto": 10.00, "Commissione acquisto": 0.00},
])
df = st.data_editor(
    default_rows,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Data": st.column_config.TextColumn(help="Formato libero. Facoltativo. Usato solo per ordinare se compilato."),
        "Quantità": st.column_config.NumberColumn(min_value=0, step=1, help="Pezzi acquistati in questo lotto."),
        "Prezzo di acquisto": st.column_config.NumberColumn(min_value=0.0, format="%.4f", help="Prezzo unitario di acquisto."),
        "Commissione acquisto": st.column_config.NumberColumn(min_value=0.0, format="%.4f", help="Commissione associata all'intero lotto."),
    },
    key="purchase_table"
)

# Parse e ordina per data (FIFO)
def _parse_date(x):
    x = str(x).strip()
    if not x:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(x, fmt)
        except:
            continue
    return None

df["parsed_date"] = df["Data"].apply(_parse_date)
df["order_key"] = df["parsed_date"].fillna(pd.Timestamp.min)
df = df.sort_values(by=["order_key"]).reset_index(drop=True)

st.subheader("3) Dettagli di vendita")
col1, col2 = st.columns(2)
with col1:
    sell_qty = st.number_input("Quantità **venduta**", min_value=0, step=1, value=100, help="Numero di pezzi venduti.")
    sell_price = st.number_input("Prezzo di **vendita** unitario", min_value=0.0, value=12.00, format="%.4f")
with col2:
    sell_comm = st.number_input("Commissione di vendita (totale)", min_value=0.0, value=0.00, format="%.4f")
    sell_date = st.text_input("Data vendita (facoltativa)", value="")

st.subheader("4) Minusvalenze pregresse **disponibili** nello stesso bucket")
available_losses = st.number_input(
    "Minusvalenze pregresse **utilizzabili** (stesso bucket fiscale)", 
    min_value=0.0, value=0.0, step=100.0, format="%.2f",
    help="Inserisci l'importo delle minusvalenze residue del **medesimo bucket** (12,5% o 26%) che vuoi usare per compensare l'eventuale plusvalenza."
)

# --- Core FIFO & tax logic ---

# Validazione quantità disponibili
total_holdings = (df["Quantità"].fillna(0).astype(float)).sum()
if sell_qty > total_holdings:
    st.error(f"Quantità venduta ({sell_qty}) superiore alla quantità detenuta ({int(total_holdings)}). Riduci la quantità venduta o aggiorna i lotti di acquisto.")
    st.stop()

# Crea coda FIFO
lots = []
for _, row in df.iterrows():
    qty = int(row.get("Quantità", 0) or 0)
    price = float(row.get("Prezzo di acquisto", 0.0) or 0.0)
    comm = float(row.get("Commissione acquisto", 0.0) or 0.0)
    if qty <= 0:
        continue
    lots.append({
        "date": row.get("Data", ""),
        "qty": qty,
        "unit_cost": price,
        "lot_commission": comm
    })

# Alloca vendita sui lotti (FIFO) con riparto commissioni pro-quota
remaining = sell_qty
matched_rows = []
for lot in lots:
    if remaining <= 0:
        break
    take = min(remaining, lot["qty"])
    lot_comm_alloc = (lot["lot_commission"] * (take / lot["qty"])) if lot["qty"] else 0.0
    matched_rows.append({
        "lot_date": lot["date"],
        "qty_sold_from_lot": take,
        "unit_cost": lot["unit_cost"],
        "comm_allocated": lot_comm_alloc,
        "cost_basis_for_chunk": take * lot["unit_cost"] + lot_comm_alloc
    })
    remaining -= take

# Costo fiscale aggregato
total_cost_basis = sum(r["cost_basis_for_chunk"] for r in matched_rows)

# Proventi e P/L
gross_sale = sell_qty * sell_price
net_before_tax = gross_sale - sell_comm  # commissioni riducono il provento
realized_pnl = net_before_tax - total_cost_basis

# Compensazione minusvalenze (solo se plusvalenza)
loss_used = 0.0
taxable_gain = 0.0
if realized_pnl > 0:
    loss_used = min(realized_pnl, available_losses)
    taxable_gain = realized_pnl - loss_used
    tax_due = taxable_gain * tax_rate
else:
    tax_due = 0.0

# Netto incasso dopo imposte
net_cash = net_before_tax - (tax_due if tax_due > 0 else 0.0)

# Residuo minusvalenze o nuova minusvalenza
if realized_pnl > 0:
    residual_losses = available_losses - loss_used
    new_carry_loss = 0.0
else:
    residual_losses = available_losses
    new_carry_loss = abs(realized_pnl)

# --- Output ---
st.subheader("✅ Risultati")
colA, colB = st.columns(2)
with colA:
    st.metric("Provento lordo vendita", f"€ {gross_sale:,.2f}")
    st.metric("Commissione vendita", f"€ {sell_comm:,.2f}")
    st.metric("Costo fiscale complessivo allocato (FIFO)", f"€ {total_cost_basis:,.2f}")
with colB:
    st.metric("Plus/Minusvalenza **prima** di compensazione", f"€ {realized_pnl:,.2f}")
    st.metric("Minusvalenze **utilizzate** in compensazione", f"€ {loss_used:,.2f}")
    st.metric(f"Imposta dovuta ({int(tax_rate*100)}%)", f"€ {tax_due:,.2f}")

st.success(f"**Netto incasso dopo imposte**: **€ {net_cash:,.2f}**")

with st.expander("📄 Dettaglio imputazione FIFO per lotto"):
    st.dataframe(pd.DataFrame(matched_rows))

with st.expander("ℹ️ Stato minusvalenze / note fiscali"):
    if realized_pnl > 0:
        st.write(f"- Residuo **minusvalenze disponibili** (stesso bucket) dopo la compensazione: **€ {residual_losses:,.2f}**")
    else:
        st.write(f"- **Nuova minusvalenza** generata (stesso bucket): **€ {new_carry_loss:,.2f}**")
    st.markdown("""
    **Promemoria operativo (non consulenza fiscale):**
    - Le minusvalenze si possono **riportare** entro i termini di legge (in genere fino a 4 anni), **solo nello stesso bucket fiscale**.  
    - In regime **amministrato**, la compensazione avviene presso l'intermediario.  
    - In regime **dichiarativo**, l'utilizzo avviene in dichiarazione, nei limiti e con le regole vigenti.  
    - Gestisci **clean/dirty price** e **ratei** coerenti con gli estratti conto fiscali.
    """)

st.divider()
st.caption("v1.1 — Strumento informativo. Verifica sempre i conteggi con l'estratto fiscale dell'intermediario e con il consulente fiscale.")
