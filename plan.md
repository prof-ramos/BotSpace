# Plano Validado (Context7): HF Spaces + HF CLI + Jobs

Este plano foi corrigido com base nas boas praticas documentadas no Hugging Face Hub/CLI via Context7.

## 1) Arquitetura recomendada

- `Space (Docker)`: roda o bot Discord e serve consultas RAG.
- `HF Job`: reconstrói o indice FAISS sob demanda ou por agendamento.
- `Dataset repo (Hub)`: armazena os artefatos versionados do indice (`faiss.index`, `meta.json`, `manifest.json`).

Motivo: o acoplamento direto de volume entre Space e Job nao deve ser assumido. Para integracao confiavel entre componentes, use artefato no Hub.

## 2) Persistencia correta no Space

No Space, habilite Persistent Storage em `Settings > Hardware`.

Use os caminhos abaixo:

- `HF_HOME=/data/.huggingface`
- `LOCAL_STORAGE_DIR=/data/storage`

Observacao:
- `/data` e o caminho de volume persistente em Spaces.
- qualquer dado fora de `/data` pode ser efemero.

## 3) Fluxo operacional (producao)

### 3.1 Build de indice (Job)

1. Job baixa os documentos (repo/dataset/origem definida).
2. Job gera `faiss.index` + `meta.json`.
3. Job publica artefatos no dataset de indices (com commit e tag/revisao).
4. Job atualiza `manifest.json` com `revision`, `created_at`, `embed_model`, `num_chunks`.

### 3.2 Consumo no Space

1. Bot inicia.
2. Bot baixa o ultimo artefato aprovado do dataset.
3. Bot salva localmente em `/data/storage` para cache quente.
4. Bot consulta `manifest.json` periodicamente e faz hot-reload quando `revision` muda.

Resultado:
- sem depender de restart para atualizar base;
- rollback simples por revisao/tag do dataset.

### 3.3 Envio de `@docs_rag` para estrutura HF

Padrao recomendado: separar fonte documental e artefato de indice.

- Dataset 1 (fonte): `<org-ou-user>/rag-docs`
- Dataset 2 (indice): `<org-ou-user>/rag-index`

Estrutura no Hub:

- `rag-docs/docs_rag/...` (originais .pdf/.doc/.docx/.rtf)
- `rag-index/artifacts/faiss.index`
- `rag-index/artifacts/meta.json`
- `rag-index/artifacts/manifest.json`

Comandos para publicar `./docs_rag`:

```bash
# criar dataset de documentos (uma vez)
hf repo create <org-ou-user>/rag-docs --repo-type dataset --private

# upload completo da pasta local docs_rag para /docs_rag no dataset
hf upload <org-ou-user>/rag-docs ./docs_rag docs_rag --repo-type dataset --commit-message "docs: carga inicial"
```

Incremental (atualizacoes futuras):

```bash
hf upload <org-ou-user>/rag-docs ./docs_rag docs_rag --repo-type dataset --commit-message "docs: update <timestamp>"
```

Upload otimizado (filtro e higiene):

```bash
hf upload <org-ou-user>/rag-docs ./docs_rag docs_rag \
  --repo-type dataset \
  --commit-message "docs: update <timestamp>" \
  --exclude "**/.DS_Store" \
  --exclude "**/Thumbs.db" \
  --exclude "**/~$*" \
  --exclude "**/*.tmp" \
  --exclude "**/*.log" \
  --exclude "**/__pycache__/**"
```

Upload otimizado com whitelist de extensoes (recomendado):

```bash
hf upload <org-ou-user>/rag-docs ./docs_rag docs_rag \
  --repo-type dataset \
  --commit-message "docs: update <timestamp>" \
  --include "**/*.pdf" \
  --include "**/*.doc" \
  --include "**/*.docx" \
  --include "**/*.rtf" \
  --exclude "**/.DS_Store" \
  --exclude "**/Thumbs.db" \
  --exclude "**/~$*"
```

Opcional para acervo muito grande (lote por pasta):

```bash
hf upload <org-ou-user>/rag-docs ./docs_rag/legislacao_grifada_e_anotada_atualiz_em_01_01_2026 docs_rag/legislacao_grifada_e_anotada_atualiz_em_01_01_2026 --repo-type dataset --commit-message "docs: lote legislacao"
hf upload <org-ou-user>/rag-docs ./docs_rag/sumulas_tse_stj_stf_e_tnu_atualiz_01_01_2026_2 docs_rag/sumulas_tse_stj_stf_e_tnu_atualiz_01_01_2026_2 --repo-type dataset --commit-message "docs: lote sumulas"
```

Observacoes operacionais:
- o Job deve ler da pasta `docs_rag/` no dataset de documentos.
- o Job publica o resultado no dataset de indice (`rag-index`).
- o Space nunca depende diretamente do filesystem do Job.

## 4) Comandos HF CLI (baseline)

## 4.1 Autenticacao e diagnostico

```bash
hf auth whoami
hf env
```

## 4.2 Criar repo de artefatos (dataset)

```bash
hf repo create <org-ou-user>/rag-index --repo-type dataset --private
```

## 4.3 Upload de artefatos do indice

```bash
hf upload <org-ou-user>/rag-index ./artifacts . --repo-type dataset --commit-message "reindex: <timestamp>"
```

## 4.4 Rodar Job manual

```bash
hf jobs run python:3.12 python ingest_job.py
```

## 4.5 Agendar Job

Use os comandos de agendamento de jobs (`hf jobs scheduled ...`) para periodicidade (ex.: diario).

## 5) Variaveis e segredos

### 5.1 Space (Variables)

- `HF_HOME=/data/.huggingface`
- `LOCAL_STORAGE_DIR=/data/storage`
- `INDEX_REPO_ID=<org-ou-user>/rag-index`
- `INDEX_REPO_TYPE=dataset`
- `INDEX_POLL_SECONDS=60`

### 5.2 Space/Job (Secrets)

- `HF_TOKEN` (escopo minimo necessario)
- `OPENROUTER_API_KEY`
- `DISCORD_TOKEN`

Regra:
- nunca commitar token no repo;
- sempre usar Secrets do Space/Job.

## 6) Checklist de robustez

- validar autenticacao antes de operacoes: `hf auth whoami`.
- validar ambiente com `hf env`.
- publicar indice com metadados (`manifest.json`).
- fazer pinagem por revisao para reproducibilidade.
- manter estrategia de rollback (tag da ultima versao estavel).
- registrar logs de reindex e troca de revisao no bot.

## 7) Custo e desempenho

- Space CPU pequeno atende bem para consulta RAG leve.
- Reindex em Job CPU normalmente e suficiente.
- `/data` reduz redownload ao manter cache com `HF_HOME`.
- separar inferencia (OpenRouter) da indexacao reduz custo total.

## 8) Criticos corrigidos neste plano

- removida suposicao de persistencia em `storage/` fora de `/data`.
- removida suposicao de compartilhamento direto de volume entre Space e Job.
- adicionada camada de artefato versionado no Hub para sincronizacao segura.
- adicionadas operacoes minimas de CLI para auditoria e rollback.
