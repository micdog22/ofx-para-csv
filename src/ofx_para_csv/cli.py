"""Linha de comando do ofx-para-csv."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .argparse_ptbr import ArgumentParser
from .output import duplicates_message, render_summary, summary_to_json, to_csv, to_json
from .parser import OFXError, merge, parse_ofx, parse_ofx_file

PROG = "ofx-para-csv"

_SEPARATOR_ALIASES = {
    "tab": "\t", "\\t": "\t",
    "virgula": ",", "vírgula": ",",
    "ponto-e-virgula": ";", "ponto-e-vírgula": ";",
}

EPILOG = """\
exemplos:
  ofx-para-csv extrato.ofx -o extrato.csv
  ofx-para-csv janeiro.ofx fevereiro.ofx --bom -o extrato.csv
  ofx-para-csv extrato.ofx --separador , --decimal ponto --data iso
  ofx-para-csv cartao.ofx --formato json
  ofx-para-csv extrato.ofx --resumo
"""


def _separator(value: str) -> str:
    value = _SEPARATOR_ALIASES.get(value.lower(), value)
    if len(value) != 1 or value in "\"\r\n":
        raise argparse.ArgumentTypeError(f"separador inválido: {value!r} (use um caractere, como ; , | ou tab)")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = ArgumentParser(
        prog=PROG,
        description=(
            "Converte extratos bancários e de cartão de crédito em OFX para CSV\n"
            "(pronto para o Excel em português), JSON ou um resumo do período."
        ),
        epilog=EPILOG,
    )
    parser.add_argument(
        "arquivos", nargs="+", metavar="ARQUIVO",
        help="um ou mais arquivos .ofx; use - para ler da entrada padrão",
    )
    parser.add_argument("-o", "--saida", metavar="ARQUIVO", help="grava o resultado no arquivo em vez de mostrar na tela")
    parser.add_argument("-f", "--formato", choices=["csv", "json"], default="csv", help="formato de saída (padrão: csv)")
    parser.add_argument("--separador", type=_separator, default=";", metavar="SEP", help="separador de colunas do CSV (padrão: ;)")
    parser.add_argument(
        "--decimal", choices=["virgula", "ponto"], default="virgula",
        help="separador decimal dos valores no CSV (padrão: virgula)",
    )
    parser.add_argument(
        "--data", choices=["br", "iso"], default="br", dest="date_style",
        help="data no CSV: br = dd/mm/aaaa, iso = aaaa-mm-dd com hora e fuso quando houver (padrão: br)",
    )
    parser.add_argument("--bom", action="store_true", help="inclui o BOM UTF-8 no CSV para o Excel do Windows reconhecer os acentos")
    parser.add_argument("--resumo", action="store_true", help="mostra só o resumo: período, créditos, débitos e saldo do período")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}", help="mostra a versão e sai")
    return parser


def _read_inputs(names: List[str]) -> list:
    files = []
    for name in names:
        if name == "-":
            files.append(parse_ofx(sys.stdin.buffer.read(), source="entrada padrão"))
            continue
        path = Path(name)
        if not path.is_file():
            raise OFXError(f"{name}: arquivo não encontrado")
        files.append(parse_ofx_file(path))
    return files


def _write(text: str, destination: Optional[str]) -> None:
    if destination and destination != "-":
        with open(destination, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    to_file = bool(args.saida) and args.saida != "-"
    if to_file:
        target = Path(args.saida).resolve()
        if any(name != "-" and Path(name).resolve() == target for name in args.arquivos):
            parser.error("o arquivo de saída não pode ser um dos arquivos de entrada")

    try:
        files = _read_inputs(args.arquivos)
    except OFXError as exc:
        print(f"{PROG}: erro: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"{PROG}: erro: não foi possível ler {exc.filename}: {exc.strerror}", file=sys.stderr)
        return 1

    accounts, transactions, duplicates = merge(files)
    if args.resumo:
        render = summary_to_json if args.formato == "json" else render_summary
        text = render(accounts, transactions, duplicates)
    elif args.formato == "json":
        text = to_json(accounts, transactions, duplicates)
    else:
        decimal = "," if args.decimal == "virgula" else "."
        text = to_csv(transactions, args.separador, decimal, args.date_style)
        if args.bom:
            text = "﻿" + text

    try:
        _write(text, args.saida)
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 1
    except OSError as exc:
        print(f"{PROG}: erro: não foi possível gravar {args.saida}: {exc.strerror}", file=sys.stderr)
        return 1

    if to_file:
        if args.resumo:
            message = f"Resumo gravado em {args.saida}."
        else:
            message = f"{_plural(len(transactions), 'transação gravada', 'transações gravadas')} em {args.saida}."
        if duplicates:
            message += " " + duplicates_message(duplicates)
        print(message, file=sys.stderr)
    elif duplicates and not args.resumo:
        print(duplicates_message(duplicates), file=sys.stderr)
    return 0
