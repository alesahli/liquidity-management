import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import BytesIO

# -----------------------------------
# FUNÇÃO PARA GERAR MODELO DE DADOS
# -----------------------------------
def gerar_template():
    df = pd.DataFrame({
        "Resgates_Brutos": [100000, 0, 500000, 150000, 200000],
        "Aportes_do_Dia": [50000, 200000, 0, 100000, 50000],
        "Patrimonio_Liquido": [10000000, 10100000, 9800000, 9600000, 9500000]
    })
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# -----------------------------------
# SIDEBAR - CONFIGURAÇÕES
# -----------------------------------
st.set_page_config(page_title="Risco de Liquidez FoF", layout="wide")

st.sidebar.header("Configurações de Liquidez")
prazo_resgate_fof = st.sidebar.number_input("Prazo de Resgate do FoF (D+X)", min_value=1, value=7)
janela_hist = st.sidebar.slider("Janela Histórica (dias para stress)", min_value=21, max_value=252, value=60, step=1)

st.sidebar.download_button(
    "📥 Baixar Modelo de Planilha (Excel)",
    data=gerar_template(),
    file_name="modelo_dados_liquidez.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

upload_file = st.sidebar.file_uploader("Upload CSV/XLSX (Histórico)", type=["csv", "xlsx"])

# -----------------------------------
# CARREGAMENTO E PROCESSAMENTO DOS DADOS
# -----------------------------------
if upload_file:
    df_hist = pd.read_csv(upload_file) if upload_file.name.endswith(".csv") else pd.read_excel(upload_file)
    df_hist.columns = [c.strip() for c in df_hist.columns]

    required_cols = {"Resgates_Brutos", "Aportes_do_Dia", "Patrimonio_Liquido"}
    if not required_cols.issubset(df_hist.columns):
        st.error("A planilha deve conter as colunas: Resgates_Brutos, Aportes_do_Dia e Patrimonio_Liquido")
        st.stop()

    st.success("Dados carregados com sucesso!")

    # Cálculo de fluxos
    df_hist["Fluxo_Liquido"] = df_hist["Aportes_do_Dia"] - df_hist["Resgates_Brutos"]
    df_hist["Fluxo_Risco"] = df_hist["Fluxo_Liquido"].apply(lambda x: abs(x) if x < 0 else 0)

    # O PL mais recente agora está na linha 0
    pl_total = df_hist["Patrimonio_Liquido"].iloc[0]

else:
    st.warning("⚠️ Sem histórico carregado — dados simulados serão usados.")
    pl_total = st.sidebar.number_input("PL (R$) para simulação", value=10000000.0)
    df_hist = None

# -----------------------------------
# FUNÇÃO DE DEMANDA ESTRESSADA (LINHA 0 COMO MAIS RECENTE)
# -----------------------------------
def demanda_estressada(historico, v):
    """
    Para um horizonte v em dias, calcula o percentil 99 da soma acumulada de resgates negativos
    em janelas que começam na linha mais recente (índice 0) e vão para datas mais antigas.
    """
    if historico is None or len(historico) < v:
        return 0.0

    risco = historico["Fluxo_Risco"].values
    rolling_sums = []
    for start in range(0, len(risco) - v + 1):
        window_sum = risco[start : start + v].sum()
        rolling_sums.append(window_sum)

    if len(rolling_sums) == 0:
        return 0.0
    return float(np.percentile(rolling_sums, 99))

vertices = sorted(list({1, 5, 21, 42, 63, prazo_resgate_fof}))
demanda_por_vertice = {v: demanda_estressada(df_hist, v) for v in vertices}

# -----------------------------------
# SEÇÃO DE CARTEIRA DE FUNDOS
# -----------------------------------
st.header("📋 Carteira de Fundos Investidos")

if "n_ativos" not in st.session_state:
    st.session_state.n_ativos = 3

if st.button("➕ Adicionar Fundo"):
    st.session_state.n_ativos += 1

ativos = []
for i in range(st.session_state.n_ativos):
    c1, c2, c3 = st.columns([3, 2, 2])
    nome = c1.text_input(f"Nome Fundo {i+1}", f"Fundo {i+1}", key=f"nome{i}")
    prazo = c2.number_input(f"Prazo de Liquidez (D+)", min_value=0, value=0, key=f"prazo{i}")
    valor = c3.number_input(f"Valor (R$)", min_value=0.0, value=pl_total/st.session_state.n_ativos, key=f"valor{i}")
    ativos.append({"Fundo": nome, "Prazo": prazo, "Valor": valor})

df_carteira = pd.DataFrame(ativos)

# -----------------------------------
# CÁLCULO DO ÍNDICE DE LIQUIDEZ (IL), DEMANDA E OFERTA
# -----------------------------------
resultados = []
for v in vertices:
    oferta = df_carteira[df_carteira["Prazo"] <= v]["Valor"].sum()
    demanda_v = demanda_por_vertice.get(v, 0.0)
    il_v = oferta / demanda_v if demanda_v > 0 else np.nan
    resultados.append({
        "Vértice": f"D+{v}",
        "Oferta": oferta,
        "Demanda_Estressada": demanda_v,
        "IL": il_v
    })

df_il = pd.DataFrame(resultados)

# -----------------------------------
# KPI PRINCIPAIS MÉTRICAS
# -----------------------------------
il_fof = df_il[df_il["Vértice"] == f"D+{prazo_resgate_fof}"]["IL"].values[0]
mismatch_val = df_carteira[df_carteira["Prazo"] > prazo_resgate_fof]["Valor"].sum()
mismatch_perc = (mismatch_val / pl_total * 100) if pl_total > 0 else 0

k1, k2, k3 = st.columns(3)
k1.metric(f"IL em D+{prazo_resgate_fof}", f"{il_fof:.2f}" if not np.isnan(il_fof) else "N/A")
k2.metric("Mismatch (> prazo FoF %)", f"{mismatch_perc:.1f}%")
k3.metric("PL Total (R$)", f"{pl_total:,.2f}")

# -----------------------------------
# GRÁFICO: OFERTA VS. DEMANDA
# -----------------------------------
fig = go.Figure()
fig.add_trace(go.Bar(x=df_il["Vértice"], y=df_il["Oferta"],
                     name="Oferta Acumulada", marker_color="#00CC96"))
fig.add_trace(go.Scatter(x=df_il["Vértice"], y=df_il["Demanda_Estressada"],
                         name="Demanda Estressada", line=dict(color="red", width=3)))
fig.update_layout(title="Cobertura de Liquidez por Vértice",
                  barmode="group", hovermode="x unified")
st.plotly_chart(fig)

# -----------------------------------
# ALERTAS (CONSERVADORES)
# -----------------------------------
if not np.isnan(il_fof):
    if il_fof < 1.0:
        st.error(f"🚨 Risco: IL < 1 em D+{prazo_resgate_fof}")
    elif il_fof < 1.25:
        st.warning("⚠️ IL em zona de atenção (soft limit).")
    else:
        st.success("✅ IL confortável.")

if mismatch_perc > 25:
    st.warning("⚠️ Mismatch > 25% do PL — revisar carteira.")
