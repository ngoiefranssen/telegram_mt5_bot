#!/usr/bin/env python3
"""
Convertir une session existante en session string pour Render
"""

from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os
import asyncio

load_dotenv()

TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID'))
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')

async def convert_session():
    print("=" * 70)
    print("CONVERSION DE LA SESSION EXISTANTE EN SESSION STRING")
    print("=" * 70)
    
    # Load existing session file
    client = TelegramClient('trading_session', TELEGRAM_API_ID, TELEGRAM_API_HASH)
    
    await client.connect()
    
    if not await client.is_user_authorized():
        print("\n❌ La session existante n'est pas valide ou expirée")
        print("Utilisez generate_session_string.py pour créer une nouvelle session")
        await client.disconnect()
        return
    
    me = await client.get_me()
    print(f"\n✅ Session valide!")
    print(f"✅ Connecté en tant que: {me.first_name}")
    print(f"✅ Numéro: {me.phone}")
    
    # Convert to StringSession
    session_string = StringSession.save(client.session)
    
    print("\n" + "=" * 70)
    print("SESSION STRING GÉNÉRÉE AVEC SUCCÈS!")
    print("=" * 70)
    print("\nCopiez cette session string et ajoutez-la sur Render:")
    print("\n" + "-" * 70)
    print(session_string)
    print("-" * 70)
    
    print("\n📋 ÉTAPES POUR RENDER:")
    print("1. Allez dans votre service Render")
    print("2. Cliquez sur 'Environment'")
    print("3. Ajoutez une nouvelle variable:")
    print("   Key: TELEGRAM_SESSION")
    print("   Value: [collez la session string ci-dessus]")
    print("4. Sauvegardez et redéployez")
    print("\n" + "=" * 70)
    
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(convert_session())
