#!/usr/bin/env python3
"""
Script pour générer une session string Telegram pour Render
Exécutez ce script LOCALEMENT
"""

from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os
import asyncio

load_dotenv()

TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID'))
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')

async def generate_session_string():
    print("=" * 70)
    print("GÉNÉRATION DE LA SESSION STRING TELEGRAM POUR RENDER")
    print("=" * 70)
    print("\nVous allez devoir:")
    print("1. Entrer votre numéro de téléphone")
    print("2. Entrer le code de vérification reçu par SMS/Telegram")
    print("3. Copier la session string générée")
    print("4. L'ajouter comme variable d'environnement sur Render")
    print("\n" + "=" * 70 + "\n")
    
    # Create client with StringSession
    client = TelegramClient(StringSession(), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    
    await client.start()
    
    me = await client.get_me()
    print(f"\n Connecté en tant que: {me.first_name}")
    print(f" Numéro: {me.phone}")
    
    # Get the session string
    session_string = client.session.save()
    
    print("\n" + "=" * 70)
    print("SESSION STRING GÉNÉRÉE AVEC SUCCÈS!")
    print("=" * 70)
    print("\nCopiez cette session string et ajoutez-la sur Render:")
    print("\n" + "-" * 70)
    print(session_string)
    print("-" * 70)
    
    print("\n ÉTAPES POUR RENDER:")
    print("1. Allez dans votre service Render")
    print("2. Cliquez sur 'Environment'")
    print("3. Ajoutez une nouvelle variable:")
    print("   Key: TELEGRAM_SESSION")
    print("   Value: [collez la session string ci-dessus]")
    print("4. Sauvegardez et redéployez")
    print("\n" + "=" * 70)
    
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(generate_session_string())
