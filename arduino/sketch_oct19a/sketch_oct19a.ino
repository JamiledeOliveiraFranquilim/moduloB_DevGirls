
#include <WiFiS3.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ===== WIFI =====
const char* WIFI_SSID = "NOME_DA_SUA_REDE";
const char* WIFI_PASSWORD = "SENHA_DA_SUA_REDE";

// ===== MQTT =====
const char* MQTT_HOST = "broker.hivemq.com";
const int MQTT_PORT = 1883;

const char* NODE_ID = "NODE_01";
const char* TOKEN = "SF40_SECRET_TOKEN_2026_XYZ";

const char* TOPICO_TELEMETRIA =
    "smartfactory/node/NODE_01/telemetry";

const char* TOPICO_COMANDOS =
    "smartfactory/node/NODE_01/commands";

// ===== PINOS =====
const int PINO_DHT = 2;
const int PINO_CHAMA = A0;
const int PINO_LDR = A1;
const int PINO_TOQUE = A2;
const int PINO_VIBRACAO = 4;
const int PINO_LASER = 5;
const int PINO_RESET = 6;

const int PINO_LED_VERDE = 7;
const int PINO_LED_AZUL = 8;
const int PINO_LED_VERMELHO = 9;
const int PINO_RELE = 10;
const int PINO_BUZZER = 12;

// ===== CONFIGURACAO DOS SENSORES =====
#define DHTTYPE DHT11

DHT dht(PINO_DHT, DHTTYPE);

const int LIMITE_CHAMA = 500;
const int LIMITE_LASER = 500;

const float TEMP_LIMITE = 30.0;
const float TEMP_REARME = 29.0;
const float UMIDADE_MIN = 40.0;
const float UMIDADE_MAX = 70.0;
const int LIMITE_VIBRACAO = 5;

// Ajuste conforme o comportamento do seu modulo.
const int VIBRACAO_ATIVA = HIGH;

// ===== REDE =====
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

// ===== ESTADO DO SISTEMA =====
float temperatura = NAN;
float umidade = NAN;

bool sensorDHTValido = false;
bool chamaDetectada = false;
bool barreiraInterrompida = false;
bool maquinaLigada = false;
bool bloqueioSeguranca = true;
bool alarmeSilenciado = false;

int quantidadeVibracoes = 0;
int ultimaLeituraVibracao = LOW;

unsigned long ultimoImpacto = 0;
unsigned long ultimaTelemetria = 0;
unsigned long ultimaLeituraDHT = 0;
unsigned long ultimaTentativaWiFi = 0;
unsigned long ultimaTentativaMQTT = 0;

const unsigned long INTERVALO_TELEMETRIA = 5000;
const unsigned long INTERVALO_DHT = 2000;
const unsigned long INTERVALO_RECONEXAO = 5000;
const unsigned long DEBOUNCE_VIBRACAO = 100;

// ===== FUNCOES AUXILIARES =====

bool temperaturaCritica() {
  return sensorDHTValido && temperatura > TEMP_LIMITE;
}

bool condicoesSeguras() {
  return sensorDHTValido &&
         !chamaDetectada &&
         !barreiraInterrompida &&
         temperatura < TEMP_REARME;
}

void desligarMaquina() {
  maquinaLigada = false;
  digitalWrite(PINO_RELE, LOW);
}

void atualizarSaidas() {
  // O rele somente e acionado quando a maquina esta liberada.
  digitalWrite(PINO_RELE, maquinaLigada ? HIGH : LOW);

  if (bloqueioSeguranca) {
    digitalWrite(PINO_LED_VERDE, LOW);
    digitalWrite(PINO_LED_AZUL, LOW);
    digitalWrite(PINO_LED_VERMELHO, HIGH);

    if (!alarmeSilenciado) {
      digitalWrite(PINO_BUZZER, HIGH);
    } else {
      digitalWrite(PINO_BUZZER, LOW);
    }
  } else if (maquinaLigada) {
    digitalWrite(PINO_LED_VERDE, HIGH);
    digitalWrite(PINO_LED_AZUL, LOW);
    digitalWrite(PINO_LED_VERMELHO, LOW);
    digitalWrite(PINO_BUZZER, LOW);
  } else {
    digitalWrite(PINO_LED_VERDE, LOW);
    digitalWrite(PINO_LED_AZUL, HIGH);
    digitalWrite(PINO_LED_VERMELHO, LOW);
    digitalWrite(PINO_BUZZER, LOW);
  }
}

void verificarSensores() {
  chamaDetectada = analogRead(PINO_CHAMA) < LIMITE_CHAMA;

  // Considera a leitura baixa como interrupcao do feixe.
  barreiraInterrompida = analogRead(PINO_LDR) < LIMITE_LASER;

  int leituraVibracao = digitalRead(PINO_VIBRACAO);
  unsigned long agora = millis();

  if (leituraVibracao == VIBRACAO_ATIVA &&
      ultimaLeituraVibracao != VIBRACAO_ATIVA &&
      agora - ultimoImpacto >= DEBOUNCE_VIBRACAO) {
    quantidadeVibracoes++;
    ultimoImpacto = agora;
  }

  ultimaLeituraVibracao = leituraVibracao;

  if (chamaDetectada ||
      barreiraInterrompida ||
      temperaturaCritica()) {
    bloqueioSeguranca = true;
    alarmeSilenciado = false;
    desligarMaquina();
  }

  atualizarSaidas();
}

void lerDHT() {
  if (millis() - ultimaLeituraDHT < INTERVALO_DHT) {
    return;
  }

  ultimaLeituraDHT = millis();

  float novaTemperatura = dht.readTemperature();
  float novaUmidade = dht.readHumidity();

  if (isnan(novaTemperatura) || isnan(novaUmidade)) {
    sensorDHTValido = false;
    bloqueioSeguranca = true;
    desligarMaquina();
    atualizarSaidas();

    Serial.println("ERRO: falha na leitura do DHT11.");
    return;
  }

  temperatura = novaTemperatura;
  umidade = novaUmidade;
  sensorDHTValido = true;

  Serial.print("Temperatura: ");
  Serial.print(temperatura);
  Serial.print(" C | Umidade: ");
  Serial.print(umidade);
  Serial.println(" %");

  if (temperaturaCritica()) {
    bloqueioSeguranca = true;
    alarmeSilenciado = false;
    desligarMaquina();
  }

  atualizarSaidas();
}

void conectarWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  if (millis() - ultimaTentativaWiFi < INTERVALO_RECONEXAO) {
    return;
  }

  ultimaTentativaWiFi = millis();

  Serial.println("Conectando ao Wi-Fi...");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void conectarMQTT() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected()) {
    return;
  }

  if (millis() - ultimaTentativaMQTT < INTERVALO_RECONEXAO) {
    return;
  }

  ultimaTentativaMQTT = millis();

  String identificacao = String(NODE_ID) + "-" +
                         String((unsigned long)millis());

  Serial.println("Conectando ao MQTT...");

  if (mqtt.connect(identificacao.c_str())) {
    Serial.println("MQTT conectado.");

    if (!mqtt.subscribe(TOPICO_COMANDOS)) {
      Serial.println("Falha ao assinar o topico de comandos.");
    }
  } else {
    Serial.print("Falha MQTT. Estado: ");
    Serial.println(mqtt.state());
  }
}

void publicarTelemetria() {
  if (!mqtt.connected() || !sensorDHTValido) {
    return;
  }

  StaticJsonDocument<384> doc;

  doc["node_id"] = NODE_ID;
  doc["token"] = TOKEN;
  doc["temperatura"] = temperatura;
  doc["umidade"] = umidade;
  doc["vibracao_impactos"] = quantidadeVibracoes;
  doc["chama"] = chamaDetectada ? 1 : 0;
  doc["barreira_laser"] = barreiraInterrompida ? 0 : 1;
  doc["estado_rele"] = maquinaLigada ? 1 : 0;
  doc["estado_maquina"] = maquinaLigada ? "LIGADA" : "DESLIGADA";

  char mensagem[384];
  size_t tamanho = serializeJson(doc, mensagem, sizeof(mensagem));

  if (tamanho > 0 &&
      mqtt.publish(TOPICO_TELEMETRIA, mensagem)) {
    Serial.print("Telemetria enviada: ");
    Serial.println(mensagem);
  } else {
    Serial.println("Falha ao publicar telemetria.");
  }

  quantidadeVibracoes = 0;
}

void processarComando(char* mensagem, unsigned int tamanho) {
  StaticJsonDocument<256> doc;

  DeserializationError erro =
      deserializeJson(doc, mensagem, tamanho);

  if (erro) {
    Serial.println("Comando recebido com JSON invalido.");
    return;
  }

  const char* node = doc["node_id"] | "";
  const char* token = doc["token"] | "";
  const char* comando = doc["comando"] | "";

  if (strcmp(node, NODE_ID) != 0 ||
      strcmp(token, TOKEN) != 0) {
    Serial.println("Comando rejeitado: identificacao invalida.");
    return;
  }

  Serial.print("Comando recebido: ");
  Serial.println(comando);

  if (strcmp(comando, "DESLIGAR_EMERGENCIA") == 0 ||
      strcmp(comando, "DESLIGAR") == 0) {
    bloqueioSeguranca = true;
    alarmeSilenciado = false;
    desligarMaquina();
  }
  else if (strcmp(comando, "LIGAR_MAQUINA") == 0) {
    if (condicoesSeguras() && !bloqueioSeguranca) {
      maquinaLigada = true;
      Serial.println("Maquina liberada para operacao.");
    } else {
      desligarMaquina();
      Serial.println("Partida negada: sistema nao liberado.");
    }
  }
  else if (strcmp(comando, "RESET_SEGURANCA") == 0) {
    if (condicoesSeguras()) {
      bloqueioSeguranca = false;
      alarmeSilenciado = false;
      Serial.println("Bloqueio rearmado.");
    } else {
      Serial.println("Rearme negado: verifique os sensores.");
    }
  }
  else if (strcmp(comando, "SILENCIAR") == 0) {
    alarmeSilenciado = true;
  }
  else if (strcmp(comando, "STATUS") == 0) {
    Serial.println("Solicitacao de status recebida.");
  }
  else {
    Serial.println("Comando desconhecido.");
  }

  atualizarSaidas();
}

void callbackMQTT(char* topico, byte* payload,
                  unsigned int tamanho) {
  if (strcmp(topico, TOPICO_COMANDOS) != 0) {
    return;
  }

  char mensagem[384];

  if (tamanho >= sizeof(mensagem)) {
    Serial.println("Comando muito grande.");
    return;
  }

  memcpy(mensagem, payload, tamanho);
  mensagem[tamanho] = '\0';

  processarComando(mensagem, tamanho);
}

void verificarBotaoReset() {
  static int leituraAnterior = HIGH;
  static unsigned long ultimaMudanca = 0;

  int leituraAtual = digitalRead(PINO_RESET);

  if (leituraAtual != leituraAnterior) {
    ultimaMudanca = millis();
    leituraAnterior = leituraAtual;
  }

  if (leituraAtual == LOW &&
      millis() - ultimaMudanca > 50) {
    if (condicoesSeguras()) {
      bloqueioSeguranca = false;
      alarmeSilenciado = false;
      Serial.println("Rearme local autorizado.");
    } else {
      Serial.println("Rearme negado: verifique os sensores.");
    }

    while (digitalRead(PINO_RESET) == LOW) {
      conectarWiFi();
      conectarMQTT();
      mqtt.loop();
      delay(10);
    }
  }

  atualizarSaidas();
}

// ===== SETUP =====

void setup() {
  Serial.begin(115200);

  pinMode(PINO_CHAMA, INPUT);
  pinMode(PINO_LDR, INPUT);
  pinMode(PINO_TOQUE, INPUT);
  pinMode(PINO_VIBRACAO, INPUT);

  pinMode(PINO_LASER, OUTPUT);
  pinMode(PINO_RESET, INPUT_PULLUP);

  pinMode(PINO_LED_VERDE, OUTPUT);
  pinMode(PINO_LED_AZUL, OUTPUT);
  pinMode(PINO_LED_VERMELHO, OUTPUT);
  pinMode(PINO_RELE, OUTPUT);
  pinMode(PINO_BUZZER, OUTPUT);

  digitalWrite(PINO_LASER, HIGH);
  digitalWrite(PINO_RELE, LOW);
  digitalWrite(PINO_BUZZER, LOW);

  dht.begin();

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(callbackMQTT);
  mqtt.setBufferSize(512);

  // Inicia bloqueado ate validar os sensores.
  bloqueioSeguranca = true;
  maquinaLigada = false;
  atualizarSaidas();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.println("SmartFactory SafeGuard 4.0 iniciado.");
  Serial.println("Maquina bloqueada ate o rearme autorizado.");
}

// ===== LOOP =====

void loop() {
  conectarWiFi();
  conectarMQTT();

  if (mqtt.connected()) {
    mqtt.loop();
  }

  lerDHT();
  verificarSensores();
  verificarBotaoReset();

  if (millis() - ultimaTelemetria >= INTERVALO_TELEMETRIA) {
    ultimaTelemetria = millis();
    publicarTelemetria();
  }

  delay(10);
}
