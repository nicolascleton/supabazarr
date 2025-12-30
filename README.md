# Supabazarr

**Service de sauvegarde automatique pour JellySetup**

Supabazarr sauvegarde quotidiennement votre bibliothèque de films/séries et vos paramètres vers Supabase, permettant de restaurer facilement votre configuration sur un nouveau Raspberry Pi.

## Fonctionnalités

- **Sauvegarde automatique quotidienne** (à 3h du matin)
- **Multi-services** : Radarr, Sonarr, Prowlarr, Jellyfin, Decypharr, Bazarr
- **Multi-devices** : Chaque Raspberry Pi a son propre espace de stockage
- **Historique** : Conserve 30 jours d'historique de backups
- **Léger** : Utilise moins de 128MB de RAM

## Données sauvegardées

| Service | Données |
|---------|---------|
| **Radarr** | Films, profils qualité, configuration |
| **Sonarr** | Séries, épisodes, profils qualité |
| **Prowlarr** | Indexeurs configurés |
| **Jellyfin** | Utilisateurs, préférences, configuration |
| **Decypharr** | Configuration (clés masquées) |

## Installation

### 1. Ajouter au docker-compose.yml

```yaml
services:
  # ... vos autres services ...

  supabazarr:
    image: ghcr.io/nicolascleton/supabazarr:latest
    container_name: supabazarr
    restart: unless-stopped
    environment:
      - TZ=Europe/Paris
      - SUPABASE_URL=https://votre-projet.supabase.co
      - SUPABASE_SERVICE_KEY=votre_service_role_key
      - HOSTNAME=jellypi
    volumes:
      - ./:/media-stack:ro
      - supabazarr_data:/etc/supabazarr
    deploy:
      resources:
        limits:
          memory: 128M

volumes:
  supabazarr_data:
```

### 2. Configurer les variables d'environnement

Créez un fichier `.env` :

```env
SUPABASE_URL=https://ncxowprkehliisvnpmlt.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIs...
```

### 3. Démarrer le service

```bash
docker-compose up -d supabazarr
```

## Configuration Supabase

Exécutez la migration SQL pour créer les tables :

```bash
supabase db push --linked
```

Ou exécutez manuellement `migrations/001_initial_schema.sql` dans l'éditeur SQL de Supabase.

## Usage

### Backup manuel

```bash
docker exec supabazarr python src/supabazarr.py --once
```

### Voir les logs

```bash
docker logs -f supabazarr
```

### Vérifier le statut

```bash
docker exec supabazarr python -c "
from src.supabazarr import get_config, SupabazarrBackup
config = get_config()
print(f'Device UUID: {config.device_uuid}')
print(f'Hostname: {config.hostname}')
"
```

## API Supabase

### Voir les films d'un device

```sql
SELECT * FROM movies WHERE device_id = 'uuid-du-device';
```

### Statistiques par device

```sql
SELECT * FROM device_stats;
```

### Derniers backups

```sql
SELECT * FROM backup_history ORDER BY backup_at DESC LIMIT 10;
```

## Restauration

Pour restaurer sur un nouveau Raspberry Pi :

1. Installez JellySetup normalement
2. Exécutez le script de restauration :

```bash
docker exec supabazarr python src/restore.py --device-uuid ANCIEN_UUID
```

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Raspberry Pi   │────▶│  Supabazarr  │────▶│  Supabase   │
│  (media-stack)  │     │   (Docker)   │     │  (Cloud)    │
└─────────────────┘     └──────────────┘     └─────────────┘
        │                       │                   │
        ▼                       ▼                   ▼
   ┌─────────┐           ┌───────────┐      ┌────────────┐
   │ Radarr  │           │  Backup   │      │   movies   │
   │ Sonarr  │           │  Service  │      │   series   │
   │ Jellyfin│           │  (cron)   │      │  indexers  │
   └─────────┘           └───────────┘      └────────────┘
```

## Contribution

1. Fork le repo
2. Créez votre branche (`git checkout -b feature/ma-feature`)
3. Committez (`git commit -m 'Add ma feature'`)
4. Push (`git push origin feature/ma-feature`)
5. Ouvrez une Pull Request

## License

MIT License - voir [LICENSE](LICENSE)
