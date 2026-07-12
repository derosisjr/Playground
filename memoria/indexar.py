# -*- coding: utf-8 -*-
"""Memória institucional do gabinete — indexação do acervo.

Consolida num único índice pesquisável (memoria.sqlite, com FTS5) tudo que o
gabinete produziu/recebeu:
  - resposta_executivo: PDFs de pedidos e respostas arquivados no Drive
    (uma subpasta por item, criadas pela automação respostas-executivo);
  - dom: atos do Diário Oficial capturados pelo monitor (diario.sqlite);
  - requerimento: requerimentos-index.json (raiz);
  - propositura: proposituras do vereador em proposituras-index.json.

FERRAMENTA INTERNA: memoria.sqlite e memoria-index.json ficam no .gitignore —
nada disso vai ao site público.

Uso:
  python memoria/indexar.py                        # tudo
  python memoria/indexar.py --origem drive --limite 20   # amostra
  python memoria/indexar.py --origem locais --dry-run
"""
import argparse
import importlib.util
import io
import os
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memoria.sqlite")
# Pasta-raiz das respostas do Executivo no Drive (mesma da automação).
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "1vkphPvia5SUcK7dXG8hwpTttAWGLqTja")


def _mod_respostas():
    """Importa respostas-executivo/index.py (diretório com hífen) p/ reusar o OAuth."""
    caminho = os.path.join(RAIZ, "respostas-executivo", "index.py")
    spec = importlib.util.spec_from_file_location("respostas_executivo", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def conectar():
    conn = sqlite3.connect(BASE)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documentos(
            id TEXT PRIMARY KEY, origem TEXT, titulo TEXT, data TEXT,
            url TEXT, md5 TEXT, texto TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
            titulo, texto, content=documentos, content_rowid=rowid,
            tokenize='unicode61 remove_diacritics 2');
        CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documentos BEGIN
            INSERT INTO docs_fts(rowid, titulo, texto)
            VALUES (new.rowid, new.titulo, new.texto);
        END;
        CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documentos BEGIN
            INSERT INTO docs_fts(docs_fts, rowid, titulo, texto)
            VALUES ('delete', old.rowid, old.titulo, old.texto);
        END;
        CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documentos BEGIN
            INSERT INTO docs_fts(docs_fts, rowid, titulo, texto)
            VALUES ('delete', old.rowid, old.titulo, old.texto);
            INSERT INTO docs_fts(rowid, titulo, texto)
            VALUES (new.rowid, new.titulo, new.texto);
        END;
    """)
    return conn


def _gravar(conn, doc: dict, dry_run: bool):
    if dry_run:
        print(f"  [{doc['origem']}] {doc['titulo'][:80]} — {len(doc.get('texto') or '')} chars")
        return
    conn.execute(
        "INSERT INTO documentos(id, origem, titulo, data, url, md5, texto) "
        "VALUES (:id, :origem, :titulo, :data, :url, :md5, :texto) "
        "ON CONFLICT(id) DO UPDATE SET titulo=:titulo, data=:data, url=:url, "
        "md5=:md5, texto=:texto", doc)


# ── Drive: PDFs de pedidos e respostas ───────────────────────────────────────
def _listar_subpastas(drive, pasta_id: str) -> list[dict]:
    pastas, token = [], None
    while True:
        res = drive.files().list(
            q=f"'{pasta_id}' in parents and trashed = false "
              "and mimeType = 'application/vnd.google-apps.folder'",
            fields="nextPageToken, files(id, name)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            pageToken=token, pageSize=1000,
        ).execute()
        pastas.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            return pastas


def _listar_pdfs(drive, pasta_id: str) -> list[dict]:
    res = drive.files().list(
        q=f"'{pasta_id}' in parents and trashed = false "
          "and mimeType != 'application/vnd.google-apps.folder'",
        fields="files(id, name, webViewLink, createdTime, md5Checksum)",
        supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=100,
    ).execute()
    return res.get("files", [])


def _texto_pdf(dados: bytes) -> str:
    import fitz  # PyMuPDF
    try:
        with fitz.open(stream=dados, filetype="pdf") as pdf:
            return "\n".join(p.get_text() for p in pdf).strip()
    except Exception:  # noqa: BLE001 — PDF corrompido não derruba a carga
        return ""


def indexar_drive(conn, limite=None, dry_run=False) -> int:
    from googleapiclient.http import MediaIoBaseDownload

    mod = _mod_respostas()
    drive, _ = mod._google_services()
    ja = {r["id"]: r["md5"] for r in conn.execute(
        "SELECT id, md5 FROM documentos WHERE origem='resposta_executivo'")}

    pastas = _listar_subpastas(drive, DRIVE_FOLDER_ID)
    print(f"drive: {len(pastas)} subpastas")
    n = 0
    for pasta in sorted(pastas, key=lambda p: p["name"]):
        if limite and n >= limite:
            break
        for arq in _listar_pdfs(drive, pasta["id"]):
            if limite and n >= limite:
                break
            fid, md5 = arq["id"], arq.get("md5Checksum", "")
            if ja.get(fid) == md5 and md5:
                continue  # já indexado nesta versão
            buf = io.BytesIO()
            baixador = MediaIoBaseDownload(
                buf, drive.files().get_media(fileId=fid, supportsAllDrives=True))
            try:
                concluido = False
                while not concluido:
                    _, concluido = baixador.next_chunk()
            except Exception as e:  # noqa: BLE001
                print(f"  aviso: falha ao baixar {pasta['name']}/{arq['name']}: {e}",
                      file=sys.stderr)
                continue
            texto = _texto_pdf(buf.getvalue())
            _gravar(conn, {
                "id": fid, "origem": "resposta_executivo",
                "titulo": f"{pasta['name']} — {arq['name']}",
                "data": (arq.get("createdTime") or "")[:10],
                "url": arq.get("webViewLink", ""),
                "md5": md5,
                "texto": texto if texto else "(PDF sem texto extraível — ocr_pendente)",
            }, dry_run)
            n += 1
            if n % 25 == 0:
                print(f"  ... {n} PDFs indexados")
                if not dry_run:
                    conn.commit()
    if not dry_run:
        conn.commit()
    return n


# ── Fontes locais ────────────────────────────────────────────────────────────
def indexar_dom(conn, dry_run=False) -> int:
    caminho = os.path.join(RAIZ, "diario-oficial", "diario.sqlite")
    if not os.path.exists(caminho):
        print("dom: diario.sqlite não encontrado — pulado")
        return 0
    src = sqlite3.connect(caminho)
    src.row_factory = sqlite3.Row
    colunas = {d[1] for d in src.execute("PRAGMA table_info(atos)")}
    extras = [c for c in ("objeto", "trecho", "processo") if c in colunas]
    n = 0
    for r in src.execute("SELECT * FROM atos"):
        corpo = " · ".join(filter(None, [
            r["categoria"], r["tipo"], r["numero"], r["secretaria"],
            r["favorecido"], *(r[c] for c in extras)]))
        _gravar(conn, {
            "id": f"dom:{r['hash']}", "origem": "dom",
            "titulo": f"{r['tipo'] or r['categoria']} {r['numero'] or ''} — "
                      f"{r['secretaria'] or 'DOM'}".strip(),
            "data": r["data_edicao"], "url": "", "md5": "",
            "texto": corpo,
        }, dry_run)
        n += 1
    if not dry_run:
        conn.commit()
    return n


def indexar_indices_site(conn, dry_run=False) -> int:
    import json
    n = 0
    req = os.path.join(RAIZ, "requerimentos-index.json")
    if os.path.exists(req):
        for r in json.load(open(req, encoding="utf-8")):
            _gravar(conn, {
                "id": f"req:{r.get('numero')}-{r.get('ano')}", "origem": "requerimento",
                # número às vezes já vem com o ano ("3440/2025") — não duplicar
                "titulo": "Requerimento " + (str(r.get("numero"))
                          if "/" in str(r.get("numero"))
                          else f"{r.get('numero')}/{r.get('ano')}"),
                "data": r.get("data_sessao") or "", "url": r.get("url_resposta") or "",
                "md5": "",
                "texto": " · ".join(filter(None, [
                    r.get("assunto"), r.get("situacao"),
                    "respondido" if r.get("respondido") else "pendente"])),
            }, dry_run)
            n += 1
    props = os.path.join(RAIZ, "proposituras-index.json")
    if os.path.exists(props):
        for p in json.load(open(props, encoding="utf-8")):
            if "rosis" not in (p.get("autor") or "").lower():
                continue  # só as proposituras do próprio mandato
            _gravar(conn, {
                "id": f"prop:{p.get('cod') or (str(p.get('numero')) + '-' + str(p.get('ano')))}",
                "origem": "propositura",
                "titulo": f"{p.get('subtipo') or 'Projeto'} {p.get('numero')}/{p.get('ano')}",
                "data": p.get("data") or "", "url": p.get("url_pdf") or "",
                "md5": "",
                "texto": " · ".join(filter(None, [
                    p.get("ementa"), p.get("situacao"), p.get("local")])),
            }, dry_run)
            n += 1
    if not dry_run:
        conn.commit()
    return n


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Indexador da memória institucional")
    ap.add_argument("--origem", choices=["drive", "locais"], help="só uma origem")
    ap.add_argument("--limite", type=int, help="máx. de PDFs do Drive (amostra)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = conectar()
    total = 0
    if args.origem in (None, "locais"):
        n = indexar_dom(conn, args.dry_run)
        print(f"dom: {n} atos")
        total += n
        n = indexar_indices_site(conn, args.dry_run)
        print(f"requerimentos+proposituras: {n} itens")
        total += n
    if args.origem in (None, "drive"):
        n = indexar_drive(conn, args.limite, args.dry_run)
        print(f"drive: {n} PDFs (in)dexados nesta carga")
        total += n

    docs = conn.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
    print(("[dry-run] " if args.dry_run else "") +
          f"carga: {total} itens · base total: {docs} documentos")


if __name__ == "__main__":
    main()
