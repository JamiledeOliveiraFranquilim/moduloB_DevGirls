import json
import sqlite3
import logging
from datetime import datetime
import threading
from flask import Flask, request, jsonify
import paho.mqtt.client as mqtt
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

import config

# Configuração de Logging
def setup_loggers():
    sec_logger = logging.getLogger("SecurityLogger")
    sec_handler = logging.FileHandler(config.SECURITY_LOG, encoding='utf-8')
    sec_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
    sec_logger.setLevel(logging.INFO)
    sec_logger.addHandler(sec_handler)

    anom_logger = logging.getLogger("AnomalyLogger")
    anom_handler = logging.FileHandler(config.ANOMALY_LOG, encoding='utf-8')
    anom_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s'))
    anom_logger.setLevel(logging.INFO)
    anom_logger.addHandler(anom_handler)

    return sec_logger, anom_logger

sec_logger, anom_logger = setup_loggers()

# Inicialização do Banco de Dados SQLite
def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leituras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            node_id TEXT,
            temperatura REAL,
            umidade REAL,
            vibracao_impactos INTEGER,
            chama INTEGER,
            barreira_laser INTEGER,
            estado_relé INTEGER,
            estado_maquina TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# LÓGICA DE PROCESSAMENTO, SEGURANÇA E ANOMALIAS
# ---------------------------------------------------------

def validar_seguranca(payload, origem_ip_ou_topico):
    if not isinstance(payload, dict):
        msg = f"Payload inválido/não-JSON recebido de {origem_ip_ou_topico}"
        sec_logger.warning(msg)
        return False, msg

    node_id = payload.get("node_id")
    token = payload.get("token")

    if not node_id or node_id not in config.VALID_TOKENS:
        msg = f"Nó desconhecido '{node_id}' tentando conexão via {origem_ip_ou_topico}"
        sec_logger.error(msg)
        return False, msg

    if config.VALID_TOKENS.get(node_id) != token:
        msg = f"Token de autenticação inválido para o nó '{node_id}' vindo de {origem_ip_ou_topico}"
        sec_logger.error(msg)
        return False, msg

    return True, "Autenticado com Sucesso"

def processar_e_salvar_telemetria(data, origem):
    valido, motivo = validar_seguranca(data, origem)
    if not valido:
        print(f"❌ [BLOQUEIO CIBERSEGURAÇA] {motivo}")
        return False

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    node_id = data.get("node_id")
    temp = float(data.get("temperatura", 0.0))
    hum = float(data.get("umidade", 0.0))
    vib = int(data.get("vibracao_impactos", 0))
    chama = int(data.get("chama", 0))          # 1 = Detectou Chama/Faísca
    laser = int(data.get("barreira_laser", 1)) # 0 = Feixe cortado (Violação)
    rele = int(data.get("estado_rele", 0))
    estado = data.get("estado_maquina", "DESCONHECIDO")

    # Persistência no SQLite
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leituras (timestamp, node_id, temperatura, umidade, vibracao_impactos, chama, barreira_laser, estado_relé, estado_maquina)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (ts, node_id, temp, hum, vib, chama, laser, rele, estado))
    conn.commit()
    conn.close()

    # Verificação Preditiva e Deteção de Anomalias em Tempo Real
    analisar_anomalias(node_id, temp, hum, vib, chama, laser)
    print(f"✅ [TELEMETRIA REGISTRADA] [{node_id}] Temp: {temp}°C | Umid: {hum}% | Vib: {vib} | Chama: {chama} | Laser: {laser}")
    return True

def analisar_anomalias(node_id, temp, hum, vib, chama, laser):
    # 1. Violações CRÍTICAS NR-12
    if laser == 0:
        msg = f"node_id={node_id} | severidade=VIOLACAO_NR12 | sensor=BarreiraLaser | valor=CORTADO (Operador invadiu perímetro)"
        anom_logger.critical(msg)
        print(f"🚨 [ANOMALIA CRÍTICA] {msg}")

    if chama == 1:
        msg = f"node_id={node_id} | severidade=CRITICO | sensor=DetectorChama | valor=INCÊNDIO/ARCO ELÉTRICO DETECTADO"
        anom_logger.critical(msg)
        print(f"🚨 [ANOMALIA CRÍTICA] {msg}")

    # 2. Excesso de Temperatura
    if temp > config.TEMP_LIMIT:
        msg = f"node_id={node_id} | severidade=CRITICO | sensor=DHT11/DS18B20 | valor={temp}°C (Limite: {config.TEMP_LIMIT}°C)"
        anom_logger.error(msg)
        print(f"⚠️ [ANOMALIA TÉRMICA] {msg}")

    # 3. Anomalias Preditivas (Umidade & Vibração)
    if hum < config.HUM_MIN or hum > config.HUM_MAX:
        msg = f"node_id={node_id} | severidade=ALERTA | sensor=DHT11 | valor={hum}% (Faixa Ideal: {config.HUM_MIN}% - {config.HUM_MAX}%)"
        anom_logger.warning(msg)

    if vib >= config.VIB_WARNING_COUNT:
        msg = f"node_id={node_id} | severidade=ALERTA | sensor=KY-002 | valor={vib} impactos (Risco Preditivo de Desgaste Mecânico)"
        anom_logger.warning(msg)

# ---------------------------------------------------------
# RELATÓRIO PREDIATIVO DE DESEMPENHO (PDF & MARKDOWN)
# ---------------------------------------------------------

def gerar_relatorio_diagnostico(node_id="NODE_01"):
    conn = sqlite3.connect(config.DB_PATH)
    df = pd.read_sql_query("SELECT * FROM leituras WHERE node_id = ?", conn, params=(node_id,))
    conn.close()

    if df.empty:
        return "Nenhum dado encontrado para gerar o relatório."

    total_leituras = len(df)
    temp_med = df['temperatura'].mean()
    temp_max = df['temperatura'].max()
    temp_min = df['temperatura'].min()
    hum_med = df['umidade'].mean()
    total_impactos = df['vibracao_impactos'].sum()
    bloqueios_nr12 = len(df[df['barreira_laser'] == 0]) + len(df[df['chama'] == 1])
    
    # Cálculo Uptime vs Downtime
    uptime_count = len(df[df['estado_relé'] == 1])
    downtime_count = len(df[df['estado_relé'] == 0])
    uptime_pct = (uptime_count / total_leituras) * 100 if total_leituras > 0 else 0

    # Recomendações Preditivas Automáticas
    recomendacoes = []
    if temp_max > config.TEMP_LIMIT and total_impactos > 20:
        recomendacoes.append("🔴 ALERTA PREDIATIVO CRÍTICO: Alta vibração mecânica acompanhada de sobreaquecimento. Recomendada parada imediata para lubrificação e inspeção dos rolamentos da prensa.")
    elif temp_max > config.TEMP_LIMIT:
        recomendacoes.append("🟡 ALERTA TÉRMICO: Verifique o sistema de refrigeração do painel elétrico e o ambiente.")
    elif total_impactos > 30:
        recomendacoes.append("🟡 ALERTA MECÂNICO: Elevado índice de impactos/trepidação. Inspecionar alinhamento da estrutura do atuador.")
    
    if bloqueios_nr12 > 0:
        recomendacoes.append(f"⚠️ SEGURANÇA OPERACIONAL: Registraram-se {bloqueios_nr12} paradas por acionamento de barreira de segurança/chama. Treinar equipe quanto à NR-12.")
    
    if not recomendacoes:
        recomendacoes.append("🟢 OPERAÇÃO NORMAL: Equipamento operando dentro dos parâmetros ideais de confiabilidade.")

    # 1. Gerar Arquivo Markdown
    md_filename = os.path.join(config.REPORT_DIR, f"relatorio_{node_id}.md")
    with open(md_filename, "w", encoding="utf-8") as f:
        f.write(f"# 📊 Relatório Diagnóstico Preditivo SmartFactory 4.0\n")
        f.write(f"**Nó Industrial:** {node_id}  \n")
        f.write(f"**Data de Emissão:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}  \n\n")
        f.write(f"### 📈 Métricas do Processo\n")
        f.write(f"- **Temperatura (°C):** Média: {temp_med:.1f} | Máx: {temp_max:.1f} | Mín: {temp_min:.1f}\n")
        f.write(f"- **Umidade Média:** {hum_med:.1f}%\n")
        f.write(f"- **Total de Impactos/Vibração:** {total_impactos} pulsos\n")
        f.write(f"- **Bloqueios de Emergência NR-12:** {bloqueios_nr12}\n")
        f.write(f"- **Disponibilidade Operacional (Uptime):** {uptime_pct:.2f}%\n\n")
        f.write(f"### 🤖 Diagnóstico e Recomendações Preditivas (IA)\n")
        for rec in recomendacoes:
            f.write(f"- {rec}\n")

    # 2. Gerar Arquivo PDF
    pdf_filename = os.path.join(config.REPORT_DIR, f"relatorio_{node_id}.pdf")
    doc = SimpleDocTemplate(pdf_filename, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor("#003366"))
    story.append(Paragraph("SmartFactory SafeGuard 4.0 - Relatório Preditivo", title_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"<b>Nó:</b> {node_id} | <b>Gerado em:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 15))

    # Tabela de Métricas
    data_table = [
        ["Métrica Operacional", "Valor Registrado"],
        ["Temperatura Média / Máxima", f"{temp_med:.1f} °C / {temp_max:.1f} °C"],
        ["Umidade Média", f"{hum_med:.1f} %"],
        ["Total de Vibrações/Impactos", f"{total_impactos}"],
        ["Bloqueios Críticos NR-12", f"{bloqueios_nr12}"],
        ["Taxa de Disponibilidade (Uptime)", f"{uptime_pct:.1f} %"]
    ]
    t = Table(data_table, colWidths=[250, 200])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#003366")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))

    story.append(Paragraph("<b>Diagnóstico Preditivo Automático:</b>", styles['Heading2']))
    for rec in recomendacoes:
        story.append(Paragraph(f"• {rec}", styles['Normal']))
        story.append(Spacer(1, 6))

    doc.build(story)
    print(f"📄 [RELATÓRIO GERADO] PDF: {pdf_filename} | MD: {md_filename}")
    return pdf_filename

# ---------------------------------------------------------
# SERVIDOR HTTP / REST (FLASK)
# ---------------------------------------------------------

app = Flask(__name__)

@app.route('/api/telemetria', methods=['POST'])
def http_telemetria():
    data = request.get_json(force=True, silent=True)
    if not data:
        sec_logger.warning("Requisição HTTP sem payload JSON válido.")
        return jsonify({"status": "erro", "mensagem": "JSON ausente ou malformado"}), 400

    sucesso = processar_e_salvar_telemetria(data, request.remote_addr)
    if sucesso:
        return jsonify({"status": "sucesso", "mensagem": "Telemetria processada"}), 200
    else:
        return jsonify({"status": "erro", "mensagem": "Acesso negado / Falha de Cibersegurança"}), 403

@app.route('/api/comando', methods=['POST'])
def http_comando():
    data = request.get_json(force=True, silent=True)
    node_id = data.get("node_id")
    comando = data.get("comando") # LIGAR_MAQUINA, DESLIGAR_EMERGENCIA, RESET_SEGURANCA, etc.
    
    print(f"🎮 [COMANDO REMOTO ENVIADO] Node: {node_id} | Comando: {comando}")
    
    # Se usar MQTT, publica no tópico de comandos do microcontrolador
    if mqtt_client:
        topico = config.TOPIC_COMMANDS.format(node_id=node_id)
        mqtt_client.publish(topico, json.dumps({"comando": comando}))

    if comando == "SOLICITAR_DIAGNOSTICO":
        gerar_relatorio_diagnostico(node_id)

    return jsonify({"status": "sucesso", "comando_enviado": comando}), 200

# ---------------------------------------------------------
# BROKER MQTT (PAHO-MQTT)
# ---------------------------------------------------------

def on_mqtt_connect(client, userdata, flags, rc):
    print(f"📡 [MQTT] Conectado ao Broker! Código de resultado: {rc}")
    client.subscribe(config.TOPIC_TELEMETRY)

def on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        processar_e_salvar_telemetria(payload, f"MQTT Tópico: {msg.topic}")
    except Exception as e:
        sec_logger.error(f"Erro no processamento do pacote MQTT: {e}")

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

def start_mqtt():
    try:
        mqtt_client.connect(config.MQTT_BROKER, config.MQTT_PORT, 60)
        mqtt_client.loop_forever()
    except Exception as e:
        print(f"⚠️ [MQTT] Não foi possível conectar ao broker: {e}. Executando modo HTTP.")

# ---------------------------------------------------------
# EXECUÇÃO PRINCIPAL
# ---------------------------------------------------------

if __name__ == "__main__":
    print("=" * 65)
    print("🚀 ESTAÇÃO CENTRAL CYBER-PHYSICAL SMARTFACTORY SAFEGUARD 4.0")
    print("=" * 65)

    # Iniciar MQTT em Thread Separada
    t_mqtt = threading.Thread(target=start_mqtt, daemon=True)
    t_mqtt.start()

    # Iniciar Servidor REST/HTTP
    app.run(host="0.0.0.0", port=config.HTTP_PORT, debug=False)