# Memória do Gabinete (`memoria/`) — USO INTERNO

Índice unificado e pesquisável de tudo que o gabinete produziu/recebeu:
PDFs de pedidos e respostas do Executivo (Drive), atos do DOM
(`diario-oficial/diario.sqlite`), requerimentos e proposituras do mandato
(índices do site). **Nada vai ao site público** — `memoria.sqlite*` e
`memoria-index.json` estão no `.gitignore`; só o código é versionado.

```bash
python memoria/indexar.py --origem drive --limite 20   # amostra
python memoria/indexar.py                              # carga completa (baixa PDFs do Drive)
python memoria/export.py                               # índice p/ o painel local
python -m http.server 8000                             # na raiz do repo
# abrir http://localhost:8000/memoria/memoria.html

python memoria/perguntar.py "o que o governo respondeu sobre a fila da saúde?"
python memoria/perguntar.py --sem-ia "iluminação"      # só os trechos (sem API)
```

- Reusa o OAuth do respostas-executivo (`token.json` / `GOOGLE_OAUTH_TOKEN`);
  pasta-raiz do Drive via `DRIVE_FOLDER_ID` (default = a da automação).
- Indexação idempotente: pula PDF cujo `md5Checksum` do Drive não mudou.
- PDFs escaneados sem texto ficam marcados `ocr_pendente` (OCR = fase 2; o
  projeto já tem Tesseract no módulo do Regimento).
- Busca: FTS5 (`unicode61 remove_diacritics`) no sqlite; painel local faz busca
  lexical no navegador (texto truncado a 1200 chars por doc).
- `perguntar.py` (RAG): BM25 → top-N trechos → Claude responde **só com base
  neles**, citando `[#N — origem, data]` + lista de fontes com link. Requer
  `ANTHROPIC_API_KEY`.
