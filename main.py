"""
VuliBeats — PC -> phone music relay + offline player host. Nice!111!!1
"""
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shutil
import threading

from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory

try:
    from mutagen import File as MutagenFile
    from mutagen.mp4 import MP4
except Exception:  # pragma: no cover - mutagen is in requirements
    MutagenFile = None
    MP4 = None

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR", os.path.join(BASE, "data"))
SECRET = os.environ.get("SECRET_KEY", "vulibeats-fallback-secret-set-SECRET_KEY-on-render")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 600 * 1024 * 1024  # per-request cap; files upload one at a time
_lock = threading.Lock()


# ---------------- auth (stateless) ----------------
def _sign(uid: str) -> str:
    return hmac.new(SECRET.encode(), uid.encode(), hashlib.sha256).hexdigest()[:32]


def make_token(username: str, password: str) -> str:
    uid = hashlib.sha256(f"{username.strip().lower()}:{password}".encode()).hexdigest()[:16]
    return f"{uid}.{_sign(uid)}"


def auth_uid():
    """Return the caller's uid or abort 401."""
    token = request.headers.get("X-Token", "")
    parts = token.split(".")
    if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{16}", parts[0]) and hmac.compare_digest(parts[1], _sign(parts[0])):
        return parts[0]
    abort(401, description="bad token")


# ---------------- per-user library on disk ----------------
def udir(uid: str) -> str:
    return os.path.join(DATA, uid)


def lib_path(uid: str) -> str:
    return os.path.join(udir(uid), "library.json")


def load_lib(uid: str) -> dict:
    try:
        with open(lib_path(uid), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_lib(uid: str, lib: dict):
    os.makedirs(udir(uid), exist_ok=True)
    tmp = lib_path(uid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False)
    os.replace(tmp, lib_path(uid))


def file_path(uid: str, rec: dict) -> str:
    return os.path.join(udir(uid), "f", f"{rec['id']}.{rec['ext']}")


def art_path(uid: str, tid: str) -> str:
    return os.path.join(udir(uid), "a", tid)


# ---------------- metadata extraction ----------------
def extract_meta(path: str, orig_name: str) -> dict:
    title = artist = album = None
    duration = 0.0
    art = None
    art_mime = "image/jpeg"

    if MutagenFile is not None:
        try:
            easy = MutagenFile(path, easy=True)
            if easy is not None:
                duration = float(getattr(easy.info, "length", 0) or 0)
                get = lambda k: (easy.get(k) or [None])[0]
                title, artist, album = get("title"), get("artist"), get("album")
        except Exception:
            pass
        try:
            f = MutagenFile(path)
            if f is not None:
                if not duration:
                    duration = float(getattr(f.info, "length", 0) or 0)
                if MP4 is not None and isinstance(f, MP4):
                    covr = (f.tags or {}).get("covr") or []
                    if covr:
                        art = bytes(covr[0])
                        art_mime = "image/png" if getattr(covr[0], "imageformat", 13) == 14 else "image/jpeg"
                elif getattr(f, "pictures", None):  # FLAC
                    p = f.pictures[0]
                    art, art_mime = p.data, (p.mime or "image/jpeg")
                elif f.tags is not None and hasattr(f.tags, "getall"):  # ID3 (mp3, wav, aiff)
                    apics = f.tags.getall("APIC")
                    if apics:
                        art, art_mime = apics[0].data, (apics[0].mime or "image/jpeg")
                elif f.tags is not None:  # ogg vorbis/opus base64 picture blocks
                    import base64
                    from mutagen.flac import Picture
                    for b64 in (f.tags.get("metadata_block_picture") or []):
                        try:
                            p = Picture(base64.b64decode(b64))
                            art, art_mime = p.data, (p.mime or "image/jpeg")
                            break
                        except Exception:
                            continue
        except Exception:
            pass

    base = re.sub(r"\.[^.]*$", "", orig_name)
    if not title:
        m = re.match(r"^(.{1,80}?)\s+-\s+(.+)$", base)
        if m and not artist:
            artist, title = m.group(1).strip(), m.group(2).strip()
        else:
            title = base
    return {
        "title": title or base,
        "artist": artist or "",
        "album": album or "",
        "duration": round(duration, 2),
        "art": art,
        "artMime": art_mime,
    }


# ---------------- pages ----------------
@app.get("/")
def page_player():
    return render_template("index.html")


@app.get("/pc")
def page_pc():
    return render_template("pc.html")


@app.get("/sw.js")
def sw():  # service worker must be served from the root scope
    return send_from_directory(os.path.join(BASE, "static"), "sw.js", mimetype="text/javascript")


# ---------------- api ----------------
@app.post("/api/login")
def api_login():
    d = request.get_json(silent=True) or {}
    u, p = str(d.get("username", "")).strip(), str(d.get("password", ""))
    if not re.fullmatch(r"[\w .\-]{1,32}", u):
        return jsonify(error="Username: 1-32 letters/numbers/spaces"), 400
    if not (1 <= len(p) <= 128):
        return jsonify(error="Password required"), 400
    return jsonify(token=make_token(u, p), username=u)


@app.get("/api/ping")
def api_ping():
    return jsonify(ok=True)


@app.get("/api/manifest")
def api_manifest():
    uid = auth_uid()
    lib = load_lib(uid)
    tracks = sorted(lib.values(), key=lambda r: r.get("at", 0))
    return jsonify(tracks=tracks, count=len(tracks))


@app.post("/api/upload")
def api_upload():
    uid = auth_uid()
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify(error="no file"), 400
    name = f.filename.replace("\\", "/").split("/")[-1]
    ext_m = re.search(r"\.([A-Za-z0-9]{1,5})$", name)
    ext = (ext_m.group(1).lower() if ext_m else "bin")

    os.makedirs(os.path.join(udir(uid), "f"), exist_ok=True)
    tmp = os.path.join(udir(uid), "f", f"_up_{threading.get_ident()}.tmp")
    f.save(tmp)
    size = os.path.getsize(tmp)
    tid = hashlib.sha1(f"{name}|{size}".encode()).hexdigest()[:12]
    rec = {"id": tid, "name": name, "size": size, "ext": ext, "at": int(os.path.getmtime(tmp))}

    meta = extract_meta(tmp, name)
    rec.update(title=meta["title"], artist=meta["artist"], album=meta["album"],
               duration=meta["duration"], hasArt=bool(meta["art"]), artMime=meta["artMime"])
    os.replace(tmp, file_path(uid, rec))
    if meta["art"]:
        os.makedirs(os.path.join(udir(uid), "a"), exist_ok=True)
        with open(art_path(uid, tid), "wb") as fh:
            fh.write(meta["art"])

    with _lock:
        lib = load_lib(uid)
        lib[tid] = rec
        save_lib(uid, lib)
    return jsonify(track=rec)


@app.get("/api/file/<tid>")
def api_file(tid):
    uid = auth_uid()
    rec = load_lib(uid).get(tid)
    if not rec:
        abort(404)
    path = file_path(uid, rec)
    if not os.path.exists(path):
        abort(404)
    mime = mimetypes.guess_type(rec["name"])[0] or "application/octet-stream"
    return send_file(path, mimetype=mime, conditional=True, download_name=rec["name"])


@app.get("/api/art/<tid>")
def api_art(tid):
    uid = auth_uid()
    rec = load_lib(uid).get(tid)
    if not rec or not rec.get("hasArt"):
        abort(404)
    path = art_path(uid, tid)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype=rec.get("artMime") or "image/jpeg", conditional=True)


@app.delete("/api/file/<tid>")
def api_delete(tid):
    uid = auth_uid()
    with _lock:
        lib = load_lib(uid)
        rec = lib.pop(tid, None)
        if rec:
            save_lib(uid, lib)
    if rec:
        for p in (file_path(uid, rec), art_path(uid, tid)):
            try:
                os.remove(p)
            except OSError:
                pass
    return jsonify(ok=True)


@app.post("/api/clear")
def api_clear():
    uid = auth_uid()
    with _lock:
        shutil.rmtree(udir(uid), ignore_errors=True)
    return jsonify(ok=True)


@app.errorhandler(401)
def e401(e):
    return jsonify(error="unauthorized"), 401


@app.errorhandler(413)
def e413(e):
    return jsonify(error="file too large"), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8614)), debug=False)
