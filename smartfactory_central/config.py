import os

# Segredos e Autenticação
VALID_TOKENS = {
    "NODE_01": "SF40_SECRET_TOKEN_2026_XYZ",
    "NODE_02": "SF40_SECRET_TOKEN_2026_ABC"
}

# Configurações de Rede / MQTT / HTTP
HTTP_PORT = 5000
MQTT_BROKER = "broker.hivemq.com"  # Ou IP da sua maquina local se usar Mosquitto local
MQTT_PORT = 1883
TOPIC_TELEMETRY = "smartfactory/node/+/telemetry"
TOPIC_COMMANDS = "smartfactory/node/{node_id}/commands"

# Limites Operacionais NR-12 & Manutenção Preditiva
TEMP_LIMIT = 30.0        # °C
HUM_MIN = 40.0           # %
HUM_MAX = 70.0           # %
VIB_WARNING_COUNT = 5   # N° de impactos para alerta preditivo

# Caminhos de Arquivos e Logs
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
DB_PATH = os.path.join(BASE_DIR, "dados_sensores.db")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

SECURITY_LOG = os.path.join(LOG_DIR, "seguranca.log")
ANOMALY_LOG = os.path.join(LOG_DIR, "anomalias.log")