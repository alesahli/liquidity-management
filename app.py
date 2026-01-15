import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import BytesIO

# ---------- FUNÇÃO PARA GERAR TEMPLATE DE DADOS ----------
def gerar_template():
    df = pd.DataFrame({
        'Resgates_Brutos': [100000, 500000, 150000, 200000, 0],
        'Aportes_do_Dia': [50000, 0, 100000, 50000, 250000],
        'Patrimonio_Liquido': [10000000, 10100000, 9800000, 9600000, 9500000]
    })
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# ---------- SIDEBAR DE CONFIGURAÇÃO ----------
st.set_page_config(page_title="Risco de Liquidez FoF", layout="wide")
st.sidebar.header("Configurações do Sistema de Liquidez")
prazo_resgate_fof = st.sidebar.number_input("Prazo de Resgate do FoF (D+X)", min_value=1, value=7)
janela_ewma = st.sidebar.slider("Janela EWMA (Meses de histórico)", 1, 36, 12)

st.sidebar.download_button(
    "📥 Baixar Modelo de Planilha (Excel)",
    data=gerar_template(),
    file_name="modelo_dados_liquidez.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

upload_file = st.sidebar.file_uploader("📁 Upload do Histórico de Fluxos (CSV/XLSX)", type=['csv', 'xlsx'])

# ---------- CARREGAMENTO E PROCESSAMENTO DE DADOS ----------
if upload_file:
    df_hist = pd.read_csv(upload_file) if upload_file.name.endswith('.csv') else pd.read_excel(upload_file)
    df_hist.columns = [c.strip() for c in df_hist.columns]

    # Confirmação de colunas mínimas
    expected = {'Resgates_Brutos', 'Aportes_do_Dia', 'Patrimonio_Liquido'}
    if not expected.issubset(set(df_hist.columns)):
        st.error("❌ A planilha deve conter as colunas: Resgates_Brutos, Aportes_do_Dia, Patrimonio_Liquido")
        st.stop()

    # Ordem cronológica suposta
    df_hist = df_hist.reset_index(drop=True)

    # Fluxo líquido e risco
    df_hist['Fluxo_Liquido'] = df_hist['Aportes_do_Dia'] - df_hist['Resgates_Brutos']
    df_hist['Fluxo_Risco'] = df_hist['Fluxo_Liquido'].apply(lambda x: abs(x) if x < 0 else 0)

    # EWMA e desvio padrão EWMA para stress
    span = janela_ewma * 21
    df_hist['EWMA'] = df_hist['Fluxo_Risco'].ewm(span=span).mean()
    df_hist['STD'] = df_hist['Fluxo_Risco'].ewm(span=span).std().fillna(0)

    pl_total = df_hist['Patrimonio_Liquido'].iloc[-1]
    # Demanda base via EWMA + 2.33*STD
    demanda_base = df_hist['EWMA'].iloc[-1] + 2.33 * df_hist['STD'].iloc[-1]

else:
    st.info("⚠️ Sem arquivo carregado. Simule entradas manualmente.")
    pl_total = st.sidebar.number_input("Patrimônio Líquido (PL)", min_value=0.0, value=10000000.0)
    demanda_base = st.sidebar.number_input("Demanda de Stress (estimada)", min_value=0.0, value=pl_total * 0.02)

# ---------- CADASTRO DA CARTEIRA DE FUNDOS ----------
st.header("📋 Carteira de Fundos Investidos")
if "n_ativos" not in st.session_state:
    st.session_state.n_ativos = 3

if st.button("➕ Adicionar Fundo"):
    st.session_state.n_ativos += 1

ativos = []
for i in range(st.session_state.n_ativos):
    cols = st.columns([3,2,2])
    nome = cols[0].text_input(f"Nome Fundo {i+1}", f"Fundo {i+1}", key=f"nome{i}")
    prazo = cols[1].number_input(f"Prazo de Liquidez (D+)", min_value=0, value=0, key=f"prazo{i}")
    valor = cols[2].number_input(f"Valor (R$)", min_value=0.0, value=pl_total/st.session_state.n_ativos, key=f"valor{i}")
    ativos.append({"Fundo": nome, "Prazo": prazo, "Valor": valor})

df_carteira = pd.DataFrame(ativos)

# ---------- CÁLCROS DO ÍNDICE DE LIQUIDEZ ----------
st.header("📊 Análise de Liquidez e Mismatch")

vertices = sorted(set([1, 5, 21, 42, 63, prazo_resgate_fof]))

resultados = []
for v in vertices:
    oferta = df_carteira[df_carteira['Prazo'] <= v]['Valor'].sum()
    # Demanda escalada por raiz ou outro método
    demanda_v = demanda_base * np.sqrt(v)
    il = oferta / demanda_v if demanda_v > 0 else 0
    resultados.append({"Vértice": f"D+{v}", "Oferta": oferta, "Demanda": demanda_v, "IL": il})

df_il = pd.DataFrame(resultados)

# KPI: índice no prazo principal
il_fof = df_il[df_il['Vértice'] == f"D+{prazo_resgate_fof}"]['IL'].values[0]
ativos_mismatch = df_carteira[df_carteira['Prazo'] > prazo_resgate_fof]
mismatch_valor = ativos_mismatch['Valor'].sum()
mismatch_perc = (mismatch_valor / pl_total * 100) if pl_total > 0 else 0

c1, c2, c3 = st.columns(3)
c1.metric(f"IL em D+{prazo_resgate_fof}", f"{il_fof:.2f}")
c2.metric("Mismatch (ativos > prazo)", f"{mismatch_perc:.1f}%", f"R$ {mismatch_valor:,.2f}")
c3.metric("PL Total", f"R$ {pl_total:,.2f}")

# ---------- GRÁFICO DE OFERTA vs DEMANDA ----------
fig = go.Figure()
fig.add_trace(go.Bar(x=df_il['Vértice'], y=df_il['Oferta'], name="Oferta Acumulada", marker_color="#00CC96"))
fig.add_trace(go.Scatter(x=df_il['Vértice'], y=df_il['Demanda'], name="Demanda de Stress", line=dict(color="red", width=3)))
fig.update_layout(title="Oferta vs. Demanda por Vértice", barmode="group", hovermode="x unified")
st.plotly_chart(fig)

# ---------- ALERTAS VISUAIS SIMPLES ----------
if il_fof < 1.0:
    st.error(f"🚨 IL abaixo de 1.0 em D+{prazo_resgate_fof}: risco de liquidez")
elif il_fof < 1.3:
    st.warning("⚠️ IL em zona de atenção (soft limit).")
else:
    st.success("✅ IL confortável.")

if mismatch_perc > 25.0:
    st.warning("⚠️ Mismatch acima de 25% — atenção à composição da carteira de fundos.")
