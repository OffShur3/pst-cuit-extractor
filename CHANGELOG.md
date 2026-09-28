# Changelog

Todos los cambios notables en este proyecto serán documentados en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/)
y este proyecto adhiere a [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
