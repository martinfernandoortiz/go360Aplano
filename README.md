# 🌍 GoPro2Geo

> **Suite integral para extracción de fotogramas, decodificación de telemetría binaria (GPMF) y georreferenciación masiva de videos GoPro (`.360` y `.MP4`) para entornos GIS (QGIS, ArcGIS, Mapillary y Google Earth).**

---

## 📑 Tabla de Contenidos

1. [¿Qué problema resuelve?](#-qué-problema-resuelve)
2. [Estructura del Paquete para Compartir](#-estructura-del-paquete-para-compartir)
3. [Requisitos del Sistema](#-requisitos-del-sistema)
4. [Guía de Uso: Script CLI (`extraer_telemetria.py`)](#-guía-de-uso-script-cli-extraer_telemetriapy)
   - [Uso Básico (Videos .360)](#1-uso-básico-videos-360)
   - [Uso con Videos .MP4](#2-uso-con-videos-mp4)
   - [Ajuste de Frecuencia de Captura (`--fps`)](#3-ajuste-de-frecuencia-de-captura---fps)
   - [MP4 sin telemetría vinculado a .360 original (`--telemetry-source`)](#4-mp4-sin-telemetría-vinculado-a-360-original---telemetry-source)
   - [Procesamiento por Lotes (Batch)](#5-procesamiento-por-lotes-batch)
5. [Tabla de Parámetros de la Línea de Comandos](#-tabla-de-parámetros-de-la-línea-de-comandos)
6. [Archivos y Capas Generadas](#-archivos-y-capas-generadas)
7. [Cómo abrir los resultados en QGIS / ArcGIS](#-cómo-abrir-los-resultados-en-qgis--arcgis)
8. [Uso de la Interfaz Gráfica de Escritorio (`app.py`)](#-uso-de-la-interfaz-gráfica-de-escritorio-apppy)
9. [Preguntas Frecuentes y Solución de Problemas](#-preguntas-frecuentes-y-solución-de-problemas)
10. [Instrucciones para subir a GitHub](#-instrucciones-para-subir-a-github)

---

## 🎯 ¿Qué problema resuelve?

Al intentar extraer fotogramas georreferenciados desde videos de cámaras GoPro (especialmente GoPro MAX o Fusion en formato `.360`), las herramientas convencionales como ExifTool fallan debido a tres limitaciones fundamentales:

```
Video GoPro (.360 / .mp4)
 ├── Pista de Video (Stream #0:0 y #0:4 en .360 -> EAC Dual Lens)
 └── Pista de Datos (Stream #0:3 gpmd -> Binario KLV GPS9 a 10 Hz)
```

1. **La telemetría no está en el encabezado:** La GoPro almacena las coordenadas en un flujo binario interno de metadatos (`gpmd`), muestreado a 10 Hz bajo el protocolo `GPS9`. ExifTool estándar solo lee una coordenada fija de cabecera si no se decodifica el stream KLV completo.
2. **Incompatibilidad de `-geotag` con `.360`:** El comando de georreferenciación automática de ExifTool no reconoce la extensión `.360` como un archivo de registro de trayectoria válido.
3. **Fotogramas extraídos sin marca de tiempo (desfase temporal):** Al extraer imágenes con FFmpeg (`fps=1`), los archivos JPG resultantes se generan "crudos" sin la etiqueta `DateTimeOriginal`. Si se intenta aplicar un archivo GPX externo, ExifTool descarta los puntos porque la hora de creación del archivo en el disco no coincide con la fecha histórica de grabación del video.
4. **Doble lente esférico (EAC):** Los videos `.360` contienen 2 pistas de video independientes en formato Equi-Angular Cubemap. Si no se proyectan a plano rectilíneo, las imágenes presentan costuras visibles y deformación angular.

**GoPro2Geo resuelve todo el flujo en un único comando automatizado.**

---

## 📦 Estructura del Paquete para Compartir

Para pasarle esta herramienta a otra persona para que procese videos en su propia PC, **solo necesitas entregarle estos 3 archivos en una misma carpeta**:

```text
mi-carpeta-gopro/
├── ffmpeg.exe              # Binario ejecutable de FFmpeg
├── exiftool.exe            # Binario ejecutable de ExifTool
└── extraer_telemetria.py   # Script principal de procesamiento
```

> **Nota:** La otra persona **NO necesita instalar paquetes con `pip`**. El script está programado usando exclusivamente librerías estándar de Python (`subprocess`, `struct`, `json`, `csv`, `math`, `datetime`, `os`, `sys`). Solo requiere tener instalado **Python 3.8 o superior**.

---

## ⚙️ Requisitos del Sistema

| Componente | Requisito | Propósito |
| :--- | :--- | :--- |
| **Python** | 3.8 o superior | Ejecutar el motor de parseo y orquestación. |
| **FFmpeg** | Versión 5.0 o superior | Extracción de fotogramas y volcado del stream GPMF. |
| **ExifTool** | Versión 12.0 o superior | Inyección masiva de etiquetas EXIF en los JPGs. |
| **PyQt5** *(Opcional)* | 5.15+ (o entorno QGIS) | Solo si deseas usar la interfaz visual (`app.py`). |

---

## 💻 Guía de Uso: Script CLI (`extraer_telemetria.py`)

Abre una terminal (PowerShell o CMD) en la carpeta donde tienes el script y ejecuta los siguientes comandos según tu caso:

### 1. Uso Básico (Videos `.360`)

Extrae 1 fotograma por segundo en vista plana rectilínea (1080p), decodifica el GPS y georreferencia cada foto:

```powershell
python extraer_telemetria.py --video "C:\Videos\260713-RECORRIDO-8K.360"
```

También admite **rutas de red UNC** directamente:
```powershell
python extraer_telemetria.py --video "\\servidor\gis\videos\recorrido.360"
```

#### ¿Qué sucede paso a paso?
1. Crea automáticamente una subcarpeta con el nombre del video (ej. `260713-RECORRIDO-8K/`).
2. Extrae los fotogramas planos rectilíneos a 1 fps dentro de dicha carpeta.
3. Extrae el stream GPMF en 1 segundo con FFmpeg (sin procesar el video completo).
4. Decodifica los puntos GPS (10 Hz) y calcula velocidad, rumbo (heading) y altitud.
5. Genera la tabla `telemetria_fotogramas.csv`, el archivo `recorrido.gpx` y la capa vectorial `fotogramas.geojson`.
6. Inyecta los metadatos EXIF en cada archivo JPG mediante ExifTool.

---

### 2. Uso con Videos `.MP4`

Si trabajas con videos estándar de cámaras GoPro (HERO 7, 8, 9, 10, 11, 12 o MAX en modo Hero 2D):

```powershell
python extraer_telemetria.py --video "C:\Videos\GH010025.mp4"
```

*El script detecta automáticamente que es un MP4 y extrae los fotogramas de forma nativa directa (sin aplicar la distorsión del filtro 360).*

---

### 3. Ajuste de Frecuencia de Captura (`--fps`)

Por defecto se extrae **1 fotograma por segundo** (`1.0 fps`). Puedes modificar la frecuencia según la velocidad del relevamiento:

```powershell
# 2 fotos por segundo (cada 0.5 segundos) - Ideal para curvas o baja velocidad
python extraer_telemetria.py --video "recorrido.360" --fps 2.0

# 1 foto cada 2 segundos (0.5 fps) - Recomendado para autopistas o recorridos largos
python extraer_telemetria.py --video "recorrido.360" --fps 0.5

# 1 foto cada 5 segundos (0.2 fps)
python extraer_telemetria.py --video "recorrido.360" --fps 0.2

# Máxima resolución GPS nativa (10 fotos por segundo)
python extraer_telemetria.py --video "recorrido.360" --fps 10.0
```

---

### 4. Formato y Calidad de Imagen (JPEG vs PNG Sin Compresión)

Por defecto, el script genera fotogramas en **JPEG a calidad máxima (`-q:v 1` / 100%)**, con interpolación de píxeles `spline16`. Esto ofrece una calidad fotográfica visualmente idéntica al video (~2 MB por foto en 4K) y compatibilidad directa con todos los SIG.

#### Ajustar la calidad JPEG (ej: 80% para ahorrar espacio):
Puedes usar el parámetro `--quality` (o `-q`) de 1 a 100:

```powershell
# Extrae en JPEG con calidad del 80% (~700 KB - 1 MB por foto en 4K)
python extraer_telemetria.py --video "recorrido.360" --quality 80

# Con la abreviatura -q:
python extraer_telemetria.py -q 80
```
*Internamente, el script traduce el porcentaje al factor de cuantización óptimo de FFmpeg (`80% -> -q:v 5`).*

#### Extracción 100% Sin Compresión (PNG Lossless):
Si requieres **cero compresión** bit a bit idéntico al fotograma decodificado:

```powershell
# Extracción 100% sin compresión (PNG Lossless con EXIF GPS inyectado)
python extraer_telemetria.py --video "recorrido.360" --lossless

# O usando el parámetro --format:
python extraer_telemetria.py --video "recorrido.360" --format png
```

*Nota: Un fotograma 4K en PNG lossless pesa entre 8 y 15 MB. En todos los formatos se realiza la inyección de metadatos GPS mediante ExifTool.*

---

### 5. MP4 sin telemetría vinculado a `.360` original (`--telemetry-source`)

Si convertiste previamente tu video `.360` a un `.mp4` plano usando GoPro Player o un editor de video, el archivo MP4 resultante suele perder los datos GPS. Puedes extraer las imágenes del MP4 plano y tomar la telemetría del archivo `.360` original:

```powershell
python extraer_telemetria.py --video "recorrido_plano.mp4" --telemetry-source "recorrido_original.360"
```

---

### 6. Procesamiento por Lotes (Batch)

Para procesar de forma desatendida todos los videos `.360` de una carpeta:

#### En CMD (Símbolo del Sistema):
```cmd
for %F in (*.360) do (
    python extraer_telemetria.py --video "%F"
)
```

#### En PowerShell:
```powershell
Get-ChildItem -Filter "*.360" | ForEach-Object {
    python extraer_telemetria.py --video $_.FullName
}
```

---

## 📋 Tabla de Parámetros de la Línea de Comandos

| Parámetro | Abreviatura | Valor por Defecto | Descripción |
| :--- | :---: | :---: | :--- |
| `--video` | `-v` | *(Requerido)* | Ruta al archivo de video (`.360` o `.mp4`). |
| `--fps` | | `2.0` | Fotogramas por segundo a extraer (por defecto `2.0`, ej: `0.5`, `1.0`, `2.0`). |
| `--quality` | `-q` | `100` | Calidad de compresión JPEG de 1 a 100 (ej: `80` para 80% de calidad). |
| `--format` | `--fmt` | `jpg` | Formato de imagen: `jpg` o `png` (sin compresión / lossless). |
| `--lossless` / `--png` | | `False` | Atajo directo para extraer en PNG 100% sin compresión. |
| `--force` | `-f` | `True` | Re-extrae siempre los fotogramas (usar `--no-force` para omitir si ya existen). |
| `--h-fov` / `--fov` | | `65.0` | Campo visual horizontal en grados (por defecto `65.0`, estándar natural sin deformación). |
| `--v-fov` | | `auto` | Campo visual vertical en grados (por defecto proporcional 16:9 automático). |
| `--width` | `-W` | `3840` | Ancho del fotograma en píxeles (resolución 4K por defecto). |
| `--height` | `-H` | `2160` | Alto del fotograma en píxeles (resolución 4K por defecto). |
| `--proj` | | `rectilinear` | Proyección: `rectilinear` (plano), `flat`, `pannini`. |
| `--pitch` | | `0.0` | Inclinación vertical de la cámara en grados. |
| `--yaw` | | `0.0` | Rotación horizontal de la cámara en grados. |
| `--mode` | `-m` | `auto` | Modo de video: `auto` (detecta por extensión), `360` o `flat`. |
| `--frames-dir` | `-d` | `auto` | Carpeta de salida. En `auto` crea una subcarpeta con el nombre del video. |
| `--pattern` | `-p` | `fotograma_%04d.jpg` | Patrón de nombrado de los fotogramas. |
| `--telemetry-source`| `-t` | `None` | Ruta a un video alternativo para extraer la telemetría GPS. |
| `--skip-frames` | | `False` | Omite la extracción con FFmpeg. |
| `--skip-exif` | | `False` | Omite la inyección EXIF con ExifTool. |

---

## 📂 Archivos y Capas Generadas

Dentro de la subcarpeta creada para cada video (ej: `260713-ACA-RAE-B-SUBIDACOLECTORACANTILO-8K/`), encontrarás:

```text
📁 260713-ACA-RAE-B-SUBIDACOLECTORACANTILO-8K/
├── 📄 fotograma_0001.jpg        <- Imagen con coordenadas EXIF incrustadas
├── 📄 fotograma_0002.jpg        <- Imagen con coordenadas EXIF incrustadas
├── ...
├── 📊 telemetria_fotogramas.csv <- Tabla de datos por segundo
├── 🗺️ fotogramas.geojson        <- Capa vectorial (Puntos + Línea)
└── 🛰️ recorrido.gpx             <- Track log estándar GPX 1.1
```

### 1. Fotogramas JPG georreferenciados
Cada imagen contiene los siguientes campos estándar EXIF grabados internamente:
* **`GPSLatitude` y `GPSLongitude`**: Coordenadas en grados decimales (WGS84).
* **`GPSAltitude`**: Altitud sobre el nivel del mar en metros.
* **`GPSImgDirection`**: Rumbo de la cámara en grados (0° a 360° respecto al Norte Verdadero).
* **`GPSSpeed`**: Velocidad del móvil en km/h calculada por el receptor GPS.
* **`DateTimeOriginal`**: Fecha y hora UTC exacta de captura de ese fotograma.

### 2. `telemetria_fotogramas.csv`
Estructura tabular lista para abrir en Excel, LibreOffice Calc o unir mediante un *Join* en SIG:
```csv
fotograma,segundo,timestamp_utc,latitud,longitud,altitud_m,velocidad_kmh,rumbo_deg,dop
fotograma_0001.jpg,0.0,2026-07-06 14:36:23,-34.540802,-58.4507696,15.77,29.65,95.3,2.0
fotograma_0002.jpg,1.0,2026-07-06 14:36:24,-34.540777,-58.4506846,10.41,27.91,92.5,2.0
...
```

### 3. `fotogramas.geojson`
Contiene:
* Una entidad tipo **`LineString`** que representa la trayectoria completa recorrida.
* Entidades tipo **`Point`** individuales para cada fotograma con todos sus atributos (velocidad, rumbo, segundo, etc.).

### 4. `recorrido.gpx`
Archivo compatible con receptores Garmin, Google Earth y visores de rutas deportivas/viales.

---

## 🗺️ Cómo abrir los resultados en QGIS / ArcGIS

### Método A: Arrastrar y Soltar (GeoJSON o GPX)
1. Abre tu proyecto en **QGIS** o **ArcGIS Pro**.
2. Arrastra el archivo `fotogramas.geojson` directamente sobre el lienzo del mapa.
3. Se cargarán dos capas vectoriales: los puntos correspondientes a cada foto y la línea del recorrido vial.

### Método B: Fotos Georreferenciadas con Complementos
* **En QGIS:**
  1. Instala el complemento **ImportPhotos** desde *Complementos → Administrar e instalar complementos*.
  2. Haz clic en el ícono de *ImportPhotos* y selecciona la carpeta del video.
  3. Las fotos se ubicarán en el mapa con hipervínculos automáticos y marcadores que indican el rumbo hacia donde apuntaba la lente.
* **En ArcGIS Pro:**
  1. Utiliza la herramienta de geoprocesamiento **GeoTagged Photos To Points** (*Fotos geoetiquetadas a puntos*).
  2. Selecciona la carpeta y genera una Feature Class con las miniaturas adjuntas.

---

## 🖥️ Uso de la Interfaz Gráfica de Escritorio (`app.py`)

El repositorio incluye una aplicación visual completa para usuarios que prefieren trabajar con una interfaz gráfica interactiva:

```bat
# Ejecutar mediante el lanzador de Windows:
launch_gui.bat
```

*O ejecutando desde el entorno Python de QGIS:*
```bat
"C:\Program Files\QGIS 3.44.14\bin\python-qgis-ltr.bat" app.py
```

### Funcionalidades de la GUI:
* **Costura Anti-Desfasaje (Stitching estricto):** Sincronización estricta de marcas de tiempo PTS (`setpts=PTS-STARTPTS`) y apilado vertical (`vstack`) de las dos lentes de la GoPro MAX, eliminando saltos temporales entre lentes al girar la cámara.
* **Reframing 2D (Modo Plano):** Control de ángulo Yaw (-180° a 180°), Pitch, Roll y FOV con presets instantáneos (Vista Frontal, Trasera, Lateral Izquierda, Derecha, Cenital y Nadir).
* **Mosaicos Cubemap (Tiles 3x2):** Descomposición del video 360 en las 6 caras del cubo.
* **Inyector Google Spatial Media:** Inyecta automáticamente los metadatos esféricos (`sv3d`/`st3d`) en el contenedor MP4 para reproducción nativa en YouTube y visores VR.

---

## ❓ Preguntas Frecuentes y Solución de Problemas

#### 1. ¿Por qué el script dice `No se encontraron registros GPS válidos`?
Las cámaras GoPro requieren conectarse a los satélites GPS **antes** de comenzar a grabar. Si iniciaste la grabación en un estacionamiento subterráneo, bajo un túnel o inmediatamente después de encender la cámara antes del bloqueo de señal (ícono GPS en blanco sólido), el archivo no contendrá muestras de ubicación.

#### 2. ¿Cómo verifico manualmente que un JPG quedó georreferenciado?
* **En Windows:** Clic derecho sobre `fotograma_0001.jpg` → **Propiedades** → pestaña **Detalles** → bajar hasta la sección **GPS** (verás Latitud, Longitud y Altitud).
* **Por consola con ExifTool:**
  ```powershell
  exiftool.exe -s -GPS* -DateTimeOriginal fotograma_0001.jpg
  ```

#### 3. ¿El script modifica el video original?
No. El video original se abre exclusivamente en modo lectura. Todo el contenido generado se almacena de forma aislada en la nueva subcarpeta.

---

## 📤 Instrucciones para subir a GitHub

Para publicar este proyecto en tu cuenta de GitHub, ejecuta los siguientes comandos desde la terminal dentro de esta carpeta:

```powershell
# 1. Inicializar el repositorio Git local
git init

# 2. Configurar la rama principal
git branch -M main

# 3. Agregar todos los archivos (el .gitignore excluye automáticamente binarios y videos)
git add .

# 4. Registrar el commit inicial
git commit -m "Commit inicial: Suite GoPro2Geo de telemetria, georreferenciacion y GUI 360"

# 5. Vincular tu repositorio remoto de GitHub (reemplaza con tu URL)
git remote add origin https://github.com/TU_USUARIO/gopro2geo.git

# 6. Subir los archivos al repositorio
git push -u origin main
```

---

## 📄 Licencia

Este proyecto se distribuye bajo los términos de la **Licencia MIT**. Consulta el archivo [LICENSE](LICENSE) para más información.
