# Copias de seguridad, archivado WAL y restauración PITR

Este procedimiento implementa la base técnica para recuperación Point-in-Time de PostgreSQL 16. No constituye aceptación de producción hasta completar una restauración en staging con almacenamiento y claves reales.

## Objetivos obligatorios

- RPO máximo: 1 hora.
- RTO máximo: 4 horas.
- Advertencia por retraso WAL: 10 minutos.
- Alerta crítica por retraso WAL: 15 minutos.
- Restauración automatizada mensual sobre una instancia limpia y aislada.
- Backups y WAL cifrados con AES-256-GCM.

## Modelo criptográfico

Los scripts usan CMS EnvelopedData con AES-256-GCM. El servidor de origen solo recibe el certificado público del destinatario. La clave privada se mantiene fuera del origen y se monta únicamente, en modo lectura, dentro del entorno de restauración aislado.

`openssl enc` no admite modos AEAD y no debe utilizarse. Los archivos `SHA256SUMS` y los sidecars `.sha256` detectan conflictos y corrupción accidental; la etiqueta GCM valida integridad criptográfica al descifrar. Para impedir reemplazos completos por un actor que posea el certificado público, el almacenamiento debe ser inmutable o el manifiesto debe firmarse mediante una clave independiente.

## Artefactos

- `backup-logical.sh`: roles sin contraseñas y dump lógico custom, cifrados durante el streaming.
- `backup-base.sh`: base física tar con WAL requerido y manifiesto SHA-256, cifrada durante el streaming.
- `pitr-archive-wal.sh`: archiva cada segmento WAL cifrado y rechaza colisiones con contenido diferente.
- `pitr-restore-wal.sh`: descifra cada WAL, valida GCM y SHA-256 y publica el segmento de forma atómica.
- `pitr-restore.sh`: prepara exclusivamente un `PGDATA` vacío bajo `/var/lib/postgresql/pitr-test/<id>/data`.
- `pitr-check-archive-lag.sh`: devuelve 0, 1 o 2 para estado normal, advertencia o crítico.

El backup físico por stdout admite solo el tablespace predeterminado. `backup-base.sh` verifica esta condición y falla si existen tablespaces adicionales. Usa `--wal-method=fetch`; `wal_keep_size` debe dimensionarse para conservar el WAL generado durante todo el backup.

## Activación explícita en un despliegue

`compose.pitr.yaml` es un overlay opt-in. No modifica el arranque local normal y exige:

- `NEXUS_BACKUP_RECIPIENT_CERT`: ruta al certificado público;
- `NEXUS_WAL_ARCHIVE_VOLUME`: volumen externo sobre almacenamiento cifrado y restringido;
- `NEXUS_BACKUP_ARTIFACTS_VOLUME`: volumen externo cifrado para bases y dumps.

Ambos volúmenes externos deben estar creados antes del arranque. La raíz del volumen WAL debe ser escribible por el usuario `postgres` de la imagen fijada; el aprovisionamiento de permisos pertenece al proveedor de almacenamiento y debe validarse sin ampliar permisos a otros usuarios.

Ejemplo de validación de configuración:

```sh
docker compose \
  --env-file .env \
  -f infra/compose.yaml \
  -f infra/compose.pitr.yaml \
  config --quiet
```

Ejemplo de backup físico después de activar el archivado:

```sh
docker compose \
  --env-file .env \
  -f infra/compose.yaml \
  -f infra/compose.pitr.yaml \
  --profile pitr-tools run --rm base-backup
```

El volumen WAL local de Docker no basta para producción. El operador debe demostrar cifrado en reposo, copia fuera del nodo, retención de 35 días, control de acceso e inmutabilidad o versionado.

## Ensayo local aislado

El ensayo genera un proyecto Compose con prefijo `nexus-pitr-test-`, red interna, cero puertos publicados y volúmenes nuevos. Nunca referencia `nexus-it_postgres_data`.

```sh
bash tests/infra/pitr-rehearsal.sh
```

Secuencia verificada por el ensayo:

1. Genera certificado y clave desechables fuera del repositorio.
2. Levanta un PostgreSQL fuente aislado con archivado WAL cifrado.
3. Crea el esquema sentinel y toma una base física.
4. Confirma una fila anterior al objetivo y otra posterior.
5. Restaura en un segundo volumen vacío.
6. Comprueba que existe únicamente la fila anterior y que PostgreSQL quedó pausado en recuperación.
7. Registra RTO y elimina únicamente el proyecto efímero creado por el propio script.

La prueba mensual de CI demuestra el mecanismo con datos desechables. No sustituye una restauración de staging con tamaño, almacenamiento, credenciales y topología representativos.

## Restauración controlada en staging

No ejecutar `pitr-restore.sh` directamente contra un volumen existente. El script requiere un identificador aislado, rechaza rutas externas, symlinks y directorios no vacíos, y nunca mueve ni reemplaza otro `PGDATA`.

Antes de promover:

- comprobar que `pg_is_in_recovery()` devuelve `true`;
- verificar que el punto objetivo contiene transacciones anteriores y excluye las posteriores;
- ejecutar validación de RLS con dos organizaciones;
- comprobar claves foráneas compuestas;
- confirmar que roles runtime no poseen `SUPERUSER` ni `BYPASSRLS`;
- verificar el head Alembic y conteos de entidades críticas;
- registrar inicio, fin, RPO observado, RTO y hashes de artefactos.

La recuperación usa `recovery_target_action = 'pause'`. Solo después de aprobar esas verificaciones puede ejecutarse `SELECT pg_wal_replay_resume();` y habilitarse tráfico.

## Operación y alertas

Ejecutar `pitr-check-archive-lag.sh` mediante el sistema de monitoreo con credenciales de solo lectura. Interpretar códigos:

- 0: retraso menor a 600 segundos;
- 1: advertencia desde 600 segundos;
- 2: crítico desde 900 segundos, consulta fallida o ausencia de un WAL archivado.

Una prueba omitida, un artefacto sin etiqueta GCM válida, una discrepancia SHA-256, un WAL faltante o un objetivo no alcanzado invalida la restauración.
