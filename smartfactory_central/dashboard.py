import streamlit as st
import pandas as pd
import sqlite3
import requests
import time
import matplotlib.pyplot as plt
import config

st.set_page_config(page_title="SmartFactory SafeGuard 4.0", layout="wide")

st.title("🏭 SmartFactory 4.0 — Estação Central de Supervisão IIoT")

# Sidebar para envio de comandos remotos
st.sidebar.header("🕹️ Painel de Controle Remoto (NR-12)")
node_id = st.sidebar.selectbox("Selecionar Nó Industrial", ["NODE_01", "NODE_02"])

st.sidebar.subheader("Comandos Operacionais")
if st.sidebar.button("🟢 LIGAR_MAQUINA"):
    requests.post("http://localhost:5000/api/comando", json={"node_id": node_id, "comando": "LIGAR_MAQUINA"})
    st.sidebar.success("Comando enviado!")

if st.sidebar.button("🚨 DESLIGAR_EMERGENCIA"):
    requests.post("http://localhost:5000/api/comando", json={"node_id": node_id, "comando": "DESLIGAR_EMERGENCIA"})
    st.sidebar.error("Parada de Emergência Ativada!")

if st.sidebar.button("🔄 RESET_SEGURANCA (Rearme NR-12)"):
    requests.post("http://localhost:5000/api/comando", json={"node_id": node_id, "comando": "RESET_SEGURANCA"})
    st.sidebar.info("Solicitação de Rearme Enviada!")

if st.sidebar.button("📄 SOLICITAR_DIAGNOSTICO (Gerar PDF/MD)"):
    requests.post("http://localhost:5000/api/comando", json={"node_id": node_id, "comando": "SOLICITAR_DIAGNOSTICO"})
    st.sidebar.success("Relatório gerado na pasta /reports!")

# Leitura do Banco de Dados
conn = sqlite3.connect(config.DB_PATH)
df = pd.read_sql_query("SELECT * FROM leituras ORDER BY id DESC LIMIT 50", conn)
conn.close()

if not df.empty:
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values(by='id')

    # Métricas Principais (Cards)
    ultima = df.iloc[-1]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Temperatura (°C)", f"{ultima['temperatura']} °C", delta=f"{ultima['temperatura']-30:.1f} °C limite")
    col2.metric("Umidade (%)", f"{ultima['umidade']} %")
    col3.metric("Total Vibrações/Impactos", int(ultima['vibracao_impactos']))
    
    estado_cor = "🟢 OPERANDO" if ultima['estado_relé'] == 1 else "🔴 BLOQUEADO / DESLIGADO"
    col4.metric("Estado da Máquina", estado_cor)

    st.markdown("---")

    # Gráficos em Tempo Real
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.subheader("🌡️ Curva Métrica de Temperatura (°C)")
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.plot(df['timestamp'], df['temperatura'], color='red', marker='o')
        ax.axhline(30, color='darkred', linestyle='--', label='Limite Critico (30°C)')
        plt.xticks(rotation=45)
        ax.legend()
        st.pyplot(fig)

    with col_g2:
        st.subheader("🔨 Histórico de Vibração / Desgaste Mecânico")
        fig2, ax2 = plt.subplots(figsize=(6, 3))
        ax2.bar(df['timestamp'], df['vibracao_impactos'], color='orange')
        plt.xticks(rotation=45)
        st.pyplot(fig2)

    # Tabela com as últimas leituras
    st.subheader("📋 Tabela de Telemetria Recente")
    st.dataframe(df[['timestamp', 'node_id', 'temperatura', 'umidade', 'vibracao_impactos', 'chama', 'barreira_laser', 'estado_maquina']])
else:
    st.warning("Aguardando os primeiros dados de telemetria do microcontrolador...")

time.sleep(3)
st.rerun()