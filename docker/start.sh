#!/bin/bash

set -e

PORT=8787

# obtener IP del contenedor
CONTAINER_IP=$(hostname -i | awk '{print $1}')

echo ""
echo "-------------------------------------------------"
echo " Hive container started ✅"
echo ""
echo " Container IP:  http://$CONTAINER_IP:$PORT"
echo " Local access:  http://localhost:$PORT"
echo ""
echo " Dashboard:     http://localhost:$PORT"
echo " Healthcheck:   http://localhost:$PORT/api/health"
echo "--------------------------------------------------"
echo ""

exec uv run hive serve --host 0.0.0.0 --port $PORT