import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import BytesIO

# Configuração da Página
st.set_page_config(page_title="Risco de Liquidez FoF", layout="wide")

# --- FUNÇÃO PARA CRIAR TEMPLATE ---
def gerar_template():
    df = pd.DataFrame({
        'Data': pd.date_range(start='2023-01-01', periods=5),
        'Resgates_Brutos': [100000, 0, 500000, 150000, 200000],
        'Aportes_do_Dia': [50000, 200000, 0, 100000, 50000],
        'Patrimonio_Liquido': [10000000, 10150000, 9650000, 9600000, 9450000]
    })
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- SIDEBAR ---
st.sidebar.header("1. Configurações e Dados")
prazo_resgate_fof = st.sidebar.number_input("Prazo de Resgate do FoF (D+X)", min_value=0, value=7)
janela_ewma = st.sidebar.slider("Janela EWMA (Meses)", 1, 36, 12)

st.sidebar.subheader("Download de Modelo")
st.sidebar.download_button(
    label="📥 Baixar Planilha Modelo (Excel)",
    data=gerar_template(),
    file_name="modelo_dados_liquidez.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

upload_file = st.sidebar.file_uploader("Upload do Histórico", type=['csv', 'xlsx'])

# --- LOGICA DE PL E DEMANDA ---
pl_manual = 0.0
demanda_base = 0.0

if upload_file:
    df_hist = pd.read_csv(upload_file) if upload_file.name.endswith('.csv') else pd.read_excel(upload_file)
    # Ajuste de nomes de colunas para flexibilidade
    df_hist.columns = [c.strip() for c in df_hist.columns]
    
    df_hist['Data'] = pd.to_datetime(df_hist['Data'])
    df_hist = df_hist.sort_values('Data')
    
    # Cálculo de Fluxo (Regra ANBIMA)
    df_hist['Fluxo_Liquido'] = df_hist['Aportes_do_Dia'] - df_hist['Resgates_Brutos']
    df_hist['Fluxo_Risco'] = df_hist['Fluxo_Liquido'].apply(lambda x: abs(x) if x < 0 else 0)
    
    span = janela_ewma * 21
    df_hist['EWMA'] = df_hist['Fluxo_Risco'].ewm(span=span).mean()
    df_hist['STD'] = df_hist['Fluxo_Risco'].ewm(span=span).std()
    
    pl_manual = df_hist['Patrimonio_Liquido'].iloc[-1]
    demanda_base = df_hist['EWMA'].iloc[-1] + (2.33 * df_hist['STD'].fillna(0).iloc[-1])
    st.success(f"Dados carregados! PL Atual: R$ {pl_manual:,.2f}")
else:
    st.warning("⚠️ Sem histórico. Insira o PL e a Demanda estimada para simular:")
    c1, c2 = st.columns(2)
    pl_manual = c1.number_input("Patrimonio Líquido (PL) para simulação", min_value=0.0, value=10000000.0)
    demanda_base = c2.number_input("Demanda de Resgate Estimada (D+1)", min_value=0.0, value=pl_manual*0.02)

# --- SEÇÃO DA CARTEIRA ---
st.divider()
st.header("📋 2. Carteira de Ativos Investidos")
st.info("Cadastre os fundos onde o FoF investe para calcular a oferta de liquidez.")

if "n_ativos" not in st.session_state:
    st.session_state.n_ativos = 3

col_n1, col_n2 = st.columns([1, 5])
if col_n1.button("➕ Adicionar Ativo"):
    st.session_state.n_ativos += 1

ativos_data = []
for i in range(st.session_state.n_ativos):
    c1, c2, c3 = st.columns([3, 2, 2])
    nome = c1.text_input(f"Ativo {i+1}", f"Fundo Investido {i+1}", key=f"n{i}")
    prazo = c2.number_input(f"Prazo (D+P)", min_value=0, value=0, key=f"p{i}")
    valor = c3.number_input(f"Valor (R$)", min_value=0.0, value=pl_manual/st.session_state.n_ativos, key=f"v{i}")
    ativos_data.append({"Ativo": nome, "Prazo": prazo, "Valor": valor})

df_carteira = pd.DataFrame(ativos_data)

# --- CÁLCULOS FINAIS ---
st.divider()
st.header("📊 3. Análise de Risco e IL")

vertices = sorted(list(set([1, 5, 21, 42, 63, prazo_resgate_fof])))
res_list = []

for v in vertices:
    oferta = df_carteira[df_carteira['Prazo'] <= v]['Valor'].sum()
    # Escala de tempo raiz de T para demanda
    demanda_v = demanda_base * np.sqrt(v)
    il = oferta / demanda_v if demanda_v > 0 else 0
    res_list.append({"Vértice": f"D+{v}", "Prazo_Num": v, "Oferta": oferta, "Demanda": demanda_v, "IL": il})

df_il = pd.DataFrame(res_list)

# KPIs
il_alvo = df_il[df_il['Prazo_Num'] == prazo_resgate_fof]['IL'].values[0]
mismatch_r = df_carteira[df_carteira['Prazo'] > prazo_resgate_fof]['Valor'].sum()
perc_mismatch = (mismatch_r / pl_manual) * 100 if pl_manual > 0 else 0

k1, k2, k3 = st.columns(3)
k1.metric(f"IL no Prazo do FoF (D+{prazo_resgate_fof})", f"{il_alvo:.2f}")
k2.metric("Mismatch (Ativos > Prazo FoF)", f"{perc_mismatch:.1f}%", f"R$ {mismatch_r:,.2f}", delta_color="inverse")
k3.metric("PL Total", f"R$ {pl_manual:,.2f}")

# Gráfico
fig = go.Figure()
fig.add_trace(go.Bar(x=df_il['Vértice'], y=df_il['Oferta'], name='Oferta Acumulada', marker_color='#00CC96'))
fig.add_trace(go.Scatter(x=df_il['Vértice'], y=df_il['Demanda'], name='Demanda Estresse', line=dict(color='#EF553B', width=4)))
fig.update_layout(title="Cobertura de Liquidez por Vértice", barmode='group', hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

# Alertas
if il_alvo < 1.0:
    st.error(f"🚨 DESENQUADRAMENTO: O fundo não possui ativos líquidos suficientes para honrar o estresse em D+{prazo_resgate_fof}")
elif il_alvo < 1.3:
    st.warning("⚠️ ATENÇÃO: Índice de liquidez em nível de alerta (Soft Limit).")
else:
    st.success("✅ CONFORMIDADE: Os níveis de liquidez estão confortáveis.")
