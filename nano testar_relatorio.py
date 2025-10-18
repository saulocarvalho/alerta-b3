#!/usr/bin/env python3
import asyncio
import os
import sys

# Adicionar o diretório atual ao path
sys.path.append(os.path.dirname(__file__))

from alerta_b3 import enviar_cotacoes_fechamento
from telegram.ext import Application
import os
from dotenv import load_dotenv

async def testar_relatorio():
    print("🚀 Iniciando teste do relatório de fechamento...")
    
    # Carregar variáveis de ambiente
    load_dotenv()
    telegram_token = os.getenv("telegram_token")
    
    if not telegram_token:
        print("❌ ERRO: telegram_token não encontrado!")
        return
    
    # Criar application REAL para testar
    application = Application.builder().token(telegram_token).build()
    
    try:
        # Inicializar a application (simula o bot rodando)
        await application.initialize()
        
        # Criar um context válido
        class MockContext:
            def __init__(self, app):
                self.bot = app.bot
        
        context = MockContext(application)
        
        print("📊 Executando relatório de fechamento...")
        await enviar_cotacoes_fechamento(context)
        print("✅ Relatório executado com sucesso! Verifique o Telegram.")
        
    except Exception as e:
        print(f"❌ Erro durante o teste: {e}")
    finally:
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(testar_relatorio())