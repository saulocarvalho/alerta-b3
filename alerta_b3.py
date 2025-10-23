from datetime import datetime
import yfinance as yf
import asyncio
import time
import datetime
import threading
from zoneinfo import ZoneInfo
import pandas as pd
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

#Configs Globais
load_dotenv()

telegram_token = os.getenv("telegram_token")
chat_id_admin = int(os.getenv("admin_chat_id"))


intevalo_monitoramento = 1200 #20 minutos

tipos_alerta = ["compra", "venda"]

#config BD - SQLite
Base = declarative_base()

class Alerta(Base):
    #Cria tabela
    __tablename__ = 'alertas' 

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False)
    tipo = Column(String, nullable=False)  # 'compra' ou 'venda'
    valor = Column(Float, nullable=False)
    chat_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime)
    disparado = Column(String, default='N')  # 'S' ou 'N'
    tkt_edt = Column(Boolean, default=False)  # Indica se o alerta foi editado

    def __repr__(self):
        return f"<Alerta(ticker='{self.ticker}', tipo='{self.tipo}', valor={self.valor})>"

#table de múltiplos usuários
class UsuarioPermitido(Base):
    __tablename__ = 'usuarios_permitidos'

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, unique=True, nullable=False)
    nome = Column(String)
    timestamp = Column(DateTime)
    ativo = Column(Boolean, default=True)  

    def __repr__(self):
        return f"<UsuarioPermitido(chat_id={self.chat_id}, nome='{self.nome}')>"

#Iniciar BD
engine = create_engine('sqlite:///alertas.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


#Funções do bot
#Verifica a existência do ativo
def ticker_existe(ticker: str) -> bool:
    try: 
        info = yf.Ticker(ticker).info
        if info and len(info) > 5:
            return True
        return False
    except Exception:
        return False

#Verifica se o usuário está autorizado
def usuario_autorizado(chat_id: int) -> bool:
    session = Session()
    existe_e_ativo = session.query(UsuarioPermitido).filter_by(chat_id=chat_id, ativo=True).first() is not None
    session.close()
    return existe_e_ativo

#Converter o ticker para o formato correto
def sanitizar_ticker(ticker: str) -> str:
    ticker = ticker.upper().strip().replace(".SA", "")
    return ticker + ".SA"

#Irá responder ao /start e mostrar o ID do usuário
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if not usuario_autorizado(user_id):
        await update.message.reply_text(f"Oxe oxe, tu não está autorizado(a) a usar esse bot não, fale com o administrador. \n\n Caso queira se cadastrar, manda teu chat ID ({user_id}) pro admin, visse.")
        return
    
    await update.message.reply_text(
        f"Olá {update.effective_user.first_name}!\n\n"
        "Seja bem-vindo(a) ao Bot de Alertas de Ativos, Meu/Minha Rei/Rainha!\n\n"
        "Para ver todos os comandos e instruções, use: **`/help`**"
    )

#Configura o alerta
async def set_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    if not usuario_autorizado(user_id):
        await update.message.reply_text("Oxe oxe, tu não está autorizado(a) a usar esse bot não, fale com o administrador.")
        return

    try:
        #coleta os dados, ex: mxrf11 compra 9.50
        ticker, tipo_alerta, valor_str = context.args

        #validações
        valor = float(valor_str)
        ticker = sanitizar_ticker(ticker)
        tipo_alerta = tipo_alerta.lower()

        if not ticker_existe(ticker):
            await update.message.reply_text(f"Opa meu/minha lídeeeer, não encontrei esse ticker não, tem certeza que {ticker} está digitado corretamente?")
            return

        if tipo_alerta not in tipos_alerta:
            await update.message.reply_text("Tipo de alerta inválido. Use 'compra' ou 'venda'.")
            return
        
        session = Session()

        #Verifica se já existe um alerta para o mesmo ticket e tipo
        alerta_existente = session.query(Alerta).filter_by(ticker=ticker, tipo=tipo_alerta, chat_id=user_id).first()

        if alerta_existente:
            #Edita o alerta caso já exista
            alerta_existente.valor = valor
            alerta_existente.disparado = 'N' #Rearmar o alerta
            alerta_existente.timestamp = datetime.datetime.now()
            alerta_existente.tkt_edt = True
            mensagem = f"Alerta **editado** para: {ticker} \nTipo: {tipo_alerta} \nNovo Valor: **R$ {valor:.2f}**"

        else:
            #Cria novo alerta
            novo_alerta = Alerta(ticker=ticker, tipo=tipo_alerta, valor=valor, chat_id=user_id, timestamp=datetime.datetime.now())
            session.add(novo_alerta)
            mensagem = f"Alerta **criado** para: {ticker} \nTipo: {tipo_alerta} \nValor: R$ {valor:.2f}"

        session.commit()
        session.close()

        await update.message.reply_text(mensagem, parse_mode='Markdown')
    
    except (ValueError, IndexError):
        await update.message.reply_text("Opa Chefe, provavelmente tem algum parametro errado. Use o comando set e depois as informações. \n\nExemplo: OIBR3 venda 3.00", 
                                        parse_mode='Markdown')
        
async def listar_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #Lista todos os alertas criados pelo usuário
    user_id = update.effective_user.id

    if not usuario_autorizado(user_id):
        await update.message.reply_text("Oxe oxe, tu não está autorizado(a) a usar esse bot não, fale com o administrador.")
        return

    session = Session()
    alertas = session.query(Alerta).filter_by(chat_id=user_id).all()
    session.close()

    if not alertas:
        await update.message.reply_text("Nenhum alerta criado até então.")
        return
    
    mensagem = "Segue seus alertas criados consagrado(a):\n\n"
    for a in alertas:
        status = "Disparado" if a.disparado == 'S' else "Ativo"
        acao = "Comprar" if a.tipo == "compra" else "Vender"

        mensagem += f"**{a.ticker}** ({acao})\n"
        mensagem += f"Valor: R$ {a.valor:.2f}\n"
        mensagem += f"Status: {status}\n"
        mensagem += "-----------------------\n"

    await update.message.reply_text(mensagem, parse_mode='Markdown')

async def remover_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #Remover alerta para um ticket e tipo
    user_id = update.effective_user.id
    
    if not usuario_autorizado(user_id):
        await update.message.reply_text("Oxe oxe, tu não está autorizado(a) a usar esse bot não, fale com o administrador.")
        return
    if context.args and context.args[0].lower() == 'all':

        query = "Maaa Rapaz, tu quer remover todos os alertas? Certeza disso? \n\n Se sim, clica no botão abaixo."

        keyboard = [
            [
            InlineKeyboardButton("❌ Cancelar", callback_data=f'RM_CANCEL_{user_id}'),
            InlineKeyboardButton("✅ Sim, Mete bala", callback_data=f'RM_ALL_CONFIRM_{user_id}'),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(query, reply_markup=reply_markup, parse_mode='Markdown')
        return
    try:
        ticker, tipos_alerta = context.args
        ticker = sanitizar_ticker(ticker)
        tipos_alerta = tipos_alerta.lower()

        session = Session()

        alerta_a_remover = session.query(Alerta).filter_by(ticker=ticker, tipo=tipos_alerta, chat_id=user_id).first()

        if alerta_a_remover:
            session.delete(alerta_a_remover)
            session.commit()
            await update.message.reply_text(f"Pronto minha Autarquia. Alerta removido para {ticker} ({tipos_alerta}).")
        else:
            await update.message.reply_text(f"Vish, Patrão(oa). Não achei nenhum alerta para {ticker} ({tipos_alerta}).")
        
        session.close()

    except (ValueError, IndexError):
        await update.message.reply_text("Opa Chefe, provavelmente tem algum parametro errado. \n\nTente assim: /rm OIBR3 venda para remover um alerta único ou /rm all para remover todos os alertas.",                                         parse_mode='Markdown')

async def confirmar_remocao_todos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query #interação do botão

    await query.answer() #responde a interação

    data = query.data
    user_id = query.from_user.id

    #ação de cada botão
    if data.startswith("RM_CANCEL_"):
        await query.edit_message_text("Cancelou a remoção geral, foi quase hein!")
        return
    
    if data.startswith("RM_ALL_CONFIRM_"):
        id_do_botao_str = data.split("_")[-1]
        if id_do_botao_str != str(user_id):
            await query.edit_message_text("Eita, esse botão não é pra você não, só quem pediu a remoção geral pode confirmar.")
            return
    
    session = Session()

    try:
        count = session.query(Alerta).filter_by(chat_id=user_id).delete(synchronize_session=False)
        session.commit()
        mensagem = f"Opa guerreiro(a), todos os seus ({count}) alertas foram removidos com sucesso."
    
    except Exception as e:
        session.rollback()
        mensagem = f"Vish, deu ruim ao tentar remover todos os alertas. Erro: {e}"
    
    finally:
        session.close()

    await query.edit_message_text(text=mensagem, parse_mode='Markdown')

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if  not usuario_autorizado(user_id):
        await update.message.reply_text("Oxe oxe, tu não está autorizado(a) a usar esse bot não, fale com o administrador.")
        return
    
    help_message = (
        "**Comandos do Bot de Alertas**\n\n"
        "**🎯 /set <TICKER> <TIPO> <VALOR>**\n"
        "  - Cria ou edita um alerta.\n"
        "  - *Exemplo:* `/set PETR4 compra 30.50`\n"
        "  - *Reativar:* Use o `/set` novamente com o mesmo ticker e tipo.\n\n"
        "**📄 /list**\n"
        "  - Lista todos os seus alertas ativos e disparados.\n\n"
        "**🗑️ /rm <TICKER> <TIPO>**\n"
        "  - Remove um alerta específico.\n"
        "  - *Exemplo:* `/rm PETR4 compra`\n\n"
        "**💣 /rm all**\n"
        "  - Remove **TODOS** os seus alertas (requer confirmação).\n\n"
        "**❓ /help**\n"
        "  - Mostra esta mensagem."
    )

    await update.message.reply_text(help_message, parse_mode='Markdown')

async def enviar_cotacoes_fechamento(context: ContextTypes.DEFAULT_TYPE) -> None:
    print("Iniciando envio de cotações de fechamento diárias...")

    session = Session()
    all_alertas = session.query(Alerta).all()
    session.close()

    if not all_alertas:
        print("Nenhum alerta cadastrado, pulando envio de cotações.")
        return

    alertas_por_usuario = {}
    tickers_para_buscar = set()
    for alerta in all_alertas:
        alertas_por_usuario.setdefault(alerta.chat_id, []).append(alerta)
        tickers_para_buscar.add(alerta.ticker)

    precos_atuais = {}

    if tickers_para_buscar:
        tickers_list = list(tickers_para_buscar)
        print(f"Buscando cotações para {len(tickers_list)} tickers...")
        
        # PRIMEIRO: Tentar método individual mais confiável
        print("Tentando método individual para cada ticker...")
        for ticker in tickers_list:
            try:
                acao = yf.Ticker(ticker)
                # Tentar várias fontes de preço
                info = acao.info
                preco_atual = (
                    info.get("regularMarketPrice") or 
                    info.get("currentPrice") or
                    info.get("previousClose") or 
                    info.get("lastPrice")
                )
                
                if preco_atual is not None and preco_atual > 0:
                    precos_atuais[ticker] = float(preco_atual)
                    print(f"✅ {ticker}: R$ {preco_atual:.2f} (método individual)")
                else:
                    # Tentar histórico diário como fallback
                    hist = acao.history(period="2d")
                    if not hist.empty and len(hist) > 0:
                        preco_atual = float(hist['Close'].iloc[-1])
                        if preco_atual > 0:
                            precos_atuais[ticker] = preco_atual
                            print(f"✅ {ticker}: R$ {preco_atual:.2f} (histórico diário)")
                        else:
                            print(f"❌ {ticker}: Preço inválido no histórico")
                    else:
                        print(f"❌ {ticker}: Sem dados disponíveis")
                        
            except Exception as e:
                print(f"❌ {ticker}: Erro no método individual - {e}")

        # SEGUNDO: Se poucos preços foram encontrados, tentar download em lote como fallback
        if len(precos_atuais) < len(tickers_list) * 0.5:  # Se menos de 50% foram encontrados
            print("Poucos preços encontrados, tentando download em lote...")
            try:
                data = yf.download(
                    tickers_list, 
                    period="1d", 
                    interval="1m", 
                    group_by='ticker', 
                    threads=True, 
                    progress=False,
                    auto_adjust=False
                )

                # Processar dados do download em lote
                if isinstance(data.columns, pd.MultiIndex):
                    for ticker in tickers_list:
                        if ticker not in precos_atuais:  # Só processar se não foi encontrado antes
                            try:
                                if (ticker, 'Close') in data.columns:
                                    close_series = data[ticker]['Close']
                                    if not close_series.empty:
                                        preco = float(close_series.iloc[-1])
                                        if preco and preco > 0 and not pd.isna(preco):
                                            precos_atuais[ticker] = preco
                                            print(f"✅ {ticker}: R$ {preco:.2f} (download lote)")
                            except Exception as e:
                                print(f"❌ {ticker}: Erro no download lote - {e}")
                
            except Exception as e:
                print(f"Erro no download em lote: {e}")

    print(f"\n📊 RESUMO: {len(precos_atuais)} de {len(tickers_list)} preços obtidos")

    # Envia as cotações para cada usuário
    for chat_id, alertas in alertas_por_usuario.items():
        # Agrupar tickers únicos do usuário
        ativos_detalhes = {}
        for alerta in alertas:
            ativos_detalhes.setdefault(alerta.ticker, []).append((alerta.tipo, alerta.valor))

        # Construir mensagem
        mensagem = "**Cotações de Fechamento B3** 📊\n"
        mensagem += f"Referência: {datetime.datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M')}\n\n"

        ativos_com_preco = []
        for ticker, detalhes in ativos_detalhes.items():
            preco = precos_atuais.get(ticker)
            if preco is not None and preco > 0 and not pd.isna(preco):
                ticker_exibicao = ticker.replace('.SA', '')
                # Adicionar emoji baseado no tipo do alerta
                emoji = "📈" if any(tipo == 'compra' for tipo, valor in detalhes) else "📉"
                if any(tipo == 'venda' for tipo, valor in detalhes):
                    emoji = "💰"
                
                mensagem += f"{emoji} **{ticker_exibicao}**: R$ {preco:.2f}\n"
                ativos_com_preco.append(ticker)

        if ativos_com_preco:
            mensagem += f"\n_Total de {len(ativos_com_preco)} ativos com cotações disponíveis_"
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=mensagem,
                    parse_mode='Markdown'
                )
                print(f"[SUCESSO DE FECHAMENTO] Mensagem com {len(ativos_com_preco)} ativos enviada para {chat_id}.")
            except Exception as e:
                print(f"[ERRO DE TELEGRAM] falha ao enviar mensagem de fechamento para {chat_id}: {e}")
        else:
            print(f"[INFO] Nenhum preço válido encontrado para o usuário {chat_id}.")
                 
#ações de amidnistrador
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #Adiciona um novo usuário autorizado (somente admin)
    user_id_admin = update.effective_user.id
    if user_id_admin != chat_id_admin:
        await update.message.reply_text("Somente o administrador pode adicionar novos usuários.")
        return
    try:
        novo_id_str, nome = context.args
        novo_id = int(novo_id_str)

        session = Session()

        novo_usuario = UsuarioPermitido(chat_id=novo_id, nome=nome, timestamp=datetime.datetime.now())
        session.add(novo_usuario)

        session.commit()
        session.close()

        await update.message.reply_text(f"Usuário {nome} com chat ID {novo_id} adicionado com sucesso.")
    
    except (ValueError, IndexError):
        await update.message.reply_text("Parâmetros inválidos. Use: /add_user <chat_id> <nome>")

async def toggle_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id_admin = update.effective_user.id
    if user_id_admin != chat_id_admin:
        await update.message.reply_text("Somente o administrador pode ativar/inativar usuários.")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("Parâmetros inválidos. Use: /toggle_user <chat_id> ativar|inativar")
        return
    
    try:
        target_id_str, status_str = context.args
        target_id_str = int(target_id_str)
        status_str = status_str.lower()

        if status_str == 'ativar':
            novo_status = True
            acao = 'ATIVADO'
        elif status_str == 'inativar':
            novo_status = False
            acao = 'INATIVADO'
        else:
            await update.message.reply_text("Status inválido. Use 'ativar' ou 'inativar'.")
            return
        
        session = Session()

        user_to_update = session.query(UsuarioPermitido).filter_by(chat_id=target_id_str).first()

        if user_to_update:
            user_to_update.ativo = novo_status
            session.commit()
            mensagem = f"Usuário com chat ID {target_id_str} foi {acao} com sucesso."
        else:   
            mensagem = f"Usuário com chat ID {target_id_str} não encontrado."

        session.close()
        await update.message.reply_text(mensagem, parse_mode='Markdown')
    
    except ValueError:
        await update.message.reply_text("O id do chat deve ser um número inteiro.")
    except Exception as e:
        await update.message.reply_text(f"Erro ao tentar atualizar o status: {e}")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id_admin = update.effective_user.id

    if user_id_admin != chat_id_admin:
        await update.message.reply_text("Somente o administrador pode listar os usuários.")
        return
    
    session = Session()
    usuarios = session.query(UsuarioPermitido).all()
    session.close()

    if not usuarios:
        await update.message.reply_text("Nenhum usuário cadastrado.")
        return
    
    mensagem = "**Usuários Cadastrados:**\n\n"
    for u in usuarios:
        status = "Ativo" if u.ativo else "Inativo"
        mensagem += f"ID: {u.chat_id}\n"
        mensagem += f"Nome: {u.nome} | Status: {status}\n"
        mensagem += "-----------------------------\n"

    await update.message.reply_text(mensagem, parse_mode='Markdown')

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id_admin = update.effective_user.id

    if user_id_admin != chat_id_admin:
        await update.message.reply_text("Somente o administrador pode acessar este comando.")
        return
    
    admin_commands_message = (
        "**Comandos de Administração (ADMIN)**\n\n"
        "👥 /add_user <ID> <Nome>\n"
        "  - Adiciona um novo usuário autorizado.\n"
        "  - *Exemplo:* `/add_user 123456789 João`\n\n"
        "📝 /list_users\n"
        "  - Lista todos os usuários cadastrados com seus IDs e status (Ativo/Inativo).\n\n"
        "⚙️ /toggle_user <ID> <ativar/inativar>\n"
        "  - Altera o status de acesso de um usuário existente.\n"
        "  - *Exemplo:* `/toggle_user 123456789 inativar`\n\n"
        "❓ /admin_help\n"
        "  - Mostra esta lista de comandos administrativos."
    )

    await update.message.reply_text(admin_commands_message, parse_mode='Markdown')

#Verificar cotações

def monitorar_cotacoes(app: Application, loop):
    #Loop que rodará em thread separada para monitorar as cotações
    print("Iniciando monitoramento de cotações 24/7")

    while True:
        try:
            session = Session()
            alertas = session.query(Alerta).all()

            if not alertas:
                session.close()
                time.sleep(intevalo_monitoramento)
                continue

            #Dicionário para agrupar tickets e não efetuar várias buscas
            tickets_para_buscar = {a.ticker for a in alertas}
            precos_atuais = {} #Salvará o ticket e o preço atual

            for ticker in tickets_para_buscar:
                try:
                    #busca a cotação mais recente
                    info = yf.Ticker(ticker).info
                    preco_atual = info.get("regularMarketPrice") #lastPrice ou close \\ são opções

                    if preco_atual is not None and preco_atual > 0:
                        precos_atuais[ticker] = preco_atual
                    
                except Exception as e:
                    print(f"Erro ao buscar cotação de {ticker}: {e}")


            #Verifica alertas
            alertas_disparados = []

            for alerta in alertas:
                preco_atual = precos_atuais.get(alerta.ticker)

                if preco_atual is None:
                    continue
                    
                #rearme   
                if alerta.disparado == 'S':
                    if alerta.tipo == 'compra' and preco_atual > alerta.valor:
                        alerta.disparado = 'N'
                        print(f"Rearmando alerta de compra para {alerta.ticker}. Está acima do alvo.")

                    elif alerta.tipo == 'venda' and preco_atual < alerta.valor:
                        alerta.disparado = 'N'
                        print(f"Rearmando alerta de venda para {alerta.ticker}. Está abaixo do alvo.")
                #Caso esteja na zona de alerta e disparado
                    if alerta.disparado == 'S':
                        continue

                if alerta.disparado == 'N':
                    if alerta.tipo == 'compra' and preco_atual <= alerta.valor:
                        assunto = f"**COMPRA** - {alerta.ticker} @ R$ {preco_atual:.2f}"
                        mensagem = f"Bora compraaaaaar, preço alvo para foi atingido! \n\nAlvo: R$ {alerta.valor:.2f} \nPreço atual: R$ {preco_atual:.2f}\n\n\nLembre-se: O alerta depois de disparado não funciona mais, caso queira reativá-lo, basta usar o /set com o mesmo ticket e tipo (compra ou venda) que ele será rearmado."

                        alertas_disparados.append((alerta.chat_id, assunto, mensagem))
                        alerta.disparado = 'S' #marca como disparado

                    elif alerta.tipo == 'venda' and preco_atual >= alerta.valor:
                        assunto = f"**VENDA** - {alerta.ticker} @ R$ {preco_atual:.2f}"
                        mensagem = f"Vamosssss seu(ua) ganancioso(a), venda! venda! venda! $$$$$ \n\n Preço alvo para foi atingido! \n\nAlvo: R$ {alerta.valor:.2f} \nPreço atual: R$ {preco_atual:.2f}\n\n\nLembre-se: O alerta depois de disparado não funciona mais, caso queira reativá-lo, basta usar o /set com o mesmo ticket e tipo (compra ou venda) que ele será rearmado."

                        alertas_disparados.append((alerta.chat_id, assunto, mensagem))  
                        alerta.disparado = 'S'

            session.commit()
            session.close()


            for chat_id, assunto, mensagem in alertas_disparados:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(
                            chat_id=chat_id, 
                            text=f"{assunto}\n\n{mensagem}", 
                            parse_mode='Markdown'
                        ),
                        loop
                    )
                    future.result(timeout=5)  # Espera a conclusão do envio
                    print(f"[SUCESSO DE ENVIO] alerta enviado para {chat_id}: {assunto}")
                
                except Exception as e:
                    print(f"[ERRO DE TELEGRAM] falha ao enviar mensagem para {chat_id}: {e}")

            #Aguardo antes da próxima verificação
            time.sleep(intevalo_monitoramento)
        
        except Exception as e:
            print(f"[ERRO GERAL] no loop de monitoramento: {e}")

            try:
                if 'session' in locals() and session.is_active:
                    session.rollback()
                    session.close()
            except:
                pass
            time.sleep(intevalo_monitoramento * 2) #espera mais tempo em caso de erro

def main() -> None:
    #configurar e inciar o bot e a thread de monitoramento
    print("Iniciando bot do Telegram...")

    application = Application.builder().token(telegram_token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("set", set_alerta))
    application.add_handler(CommandHandler("list", listar_alertas))
    application.add_handler(CommandHandler("rm", remover_alerta))
    application.add_handler(CallbackQueryHandler(confirmar_remocao_todos,pattern=r"^RM_."))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("add_user", add_user))
    application.add_handler(CommandHandler("toggle_user", toggle_user))
    application.add_handler(CommandHandler("list_users", list_users))
    application.add_handler(CommandHandler("admin_help", admin_help))
    
    #Restringir mensagens que não são comandos
    async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("E ai, minha chefia! Só aceitamos os seguintes comandos: /set, /list, /rm, /rm all")
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    #agendar job
    try:
        # Verificar se job_queue está disponível
        if hasattr(application, 'job_queue') and application.job_queue:
            application.job_queue.run_daily(
                callback=enviar_cotacoes_fechamento,
                time=datetime.time(hour=17, minute=30, second=0, tzinfo=ZoneInfo("America/Sao_Paulo")),
                name='fechamento_b3'
            )
            print("Rotina de Fechamento B3 agendada para 17:30h (Seg-Sex).")
        else:
            print("⚠️  Job queue não disponível. Rotina de fechamento não agendada.")
    except Exception as e:
        print(f"❌ Erro ao agendar job diário: {e}")
    
    loop = asyncio.get_event_loop()

    #Iniciar thread de monitoramento
    monitor_thread = threading.Thread(target=monitorar_cotacoes, args=(application, loop))
    monitor_thread.start()
    

    #Iniciar o bot
    print("Bot iniciado. Aguardando comandos...")
    application.run_polling(poll_interval=1)
      
if __name__ == "__main__":
    main()      