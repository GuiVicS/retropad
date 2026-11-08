"""Lógica do gerenciador de ROMs: listar, validar, gravar, renomear e apagar.

Não depende de Flask. Todas as funções recebem a pasta de ROMs, para poderem
ser testadas com uma pasta temporária.
"""
import json
import os
import re
import shutil
import unicodedata

CHUNK = 1024 * 1024  # 1 MB por vez, o arquivo nunca é carregado inteiro na memória
SYSTEM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Letras (inclusive acentuadas), números, espaço e pontuação comum em nomes de ROM.
BAD_CHARS = re.compile(r"[^\w\s.\-()\[\]!&',+]", re.UNICODE)
MAX_NAME_BYTES = 200


class RomError(Exception):
    """Erro com mensagem para o usuário e código HTTP."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- sistemas

def load_systems(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        key: {"name": v.get("name", key), "extensions": [x.lower() for x in v.get("extensions", [])]}
        for key, v in data.items()
    }


def system_dir(roms_dir, system):
    """Devolve o caminho real da pasta do sistema, garantindo que fica dentro de roms_dir."""
    if not isinstance(system, str) or not SYSTEM_RE.match(system):
        raise RomError("Sistema inválido")
    root = os.path.realpath(roms_dir)
    path = os.path.realpath(os.path.join(root, system))
    if os.path.dirname(path) != root:
        raise RomError("Sistema inválido")
    if not os.path.isdir(path):
        raise RomError("Sistema não encontrado", 404)
    return path


def extensions_for(systems, system):
    info = systems.get(system)
    if not info or not info["extensions"]:
        raise RomError(f"O sistema '{system}' não tem extensões configuradas em systems.json")
    return info["extensions"]


# ------------------------------------------------------------------- nomes

def sanitize_filename(name):
    """Limpa o nome enviado. Mantém espaços, acentos e ()[] para os nomes de ROM
    continuarem legíveis (e casando com scrapers); remove separadores de caminho,
    caracteres de controle e pontos no início."""
    if not isinstance(name, str):
        raise RomError("Nome de arquivo inválido")
    name = unicodedata.normalize("NFC", name.replace("\\", "/").split("/")[-1])
    name = BAD_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip().lstrip(".").strip()
    if name in ("", ".", ".."):
        raise RomError("Nome de arquivo inválido")
    if len(name.encode("utf-8")) > MAX_NAME_BYTES:
        stem, ext = os.path.splitext(name)
        stem = stem.encode("utf-8")[: MAX_NAME_BYTES - len(ext.encode("utf-8"))].decode("utf-8", "ignore")
        name = stem.rstrip() + ext
    return name


def check_extension(systems, system, filename):
    ext = os.path.splitext(filename)[1].lower()
    allowed = extensions_for(systems, system)
    if ext not in allowed:
        raise RomError(f"Extensão '{ext or '(nenhuma)'}' não aceita em {system}. Aceitas: {', '.join(allowed)}", 415)
    return ext


def rom_path(roms_dir, system, filename):
    """Caminho de uma ROM existente ou futura, garantido dentro da pasta do sistema."""
    base = system_dir(roms_dir, system)
    if (not isinstance(filename, str) or filename in ("", ".", "..")
            or "/" in filename or "\\" in filename or "\x00" in filename):
        raise RomError("Nome de arquivo inválido")
    path = os.path.realpath(os.path.join(base, filename))
    if os.path.dirname(path) != base:
        raise RomError("Nome de arquivo inválido")
    return path


# ------------------------------------------------------------------ espaço

def free_space(roms_dir):
    u = shutil.disk_usage(roms_dir)
    return {"total": u.total, "used": u.used, "free": u.free}


def check_space(roms_dir, needed, min_free):
    free = shutil.disk_usage(roms_dir).free
    if free - max(needed, 0) < min_free:
        raise RomError(
            f"Sem espaço suficiente: livre {free // 2**20} MB, arquivo {max(needed, 0) // 2**20} MB, "
            f"margem exigida {min_free // 2**20} MB", 507)


# -------------------------------------------------------------- assinaturas

def verify_signature(path, ext):
    """Confere o conteúdo para os formatos com assinatura conhecida."""
    with open(path, "rb") as fh:
        head = fh.read(16)
        if ext == ".zip" and not (head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06")):
            raise RomError("O arquivo não é um ZIP válido", 422)
        if ext == ".7z" and not head.startswith(b"7z\xbc\xaf\x27\x1c"):
            raise RomError("O arquivo não é um 7z válido", 422)
        if ext == ".chd" and not head.startswith(b"MComprHD"):
            raise RomError("O arquivo não é um CHD válido", 422)
        if ext == ".pbp" and not head.startswith(b"\x00PBP"):
            raise RomError("O arquivo não é um PBP válido", 422)
        if ext == ".iso":
            # ISO 9660 cozida (2048 B/setor) tem "CD001" em 0x8001;
            # imagem bruta (2352 B/setor) tem o mesmo marcador em 0x9319.
            for offset in (0x8001, 0x9319):
                fh.seek(offset)
                if fh.read(5) == b"CD001":
                    return
            raise RomError("O arquivo não parece uma ISO 9660 válida", 422)


# ----------------------------------------------------------------- listagem

def _is_rom(entry, allowed):
    return (entry.is_file() and not entry.name.startswith(".")
            and os.path.splitext(entry.name)[1].lower() in allowed)


def list_roms(roms_dir, systems, system):
    base = system_dir(roms_dir, system)
    allowed = set(systems.get(system, {}).get("extensions", []))
    out = []
    with os.scandir(base) as it:
        for entry in it:
            if _is_rom(entry, allowed):
                st = entry.stat()
                out.append({"name": entry.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    out.sort(key=lambda r: r["name"].casefold())
    return out


def list_systems(roms_dir, systems):
    """Subpastas de roms_dir com quantidade de ROMs e tamanho total (sem recursão)."""
    if not os.path.isdir(roms_dir):
        raise RomError(f"Pasta de ROMs não encontrada: {roms_dir}", 500)
    out = []
    with os.scandir(roms_dir) as it:
        for entry in it:
            if entry.name.startswith(".") or not entry.is_dir() or not SYSTEM_RE.match(entry.name):
                continue
            info = systems.get(entry.name)
            allowed = set(info["extensions"]) if info else set()
            count = size = 0
            with os.scandir(entry.path) as inner:
                for f in inner:
                    if _is_rom(f, allowed):
                        count += 1
                        size += f.stat().st_size
            out.append({
                "id": entry.name,
                "name": info["name"] if info else entry.name,
                "extensions": sorted(allowed),
                "configured": bool(info and info["extensions"]),
                "count": count,
                "size": size,
            })
    out.sort(key=lambda s: s["name"].casefold())
    return out


# ------------------------------------------------------------------ gravação

def prepare_upload(roms_dir, systems, system, raw_name, size, max_bytes, min_free):
    """Validações que não exigem ler o arquivo. Devolve (nome final, caminho, existe)."""
    system_dir(roms_dir, system)          # sistema inválido ou inexistente falha primeiro
    name = sanitize_filename(raw_name)
    check_extension(systems, system, name)
    if size is not None:
        if size > max_bytes:
            raise RomError(f"Arquivo maior que o limite de {max_bytes // 2**20} MB", 413)
        check_space(roms_dir, size, min_free)
    else:
        check_space(roms_dir, 0, min_free)
    path = rom_path(roms_dir, system, name)
    return name, path, os.path.lexists(path)


def save_stream(roms_dir, systems, system, raw_name, stream, size, max_bytes, min_free, overwrite=False):
    """Grava o fluxo em disco, em blocos, num arquivo .part e só então renomeia."""
    name, path, exists = prepare_upload(roms_dir, systems, system, raw_name, size, max_bytes, min_free)
    if exists and not overwrite:
        raise RomError(f"'{name}' já existe. Confirme para sobrescrever.", 409)

    ext = os.path.splitext(name)[1].lower()
    part = os.path.join(os.path.dirname(path), f".{name}.part")
    written = 0
    try:
        with open(part, "wb") as out:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise RomError(f"Arquivo maior que o limite de {max_bytes // 2**20} MB", 413)
                out.write(chunk)
        if written == 0:
            raise RomError("Arquivo vazio")
        verify_signature(part, ext)
        if os.path.lexists(path) and not overwrite:
            raise RomError(f"'{name}' já existe. Confirme para sobrescrever.", 409)
        os.replace(part, path)
    except OSError as exc:
        raise RomError(f"Erro ao gravar o arquivo: {exc.strerror or exc}", 500)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return {"name": name, "size": written, "overwritten": exists}


def delete_rom(roms_dir, systems, system, filename):
    path = rom_path(roms_dir, system, filename)
    check_extension(systems, system, filename)
    if not os.path.isfile(path):
        raise RomError("Arquivo não encontrado", 404)
    os.remove(path)


def rename_rom(roms_dir, systems, system, filename, new_name):
    old = rom_path(roms_dir, system, filename)
    check_extension(systems, system, filename)
    if not os.path.isfile(old):
        raise RomError("Arquivo não encontrado", 404)
    new_name = sanitize_filename(new_name)
    check_extension(systems, system, new_name)
    new = rom_path(roms_dir, system, new_name)
    if new == old:
        return new_name
    if os.path.lexists(new):
        raise RomError(f"'{new_name}' já existe", 409)
    os.rename(old, new)
    return new_name
