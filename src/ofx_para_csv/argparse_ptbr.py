"""argparse com títulos e mensagens de erro em português."""

from __future__ import annotations

import argparse
import re
import sys

_ERRORS = [
    (r"the following arguments are required: ", "faltam argumentos obrigatórios: "),
    (r"unrecognized arguments: ", "argumentos não reconhecidos: "),
    (r"invalid choice: (.+?) \(choose from (.+)\)", r"opção inválida: \1 (escolha entre \2)"),
    (r"invalid \S+ value: ", "valor inválido: "),
    (r"expected one argument", "esperava um valor"),
    (r"expected at least one argument", "esperava pelo menos um valor"),
    (r"not allowed with argument ", "não pode ser usado junto com "),
    (r"ambiguous option: (.+?) could match (.+)", r"opção ambígua: \1 pode ser \2"),
    (r"one of the arguments (.+) is required", r"informe um destes argumentos: \1"),
    (r"^argument ", "argumento "),
]


def translate(message: str) -> str:
    for pattern, replacement in _ERRORS:
        message = re.sub(pattern, replacement, message)
    return message


class HelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        return super().add_usage(usage, actions, groups, prefix or "uso: ")


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", HelpFormatter)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "argumentos"
        self._optionals.title = "opções"
        self.add_argument(
            "-h", "--help", action="help", default=argparse.SUPPRESS,
            help="mostra esta ajuda e sai",
        )

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: erro: {translate(message)}\n")
