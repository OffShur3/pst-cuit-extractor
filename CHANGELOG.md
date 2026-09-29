# Changelog

Todos los cambios notables en este proyecto serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y este proyecto adhiere a [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] - 2026-09-29

### Cambiado
- **Modelo de datos granular:** Se abandonó la consolidación agregada por CUIT único. Ahora cada correo procesado genera un registro transaccional independiente (1 fila por correo) tanto en la base local como en Google BigQuery.
- **Normalización de CUIT:** El formato de CUIT pasó de la representación con guiones (`XX-XXXXXXXX-X`) a un formato numérico continuo de 11 dígitos (`20441769734`).
- **Desglose atómico de domicilios:** La dirección de instalación dejó de guardarse como cadena concatenada y pasó a dividirse en 7 columnas independientes: `calle`, `altura`, `piso`, `departamento`, `codigo_postal`, `localidad` y `provincia`.
- **Estrategia de carga en BigQuery:** Transición de sobreescritura total (`WRITE_TRUNCATE`) a cargas incrementales por lotes (`WRITE_APPEND`), manteniendo compatibilidad con BigQuery Sandbox (sin consultas DML).
- **Métrica temporal:** Se sustituyó el campo `ultimo_contacto` por `fecha_email`, conservando la fecha y hora original de recepción del mensaje.
- **Rediseño de interfaz gráfica:** La ventana principal de `CustomTkinter` se compactó a un formato flotante centrado de 500x580 px con distribución basada en tarjetas, reduciendo el consumo de espacio en pantalla.
- **Automatización de releases:** Se configuró el workflow de GitHub Actions para inyectar automáticamente el contenido de `CHANGELOG.md` en el cuerpo del Release oficial (`body_path`).

### Agregado
- **Campo de auditoría `mail_id`:** Incorporación de un identificador técnico único en la columna 19 para trazabilidad entre los registros de BigQuery y los correos originales de Outlook.
- **Mecanismo de idempotencia remoto:** Función `get_existing_mail_ids` que consulta los identificadores ya presentes en BigQuery antes de sincronizar, evitando duplicar registros ante reprocesamientos del mismo archivo o ingesta de múltiples PSTs.
- **Reseteo automático de sincronización:** Función `mark_all_unsynced` vinculada a `--reset-bq` para reactivar la sincronización local automáticamente si se recrea la tabla en la nube.

### Eliminado
- Tabla intermedia `consolidated_clients` y módulo de consolidación grupal por conjuntos.
- Columnas `asunto`, `message_id` y métricas agregadas como `total_tickets` en el esquema exportado a BigQuery.

---

## [1.0.0] - 2026-09-28

### Agregado
- Módulo extractor de correos PST (`PSTReader`) basado en enlaces nativos de `libpff-python`, con navegación recursiva de carpetas y bajo consumo de memoria.
- Función de decodificación adaptativa (`smart_decode`) con soporte para codificaciones Windows-1252, ISO-8859-1 y UTF-8 para preservar acentuación y caracteres del idioma español.
- Motor de análisis sintáctico por expresiones regulares (`regex_engine`) orientado a tickets de alta e instalación de Posnet y Fiserv.
- Validación de CUITs argentinos mediante implementación del algoritmo de Módulo 11 oficial de AFIP.
- Persistencia local en SQLite con modo Write-Ahead Logging (WAL), caché ampliada y esquema relacional para auditoría de tickets individuales y consolidación de clientes.
- Sistema de puntos de control (`checkpointing`) para permitir la pausa y reanudación ordenada del procesamiento ante cortes de energía o cierre de aplicación.
- Módulo de unificación acumulativa (`consolidate_clients`) que consolida terminales, teléfonos, códigos MC, localidades y razones sociales por CUIT único.
- Integración con Google BigQuery (`BigQuerySyncManager`) basada en operaciones por lotes (`LoadJob` con disposición `WRITE_TRUNCATE`), compatible con la capa gratuita (Sandbox) sin necesidad de sentencias DML.
- Interfaz gráfica compacta con estética moderna utilizando `CustomTkinter`, soporte para temas claros y oscuros, barra de progreso porcentual, contadores dinámicos y log de eventos.
- Ejecución asíncrona de la lógica de negocio mediante hilos de trabajo (`threading.Thread`) para evitar el bloqueo del bucle de eventos de la GUI.
- Scripts de utilidad interna en `src/scripts/` para diagnóstico estructural de carpetas PST, inspección de cuerpos crudos y reseteo de esquemas en BigQuery.
- Script de automatización de compilación local para plataformas Linux (`scripts/build_linux.sh`).
- Pipeline de integración continua en GitHub Actions (`.github/workflows/build.yml`) con compilación matricial para Windows (`.exe`) y Linux en calidad de artefactos de prueba descargables.

### Seguridad
- Configuración defensiva en `.gitignore` para bloquear la indexación involuntaria de credenciales GCP (`service_account.json`), respaldos de correo corporativo (`.pst`), bases SQLite intermedias y artefactos de compilación (`dist/`, `build/`).
