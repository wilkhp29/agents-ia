#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Uso: ./install-agents.sh [--dry-run] [--replace]

Instala os agents deste repositório em "$CODEX_HOME/agents" (ou "$HOME/.codex/agents").
Por segurança, arquivos de mesmo nome existentes não são substituídos sem --replace.
--dry-run  Mostra as ações sem escrever arquivos.
--replace  Faz backup dos arquivos conflitantes e os substitui.
EOF
}

dry_run=false
replace=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    --replace) replace=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Opção desconhecida: %s\n' "$arg" >&2; usage >&2; exit 2 ;;
  esac
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
agents_src="$script_dir/agents"
codex_home="${CODEX_HOME:-$HOME/.codex}"
agents_dst="$codex_home/agents"

if [[ -L "$agents_dst" ]]; then
  printf 'Por segurança, o diretório de destino não pode ser um link simbólico: %s\n' "$agents_dst" >&2
  exit 1
fi

if [[ ! -d "$agents_src" ]]; then
  printf 'Diretório de origem não encontrado: %s\n' "$agents_src" >&2
  exit 1
fi

shopt -s nullglob
files=("$agents_src"/*.toml)
if ((${#files[@]} == 0)); then
  printf 'Nenhum arquivo TOML de agente encontrado em %s\n' "$agents_src" >&2
  exit 1
fi

is_unchanged() {
  local candidate="$1"
  if ((${#unchanged[@]} > 0)); then
    for existing in "${unchanged[@]}"; do
      [[ "$existing" == "$candidate" ]] && return 0
    done
  fi
  return 1
}

conflicts=()
unchanged=()
for src in "${files[@]}"; do
  name="$(basename -- "$src")"
  if [[ -L "$src" || ! -f "$src" ]]; then
    printf 'A origem do agente não é um arquivo regular: %s\n' "$src" >&2
    exit 1
  fi
  if [[ -L "$agents_dst/$name" ]]; then
    printf 'Por segurança, o destino existente não pode ser link simbólico: %s\n' "$agents_dst/$name" >&2
    exit 1
  fi
  if [[ -e "$agents_dst/$name" || -L "$agents_dst/$name" ]]; then
    if [[ ! -f "$agents_dst/$name" ]]; then
      printf 'O destino existente não é um arquivo regular: %s\n' "$agents_dst/$name" >&2
      exit 1
    elif cmp -s -- "$src" "$agents_dst/$name"; then
      unchanged+=("$name")
    else
      conflicts+=("$name")
    fi
  fi
done

printf 'Origem:  %s\nDestino: %s\nAgents:  %s\nIguais:   %s\n' "$agents_src" "$agents_dst" "${#files[@]}" "${#unchanged[@]}"
if ((${#conflicts[@]} > 0)); then
  printf 'Conflitos com conteúdo diferente: %s\n' "${conflicts[*]}"
  if [[ "$replace" != true ]]; then
    printf 'Nenhum arquivo será substituído. Revise os conflitos e use --replace se desejar sobrescrevê-los.\n' >&2
    exit 3
  fi
fi

if [[ "$dry_run" == true ]]; then
  if ((${#unchanged[@]} > 0)); then
    for name in "${unchanged[@]}"; do printf 'Sem alteração: %s\n' "$name"; done
  fi
  for src in "${files[@]}"; do
    name="$(basename -- "$src")"
    if ! is_unchanged "$name"; then printf 'Copiaria %s\n' "$name"; fi
  done
  exit 0
fi

mkdir -p -- "$agents_dst"
backup_dir=""
if ((${#conflicts[@]} > 0)); then
  backup_root="$codex_home/agent-backups"
  if [[ -L "$backup_root" ]]; then
    printf 'Por segurança, o diretório de backups não pode ser um link simbólico: %s\n' "$backup_root" >&2
    exit 1
  fi
  if [[ -e "$backup_root" && ! -d "$backup_root" ]]; then
    printf 'O caminho de backups existente não é um diretório: %s\n' "$backup_root" >&2
    exit 1
  fi
  mkdir -p -- "$backup_root"
  backup_dir="$(mktemp -d "$backup_root/backup.XXXXXXXX")"
  chmod 700 "$backup_dir"
  for name in "${conflicts[@]}"; do
    cp -p -- "$agents_dst/$name" "$backup_dir/$name"
  done
  printf 'Backup dos conflitos: %s\n' "$backup_dir"
fi

for src in "${files[@]}"; do
  name="$(basename -- "$src")"
  if is_unchanged "$name"; then
    printf 'Sem alteração: %s\n' "$name"
    continue
  fi
  if [[ -e "$agents_dst/$name" || -L "$agents_dst/$name" ]]; then
    if [[ "$replace" != true ]]; then
      printf 'Conflito inesperado durante a instalação: %s\n' "$name" >&2
      exit 3
    fi
  fi
  tmp_dir="$(mktemp -d "$agents_dst/.${name}.tmp.XXXXXXXX")"
  tmp="$tmp_dir/$name"
  cp -- "$src" "$tmp"
  chmod 600 "$tmp"
  mv -f -- "$tmp" "$agents_dst/$name"
  rmdir -- "$tmp_dir"
  printf 'Instalado: %s\n' "$name"
done

printf 'Instalação concluída. Reinicie o Codex se os agentes não aparecerem imediatamente.\n'
