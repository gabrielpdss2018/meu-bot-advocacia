# Importação das bibliotecas necessárias
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import pytz

# Configuração do sistema de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 1. DADOS DO ESCRITÓRIO E CONFIGURAÇÕES ---
FIRM_DATA = {
    "advogado_principal": "Dr. Nestor da Silva Lara Junior Sena",
    "pj_razao_social": "Nestor S. Lara Junior Sociedade Individual de Advocacia",
    "pj_pix_cnpj": "47.254.343/0001-46"
}
API_BASE_URL = "https://api.z-api.io"
INSTANCE_ID = "3E43C63C3E92A12C7BB1D61DEFA5F49C"
INSTANCE_TOKEN = "DF61438D38C2ED01D31A72D0"
CLIENT_TOKEN = "F81459c6eb1ab4daba4bcc411184b9283S"
SESSION_TIMEOUT_MINUTES = 30
FORWARDING_NUMBER = "5565996290222"

SEND_TEXT_ENDPOINT = f"{API_BASE_URL}/instances/{INSTANCE_ID}/token/{INSTANCE_TOKEN}/send-text"

# --- 2. GERENCIAMENTO DE ESTADO ---
user_sessions = {}

# --- 3. FUNÇÕES AUXILIARES ---
def send_message(phone, message):
    payload = {"phone": phone, "message": message}
    headers = {"Content-Type": "application/json", "Client-Token": CLIENT_TOKEN}
    logging.info(f"Enviando mensagem para {phone}...")
    try:
        response = requests.post(SEND_TEXT_ENDPOINT, json=payload, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logging.error(f"ERRO DE HTTP AO ENVIAR MENSAGEM: {e}")

def set_user_session(phone, state, intent=None, data=None):
    now_utc = datetime.now(pytz.utc)
    if phone not in user_sessions or user_sessions[phone] is None:
        user_sessions[phone] = {'data': {}}
    session = user_sessions[phone]
    session['state'] = state
    session['last_interaction'] = now_utc
    if intent is not None:
        session['intent'] = intent
    if data:
        session['data'].update(data)
    logging.info(f"Sessão de {phone} atualizada: {session}")

def get_user_session(phone):
    session = user_sessions.get(phone)
    if not session: return None
    if (datetime.now(pytz.utc) - session['last_interaction']) > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        user_sessions.pop(phone, None)
        return None 
    return session

def forward_request_to_team(user_phone, session, user_message):
    primary_user = session.get('data', {}).get('primary_user', {})
    request_details = session.get('data', {}).get('request_details', {})
    
    owner_name = request_details.get('name', primary_user.get('name', 'N/A'))
    owner_cpf = request_details.get('cpf', primary_user.get('cpf', 'N/A'))
    
    intent_map = { 'FINANCIAL': 'Financeiro', 'CASE_LOOKUP': 'Consulta Processual', 'SCHEDULING': 'Agendamento', 'LAWYER_TALK': 'Falar com Advogado' }
    department = intent_map.get(session.get('intent'), 'Geral')

    forward_message = f"""*⚠️ Nova Solicitação Recebida via Bot ⚠️*

*Contato Original:* {user_phone}
*Nome do Solicitante:* {primary_user.get('name', 'N/A')}

*Assunto para:* {owner_name} (CPF: {owner_cpf})
*Setor:* {department}
-----------------------------------
*Detalhes da Solicitação:*
_{user_message}_"""
    send_message(FORWARDING_NUMBER, forward_message)

# --- 4. CONTEÚDO DAS MENSAGENS ---
def get_main_menu_text(user_name):
    return f"""Perfeito, {user_name}. Identificação concluída.

Como posso ajudar hoje?

*1. Financeiro*
    -> Consultas sobre Honorários
    -> Faturas 
    -> Pagamentos

*2. Consulta Processual*
    -> Verificar Andamentos
    -> Documentos
    -> Prazos

*3. Agendar Horário*
    -> Agendamento de Consultas 
    -> Reuniões

*4. Falar com o Advogado*
    -> Encaminhamento de Dúvidas 
    -> Assuntos Urgentes

A qualquer momento, digite *MENU* para voltar ou *SAIR* para encerrar."""

# --- 5. CRIAÇÃO DO SERVIDOR WEB ---
app = Flask(__name__)

# --- 6. ROTA PRINCIPAL DO WEBHOOK ---
@app.route('/webhook/onReceive', methods=['POST'])
def webhook_handler():
    try:
        data = request.get_json()
        phone = data.get('phone')
        text_info = data.get('text')
        
        if not (phone and text_info and isinstance(text_info, dict) and 'message' in text_info and not data.get('fromMe')):
            return jsonify({"status": "ignored"}), 200

        sender_phone = phone
        received_message = text_info['message'].strip()
        session = get_user_session(sender_phone)

        # Comandos Globais
        if received_message.lower() == 'sair':
            send_message(sender_phone, "Atendimento encerrado. Agradecemos o seu contato!")
            user_sessions.pop(sender_phone, None)
            return jsonify({"status": "success"}), 200

        if received_message.lower() in ['menu', 'voltar']:
            primary_user_name = session.get('data', {}).get('primary_user', {}).get('name', 'Prezado(a) Cliente')
            send_message(sender_phone, get_main_menu_text(primary_user_name.split(' ')[0]))
            set_user_session(sender_phone, state='AWAITING_MENU_CHOICE')
            return jsonify({"status": "success"}), 200
        
        # Fluxo de Início de Conversa (Identificação)
        if not session:
            greeting = "Boa tarde." if 12 <= datetime.now(pytz.timezone('America/Sao_Paulo')).hour < 18 else "Boa noite." if datetime.now(pytz.timezone('America/Sao_Paulo')).hour >= 18 else "Bom dia."
            send_message(sender_phone, f"{greeting} Bem-vindo(a) ao atendimento digital da *{FIRM_DATA['pj_razao_social']}*. Para começarmos, por favor, qual o seu *nome completo*?")
            set_user_session(sender_phone, state='AWAITING_PRIMARY_NAME')
            return jsonify({"status": "success"}), 200

        current_state = session.get('state')

        # Coleta de dados iniciais
        if current_state == 'AWAITING_PRIMARY_NAME':
            set_user_session(sender_phone, state='AWAITING_PRIMARY_CPF', data={'primary_user': {'name': received_message}})
            send_message(sender_phone, f"Obrigado, {received_message.split(' ')[0]}. Agora, por favor, informe seu *CPF* para validarmos seu cadastro.")
        
        elif current_state == 'AWAITING_PRIMARY_CPF':
            session['data']['primary_user']['cpf'] = received_message
            primary_user_name = session['data']['primary_user']['name']
            send_message(sender_phone, get_main_menu_text(primary_user_name.split(' ')[0]))
            set_user_session(sender_phone, state='AWAITING_MENU_CHOICE', data=session['data'])

        # Roteamento após escolha do menu
        elif current_state == 'AWAITING_MENU_CHOICE':
            if received_message in ['1', '2', '3', '4']:
                intent_map = {'1': 'FINANCIAL', '2': 'CASE_LOOKUP', '3': 'SCHEDULING', '4': 'LAWYER_TALK'}
                primary_user_name = session.get('data', {}).get('primary_user', {}).get('name', 'cliente')
                send_message(sender_phone, f"Entendido. A solicitação é para você, *{primary_user_name.split(' ')[0]}*, ou para um terceiro?\n\n*1.* Para mim\n*2.* Para um terceiro")
                set_user_session(sender_phone, state='AWAITING_OWNER_CONFIRM', intent=intent_map[received_message])
            else:
                send_message(sender_phone, "Opção inválida. Por favor, digite um número de 1 a 4.")

        # Confirmação se o atendimento é para o próprio usuário ou terceiro
        elif current_state == 'AWAITING_OWNER_CONFIRM':
            intent = session.get('intent')
            if received_message == '1': # Para mim
                set_user_session(sender_phone, state='AWAITING_DETAILS_FOR_SELF')
                if intent == 'FINANCIAL':
                    send_message(sender_phone, f"Certo. Por favor, descreva sua necessidade *Financeira*.\n\nLembrando, nossa chave PIX (CNPJ) para honorários é: *{FIRM_DATA['pj_pix_cnpj']}*")
                elif intent == 'CASE_LOOKUP':
                    send_message(sender_phone, "Certo. Como a consulta é para você, por favor, informe apenas o *Número do Processo*.")
                elif intent == 'SCHEDULING':
                    send_message(sender_phone, "Certo. Para o *agendamento*, por favor, informe qual o *assunto principal* a ser tratado.")
                elif intent == 'LAWYER_TALK':
                    send_message(sender_phone, f"Certo. Por favor, *resuma sua dúvida ou urgência* para encaminharmos ao *{FIRM_DATA['advogado_principal']}*.")
            elif received_message == '2': # Para um terceiro
                set_user_session(sender_phone, state='AWAITING_DETAILS_FOR_THIRD_PARTY')
                send_message(sender_phone, "Entendido. Para a solicitação do terceiro, por favor, envie as seguintes informações em uma *única mensagem*:\n\n- *Nome Completo do Terceiro:*\n- *CPF do Terceiro:*\n- *Detalhes da Solicitação:* (Ex: Número do processo, dúvida financeira, etc.)")
            else:
                send_message(sender_phone, "Opção inválida. Digite *1* se for para você ou *2* se for para um terceiro.")

        # Recebeu os detalhes finais (para si ou para terceiro)
        elif current_state in ['AWAITING_DETAILS_FOR_SELF', 'AWAITING_DETAILS_FOR_THIRD_PARTY']:
            forward_request_to_team(sender_phone, session, received_message)
            send_message(sender_phone, "Obrigado. Sua solicitação foi registrada e encaminhada para nossa equipe. Deseja realizar outra operação no menu?\n\nResponda com *Sim* ou *Não*.")
            set_user_session(sender_phone, state='AWAITING_FINAL_CONFIRMATION')

        # Confirmação final para encerrar ou voltar ao menu
        elif current_state == 'AWAITING_FINAL_CONFIRMATION':
            primary_user_name = session.get('data', {}).get('primary_user', {}).get('name', 'Prezado(a) Cliente')
            if received_message.lower() == 'sim':
                send_message(sender_phone, get_main_menu_text(primary_user_name.split(' ')[0]))
                set_user_session(sender_phone, state='AWAITING_MENU_CHOICE')
            elif received_message.lower() == 'não':
                send_message(sender_phone, "Agradecemos o contato. Sua solicitação já está com nossa equipe, que dará o retorno assim que possível.")
                set_user_session(sender_phone, state='CONVERSATION_HANDED_OFF')
            else:
                send_message(sender_phone, "Resposta não compreendida. Por favor, responda com *Sim* ou *Não*.")
        
        elif current_state == 'CONVERSATION_HANDED_OFF':
            logging.info(f"Conversa com {sender_phone} em modo manual. Ignorando.")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"ERRO CRÍTICO NO WEBHOOK: {e}", exc_info=True)
        return jsonify({"status": "error"}), 500

@app.route('/')
def index():
    return "<h1>Servidor do Bot de Advocacia (VIP) está ativo.</h1>", 200

# --- 7. EXECUÇÃO DO SERVIDOR ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)