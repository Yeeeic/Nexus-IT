# HTTPS para el MVP de nodo único

`compose.tls.yaml` añade un proxy TLS 1.3. Requiere Docker Compose 2.24.4 o posterior para reemplazar los puertos con `!override`. El frontend deja de publicar HTTP y la API solo publica en `127.0.0.1`; el acceso externo pasa por los puertos 80/443. No cambia los volúmenes de datos.

El operador debe aportar un dominio controlado, DNS y certificado válido con su cadena completa. Definir `NEXUS_TLS_CERT_FILE` y `NEXUS_TLS_KEY_FILE` con rutas absolutas a archivos PEM existentes fuera del repositorio. En Docker WSL, usar rutas Linux accesibles por su motor. Proteger la clave privada mediante permisos del sistema; no copiarla al proyecto.

Configurar `NEXUS_ALLOWED_ORIGINS` con el origen HTTPS real y `NEXUS_PASSWORD_RESET_URL` con su URL HTTPS real. Autorizar solamente ese origen en navegador y agente. No usar certificados de prueba ni omitir validación TLS en producción.

Desde la raíz, tras configurar las variables y realizar el aprovisionamiento descrito en `README.md`:

```sh
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.tls.yaml config --quiet
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.tls.yaml up -d backend frontend tls
```

Mantener ambos archivos en todos los comandos de actualización; omitir el override volvería a publicar los puertos HTTP de desarrollo. El host y los contenedores de la red `edge` forman un límite de confianza: Uvicorn acepta sus cabeceras de proxy. El proxy reemplaza `X-Forwarded-For` por la IP real de la conexión. No conectar contenedores no confiables a esa red ni publicar nuevamente la API.

El proxy conserva cookies y cabeceras de autorización, soporta WSS y envía `/api/` directamente al backend. Permite 11 MB de cuerpo para el overhead multipart; el backend sigue imponiendo el límite de adjunto de 10 MB. HSTS exige HTTPS durante un año. La ruta `/tls-health` valida únicamente el proxy, no la salud del backend. Los accesos del proxy no registran URLs con tokens.

Para renovar, sustituir de forma segura los archivos del operador y recrear el servicio `tls` con los mismos archivos Compose; la recreación asegura que los bind mounts tomen el archivo nuevo. Mantener una copia protegida del certificado anterior permite revertir si la validación falla. Programar renovación y alerta de caducidad en el entorno operativo.

## Verificación

`bash infra/nginx/verify-tls.sh` crea un certificado efímero para localhost, comprueba `nginx -t`, conexión TLS 1.3 con confianza explícita, rechazo de TLS 1.2, HSTS y redirección HTTP. Elimina exclusivamente su contenedor y carpeta temporal. No levanta el producto ni acredita un dominio real.

En el despliegue operativo verificar cadena/caducidad, sesión de navegador con cookie Secure, WSS autenticado, agente sin opciones inseguras y rechazo del acceso externo a 8000/8080. Un ensayo local no sustituye esta evidencia.

Referencias: [merge de Compose](https://docs.docker.com/reference/compose-file/merge/), [TLS de NGINX](https://nginx.org/en/docs/http/ngx_http_ssl_module.html), [WebSocket de NGINX](https://nginx.org/en/docs/http/websocket.html).
