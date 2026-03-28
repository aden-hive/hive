"""Entry point for testing the QA Engineer Agent directly."""

import asyncio
import logging
from .agent import default_agent

# Configure logging to see what the agent is doing
logging.basicConfig(level=logging.INFO)

async def main():
    print("=== Démarrage du QA Engineer Agent ===")
    
    # Message de test simulant la requête d'un utilisateur
    test_context = {
        "user_request": "Please run the automated tests in the 'test_project/' directory using 'pytest' and tell me if there are any bugs."
    }
    
    # Exécuter l'agent
    result = await default_agent.run(test_context)
    
    print("\n=== Résultat de l'exécution ===")
    if result.success:
        print("Succès !")
    else:
        print(f"Erreur : {result.error}")

if __name__ == "__main__":
    asyncio.run(main())