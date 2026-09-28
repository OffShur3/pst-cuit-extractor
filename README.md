# PST CUIT Extractor & Enterprise Data Pipeline

Solución integral de procesamiento automatizado (ETL/RPA) para la extracción, validación algorítmica, persistencia y sincronización en la nube de metadatos fiscales y comerciales almacenados en archivos de correo masivo (.pst).

---

## 1. Resumen Ejecutivo y Valor de Negocio

En entornos corporativos y de servicios de pago electrónico, el procesamiento de notificaciones transaccionales o tickets de instalación distribuidos en cientos de miles de correos electrónicos representa un desafío operativo crítico. La recopilación manual de estos registros resulta inviable por volumen, introduce márgenes inaceptables de error humano y dispersa información comercial clave.

Este proyecto reemplaza tareas manuales intensivas por una canalización automatizada resiliente, logrando:

- **Reducción de tiempos operativos:** Procesamiento masivo capaz de transformar cientos de miles de correos en registros comerciales unificados en cuestión de minutos.
- **Garantía de integridad fiscal:** Validación criptográfica de CUITs argentinos mediante el algoritmo de Módulo 11 (estándar AFIP) antes del almacenamiento.
- **Consolidación de datos (Single Source of Truth):** Transformación de tickets individuales dispersos en un maestro de clientes unificado por CUIT, deduplicando terminales, teléfonos, códigos de comercio y direcciones.
- **Escalabilidad y costo cero de infraestructura:** Arquitectura orientada a BigQuery mediante tareas por lotes (Load Jobs), eliminando el consumo innecesario de cuotas y permitiendo analítica directa en Google Sheets (Connected Sheets) sin sobrecargar estaciones de trabajo.

---

## 2. Arquitectura de la Solución (Pipeline ETL)

El sistema opera bajo un esquema desacoplado y tolerante a fallos compuesto por cuatro capas:

```
[ Archivo Outlook .PST ]
          │
          ▼
┌──────────────────────────────────────────────┐
│ 1. Extractor (pypff / libpff nativo en C)    │
│    - Decodificación adaptativa (CP1252/UTF8) │
│    - Recorrido iterativo sin saturar RAM     │
└──────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│ 2. Motor de Normalización y Validación Regex │
│    - Validación estricta Módulo 11           │
│    - Parsing posicional de campos Fiserv     │
└──────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│ 3. Almacenamiento Intermedio (SQLite WAL)    │
│    - Checkpoint transaccional (Pausa/Resume) │
│    - Agrupación acumulativa por CUIT         │
└──────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│ 4. Sincronización Cloud (Google BigQuery)    │
│    - Cargas por lotes atómicas (sin DML)     │
│    - Consulta conectada en Google Sheets     │
└──────────────────────────────────────────────┘
```

### Componentes Principales

- **Lector PST Agnóstico (`src/extractor/pst_reader.py`):** Utiliza enlaces nativos de `libpff` para inspeccionar la estructura jerárquica de carpetas de Outlook sin depender de dependencias propietarias ni de la instalación previa de Microsoft Office. Implementa decodificación multietapa para preservar acentuación y caracteres del español.
- **Motor de Reglas y Validación (`src/parser/regex_engine.py`):** Extrae de forma determinista metadatos de tickets de POS (Terminal, MC, Vendedor, Dirección, Localidad, Teléfono, Tier y Denominación de equipo). Descarta registros no verificados mediante el dígito verificador fiscal de AFIP.
- **Gestor de Persistencia y Checkpoints (`src/storage/db_manager.py`):** Implementa SQLite con modo Write-Ahead Logging (WAL) y asignación de memoria extendida. Mantiene un registro de control de estado que permite reanudar tareas interrumpidas exactamente en el último mensaje procesado.
- **Sincronizador BigQuery (`src/integrations/bigquery_sync.py`):** Diseñado específicamente para entornos empresariales y BigQuery Sandbox. Descarga metadatos previos, ejecuta la unión acumulativa de conjuntos en local y reemplaza la tabla destino mediante operaciones atómicas libres de costos por consulta DML.
- **Interfaz de Usuario Desktop (`src/ui/app.py`):** GUI flotante y compacta construida sobre `CustomTkinter`. La ejecución de procesos intensivos se delega a hilos secundarios (`threading`), asegurando la responsividad continua de la interfaz y proveyendo métricas visuales en tiempo real.

---

## 3. Modelo de Datos Consolidado (BigQuery / SQLite)

Cada fila representa una entidad comercial única con historial acumulado:

| Campo | Tipo | Descripción |
|---|---|---|
| `cuit` | STRING | Clave primaria fiscal normalizada (XX-XXXXXXXX-X) |
| `razon_social` | STRING | Razón social oficial más reciente |
| `nombres` | STRING | Lista consolidada de nombres de fantasía/comercio |
| `tier` | STRING | Nivel de categorización de servicio (ej. VIP) |
| `terminales` | STRING | Lista acumulativa de números de terminales Posnet |
| `telefonos` | STRING | Números telefónicos deduplicados |
| `direcciones` | STRING | Domicilios de instalación vinculados al contribuyente |
| `mcs` | STRING | Códigos de comercio de tarjeta de crédito (MasterCard) |
| `denominaciones`| STRING | Modelos de hardware provistos (ej. Clover Flex) |
| `vendedores` | STRING | Identificadores y nombres de ejecutivos asignados |
| `otros` | STRING | Observaciones y zonas comerciales operativas |
| `total_tickets` | INTEGER | Volumen histórico de solicitudes registradas |
| `ultimo_contacto`| STRING | Timestamp del último evento registrado |

---

## 4. Instalación y Uso Local

### Requisitos del Sistema
- Python 3.10 o superior.
- Librería de sistema Tcl/Tk (`tk` en distribuciones basadas en Arch Linux, `python3-tk` en Debian/Ubuntu).

### Configuración del Entorno de Desarrollo
```bash
# Clonar repositorio
git clone git@github.com:OffShur3/pst-cuit-extractor.git
cd pst-cuit-extractor

# Configurar entorno virtual
python -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Ejecución Directa
```bash
python main.py
```

### Compilación Local para Linux
```bash
./scripts/build_linux.sh
# El ejecutable se generará en dist/pst-cuit-extractor
```

---

## 5. Integración Continua y Despliegue (CI/CD)

El repositorio incorpora un flujo automatizado mediante **GitHub Actions** (`.github/workflows/build.yml`):

1. **Matriz de Compilación Cruzada:**
   - Compilación en runner nativo Windows (`windows-latest`) generando `PST-CUIT-Extractor-Windows.exe`.
   - Compilación en runner nativo Linux (`ubuntu-latest`) generando `PST-CUIT-Extractor-Linux`.
2. **Generación de Artefactos de Prueba:** Ante cualquier evento de `push` o `pull_request`, los binarios resultantes quedan disponibles en la pestaña de artefactos de GitHub Actions para validación interna sin alterar el historial público.
3. **Distribución Formal de Versiones:** La creación de etiquetas de versión (`git tag vX.Y.Z`) activa la publicación automática de un GitHub Release con los instalables finales adjuntos.

---

## 6. Seguridad y Gobernanza de Datos

- **Aislamiento de Credenciales:** Los archivos de servicio de Google Cloud (`service_account.json`), bases SQLite intermedias (`.db`) y archivos de correo corporativo (`.pst`) se encuentran estrictamente excluidos del control de versiones a través de `.gitignore`.
- **Acceso por Principio de Menor Privilegio:** La cuenta de servicio de GCP solo requiere permisos de lectura/escritura a nivel Dataset (`BigQuery Data Editor` y `BigQuery Job User`), sin exigir privilegios administrativos en el proyecto global.
