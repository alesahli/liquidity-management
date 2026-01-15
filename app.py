import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import BytesIO

# Configuração da Página
st.set_page_config(page_title="Gestão de Liquidez FoF - CVM 175", layout="wide")

# --- TÍTULO E SIDEBAR ---
st.title("📊 Gestão de Risco de Liquidez (FoF)")
st.sidebar.header("Configurações do Fundo")

# Inputs do Usuário
prazo_resgate_fof = st.sidebar.number_input("Prazo de Resgate do FoF (D+X)", min_value=0, value=7, step=1)
janela_ewma = st.sidebar.slider("Janela Histórica EWMA (Meses)", 1, 36, 12)
upload_file = st.sidebar.file_uploader("Upload de Histórico (Excel ou CSV)", type=['csv', 'xlsx'])

# --- FUNÇÕES DE CÁLCULO ---
def calcular_ewma(serie, span):
    return serie.ewm(span=span, adjust=False).mean()

def processar_dados(df, janela):
    df['Data'] = pd.to_datetime(df['Data'])
    df = df.sort_values('Data')
    
    # Captação Líquida e Regra ANBIMA (Min de 0 e Captação Líquida Negativa)
    df['Captacao_Liquida'] = df['Aportes_Agendados'] - df['Resgates_Brutos']
    df['Fluxo_Risco'] = df['Captacao_Liquida'].apply(lambda x: abs(x) if x < 0 else 0)
    
    # EWMA e Desvio Padrão para Estresse (99% de confiança = 2.33 DP)
    span_dias = janela * 21
    df['EWMA_Resgates'] = df['Fluxo_Risco'].ewm(span=span_dias).mean()
    df['Std_Resgates'] = df['Fluxo_Risco'].ewm(span=span_dias).std()
    df['Demanda_Estresse'] = df['EWMA_Resgates'] + (2.33 * df['Std_Resgates'])
    
    return df

# --- INTERFACE PRINCIPAL ---
if upload_file:
    if upload_file.name.endswith('.csv'):
        df_historico = pd.read_csv(upload_file)
    else:
        df_historico = pd.read_excel(upload_file)
    
    df_processado = processar_dados(df_historico, janela_ewma)
    ultimo_pl = df_processado['Patrimonio_Liquido'].iloc[-1]
    demanda_base = df_processado['Demanda_Estresse'].iloc[-1]

    # --- CADASTRO DE CARTEIRA (ATIVOS) ---
    st.subheader("📋 Carteira de Ativos Investidos")
    st.write("Insira os prazos de resgate dos fundos na sua carteira:")
    
    col1, col2 = st.columns(2)
    with col1:
        n_ativos = st.number_input("Quantidade de Ativos na Carteira", min_value=1, value=3)
    
    ativos_data = []
    for i in range(int(n_ativos)):
        c1, c2, c3 = st.columns([3, 2, 2])
        nome = c1.text_input(f"Nome do Ativo {i+1}", f"Fundo {i+1}")
        prazo = c2.number_input(f"Prazo (D+P) Ativo {i+1}", min_value=0, value=0, key=f"p{i}")
        valor = c3.number_input(f"Valor Alocado (R$)", min_value=0.0, value=ultimo_pl/n_ativos, key=f"v{i}")
        ativos_data.append({"Ativo": nome, "Prazo": prazo, "Valor": valor})
    
    df_carteira = pd.DataFrame(ativos_data)
    
    # --- LÓGICA DE VÉRTICES ---
    vertices = sorted(list(set([1, 5, 21, 42, 63, prazo_resgate_fof])))
    resultados = []

    for v in vertices:
        # Oferta: Soma ativos onde Prazo <= Vértice
        oferta = df_carteira[df_carteira['Prazo'] <= v]['Valor'].sum()
        # Demanda: Projetada para o vértice (simplificação linear do estresse diário)
        demanda_v = demanda_base * np.sqrt(v) # Raiz de T para escala de tempo de risco
        
        il = oferta / demanda_v if demanda_v > 0 else 0
        resultados.append({"Vértice": f"D+{v}", "Prazo_Num": v, "Oferta": oferta, "Demanda": demanda_v, "IL": il})

    df_il = pd.DataFrame(resultados)

    # --- DASHBOARD ---
    st.divider()
    
    # KPIs principais
    il_critico = df_il[df_il['Prazo_Num'] == prazo_resgate_fof]['IL'].values[0]
    mismatch_ativos = df_carteira[df_carteira['Prazo'] > prazo_resgate_fof]['Valor'].sum()
    perc_mismatch = (mismatch_ativos / ultimo_pl) * 100

    k1, k2, k3 = st.columns(3)
    k1.metric(f"IL no Vértice Alvo (D+{prazo_resgate_fof})", f"{il_critico:.2f}")
    k2.metric("Total Mismatch (Ativos > D+X)", f"R$ {mismatch_ativos:,.2/}", f"{perc_mismatch:.2f}%", delta_color="inverse")
    k3.metric("PL Total do Fundo", f"R$ {ultimo_pl:,.2f}")

    # Gráfico
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_il['Vértice'], y=df_il['Oferata'], name='Oferta de Liquidez (Ativo)', marker_color='royalblue'))
    fig.add_trace(go.Scatter(x=df_il['Vértice'], y=df_il['Demanda'], name='Demanda Estressada (Passivo)', line=dict(color='red', width=3)))
    fig.update_layout(title="Oferta vs Demanda Acumulada por Vértice", barmode='group')
    st.plotly_chart(fig, use_container_width=True)

    # Alertas de Conformidade
    st.subheader("⚠️ Verificação de Conformidade")
    if il_critico < 1.0:
        st.error(f"ALERTA VERMELHO: Índice de Liquidez abaixo de 1.0 no prazo D+{prazo_resgate_fof}.")
    elif il_critico < 1.2:
        st.warning(f"ALERTA AMARELO: Soft Limit atingido. IL próximo ao limite prudencial.")
    else:
        st.success("SITUAÇÃO CONFORTÁVEL: IL acima de 1.2.")

    if perc_mismatch > 25:
        st.error(f"DESENQUADRAMENTO: Mismatch de {perc_mismatch:.2f}% excede o limite de 25% do PL.")
    
    fundos_longos = df_carteira[df_carteira['Prazo'] > 30]['Ativo'].tolist()
    if fundos_longos:
        st.info(f"OBSERVAÇÃO: Existem ativos com prazo superior a D+30: {', '.join(fundos_longos)}")

    # Exportação
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_il.to_excel(writer, index=False, sheet_name='Indices_Liquidez')
        df_carteira.to_excel(writer, index=False, sheet_name='Carteira')
    st.download_button("📥 Exportar Relatório para Excel", data=output.getvalue(), file_name="relatorio_liquidez.xlsx")

else:
    st.info("Aguardando upload de arquivo para processar cálculos...")
    # Exemplo de como deve ser o arquivo
    st.write("O arquivo deve conter as colunas: `Data`, `Resgates_Brutos`, `Aportes_Agendados`, `Patrimonio_Liquido`")
