#!/usr/bin/env python3
"""
Script pour créer une session Telegram à utiliser sur Render
Exécutez ce script LOCALEMENT pour générer le fichier trading_session.session
"""

from telethon import TelegramClient
from dotenv import load_dotenv
import os
import asyncio

load_dotenv()

TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID'))
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')

async def create_session():
    print("=" * 60)
    print("CRÉATION DE LA SESSION TELEGRAM")
    print("=" * 60)
    print("\nCe script va créer le fichier 'trading_session.session'")
    print("que vous devrez uploader sur Render.\n")
    
    client = TelegramClient('trading_session', TELEGRAM_API_ID, TELEGRAM_API_HASH)
    
    await client.start()
    
    me = await client.get_me()
    print(f"\n Connecté en tant que: {me.first_name}")
    print(f" Numéro: {me.phone}")
    
    print("\n" + "=" * 60)
    print("SESSION CRÉÉE AVEC SUCCÈS!")
    print("=" * 60)
    print("\nFichier créé: trading_session.session")
    print("\nÉtapes suivantes:")
    print("1. Convertir le fichier en base64:")
    print("   base64 trading_session.session > session.txt")
    print("\n2. Sur Render, créer une variable d'environnement:")
    print("   TELEGRAM_SESSION = [contenu de session.txt]")
    print("\n3. Le bot utilisera automatiquement cette session")
    print("=" * 60)
    
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(create_session())
