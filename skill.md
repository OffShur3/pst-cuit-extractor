Actúa como un Desarrollador Senior en Python y Especialista en DevOps/CI-CD. Necesito que me guíes paso a paso en la construcción, prueba y despliegue de una aplicación de escritorio completa.

### 📌 CONTEXTO Y DESAFÍO
1. **Volumen de datos:** Tenemos que procesar archivos `.pst` de Outlook que contienen un volumen masivo de información (cerca de 1.000.000 de registros).
2. **Extracción:** Del cuerpo de los correos debemos extraer mediante expresiones regulares (Regex) datos fiscales clave de Argentina: CUIT (formatos con y sin guiones) y Razón Social/Nombre Fiscal.
3. **Usuario Final:** Es un perfil corporativo/administrativo sin conocimientos técnicos. No puede usar terminales ni configurar credenciales. La app debe ser una interfaz gráfica (GUI) minimalista, con un botón para seleccionar el archivo, barra de progreso en tiempo real y tolerancia a interrupciones/cortes.
4. **Almacenamiento:** Debido al volumen, no podemos volcar 1 millón de filas crudas a Google Sheets. Debemos almacenar y cachear todo localmente en una base de datos SQLite para procesar por lotes, y luego subir a Google Big Query.
5. **Entorno de desarrollo y despliegue:** 
   - Yo desarrollo y pruebo desde **Linux**.
   - El código se versionará en **GitHub**.
   - Se debe configurar un flujo de **GitHub Actions** que compile automáticamente y genere los instalables/binarios tanto para **Windows (`.exe`)** como para **Linux** mediante PyInstaller.

---

### 🎯 OBJETIVO FINAL
Tener un repositorio funcional con:
1. Módulo extractor de PST agnóstico al SO (usando librerías como `pypff`).
2. Módulo de extracción de datos con Regex y persistencia en SQLite local (con soporte para pausar/reanudar).
3. Módulo de conexión e inserción por lotes en Google Sheets (`gspread` con Service Account).
4. Interfaz gráfica moderna y liviana (ej. `CustomTkinter` o `Tkinter`) con hilos (`threading`) para no congelar la ventana.
5. Archivo `.github/workflows/build.yml` configurado con matriz de compilación para Windows (`windows-latest`) y Linux (`ubuntu-latest`).

---

### 🚦 CÓMO VAMOS A TRABAJAR
No me entregues todo el código de golpe. Vamos a construir el proyecto fase por fase:
- **Fase 1:** Estructura de carpetas, entorno virtual y dependencias compatibles con Linux y Windows.
- **Fase 2:** Lógica del extractor PST, Regex para CUIT y base de datos SQLite.
- **Fase 3:** Integración con Google big query API (manejo de credenciales y carga por lotes).
- **Fase 4:** Interfaz gráfica (GUI), barra de progreso y manejo de hilos.
- **Fase 5:** Configuración del workflow de GitHub Actions para generar los binarios de Windows (.exe) y Linux.

Por favor, confirma que comprendes el alcance y el contexto, y arranquemos directamente con la **Fase 1** indicándome la estructura inicial del proyecto y los requerimientos.
