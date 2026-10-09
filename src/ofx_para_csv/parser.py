"""Leitura de arquivos OFX 1.x (SGML) e 2.x (XML)."""

from __future__ import annotations

import dataclasses
import html
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple


class OFXError(Exception):
    """Erro de leitura com mensagem pronta para mostrar ao usuário."""


# Agregados do OFX: nunca têm valor próprio, só outras tags dentro.
KNOWN_AGGREGATES = {
    "OFX", "SIGNONMSGSRSV1", "SONRS", "STATUS", "FI",
    "BANKMSGSRSV1", "STMTTRNRS", "STMTRS", "BANKACCTFROM", "BANKACCTTO",
    "BANKTRANLIST", "STMTTRN", "PAYEE", "LEDGERBAL", "AVAILBAL", "BALLIST", "BAL",
    "CREDITCARDMSGSRSV1", "CCSTMTTRNRS", "CCSTMTRS", "CCACCTFROM", "CCACCTTO",
    "CURRENCY", "ORIGCURRENCY",
}


@dataclass
class Node:
    name: str
    value: Optional[str] = None
    children: List["Node"] = field(default_factory=list)

    def find(self, name: str) -> Optional["Node"]:
        for child in self.children:
            if child.name == name:
                return child
        return None

    def text(self, name: str) -> str:
        child = self.find(name)
        return (child.value or "") if child is not None else ""

    def iter(self, name: str) -> Iterator["Node"]:
        for child in self.children:
            if child.name == name:
                yield child
            yield from child.iter(name)


@dataclass
class OFXDate:
    """Data como o banco informou: com ou sem hora, com ou sem fuso."""

    value: datetime
    has_time: bool

    def iso(self) -> str:
        if not self.has_time:
            return self.value.date().isoformat()
        spec = "milliseconds" if self.value.microsecond else "seconds"
        return self.value.isoformat(timespec=spec)

    def br(self) -> str:
        d = self.value
        return f"{d.day:02d}/{d.month:02d}/{d.year:04d}"

    def sort_key(self) -> datetime:
        # Ordena pelo horário local informado, sem converter fusos.
        return self.value.replace(tzinfo=None)


@dataclass
class Transaction:
    type: str
    date: Optional[OFXDate]
    amount: Decimal
    fitid: str = ""
    checknum: str = ""
    refnum: str = ""
    name: str = ""
    memo: str = ""
    bank_id: str = ""
    account_id: str = ""
    source: str = ""

    @property
    def description(self) -> str:
        name, memo = self.name.strip(), self.memo.strip()
        if not name or name.casefold() in memo.casefold():
            return memo
        if not memo or memo.casefold() in name.casefold():
            return name
        return f"{name} - {memo}"

    @property
    def document(self) -> str:
        return self.checknum or self.refnum


@dataclass
class Account:
    kind: str  # "banco" ou "cartao"
    bank_id: str = ""
    branch_id: str = ""
    account_id: str = ""
    account_type: str = ""
    currency: str = ""
    start: Optional[OFXDate] = None
    end: Optional[OFXDate] = None
    ledger_balance: Optional[Decimal] = None
    ledger_date: Optional[OFXDate] = None
    available_balance: Optional[Decimal] = None
    available_date: Optional[OFXDate] = None
    transactions: List[Transaction] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.kind, self.bank_id, self.account_id)


# ---------------------------------------------------------------- datas e valores

_DATE_RE = re.compile(
    r"^(\d{4})(\d{2})(\d{2})"
    r"(?:(\d{2})(\d{2})(?:(\d{2})(?:[.,](\d{1,6}))?)?)?"
    r"\s*(?:\[\s*([+-]?\d{1,2}(?:[.,]\d{1,2})?)\s*(?::[^\]]*)?\])?\s*$"
)


def _parse_offset(raw: str) -> timezone:
    raw = raw.replace(",", ".")
    sign = -1 if raw.startswith("-") else 1
    hours, _, frac = raw.lstrip("+-").partition(".")
    if len(frac) == 2 and int(frac) < 60:
        minutes = int(frac)  # "5.30" = 5h30
    elif frac:
        minutes = round(float("0." + frac) * 60)  # "5.5" = 5h30
    else:
        minutes = 0
    return timezone(timedelta(hours=int(hours), minutes=minutes) * sign)


def parse_date(raw: str) -> Optional[OFXDate]:
    """Converte AAAAMMDD[HHMM[SS[.XXX]]][fuso] em OFXDate (None se vazio)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    match = _DATE_RE.match(raw)
    if not match:
        raise ValueError(f"data inválida: {raw!r}")
    year, month, day, hour, minute, second, frac, offset = match.groups()
    micro = int(frac.ljust(6, "0")) if frac else 0
    try:
        tz = _parse_offset(offset) if offset else None
        value = datetime(
            int(year), int(month), int(day),
            int(hour or 0), int(minute or 0), int(second or 0), micro, tzinfo=tz,
        )
    except ValueError:
        raise ValueError(f"data inválida: {raw!r}") from None
    return OFXDate(value, has_time=hour is not None)


_AMOUNT_RE = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)")


def parse_amount(raw: str) -> Decimal:
    """Aceita ponto ou vírgula como separador decimal (-1234.56, -1234,56, 1.234,56)."""
    s = (raw or "").strip().replace(" ", "").replace("\u00a0", "")
    if not s:
        raise ValueError("valor vazio")
    if s.startswith("+"):
        s = s[1:]
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if s.count(",") > 1 else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    if not _AMOUNT_RE.fullmatch(s):
        raise ValueError(f"valor inválido: {raw.strip()!r}")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"valor inválido: {raw.strip()!r}") from None


# ---------------------------------------------------------------- texto e cabeçalho

_ENTITY_RE = re.compile(r"&(#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
_SGML_HEADER_RE = re.compile(r"([A-Z]+)\s*:\s*([^\s<]*)")
_XML_ENCODING_RE = re.compile(rb"<\?xml[^>]*encoding\s*=\s*[\"']([A-Za-z0-9_.:-]+)[\"']", re.I)
_CHARSET_ALIASES = {
    "1252": "cp1252", "WINDOWS-1252": "cp1252", "CP1252": "cp1252",
    # Na prática, arquivos "latin-1" costumam ser cp1252 (mesmo caso dos navegadores).
    "ISO-8859-1": "cp1252", "8859-1": "cp1252", "LATIN1": "cp1252", "LATIN-1": "cp1252",
    "UTF-8": "utf-8", "UTF8": "utf-8",
}


def _decode_entities(text: str) -> str:
    # Só entidades com ";" para não estragar textos como "R&COPY" ou "P&G".
    return _ENTITY_RE.sub(lambda m: html.unescape(m.group(0)), text)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _declared_encoding(data: bytes) -> Optional[str]:
    head = data[:2048]
    match = _XML_ENCODING_RE.search(head)
    if match:
        name = match.group(1).decode("ascii").upper()
        return _CHARSET_ALIASES.get(name, name.lower())
    header = head.decode("latin-1").split("<", 1)[0].upper()
    fields = dict(_SGML_HEADER_RE.findall(header))
    if fields.get("ENCODING") in ("UTF-8", "UTF8"):
        return "utf-8"
    return _CHARSET_ALIASES.get(fields.get("CHARSET", ""))


def decode_bytes(data: bytes) -> Tuple[str, str]:
    """Decodifica respeitando o cabeçalho, com plano B para cp1252/latin-1.

    UTF-8 válido vem primeiro: muitos bancos declaram CHARSET:1252 e mandam UTF-8,
    e um texto cp1252 com acentos quase nunca é UTF-8 válido por acaso.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    candidates = ["utf-8"]
    declared = _declared_encoding(data)
    if declared and declared not in candidates:
        candidates.append(declared)
    candidates += ["cp1252", "latin-1"]
    for encoding in candidates:
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1", errors="replace"), "latin-1"


# ---------------------------------------------------------------- árvore de tags

_TAG_RE = re.compile(r"^<\s*(/)?\s*([^\s/>]+)[^>]*?(/)?\s*>$")


def _tokenize(body: str) -> List[Tuple[str, str, str]]:
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    pieces = re.split(r"(<[^<>]*>)", body)
    tokens = []
    for i in range(1, len(pieces), 2):
        tag, text = pieces[i], pieces[i + 1] if i + 1 < len(pieces) else ""
        if tag.startswith(("<?", "<!")):
            continue
        match = _TAG_RE.match(tag)
        if not match:
            continue
        closing, name, self_closing = match.groups()
        name = name.upper()
        if closing:
            tokens.append(("close", name, ""))
        elif self_closing:
            tokens.append(("empty", name, ""))
        else:
            tokens.append(("open", name, text.strip()))
    return tokens


def _is_aggregate(tokens: list, index: int, open_names: List[str]) -> bool:
    name = tokens[index][1]
    if name in KNOWN_AGGREGATES:
        return True
    # Tag desconhecida sem valor: só é agregado se for fechada antes do pai
    # (e antes de outra tag de mesmo nome, que seria uma irmã).
    for kind, other, _ in tokens[index + 1:]:
        if kind == "open" and other == name:
            return False
        if kind == "close":
            if other == name:
                return True
            if other in open_names:
                return False
    return False


def build_tree(body: str) -> Node:
    """Monta a árvore aceitando tags sem fechamento (SGML) ou fechadas (XML)."""
    tokens = _tokenize(body)
    root = Node("#raiz")
    stack = [root]
    i = 0
    while i < len(tokens):
        kind, name, text = tokens[i]
        closes_next = i + 1 < len(tokens) and tokens[i + 1][:2] == ("close", name)
        if kind == "empty":
            stack[-1].children.append(Node(name, ""))
        elif kind == "open" and (text or closes_next):
            stack[-1].children.append(Node(name, _decode_entities(text)))
            if closes_next:
                i += 1
        elif kind == "open":
            if _is_aggregate(tokens, i, [n.name for n in stack]):
                node = Node(name)
                stack[-1].children.append(node)
                stack.append(node)
            else:
                stack[-1].children.append(Node(name, ""))
        elif any(n.name == name for n in stack[1:]):
            while stack[-1].name != name:
                stack.pop()
            stack.pop()
        # Fechamento de tag com valor (opcional no SGML) é simplesmente ignorado.
        i += 1
    return root


# ---------------------------------------------------------------- extração

def _optional_date(raw: str) -> Optional[OFXDate]:
    try:
        return parse_date(raw)
    except ValueError:
        return None


def _optional_amount(raw: str) -> Optional[Decimal]:
    try:
        return parse_amount(raw)
    except ValueError:
        return None


def _read_transaction(node: Node, account: Account, source: str) -> Transaction:
    fitid = node.text("FITID")
    where = f"transação FITID {fitid}" if fitid else "transação sem FITID"
    try:
        date = parse_date(node.text("DTPOSTED"))
    except ValueError as exc:
        raise OFXError(f"{exc} em DTPOSTED ({where})") from None
    try:
        amount = parse_amount(node.text("TRNAMT"))
    except ValueError as exc:
        raise OFXError(f"{exc} em TRNAMT ({where})") from None
    name = node.text("NAME")
    payee = node.find("PAYEE")
    if not name and payee is not None:
        name = payee.text("NAME")
    return Transaction(
        type=node.text("TRNTYPE").upper(),
        date=date,
        amount=amount,
        fitid=fitid,
        checknum=node.text("CHECKNUM"),
        refnum=node.text("REFNUM"),
        name=_clean(name),
        memo=_clean(node.text("MEMO")),
        bank_id=account.bank_id,
        account_id=account.account_id,
        source=source,
    )


def _read_statement(node: Node, kind: str, source: str) -> Account:
    account = Account(kind=kind, currency=node.text("CURDEF").upper(), sources=[source])
    acct = node.find("BANKACCTFROM" if kind == "banco" else "CCACCTFROM")
    if acct is not None:
        account.bank_id = acct.text("BANKID")
        account.branch_id = acct.text("BRANCHID")
        account.account_id = acct.text("ACCTID")
        account.account_type = acct.text("ACCTTYPE").upper()
    if kind == "cartao" and not account.account_type:
        account.account_type = "CREDITCARD"
    tranlist = node.find("BANKTRANLIST")
    if tranlist is not None:
        account.start = _optional_date(tranlist.text("DTSTART"))
        account.end = _optional_date(tranlist.text("DTEND"))
    for tag, amount_attr, date_attr in (
        ("LEDGERBAL", "ledger_balance", "ledger_date"),
        ("AVAILBAL", "available_balance", "available_date"),
    ):
        bal = node.find(tag)
        if bal is not None:
            setattr(account, amount_attr, _optional_amount(bal.text("BALAMT")))
            setattr(account, date_attr, _optional_date(bal.text("DTASOF")))
    account.transactions = [_read_transaction(t, account, source) for t in node.iter("STMTTRN")]
    return account


def parse_ofx(data: bytes, source: str = "") -> List[Account]:
    """Lê o conteúdo de um arquivo OFX e devolve as contas e cartões encontrados."""
    text, _ = decode_bytes(data)
    if "OFXHEADER" not in text[:4096].upper() and not re.search(r"<\s*OFX\s*>", text, re.I):
        raise OFXError("não parece ser um arquivo OFX (cabeçalho OFXHEADER e tag <OFX> não encontrados)")
    start = text.find("<")
    tree = build_tree(text[start:] if start >= 0 else "")
    accounts = [_read_statement(n, "banco", source) for n in tree.iter("STMTRS")]
    accounts += [_read_statement(n, "cartao", source) for n in tree.iter("CCSTMTRS")]
    if not accounts:
        raise OFXError("nenhum extrato de conta (STMTRS) ou de cartão (CCSTMTRS) encontrado")
    return accounts


def parse_ofx_file(path) -> List[Account]:
    path = Path(path)
    try:
        return parse_ofx(path.read_bytes(), source=path.name)
    except OFXError as exc:
        raise OFXError(f"{path.name}: {exc}") from None


# ---------------------------------------------------------------- junção de arquivos

def _dedup_key(t: Transaction) -> tuple:
    if t.fitid:
        return (t.bank_id, t.account_id, "fitid", t.fitid, t.amount)
    day = t.date.value.date().isoformat() if t.date else ""
    return (t.bank_id, t.account_id, "dados", day, t.amount, (t.memo or t.name).casefold())


def _is_newer(candidate: Optional[OFXDate], current: Optional[OFXDate]) -> bool:
    if candidate is None:
        return False
    return current is None or candidate.sort_key() >= current.sort_key()


def _merge_account(target: Account, other: Account) -> None:
    starts = [d for d in (target.start, other.start) if d]
    ends = [d for d in (target.end, other.end) if d]
    target.start = min(starts, key=OFXDate.sort_key) if starts else None
    target.end = max(ends, key=OFXDate.sort_key) if ends else None
    for amount_attr, date_attr in (("ledger_balance", "ledger_date"), ("available_balance", "available_date")):
        if getattr(other, amount_attr) is None:
            continue
        if getattr(target, amount_attr) is None or _is_newer(getattr(other, date_attr), getattr(target, date_attr)):
            setattr(target, amount_attr, getattr(other, amount_attr))
            setattr(target, date_attr, getattr(other, date_attr))
    for attr in ("branch_id", "account_type", "currency"):
        if not getattr(target, attr):
            setattr(target, attr, getattr(other, attr))
    target.sources += [s for s in other.sources if s not in target.sources]


def _by_date(t: Transaction) -> tuple:
    return (t.date is None, t.date.sort_key() if t.date else datetime.min)


def merge(files: List[List[Account]]) -> Tuple[List[Account], List[Transaction], int]:
    """Junta vários arquivos, remove repetições entre eles e ordena por data.

    Dentro de um mesmo arquivo nada é descartado (duas compras iguais no mesmo dia
    são legítimas). Entre arquivos, cada transação conta uma vez só.
    """
    accounts: Dict[tuple, Account] = {}
    seen: Counter = Counter()
    transactions: List[Transaction] = []
    duplicates = 0
    for file_accounts in files:
        in_file: Counter = Counter()
        for account in file_accounts:
            if account.key in accounts:
                _merge_account(accounts[account.key], account)
            else:
                accounts[account.key] = dataclasses.replace(
                    account, transactions=[], sources=list(account.sources)
                )
            for t in account.transactions:
                key = _dedup_key(t)
                in_file[key] += 1
                if in_file[key] > seen[key]:
                    transactions.append(t)
                    accounts[account.key].transactions.append(t)
                else:
                    duplicates += 1
        for key, count in in_file.items():
            seen[key] = max(seen[key], count)
    transactions.sort(key=_by_date)
    for account in accounts.values():
        account.transactions.sort(key=_by_date)
    return list(accounts.values()), transactions, duplicates
