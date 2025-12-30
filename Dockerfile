FROM python:3.11-slim

LABEL maintainer="JellySetup"
LABEL description="Supabazarr - Backup service for JellySetup media stack"
LABEL version="1.1.0"

# Installer les dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Créer l'utilisateur non-root
RUN useradd -m -s /bin/bash supabazarr

# Créer les répertoires
RUN mkdir -p /app /etc/supabazarr /var/log/supabazarr \
    && chown -R supabazarr:supabazarr /app /etc/supabazarr /var/log/supabazarr

WORKDIR /app

# Copier les fichiers
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Permissions
RUN chmod +x ./src/supabazarr.py

# Variables d'environnement par défaut
ENV PYTHONUNBUFFERED=1
ENV MEDIA_STACK_PATH=/media-stack
ENV TZ=Europe/Paris
ENV BACKUP_HOUR=03:00

# Port pour l'interface web
EXPOSE 8383

# Santé du container (vérifie l'interface web)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8383/api/status || exit 1

# Exécuter en tant que root pour lire les DBs des autres services
ENTRYPOINT ["python", "src/supabazarr.py"]
CMD []
