# PST CUIT Extractor & Enterprise Data Pipeline

Solución integral de procesamiento automatizado (ETL/RPA) para la extracción, validación algorítmica, persistencia y sincronización en la nube de metadatos fiscales y comerciales almacenados en archivos de correo masivo (.pst).

---

## 1. Resumen Ejecutivo y Valor de Negocio

En entornos corporativos y de servicios de pago electrónico, el procesamiento de notificaciones transaccionales o tickets de instalación distribuidos en cientos de miles de correos electrónicos representa un desafío operativo crítico. La recopilación manual de estos registros resulta inviable por volumen, introduce márgenes inaceptables de error humano y dispersa información comercial clave.

Este proyecto reemplaza tareas manuales intensivas por una canalización automatizada resiliente, logrando:

- **Procesamiento granular (1 fila por correo):** Cada mensaje o ticket procesado genera un registro transaccional independiente para su auditoría y análisis temporal.
- **Garantía de integridad fiscal:** Validación algorítmica de CUITs argentinos mediante el algoritmo de Módulo 11 (estándar AFIP) y normalización numérica pura (11 dígitos sin guiones).
- **Desglose atómico de domicilios:** Extracción estructurada de cada componente de la dirección de instalación (calle, altura, piso, departamento, código postal, localidad y provincia).
- **Idempotencia y trazabilidad absoluta (`mail_id`):** Incorporación del identificador único de correo al final de cada registro, permitiendo contrastar contra la base en BigQuery para omitir duplicados ante múltiples PSTs o actualizaciones continuas.
- **Escalabilidad y costo cero de infraestructura:** Arquitectura orientada a BigQuery mediante tareas por lotes (Load Jobs con `WRITE_APPEND`), eliminando el consumo de cuotas DML y permitiendo analítica directa en Google Sheets (Connected Sheets).

---

## 2. Arquitectura de la Solución (Pipeline ETL)

El sistema opera bajo un esquema desacoplado y tolerante a fallos compuesto por cuatro capas:

```
[ Archivos Outlook .PST ]
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
│    - CUIT numérico puro (11 dígitos)         │
│    - Desglose de dirección posicional        │
└──────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│ 3. Almacenamiento Intermedio (SQLite WAL)    │
│    - Checkpoint transaccional (Pausa/Resume) │
│    - Control anti-duplicados por mail_id     │
└──────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────┐
│ 4. Sincronización Cloud (Google BigQuery)    │
│    - Chequeo previo de mail_ids en la nube   │
│    - Inserción por lotes sin DML             │
│    - Conector nativo en Google Sheets        │
└──────────────────────────────────────────────┘
```

---

## 3. Modelo de Datos Final (BigQuery / SQLite)

Cada fila representa un correo o ticket procesado con sus atributos comerciales:

| # | Campo | Tipo | Descripción |
|---|---|---|---|
| 1 | `cuit` | STRING | CUIT numérico sin guiones (ej. `20441769734`) |
| 2 | `razon_social` | STRING | Razón social identificada en el cuerpo |
| 3 | `nombre` | STRING | Nombre de fantasía o comercio destinatario |
| 4 | `tier` | STRING | Categorización de servicio (ej. VIP / Estándar) |
| 5 | `terminal` | STRING | Número de terminal Posnet asociada |
| 6 | `mc` | STRING | Código de comercio de tarjeta MasterCard |
| 7 | `denominacion`| STRING | Modelo de equipamiento provisto (ej. Clover Flex) |
| 8 | `calle` | STRING | Nombre de la arteria o calle de instalación |
| 9 | `altura` | STRING | Altura catastral o numeración |
| 10| `piso` | STRING | Nivel o piso si aplica |
| 11| `departamento` | STRING | Unidad funcional o departamento |
| 12| `codigo_postal`| STRING | Código Postal (C.P.) |
| 13| `localidad` | STRING | Ciudad o localidad de instalación |
| 14| `provincia` | STRING | Jurisdicción provincial |
| 15| `telefono` | STRING | Teléfono de contacto registrado |
| 16| `vendedor` | STRING | Código y denominación del ejecutivo o sucursal |
| 17| `otros` | STRING | Zona comercial y observaciones operativas |
| 18| `fecha_email` | STRING | Fecha y hora original de recepción del mensaje |
| 19| `mail_id` | STRING | Identificador único de mensaje para auditoría |

---

## 4. Instalación y Uso Local

### Requisitos del Sistema
- Python 3.10 o superior.
- Librería de sistema Tcl/Tk (`tk` en Arch/Endeavour/Manjaro, `python3-tk` en Debian/Ubuntu).

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
# El binario se generará en dist/pst-cuit-extractor
```

---

## 5. Integración Continua y Despliegue (CI/CD)

El repositorio incorpora un flujo automatizado mediante **GitHub Actions** (`.github/workflows/build.yml`):

1. **Compilación Multiplataforma:**
   - Compilación en runner Windows (`windows-latest`) generando `PST-CUIT-Extractor-Windows.exe`.
   - Compilación en runner Linux (`ubuntu-latest`) generando `PST-CUIT-Extractor-Linux`.
2. **Artefactos de Prueba:** En cada `push` a ramas principales, los binarios se empaquetan como artefactos descargables desde GitHub Actions para pruebas intermedias.
3. **Publicación Automática de Releases:** Al crear y subir una etiqueta de versión (`git tag vX.Y.Z`), el workflow compila ambos sistemas y publica un Release formal adjuntando el contenido de `CHANGELOG.md` como nota descriptiva.

---

## 6. Seguridad y Gobernanza de Datos

- **Aislamiento de Credenciales:** Los archivos de servicio de Google Cloud (`service_account.json`), bases SQLite intermedias (`.db`) y archivos de correo corporativo (`.pst`) se encuentran estrictamente excluidos del control de versiones a través de `.gitignore`.
- **Acceso por Principio de Menor Privilegio:** La cuenta de servicio de GCP solo requiere permisos a nivel Dataset (`BigQuery Data Editor` y `BigQuery Job User`).
```

---

