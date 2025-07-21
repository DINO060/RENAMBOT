# 🎯 Système de Limites et Nettoyage Automatique

## 📊 Limites d'Utilisation

### Limite Quotidienne
- **1 GB par jour** par utilisateur
- Reset automatique à minuit (00:00)
- Suivi en temps réel de l'utilisation

### Délai entre Fichiers
- **30 secondes** de cooldown entre chaque fichier
- Évite le spam et protège les ressources

## 🔧 Nouvelles Commandes

### `/usage`
Affiche les statistiques d'utilisation de l'utilisateur :
- Utilisation quotidienne actuelle
- Limite restante
- Barre de progression visuelle
- Prochain reset

### `/cleanup` (Admin seulement)
Nettoie tous les fichiers d'un utilisateur :
- Supprime les fichiers temporaires
- Préserve les thumbnails
- Nettoyage des sessions

## 🗂️ Gestion des Fichiers

### Nettoyage Automatique
- **Toutes les heures** : Nettoyage des fichiers orphelins
- **Après chaque 1GB** : Nettoyage silencieux des fichiers utilisateur
- **Sessions expirées** : Nettoyage automatique après 10 minutes

### Fichiers Préservés
- ✅ Thumbnails personnalisés
- ✅ Données d'utilisation
- ✅ Sessions actives

### Fichiers Supprimés
- ❌ Fichiers temporaires orphelins (>1 heure)
- ❌ Sessions expirées
- ❌ Fichiers de traitement terminés

## 📈 Suivi d'Utilisation

### Stockage
- Données sauvegardées dans `user_usage.json`
- Persistance entre les redémarrages
- Format JSON lisible

### Métriques
- Taille totale utilisée par jour
- Nombre de fichiers traités
- Dernière activité
- Historique des resets

## 🛡️ Sécurité

### Protection contre les Abus
- Limite de débit par utilisateur
- Vérification des limites avant traitement
- Messages d'erreur informatifs

### Gestion des Erreurs
- Logging détaillé des opérations
- Récupération automatique en cas d'erreur
- Nettoyage en cas de crash

## ⚙️ Configuration

### Variables Modifiables
```python
DAILY_LIMIT_GB = 1  # Limite quotidienne en GB
COOLDOWN_SECONDS = 30  # Délai entre fichiers
USER_TIMEOUT = 600  # Timeout session (10 min)
```

### Fichiers de Données
- `user_usage.json` : Données d'utilisation
- `temp_files/` : Fichiers temporaires
- `thumbnails/` : Miniatures utilisateur

## 🚀 Utilisation

1. **Envoi de fichier** : Vérification automatique des limites
2. **Traitement** : Mise à jour de l'utilisation après succès
3. **Nettoyage** : Suppression automatique des fichiers temporaires
4. **Suivi** : Commande `/usage` pour vérifier les limites

## 📝 Logs

Le système génère des logs détaillés :
- Mise à jour de l'utilisation
- Nettoyage automatique
- Erreurs de limites
- Suppression de fichiers

## 🔄 Maintenance

### Nettoyage Manuel
```bash
# Supprimer tous les fichiers temporaires
rm -rf temp_files/*

# Supprimer les données d'utilisation
rm user_usage.json
```

### Surveillance
- Vérifier l'espace disque
- Monitorer les logs d'erreur
- Contrôler l'utilisation par utilisateur 