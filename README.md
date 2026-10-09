# OFX para CSV: converta extratos bancários OFX em CSV, JSON ou planilha (Python)

Quase todo banco deixa baixar o extrato em OFX, mas abrir esse arquivo numa planilha é outra história: cada banco usa uma variação do formato (SGML antigo ou XML), acentos em cp1252, valores com vírgula, datas com fuso entre colchetes. O **ofx-para-csv** lê tudo isso e entrega um CSV que abre direto no Excel ou no Google Planilhas em português, um JSON para os seus scripts ou um resumo rápido do período.

Serve para extratos de conta corrente, poupança e cartão de crédito. Roda offline, não envia nada para lugar nenhum e não tem dependências além do Python.

## Recursos

- Lê **OFX 1.x** (SGML, com tags sem fechamento) e **OFX 2.x** (XML).
- Extratos bancários (`STMTRS`) e de **cartão de crédito** (`CCSTMTRS`), inclusive várias contas no mesmo arquivo.
- Extrai banco, agência, conta, tipo de conta, moeda, período (`DTSTART`/`DTEND`), saldos (`LEDGERBAL`/`AVAILBAL`) e as transações (`TRNTYPE`, `DTPOSTED`, `TRNAMT`, `FITID`, `CHECKNUM`, `REFNUM`, `NAME`, `MEMO`, `PAYEE`).
- Datas como `20240105143000.000[-3:BRT]` (e formas curtas) viram `05/01/2024` no CSV e ISO 8601 com fuso no JSON.
- Valores com ponto ou vírgula decimal: `-150.00`, `-150,00`, `1.234,56`.
- Respeita `CHARSET:1252` e `ENCODING:UTF-8` e se recupera quando o banco declara uma codificação e manda outra.
- Decodifica entidades como `&amp;`.
- CSV no padrão do Excel brasileiro (`;` e vírgula decimal), com `--separador`, `--decimal`, `--data iso` e `--bom`.
- `--resumo` com período, quantidade, créditos, débitos e saldo do período, por conta e no total.
- Junta vários arquivos, ignora transações repetidas entre eles (meses sobrepostos) e ordena tudo por data.

## Instalação

```bash
pipx install git+https://github.com/micdog22/ofx-para-csv
# ou
pip install git+https://github.com/micdog22/ofx-para-csv
```

Requer Python 3.9 ou mais novo.

## Como usar

Converter um extrato e ver o resultado na tela:

```console
$ ofx-para-csv janeiro.ofx
Data;Descrição;Valor;Tipo;Documento;FITID;Banco;Conta
05/01/2024;SALÁRIO EMPRESA EXEMPLO;3500,00;Crédito;778899;202401050001;999;12345-6
08/01/2024;CONTA DE LUZ - SÃO PAULO;-89,90;Débito;000123;202401080001;999;12345-6
10/01/2024;LANCHONETE EXEMPLO & CIA - COMPRA NO DÉBITO;-42,50;Compra;;202401100001;999;12345-6
15/01/2024;PIX ENVIADO MARIA EXEMPLO;-250,00;Transferência;;202401150001;999;12345-6
31/01/2024;TARIFA PACOTE DE SERVIÇOS;-12,90;Tarifa;;202401310001;999;12345-6
```

Juntar dois meses num arquivo para o Excel (o `--bom` faz o Excel do Windows reconhecer os acentos):

```console
$ ofx-para-csv janeiro.ofx fevereiro.ofx --bom -o extrato.csv
8 transações gravadas em extrato.csv. 3 transações repetidas entre arquivos foram ignoradas.
```

Ver só o resumo do período:

```console
$ ofx-para-csv janeiro.ofx fevereiro.ofx --resumo
Conta 12345-6 (banco 999, agência 0001)
  Período:          01/01/2024 a 10/02/2024
  Transações:       8
  Créditos:         R$ 3.650,00 (2)
  Débitos:          R$ 410,30 (6)
  Saldo do período: R$ 3.239,70
  Saldo informado:  R$ 4.240,20 em 10/02/2024

3 transações repetidas entre arquivos foram ignoradas.
```

JSON com contas, saldos e transações (valores como número, datas em ISO 8601):

```console
$ ofx-para-csv cartao.ofx --formato json
{
  "contas": [
    {
      "tipo": "cartao",
      "conta": "0000********1234",
      "saldo": -379.9,
      ...
    }
  ],
  "transacoes": [
    {
      "data": "2024-02-07T00:00:00-03:00",
      "valor": -59.9,
      "tipo": "DEBIT",
      "tipo_descricao": "Débito",
      "descricao": "Streaming Exemplo - assinatura mensal",
      ...
```

Outros exemplos:

```bash
# CSV "internacional": vírgula como separador, ponto decimal e data ISO
ofx-para-csv extrato.ofx --separador , --decimal ponto --data iso -o extrato.csv

# Ler da entrada padrão
cat extrato.ofx | ofx-para-csv -
```

### Opções

| Opção | O que faz |
|---|---|
| `-o`, `--saida ARQUIVO` | grava em arquivo em vez de mostrar na tela |
| `-f`, `--formato csv\|json` | formato de saída (padrão: `csv`) |
| `--separador SEP` | separador do CSV: `;` (padrão), `,`, `\|` ou `tab` |
| `--decimal virgula\|ponto` | separador decimal dos valores no CSV (padrão: `virgula`) |
| `--data br\|iso` | data no CSV: `dd/mm/aaaa` (padrão) ou ISO 8601 |
| `--bom` | inclui o BOM UTF-8 no CSV, para o Excel no Windows |
| `--resumo` | mostra só o resumo (combina com `--formato json`) |

### Colunas do CSV

`Data`, `Descrição`, `Valor`, `Tipo`, `Documento`, `FITID`, `Banco` e `Conta`.

- **Descrição** junta `NAME` (ou `PAYEE/NAME`) e `MEMO` sem repetir texto: muitos bancos colocam a descrição só em um dos dois.
- **Valor** sai com sinal: negativo é saída, positivo é entrada.
- **Tipo** é o `TRNTYPE` traduzido (Crédito, Débito, Transferência, Tarifa, Pagamento...).
- **Documento** é o `CHECKNUM` ou, na falta dele, o `REFNUM`.

Códigos de saída: `0` deu certo, `1` erro ao ler ou gravar algum arquivo, `2` uso incorreto das opções.

## Rodando a partir do código-fonte

```bash
git clone https://github.com/micdog22/ofx-para-csv
cd ofx-para-csv
PYTHONPATH=src python3 -m ofx_para_csv tests/fixtures/bank_sgml_cp1252.ofx --resumo
```

A pasta `tests/fixtures` tem extratos fictícios em vários formatos para você testar.

## Testes

```bash
python3 -m unittest discover -s tests -v
```

## Como funciona

- **Formato:** o OFX 1.x é SGML, em que tags com valor (`<TRNAMT>-10.00`) normalmente não são fechadas; o 2.x é XML. O leitor monta uma árvore única para os dois: tag com valor é folha, e agregados conhecidos (`STMTTRN`, `BANKACCTFROM`...) só fecham com a tag de fechamento. Tags vazias ou desconhecidas são resolvidas olhando se o fechamento aparece adiante.
- **Codificação:** UTF-8 válido é aceito primeiro, porque muitos bancos declaram `CHARSET:1252` e mandam UTF-8. Se não for UTF-8, vale o que o cabeçalho declara, com cp1252 e latin-1 como plano B.
- **Datas:** o dia e a hora são mantidos como o banco informou, sem conversão de fuso. Uma compra às 23h de 31/01 em Brasília continua em 31/01.
- **Repetições entre arquivos:** cada transação é identificada por conta + `FITID` + valor ou, sem `FITID`, por conta + data + valor + descrição. Dentro do mesmo arquivo nada é descartado (duas compras iguais no mesmo dia são legítimas); entre arquivos, cada ocorrência conta uma vez só.
- **Período e saldo:** quando os arquivos são da mesma conta, o período vai do menor `DTSTART` ao maior `DTEND`, e o saldo informado é o mais recente.

> Os valores e o resumo vêm do arquivo exportado pelo banco. Confira sempre com o extrato oficial antes de usar os números para pagamentos, declarações ou contabilidade.

## Contribuindo

Issues e pull requests são bem-vindos. Se o OFX do seu banco não for lido corretamente, abra uma issue com um trecho do arquivo **com os dados pessoais trocados por valores fictícios**.

## Licença

MIT. Veja [LICENSE](LICENSE).
