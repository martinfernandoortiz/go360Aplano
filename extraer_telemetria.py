#!/usr/bin/env python3
"""
GoPro2Geo - Extractor de Telemetría y Fotogramas (Soporta .360 y .MP4)
=====================================================================
Extrae la telemetría GPS (GPMF binario) de videos .360 y .mp4 de GoPro,
crea automáticamente una carpeta con el nombre del video, extrae los fotogramas,
calcula la correlación segundo a segundo con los fotogramas extraídos (fps configurable)
y genera archivos de exportación (CSV, GPX, GeoJSON) además de georreferenciar
las imágenes JPG directamente mediante ExifTool.

Soporta:
- Videos 360 (.360 o MP4 esférico): Proyección a plano (rectilíneo / flat) desde lente frontal fisheye.
- Videos 2D (.mp4 estándar / GoPro Hero): Extracción directa sin distorsión 360.
- Nomenclatura: <video>_<num_frame>.<ext>
- Registro temporal: Timestamp UTC, Hora Local y Momento del Día (Mañana, Tarde, Noche, etc.).
"""

import os
import sys
import struct
import subprocess
import datetime
import math
import json
import csv
import argparse
from typing import List, Dict, Any, Optional


class TelemetryPoint:
    def __init__(
        self,
        timestamp: Optional[datetime.datetime] = None,
        video_time_sec: float = 0.0,
        lat: float = 0.0,
        lon: float = 0.0,
        alt: float = 0.0,
        speed_2d: float = 0.0,
        speed_3d: float = 0.0,
        fix: int = 3,
        dop: float = 1.0,
        heading: float = 0.0
    ):
        self.timestamp = timestamp
        self.video_time_sec = video_time_sec
        self.lat = lat
        self.lon = lon
        self.alt = alt
        self.speed_2d = speed_2d
        self.speed_3d = speed_3d
        self.fix = fix
        self.dop = dop
        self.heading = heading


class GPMFParser:
    """Parser para flujos binarios GoPro GPMF (soporta GPS5 y GPS9)."""
    def __init__(self, raw_bytes: bytes):
        self.data = raw_bytes
        self.length = len(raw_bytes)

    def parse(self) -> List[TelemetryPoint]:
        points: List[TelemetryPoint] = []
        if self.length < 8:
            return points

        pos = 0
        current_scal = [1.0]
        current_gpsu: Optional[datetime.datetime] = None
        current_fix = 3
        current_dop = 1.0
        sample_interval = 0.1

        while pos + 8 <= self.length:
            if pos + 8 <= self.length and self.data[pos+4:pos+8] == b'DEVC':
                pos += 4

            fourcc = self.data[pos:pos+4]
            type_char = chr(self.data[pos+4]) if 32 <= self.data[pos+4] <= 126 else '?'
            sample_size = self.data[pos+5]
            repeat = struct.unpack(">H", self.data[pos+6:pos+8])[0]
            payload_len = sample_size * repeat
            padded_len = (payload_len + 3) & ~3
            val_start = pos + 8
            val_end = val_start + payload_len

            if val_end > self.length:
                break

            if fourcc == b'SCAL':
                scales = []
                try:
                    if type_char in ('s', 'S'):
                        count = payload_len // 2
                        scales = [float(x) for x in struct.unpack(f">{count}h", self.data[val_start:val_start + count*2])]
                    elif type_char in ('l', 'L'):
                        count = payload_len // 4
                        scales = [float(x) for x in struct.unpack(f">{count}i", self.data[val_start:val_start + count*4])]
                    elif type_char in ('f', 'F'):
                        count = payload_len // 4
                        scales = [float(x) for x in struct.unpack(f">{count}f", self.data[val_start:val_start + count*4])]
                except Exception:
                    pass
                if scales:
                    current_scal = scales

            elif fourcc == b'GPSU':
                try:
                    time_str = self.data[val_start:val_end].decode("ascii", errors="ignore").strip()
                    if len(time_str) >= 12:
                        y = int("20" + time_str[0:2])
                        m = int(time_str[2:4])
                        d = int(time_str[4:6])
                        H = int(time_str[6:8])
                        M = int(time_str[8:10])
                        S = int(time_str[10:12])
                        ms = int(float("0." + time_str[13:]) * 1000000) if "." in time_str else 0
                        current_gpsu = datetime.datetime(y, m, d, H, M, S, ms, tzinfo=datetime.timezone.utc)
                except Exception:
                    pass

            elif fourcc == b'GPSF':
                if payload_len >= 4:
                    try:
                        current_fix = struct.unpack(">I", self.data[val_start:val_start+4])[0]
                    except Exception:
                        pass

            elif fourcc == b'GPSP':
                if payload_len >= 2:
                    try:
                        current_dop = struct.unpack(">H", self.data[val_start:val_start+2])[0] / 100.0
                    except Exception:
                        pass

            elif fourcc == b'GPS5':
                scale_lat = current_scal[0] if len(current_scal) > 0 else 1.0
                scale_lon = current_scal[1] if len(current_scal) > 1 else scale_lat
                scale_alt = current_scal[2] if len(current_scal) > 2 else 1.0
                scale_spd2 = current_scal[3] if len(current_scal) > 3 else 1.0
                scale_spd3 = current_scal[4] if len(current_scal) > 4 else 1.0

                for i in range(repeat):
                    offset = val_start + i * 20
                    if offset + 20 <= val_end:
                        try:
                            raw_vals = struct.unpack(">5i", self.data[offset:offset+20])
                            lat = raw_vals[0] / scale_lat
                            lon = raw_vals[1] / scale_lon
                            alt = raw_vals[2] / scale_alt
                            spd2 = raw_vals[3] / scale_spd2
                            spd3 = raw_vals[4] / scale_spd3

                            if abs(lat) > 0.0001 or abs(lon) > 0.0001:
                                pt_time = current_gpsu + datetime.timedelta(seconds=i * sample_interval) if current_gpsu else None
                                pt = TelemetryPoint(
                                    timestamp=pt_time,
                                    lat=lat, lon=lon, alt=alt,
                                    speed_2d=spd2, speed_3d=spd3,
                                    fix=current_fix, dop=current_dop
                                )
                                points.append(pt)
                        except Exception:
                            pass

            elif fourcc == b'GPS9':
                scale_lat = current_scal[0] if len(current_scal) > 0 else 1.0
                scale_lon = current_scal[1] if len(current_scal) > 1 else scale_lat
                scale_alt = current_scal[2] if len(current_scal) > 2 else 1.0
                scale_spd = current_scal[3] if len(current_scal) > 3 else 1.0
                scale_spd3 = current_scal[4] if len(current_scal) > 4 else 1.0
                scale_msec = current_scal[6] if len(current_scal) > 6 else 1000.0
                item_sz = sample_size if sample_size >= 32 else 32

                for i in range(repeat):
                    offset = val_start + i * item_sz
                    if offset + 32 <= val_end:
                        try:
                            raw_vals = struct.unpack(">5iIIHH", self.data[offset:offset+32])
                            lat = raw_vals[0] / scale_lat
                            lon = raw_vals[1] / scale_lon
                            alt = raw_vals[2] / scale_alt
                            spd2 = raw_vals[3] / scale_spd
                            spd3 = raw_vals[4] / scale_spd3
                            days = raw_vals[5]
                            msecs = raw_vals[6] / scale_msec
                            dop_val = raw_vals[7] / 100.0
                            fix_val = raw_vals[8]

                            if abs(lat) > 0.0001 or abs(lon) > 0.0001:
                                if days > 0:
                                    pt_time = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=days, seconds=msecs)
                                elif current_gpsu:
                                    pt_time = current_gpsu + datetime.timedelta(seconds=i * sample_interval)
                                else:
                                    pt_time = None

                                pt = TelemetryPoint(
                                    timestamp=pt_time,
                                    lat=lat, lon=lon, alt=alt,
                                    speed_2d=spd2, speed_3d=spd3,
                                    fix=fix_val, dop=dop_val
                                )
                                points.append(pt)
                        except Exception:
                            pass

            if sample_size == 0 or type_char == '\0' or fourcc in (b'DEVC', b'STRM'):
                pos += 8
            else:
                pos += 8 + padded_len

        if points and points[0].timestamp:
            t0 = points[0].timestamp
            for p in points:
                if p.timestamp:
                    p.video_time_sec = (p.timestamp - t0).total_seconds()
        else:
            for idx, p in enumerate(points):
                p.video_time_sec = idx * sample_interval

        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            lat1, lon1 = math.radians(p1.lat), math.radians(p1.lon)
            lat2, lon2 = math.radians(p2.lat), math.radians(p2.lon)
            dlon = lon2 - lon1
            x = math.sin(dlon) * math.cos(lat2)
            y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
            p1.heading = (math.degrees(math.atan2(x, y)) + 360) % 360

        if points:
            points[-1].heading = points[-2].heading if len(points) > 1 else 0.0

        return points


def extract_gpmf_with_ffmpeg(input_file: str, ffmpeg_exe: str = "ffmpeg") -> bytes:
    """Extrae el stream binario GPMF sin decodificar video (toma ~1 segundo)."""
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", input_file,
        "-codec", "copy",
        "-map", "0:d:m:handler_name:GoPro MET?",
        "-f", "rawvideo",
        "-"
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if len(p.stdout) > 0:
        return p.stdout

    cmd_fallback = [
        ffmpeg_exe, "-y", "-i", input_file,
        "-codec", "copy", "-map", "0:d?", "-f", "rawvideo", "-"
    ]
    p = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stdout


def obtener_momento_dia(dt: datetime.datetime) -> str:
    """Clasifica el horario en rangos del día."""
    h = dt.hour + dt.minute / 60.0
    if 0.0 <= h < 6.0:
        return "Madrugada"
    elif 6.0 <= h < 12.0:
        return "Mañana"
    elif 12.0 <= h < 14.0:
        return "Mediodía"
    elif 14.0 <= h < 19.5:
        return "Tarde"
    else:
        return "Noche"


def extract_frames_if_needed(
    video_path: str,
    output_dir: str,
    pattern: str,
    fps: float = 2.0,
    mode: str = "auto",
    h_fov: float = 55.0,
    v_fov: Optional[float] = 32.6,
    width: int = 3840,
    height: int = 2160,
    proj: str = "rectilinear",
    pitch: float = 0.0,
    yaw: float = 0.0,
    roll: float = 0.0,
    force: bool = True,
    quality: int = 100,
    img_format: str = "jpg",
    ffmpeg_exe: str = "ffmpeg"
) -> int:
    """Extrae fotogramas con FFmpeg respetando el nuevo patrón con nombre concatenado."""
    ext_img = "." + img_format.lower()
    existing = [f for f in os.listdir(output_dir) if f.lower().endswith(ext_img)]
    if existing and not force:
        print(f"      Se encontraron {len(existing)} fotogramas en '{output_dir}'. Omitiendo extracción.")
        print(f"      [TIP] Usa el parámetro --force para re-extraer.")
        return len(existing)
    elif existing and force:
        print(f"      Re-extracción activa: actualizando fotogramas anteriores en '{output_dir}'...")
        for f in existing:
            try:
                os.remove(os.path.join(output_dir, f))
            except Exception:
                pass

    ext = os.path.splitext(video_path)[1].lower()
    is_360 = (mode == "360") or (mode == "auto" and ext == ".360")

    out_pattern = os.path.join(output_dir, pattern)

    if is_360:
        angles = ""
        if pitch != 0.0:
            angles += f":pitch={pitch}"
        if yaw != 0.0:
            angles += f":yaw={yaw}"
        if roll != 0.0:
            angles += f":roll={roll}"

        v_fov_str = f":v_fov={v_fov}" if v_fov is not None else ""
        vf_filter = f"v360=input=fisheye:id_fov=180:output={proj}:h_fov={h_fov}{v_fov_str}:w={width}:h={height}:interp=lanczos{angles},fps={fps}"
        vf_desc = f"v_fov={v_fov}°" if v_fov is not None else "v_fov=auto(16:9)"
        print(f"      Modo: VIDEO 360 Fisheye (proy {proj}, h_fov={h_fov}°, {vf_desc}, {width}x{height} a {fps} fps, lanczos)...")
        print(f"      Filtro FFmpeg: {vf_filter}")
        cmd = [ffmpeg_exe, "-y", "-i", video_path, "-map", "0:v:0", "-vf", vf_filter]
    else:
        print(f"      Modo: VIDEO PLANO / MP4 (extracción directa a {fps} fps)...")
        vf_filter = f"fps={fps}"
        cmd = [ffmpeg_exe, "-y", "-i", video_path, "-vf", vf_filter]

    if img_format.lower() == "png":
        cmd.extend(["-compression_level", "3"])
        fmt_desc = "PNG (100% lossless)"
    else:
        q_val = 1 if quality >= 98 else max(1, min(31, round((100 - quality) * 0.2 + 1)))
        cmd.extend(["-q:v", str(q_val)])
        fmt_desc = f"JPEG (calidad {quality}%, -q:v {q_val})" if quality < 98 else "JPEG (máxima calidad 100% / q:1)"

    cmd.append(out_pattern)
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    created = [f for f in os.listdir(output_dir) if f.lower().endswith(ext_img)]
    print(f"      [OK] Extraídos {len(created)} fotogramas en formato {fmt_desc}.")
    return len(created)


def export_gpx(points: List[TelemetryPoint], output_path: str, name: str = "GoPro Track"):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="GoPro2Geo" xmlns="http://www.topografix.com/GPX/1/1">',
        '  <trk>',
        f'    <name>{name}</name>',
        '    <trkseg>'
    ]
    for p in points:
        t_str = f"<time>{p.timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')}</time>" if p.timestamp else ""
        lines.append(
            f'      <trkpt lat="{p.lat:.7f}" lon="{p.lon:.7f}">'
            f'<ele>{p.alt:.2f}</ele>{t_str}'
            f'<speed>{p.speed_2d:.2f}</speed>'
            f'</trkpt>'
        )
    lines.extend(['    </trkseg>', '  </trk>', '</gpx>'])
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def export_geojson(frame_rows: List[Dict[str, Any]], all_points: List[TelemetryPoint], output_path: str):
    coords_line = [[round(p.lon, 7), round(p.lat, 7), round(p.alt, 2)] for p in all_points]
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords_line},
            "properties": {"tipo": "Trayectoria_Completa", "total_puntos": len(all_points)}
        }
    ]
    for row in frame_rows:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["longitud"], row["latitud"], row["altitud_m"]]
            },
            "properties": row
        })
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=2, ensure_ascii=False)


def main():
    default_video = r"\\ausafs\Repositorio GIS\01-Recorridos GoPro\01-Videos\16-videos 360 8K (JUNIO26)\ACA-AV.CANTILO\260713-ACA-RAE-B-SUBIDACOLECTORACANTILO-8K.360"
    
    parser = argparse.ArgumentParser(description="Extraer telemetría GPMF para fotogramas de video GoPro (.360 o .MP4)")
    parser.add_argument("--video", "-v", default=default_video, help="Ruta al video (.360 o .mp4)")
    parser.add_argument("--mode", "-m", choices=["auto", "360", "flat"], default="auto",
                        help="Modo de video: 'auto', '360' o 'flat'")
    parser.add_argument("--fps", type=float, default=2.0, help="FPS usado al extraer los fotogramas (por defecto 2.0)")
    parser.add_argument("--frames-dir", "-d", default="auto", help="Carpeta destino")
    parser.add_argument("--pattern", "-p", default=None,
                        help="Patrón de fotogramas opcional. Si no se pasa, usa: '<nombre_video>_%04d.jpg'")
    parser.add_argument("--telemetry-source", "-t", default=None,
                        help="Video alternativo desde donde extraer la telemetría")
    parser.add_argument("--tz-offset", type=float, default=-3.0,
                        help="Offset de zona horaria local respecto a UTC en horas (por defecto -3.0 para Argentina)")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Ruta a ffmpeg.exe")
    parser.add_argument("--exiftool", default="exiftool", help="Ruta a exiftool.exe")
    parser.add_argument("--skip-frames", action="store_true", help="No extraer fotogramas con ffmpeg")
    parser.add_argument("--skip-exif", action="store_true", help="No escribir metadatos en las imágenes")
    parser.add_argument("--format", "--fmt", choices=["jpg", "png"], default="jpg",
                        help="Formato de imagen de salida: 'jpg' o 'png'")
    parser.add_argument("--quality", "-q", type=int, default=100,
                        help="Calidad de compresión JPEG (1-100)")
    parser.add_argument("--lossless", "--png", dest="lossless", action="store_true",
                        help="Extraer fotogramas PNG lossless")
    parser.add_argument("--force", "-f", action="store_true", default=True, help="Re-extraer fotogramas siempre")
    parser.add_argument("--no-force", dest="force", action="store_false", help="Omitir extracción si ya existen fotogramas")
    parser.add_argument("--h-fov", "--fov", dest="h_fov", type=float, default=55.0, help="Campo visual horizontal en grados")
    parser.add_argument("--v-fov", dest="v_fov", type=float, default=32.6, help="Campo visual vertical en grados")
    parser.add_argument("--width", "-W", type=int, default=3840, help="Ancho en píxeles")
    parser.add_argument("--height", "-H", type=int, default=2160, help="Alto en píxeles")
    parser.add_argument("--proj", choices=["rectilinear", "flat", "pannini", "cylindrical"], default="rectilinear", help="Tipo de proyección")
    parser.add_argument("--pitch", type=float, default=0.0, help="Inclinación vertical en grados")
    parser.add_argument("--yaw", type=float, default=0.0, help="Rotación horizontal en grados")
    parser.add_argument("--roll", type=float, default=0.0, help="Nivelación angular en grados")

    args = parser.parse_args()

    if args.lossless:
        args.format = "png"

    # Detectar ejecutables
    ffmpeg_exe = args.ffmpeg
    if not os.path.isabs(ffmpeg_exe):
        for candidate in ["ffmpeg.exe", r"C:\Users\mfortiz\Documents\ffmpeg\ffmpeg.exe"]:
            if os.path.exists(candidate):
                ffmpeg_exe = candidate
                break

    exiftool_exe = args.exiftool
    if not os.path.isabs(exiftool_exe):
        for candidate in ["exiftool.exe", r"C:\Users\mfortiz\Documents\ffmpeg\exiftool.exe"]:
            if os.path.exists(candidate):
                exiftool_exe = candidate
                break

    if not os.path.exists(args.video):
        print(f"\n[ERROR] No se puede acceder al video: {args.video}")
        sys.exit(1)

    # Determinar nombre base y carpeta destino
    video_base = os.path.splitext(os.path.basename(args.video))[0]
    if args.frames_dir == "auto" or not args.frames_dir:
        frames_dir = os.path.abspath(video_base)
    else:
        frames_dir = os.path.abspath(args.frames_dir)

    os.makedirs(frames_dir, exist_ok=True)

    # Patrón con nombre de archivo concatenado: <nombre_video>_%04d.<ext>
    if args.pattern:
        pattern = args.pattern
    else:
        pattern = f"{video_base}_%04d.{args.format}"

    # Archivo desde donde se extrae la telemetría
    tel_video = args.telemetry_source if args.telemetry_source and os.path.exists(args.telemetry_source) else args.video

    v_desc = f"{args.v_fov}°" if args.v_fov is not None else "auto(16:9)"
    if args.format == "png":
        fmt_desc = "PNG (100% lossless)"
    else:
        q_val = 1 if args.quality >= 98 else max(1, min(31, round((100 - args.quality) * 0.2 + 1)))
        fmt_desc = f"JPEG (calidad {args.quality}%, -q:v {q_val})" if args.quality < 98 else "JPEG (máxima calidad 100% / q:1)"

    print("=" * 70)
    print(" GoPro2Geo - Extractor de Telemetría para Fotogramas (.360 / .MP4)")
    print("=" * 70)
    print(f"Video imagen    : {args.video}")
    print(f"Patrón nombres  : {pattern}")
    print(f"Modo proyección : {args.mode} (proy: {args.proj}, h_fov: {args.h_fov}°, v_fov: {v_desc}, {args.width}x{args.height})")
    print(f"Carpeta destino : {frames_dir}")
    print(f"Tasa fotogramas : {args.fps} fps")
    print(f"Formato imagen  : {fmt_desc}")

    # [1/4] Extracción de fotogramas
    if not args.skip_frames:
        print("\n[1/4] Verificando / Extrayendo fotogramas con FFmpeg...")
        extract_frames_if_needed(
            video_path=args.video,
            output_dir=frames_dir,
            pattern=pattern,
            fps=args.fps,
            mode=args.mode,
            h_fov=args.h_fov,
            v_fov=args.v_fov,
            width=args.width,
            height=args.height,
            proj=args.proj,
            pitch=args.pitch,
            yaw=args.yaw,
            roll=args.roll,
            force=args.force,
            quality=args.quality,
            img_format=args.format,
            ffmpeg_exe=ffmpeg_exe
        )
    else:
        print("\n[1/4] Omitiendo extracción de fotogramas (--skip-frames activo).")

    # [2/4] Extracción de telemetría GPMF
    print(f"\n[2/4] Extrayendo flujo de telemetría GPMF desde '{os.path.basename(tel_video)}'...")
    raw_gpmf = extract_gpmf_with_ffmpeg(tel_video, ffmpeg_exe)
    if not raw_gpmf:
        print("\n[ADVERTENCIA] No se detectó flujo GPMF en este archivo.")
        sys.exit(1)
    print(f"      Stream extraído: {len(raw_gpmf):,} bytes.")

    print("\n[3/4] Decodificando muestras GPS y calculando momento del día...")
    parser_gpmf = GPMFParser(raw_gpmf)
    all_points = parser_gpmf.parse()
    if not all_points:
        print("[ERROR] No se encontraron registros GPS válidos en la telemetría.")
        sys.exit(1)

    duration_sec = all_points[-1].video_time_sec
    print(f"      Puntos GPS decodificados: {len(all_points)}")
    print(f"      Duración registrada      : {duration_sec:.2f} segundos")

    total_frames = int(duration_sec * args.fps) + 1
    frame_rows = []
    exif_rows = []
    tz_local = datetime.timezone(datetime.timedelta(hours=args.tz_offset))

    for frame_idx in range(1, total_frames + 1):
        target_sec = (frame_idx - 1) / args.fps
        closest_pt = min(all_points, key=lambda p: abs(p.video_time_sec - target_sec))
        fname = pattern % frame_idx

        # Procesar tiempos y momento del día
        if closest_pt.timestamp:
            ts_utc = closest_pt.timestamp
            ts_local = ts_utc.astimezone(tz_local)
            momento_dia = obtener_momento_dia(ts_local)
            str_utc = ts_utc.strftime("%Y-%m-%d %H:%M:%S")
            str_local = ts_local.strftime("%Y-%m-%d %H:%M:%S")
            str_hora = ts_local.strftime("%H:%M:%S")
        else:
            str_utc = ""
            str_local = ""
            str_hora = ""
            momento_dia = "Desconocido"

        row_info = {
            "fotograma": fname,
            "numero_frame": frame_idx,
            "segundo": round(target_sec, 2),
            "timestamp_utc": str_utc,
            "timestamp_local": str_local,
            "hora_local": str_hora,
            "momento_dia": momento_dia,
            "latitud": round(closest_pt.lat, 7),
            "longitud": round(closest_pt.lon, 7),
            "altitud_m": round(closest_pt.alt, 2),
            "velocidad_kmh": round(closest_pt.speed_2d * 3.6, 2),
            "rumbo_deg": round(closest_pt.heading, 1),
            "dop": round(closest_pt.dop, 2)
        }
        frame_rows.append(row_info)

        full_img_path = os.path.abspath(os.path.join(frames_dir, fname)).replace("\\", "/")
        exif_rows.append({
            "SourceFile": full_img_path,
            "GPSLatitude": round(closest_pt.lat, 7),
            "GPSLongitude": round(closest_pt.lon, 7),
            "GPSAltitude": round(closest_pt.alt, 2),
            "GPSLatitudeRef": "S" if closest_pt.lat < 0 else "N",
            "GPSLongitudeRef": "W" if closest_pt.lon < 0 else "E",
            "GPSAltitudeRef": 0,
            "GPSImgDirection": round(closest_pt.heading, 1),
            "GPSImgDirectionRef": "T",
            "GPSSpeed": round(closest_pt.speed_2d * 3.6, 2),
            "GPSSpeedRef": "K",
            "DateTimeOriginal": str_local if str_local else str_utc
        })

    # Guardar CSV GIS
    csv_gis_path = os.path.join(frames_dir, "telemetria_fotogramas.csv")
    with open(csv_gis_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(frame_rows[0].keys()))
        writer.writeheader()
        writer.writerows(frame_rows)
    print(f"      [OK] Tabla GIS generada     : {csv_gis_path}")

    # Guardar CSV ExifTool
    csv_exif_path = os.path.join(frames_dir, "telemetria_exiftool.csv")
    with open(csv_exif_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(exif_rows[0].keys()))
        writer.writeheader()
        writer.writerows(exif_rows)

    # GPX y GeoJSON
    gpx_path = os.path.join(frames_dir, "recorrido.gpx")
    export_gpx(all_points, gpx_path, name=video_base)
    print(f"      [OK] GPX generado           : {gpx_path}")

    geojson_path = os.path.join(frames_dir, "fotogramas.geojson")
    export_geojson(frame_rows, all_points, geojson_path)
    print(f"      [OK] GeoJSON generado       : {geojson_path}")

    # [4/4] Inyección de metadatos EXIF
    if not args.skip_exif:
        ext_target = f".{args.format}"
        img_found = [f for f in os.listdir(frames_dir) if f.lower().endswith(ext_target)]
        if img_found:
            print(f"\n[4/4] Inyectando metadatos GPS en {len(img_found)} fotogramas con ExifTool...")
            exif_cmd = [
                exiftool_exe,
                f"-csv={csv_exif_path}",
                "-overwrite_original",
                "-ext", args.format,
                frames_dir
            ]
            res = subprocess.run(exif_cmd, capture_output=True, text=True)
            output_msg = (res.stderr + "\n" + res.stdout).strip()
            for line in output_msg.splitlines():
                if "updated" in line or "image files" in line:
                    print("      " + line.strip())
            print(f"      [OK] Metadatos inyectados exitosamente.")
        else:
            print(f"\n[4/4] No se encontraron fotogramas para inyectar EXIF.")

    print("\n" + "=" * 70)
    print(f" Proceso finalizado. Todo guardado en: {frames_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()