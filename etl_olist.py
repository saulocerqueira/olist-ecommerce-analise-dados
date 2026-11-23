#!/usr/bin/env python3
"""
ETL do dataset Olist (e-commerce brasileiro) -> PostgreSQL -> Power BI

Etapas
  1. Localiza o .zip na pasta do projeto e extrai os CSVs
  2. Carrega os 9 CSVs com Pandas
  3. Identifica inconsistências, remove duplicidades e trata os dados
  4. Valida integridade referencial (remove órfãos)
  5. Gera relatórios de qualidade (reports/)
  6. Salva os dados tratados em CSV (data/processed/)
  7. Carrega no PostgreSQL (schema "olist") com PKs, FKs, índices e views

Uso
  python etl_olist.py                      # fluxo completo
  python etl_olist.py --skip-db            # só limpeza (gera CSVs e relatórios)
  python etl_olist.py --projeto "D:/caminho/projeto-olist"

Senha do banco: variável de ambiente PGPASSWORD ou digitada quando solicitada.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import unicodedata
import zipfile
from getpass import getpass
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("olist")

SCHEMA = "olist"

ARQUIVOS = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

# CEP precisa ser texto (senão perde o zero à esquerda: 01310 -> 1310)
DTYPES_LEITURA = {
    "customers": {"customer_zip_code_prefix": "string"},
    "sellers": {"seller_zip_code_prefix": "string"},
    "geolocation": {"geolocation_zip_code_prefix": "string"},
}

UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

STATUS_VALIDOS = {
    "created", "approved", "invoiced", "processing", "shipped",
    "delivered", "unavailable", "canceled",
}

# Categorias presentes em products mas ausentes no arquivo de tradução
TRADUCOES_FALTANTES = {
    "pc_gamer": "pc_gamer",
    "portateis_cozinha_e_preparadores_de_alimentos": "portable_kitchen_food_preparers",
}

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# --------------------------------------------------------------------------- #
# Registro de problemas de qualidade
# --------------------------------------------------------------------------- #
class Qualidade:
    """Acumula cada verificação feita (inclusive as que não encontraram nada)."""

    def __init__(self) -> None:
        self.registros: list[dict] = []

    def add(self, tabela: str, verificacao: str, qtd: int, acao: str) -> None:
        qtd = int(qtd)
        self.registros.append(
            {"tabela": tabela, "verificacao": verificacao, "ocorrencias": qtd, "acao": acao}
        )
        if qtd:
            log.info("[%s] %s: %s -> %s", tabela, verificacao, f"{qtd:,}", acao)

    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.registros)


# --------------------------------------------------------------------------- #
# Funções utilitárias
# --------------------------------------------------------------------------- #
def remover_duplicados(df, tabela, q, subset=None, ordenar_por=None, ascending=False):
    """Remove duplicatas exatas e, se informado, duplicatas por chave."""
    n = df.duplicated().sum()
    q.add(tabela, "Linhas totalmente duplicadas", n, "removidas")
    df = df.drop_duplicates()
    if subset:
        if ordenar_por:
            df = df.sort_values(ordenar_por, ascending=ascending, na_position="last")
        n = df.duplicated(subset=subset).sum()
        acao = "mantido o registro mais recente" if ordenar_por else "mantido o primeiro registro"
        q.add(tabela, f"Chave duplicada ({', '.join(subset)})", n, acao)
        df = df.drop_duplicates(subset=subset, keep="first")
    return df


def remover_chaves_nulas(df, tabela, q, cols):
    mask = df[cols].isna().any(axis=1)
    q.add(tabela, f"Chave nula ({', '.join(cols)})", mask.sum(), "removidas")
    return df[~mask]


def filtrar_orfaos(df, col, validos, tabela, referencia, q):
    mask = ~df[col].isin(validos)
    q.add(tabela, f"{col} sem correspondência em {referencia}", mask.sum(), "removidas")
    return df[~mask]


def strip_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar_cidade(serie: pd.Series) -> pd.Series:
    """minúsculas, sem acento, sem sufixo 'cidade / UF', sem lixo numérico."""
    s = serie.astype("string").str.strip().str.lower()
    s = s.map(lambda x: strip_acentos(x) if pd.notna(x) else x).astype("string")
    s = s.str.split(r"[/,\\]", n=1, regex=True).str[0].str.strip()
    s = s.str.replace(r"\s+", " ", regex=True)
    so_lixo = s.str.fullmatch(r"[\d\W]*", na=False)  # vazio, só números ou símbolos
    return s.mask(so_lixo)


def tratar_localidade(df, prefixo, tabela, q):
    col_cep, col_cid, col_uf = (
        f"{prefixo}_zip_code_prefix", f"{prefixo}_city", f"{prefixo}_state",
    )
    df[col_cep] = df[col_cep].astype("string").str.strip().str.zfill(5)

    antes = df[col_cid].astype("string")
    df[col_cid] = normalizar_cidade(df[col_cid])
    alteradas = (antes.fillna("") != df[col_cid].fillna("")).sum()
    q.add(tabela, "Nomes de cidade fora do padrão (acento/caixa/símbolos)", alteradas,
          "padronizados (minúsculas, sem acento)")

    df[col_uf] = df[col_uf].astype("string").str.strip().str.upper()
    invalidas = df[col_uf].notna() & ~df[col_uf].isin(UFS_VALIDAS)
    q.add(tabela, "UF inválida", invalidas.sum(), "convertida para nulo")
    df.loc[invalidas, col_uf] = pd.NA
    return df


def converter_datas(df, cols, tabela, q):
    for c in cols:
        convertido = pd.to_datetime(df[c], errors="coerce")
        invalidas = convertido.isna() & df[c].notna()
        q.add(tabela, f"Datas não interpretáveis em {c}", invalidas.sum(), "convertidas para nulo")
        df[c] = convertido
    return df


# --------------------------------------------------------------------------- #
# 1-2. Extração e leitura
# --------------------------------------------------------------------------- #
def localizar_projeto(arg: str | None) -> Path:
    if arg:
        p = Path(arg).expanduser()
        if not p.exists():
            sys.exit(f"Pasta não encontrada: {p}")
        return p
    home = Path.home()
    for pasta in ("Documents", "Documentos", "OneDrive/Documents", "OneDrive/Documentos"):
        candidato = home / pasta / "projeto-olist"
        if candidato.exists():
            return candidato
    sys.exit("Não achei a pasta 'projeto-olist'. Informe o caminho com --projeto.")


def preparar_dados_brutos(projeto: Path, raw_dir: Path) -> dict[str, Path]:
    zips = [z for z in projeto.rglob("*.zip") if raw_dir not in z.parents]
    zips.sort(key=lambda z: (not any(k in z.name.lower() for k in ("olist", "brazil", "ecommerce")), z.name))
    if zips:
        log.info("Extraindo %s -> %s", zips[0].name, raw_dir)
        raw_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zips[0]) as zf:
            zf.extractall(raw_dir)
    else:
        log.info("Nenhum .zip encontrado; procurando CSVs já extraídos.")

    csvs = {p.name: p for p in raw_dir.rglob("*.csv")} if raw_dir.exists() else {}
    csvs.update({p.name: p for p in projeto.glob("*.csv") if p.name not in csvs})

    faltando = [f for f in ARQUIVOS.values() if f not in csvs]
    if faltando:
        sys.exit("Arquivos ausentes: " + ", ".join(faltando))
    return csvs


def carregar(csvs: dict[str, Path]) -> dict[str, pd.DataFrame]:
    dados = {}
    for nome, arquivo in ARQUIVOS.items():
        df = pd.read_csv(csvs[arquivo], dtype=DTYPES_LEITURA.get(nome), encoding="utf-8")
        log.info("Carregado %-22s %9s linhas x %d colunas", nome, f"{len(df):,}", df.shape[1])
        dados[nome] = df
    return dados


# --------------------------------------------------------------------------- #
# 3. Tratamento por tabela
# --------------------------------------------------------------------------- #
def tratar_customers(df, q):
    t = "customers"
    df = remover_duplicados(df, t, q, subset=["customer_id"])
    df = remover_chaves_nulas(df, t, q, ["customer_id", "customer_unique_id"])
    return tratar_localidade(df.copy(), "customer", t, q)


def tratar_sellers(df, q):
    t = "sellers"
    df = remover_duplicados(df, t, q, subset=["seller_id"])
    df = remover_chaves_nulas(df, t, q, ["seller_id"])
    return tratar_localidade(df.copy(), "seller", t, q)


def tratar_geolocation(df, q):
    t = "geolocation"
    df = tratar_localidade(df.copy(), "geolocation", t, q)
    df = remover_duplicados(df, t, q)  # a base original tem centenas de milhares de repetições

    # Coordenadas fora do território brasileiro (lat -34..6 / lng -74..-34)
    fora = ~(df.geolocation_lat.between(-34, 6) & df.geolocation_lng.between(-74, -34))
    q.add(t, "Coordenadas fora do Brasil", fora.sum(), "removidas")
    df = df[~fora]

    def moda(s):
        m = s.dropna().mode()
        return m.iloc[0] if len(m) else pd.NA

    n_antes = len(df)
    agg = df.groupby("geolocation_zip_code_prefix").agg(
        geolocation_lat=("geolocation_lat", "median"),
        geolocation_lng=("geolocation_lng", "median"),
        geolocation_city=("geolocation_city", moda),
        geolocation_state=("geolocation_state", moda),
    ).reset_index()
    q.add(t, "Múltiplos pontos por CEP", n_antes - len(agg),
          "consolidados em 1 linha por CEP (mediana de lat/lng, moda de cidade/UF)")
    return agg


def tratar_products(df, trad, q):
    t = "products"
    df = df.rename(columns={
        "product_name_lenght": "product_name_length",
        "product_description_lenght": "product_description_length",
    })
    q.add(t, "Colunas com erro de grafia (lenght)", 2, "renomeadas para length")
    df = remover_duplicados(df, t, q, subset=["product_id"])
    df = remover_chaves_nulas(df, t, q, ["product_id"])
    df = df.copy()

    df["product_category_name"] = df["product_category_name"].astype("string").str.strip().str.lower()
    sem_cat = df["product_category_name"].isna() | (df["product_category_name"] == "")
    q.add(t, "Produtos sem categoria", sem_cat.sum(), "preenchidos com 'sem_categoria'")
    df.loc[sem_cat, "product_category_name"] = "sem_categoria"

    # Tradução da categoria
    trad = trad.drop_duplicates("product_category_name").copy()
    novas = pd.DataFrame({
        "product_category_name": list(TRADUCOES_FALTANTES),
        "product_category_name_english": list(TRADUCOES_FALTANTES.values()),
    })
    trad = pd.concat([trad, novas[~novas.product_category_name.isin(trad.product_category_name)]])
    trad.loc[len(trad)] = ["sem_categoria", "uncategorized"]
    df = df.merge(trad, on="product_category_name", how="left")
    sem_trad = df["product_category_name_english"].isna()
    q.add(t, "Categorias sem tradução para inglês", sem_trad.sum(), "mantido o nome original")
    df["product_category_name_english"] = df["product_category_name_english"].fillna(df["product_category_name"])

    # Medidas zeradas são impossíveis (peso/dimensão de produto físico)
    for c in ["product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]:
        zero = df[c] <= 0
        q.add(t, f"{c} <= 0", zero.sum(), "convertido para nulo")
        df.loc[zero, c] = np.nan

    inteiros = ["product_name_length", "product_description_length", "product_photos_qty",
                "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]
    for c in inteiros:
        df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
    df["volume_cm3"] = (df.product_length_cm * df.product_height_cm * df.product_width_cm).astype("Int64")
    return df


def tratar_orders(df, q):
    t = "orders"
    df = remover_duplicados(df, t, q, subset=["order_id"])
    df = remover_chaves_nulas(df, t, q, ["order_id", "customer_id"])
    df = df.copy()

    df["order_status"] = df["order_status"].astype("string").str.strip().str.lower()
    invalido = ~df["order_status"].isin(STATUS_VALIDOS)
    q.add(t, "Status de pedido desconhecido", invalido.sum(), "removidos")
    df = df[~invalido].copy()

    cols_data = ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
                 "order_delivered_customer_date", "order_estimated_delivery_date"]
    df = converter_datas(df, cols_data, t, q)
    df = remover_chaves_nulas(df, t, q, ["order_purchase_timestamp"])

    c, a = df.order_purchase_timestamp, df.order_approved_at
    tr, en = df.order_delivered_carrier_date, df.order_delivered_customer_date
    entregue = df.order_status.eq("delivered")

    m_ent_sem_data = entregue & en.isna()
    q.add(t, "Status 'delivered' sem data de entrega", m_ent_sem_data.sum(),
          "mantidos; ficam fora das métricas de prazo")
    m_data_sem_ent = ~entregue & en.notna()
    q.add(t, "Pedidos não entregues com data de entrega preenchida", m_data_sem_ent.sum(),
          "mantidos; métricas de prazo consideram só status 'delivered'")

    m_apr = a.notna() & (a < c)
    m_car = tr.notna() & (tr < c)
    m_ent = en.notna() & (en < c)
    m_ent_car = en.notna() & tr.notna() & (en < tr) & ~m_ent & ~m_car
    q.add(t, "Aprovação anterior à compra", m_apr.sum(), "data convertida para nulo")
    q.add(t, "Postagem à transportadora anterior à compra", m_car.sum(), "data convertida para nulo")
    q.add(t, "Entrega ao cliente anterior à compra", m_ent.sum(), "data convertida para nulo")
    q.add(t, "Entrega ao cliente anterior à postagem na transportadora", m_ent_car.sum(),
          "apenas sinalizado em possui_inconsistencia_data")

    df["possui_inconsistencia_data"] = (m_apr | m_car | m_ent | m_ent_car | m_ent_sem_data)
    df.loc[m_apr, "order_approved_at"] = pd.NaT
    df.loc[m_car, "order_delivered_carrier_date"] = pd.NaT
    df.loc[m_ent, "order_delivered_customer_date"] = pd.NaT

    # Colunas derivadas (prontas para o Power BI)
    c, en = df.order_purchase_timestamp, df.order_delivered_customer_date
    est = df.order_estimated_delivery_date
    df["data_compra"] = c.dt.date
    df["dias_entrega_real"] = ((en - c).dt.total_seconds() / 86400).round(2).where(entregue)
    df["dias_entrega_estimada"] = ((est - c).dt.total_seconds() / 86400).round(2)
    dias_atraso = (en.dt.normalize() - est.dt.normalize()).dt.days
    df["dias_atraso"] = dias_atraso.where(entregue).astype("Int64")
    df["entregue_com_atraso"] = (df["dias_atraso"] > 0).astype("boolean")
    return df


def tratar_order_items(df, q):
    t = "order_items"
    df = remover_duplicados(df, t, q, subset=["order_id", "order_item_id"])
    df = remover_chaves_nulas(df, t, q, ["order_id", "order_item_id", "product_id", "seller_id"])
    df = df.copy()
    df["order_item_id"] = pd.to_numeric(df["order_item_id"], errors="coerce").astype("Int64")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["freight_value"] = pd.to_numeric(df["freight_value"], errors="coerce")
    df = converter_datas(df, ["shipping_limit_date"], t, q)

    ruim = df["price"].isna() | (df["price"] <= 0)
    q.add(t, "Preço nulo ou <= 0", ruim.sum(), "removidos")
    df = df[~ruim].copy()

    neg = df["freight_value"].isna() | (df["freight_value"] < 0)
    q.add(t, "Frete nulo ou negativo", neg.sum(), "convertido para 0")
    df.loc[neg, "freight_value"] = 0.0

    df["valor_total_item"] = (df["price"] + df["freight_value"]).round(2)
    return df


def tratar_order_payments(df, q):
    t = "order_payments"
    df = remover_duplicados(df, t, q, subset=["order_id", "payment_sequential"])
    df = remover_chaves_nulas(df, t, q, ["order_id", "payment_sequential"])
    df = df.copy()
    df["payment_type"] = df["payment_type"].astype("string").str.strip().str.lower()
    for c in ["payment_sequential", "payment_installments"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    df["payment_value"] = pd.to_numeric(df["payment_value"], errors="coerce")

    nd = df["payment_type"].eq("not_defined") | df["payment_value"].isna() | (df["payment_value"] < 0)
    q.add(t, "Pagamento 'not_defined', nulo ou negativo", nd.sum(), "removidos")
    df = df[~nd].copy()

    parc = df["payment_installments"].isna() | (df["payment_installments"] < 1)
    q.add(t, "Parcelas < 1", parc.sum(), "ajustadas para 1 (pagamento à vista)")
    df.loc[parc, "payment_installments"] = 1
    return df


def tratar_order_reviews(df, q):
    t = "order_reviews"
    df = converter_datas(df.copy(), ["review_creation_date", "review_answer_timestamp"], t, q)
    # review_id se repete entre pedidos diferentes; a chave real é (review_id, order_id)
    df = remover_duplicados(df, t, q, subset=["review_id", "order_id"],
                            ordenar_por="review_answer_timestamp", ascending=False)
    df = remover_chaves_nulas(df, t, q, ["review_id", "order_id"])
    df = df.copy()

    df["review_score"] = pd.to_numeric(df["review_score"], errors="coerce")
    fora = ~df["review_score"].between(1, 5)
    q.add(t, "Nota fora da faixa 1-5", fora.sum(), "removidas")
    df = df[~fora].copy()
    df["review_score"] = df["review_score"].astype("Int64")

    for c in ["review_comment_title", "review_comment_message"]:
        df[c] = df[c].astype("string").str.strip()
        df.loc[df[c] == "", c] = pd.NA
    df["possui_comentario"] = df["review_comment_message"].notna()
    return df


def criar_dim_calendario(orders: pd.DataFrame) -> pd.DataFrame:
    ini = orders.order_purchase_timestamp.min().year
    fim = max(orders.order_estimated_delivery_date.max().year, orders.order_purchase_timestamp.max().year)
    datas = pd.date_range(f"{ini}-01-01", f"{fim}-12-31", freq="D")
    cal = pd.DataFrame({"data": datas})
    cal["ano"] = cal.data.dt.year
    cal["trimestre"] = cal.data.dt.quarter
    cal["mes"] = cal.data.dt.month
    cal["nome_mes"] = cal.mes.map(lambda m: MESES[m - 1])
    cal["mes_abrev"] = cal.nome_mes.str[:3]
    cal["ano_mes"] = cal.data.dt.strftime("%Y-%m")
    cal["dia"] = cal.data.dt.day
    cal["dia_semana"] = cal.data.dt.dayofweek + 1  # 1 = segunda
    cal["nome_dia_semana"] = cal.data.dt.dayofweek.map(lambda d: DIAS[d])
    cal["fim_de_semana"] = cal.data.dt.dayofweek >= 5
    cal["data"] = cal["data"].dt.date
    return cal


# --------------------------------------------------------------------------- #
# 4. Pipeline de limpeza
# --------------------------------------------------------------------------- #
def limpar(raw: dict[str, pd.DataFrame], q: Qualidade) -> dict[str, pd.DataFrame]:
    t = {}
    t["customers"] = tratar_customers(raw["customers"], q)
    t["sellers"] = tratar_sellers(raw["sellers"], q)
    t["geolocation"] = tratar_geolocation(raw["geolocation"], q)
    t["products"] = tratar_products(raw["products"], raw["category_translation"], q)
    t["orders"] = tratar_orders(raw["orders"], q)
    t["order_items"] = tratar_order_items(raw["order_items"], q)
    t["order_payments"] = tratar_order_payments(raw["order_payments"], q)
    t["order_reviews"] = tratar_order_reviews(raw["order_reviews"], q)

    # Integridade referencial (necessária para criar as FKs no PostgreSQL)
    t["orders"] = filtrar_orfaos(t["orders"], "customer_id", set(t["customers"].customer_id),
                                 "orders", "customers", q)
    ids = set(t["orders"].order_id)
    t["order_items"] = filtrar_orfaos(t["order_items"], "order_id", ids, "order_items", "orders", q)
    t["order_items"] = filtrar_orfaos(t["order_items"], "product_id", set(t["products"].product_id),
                                      "order_items", "products", q)
    t["order_items"] = filtrar_orfaos(t["order_items"], "seller_id", set(t["sellers"].seller_id),
                                      "order_items", "sellers", q)
    t["order_payments"] = filtrar_orfaos(t["order_payments"], "order_id", ids, "order_payments", "orders", q)
    t["order_reviews"] = filtrar_orfaos(t["order_reviews"], "order_id", ids, "order_reviews", "orders", q)

    sem_itens = ~t["orders"].order_id.isin(t["order_items"].order_id)
    q.add("orders", "Pedidos sem nenhum item", sem_itens.sum(),
          "mantidos (em geral cancelados/indisponíveis); filtre por status nas análises")

    t["dim_calendario"] = criar_dim_calendario(t["orders"])
    return t


def perfil_dados(tabelas: dict[str, pd.DataFrame]) -> pd.DataFrame:
    linhas = []
    for nome, df in tabelas.items():
        for col in df.columns:
            nulos = int(df[col].isna().sum())
            linhas.append({
                "tabela": nome, "coluna": col, "linhas": len(df), "nulos": nulos,
                "pct_nulos": round(100 * nulos / max(len(df), 1), 2), "tipo": str(df[col].dtype),
            })
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- #
# 5-6. Saídas em arquivo
# --------------------------------------------------------------------------- #
def salvar_arquivos(tabelas, q, raw, processed_dir: Path, report_dir: Path) -> None:
    processed_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    for nome, df in tabelas.items():
        df.to_csv(processed_dir / f"{nome}.csv", index=False, encoding="utf-8")

    q.to_df().to_csv(report_dir / "relatorio_qualidade.csv", index=False, encoding="utf-8-sig")
    perfil_dados(tabelas).to_csv(report_dir / "perfil_dados_tratados.csv", index=False, encoding="utf-8-sig")

    resumo = [{
        "tabela": n,
        "linhas_originais": len(raw[n]) if n in raw else None,
        "linhas_tratadas": len(df),
    } for n, df in tabelas.items()]
    pd.DataFrame(resumo).to_csv(report_dir / "resumo_linhas.csv", index=False, encoding="utf-8-sig")
    log.info("CSVs tratados em %s | relatórios em %s", processed_dir, report_dir)


# --------------------------------------------------------------------------- #
# 7. PostgreSQL
# --------------------------------------------------------------------------- #
SQL_CONSTRAINTS = f"""
ALTER TABLE {SCHEMA}.customers      ADD PRIMARY KEY (customer_id);
ALTER TABLE {SCHEMA}.sellers        ADD PRIMARY KEY (seller_id);
ALTER TABLE {SCHEMA}.products       ADD PRIMARY KEY (product_id);
ALTER TABLE {SCHEMA}.geolocation    ADD PRIMARY KEY (geolocation_zip_code_prefix);
ALTER TABLE {SCHEMA}.dim_calendario ADD PRIMARY KEY (data);
ALTER TABLE {SCHEMA}.orders         ADD PRIMARY KEY (order_id);
ALTER TABLE {SCHEMA}.order_items    ADD PRIMARY KEY (order_id, order_item_id);
ALTER TABLE {SCHEMA}.order_payments ADD PRIMARY KEY (order_id, payment_sequential);
ALTER TABLE {SCHEMA}.order_reviews  ADD PRIMARY KEY (review_id, order_id);

ALTER TABLE {SCHEMA}.orders         ADD FOREIGN KEY (customer_id) REFERENCES {SCHEMA}.customers(customer_id);
ALTER TABLE {SCHEMA}.order_items    ADD FOREIGN KEY (order_id)    REFERENCES {SCHEMA}.orders(order_id);
ALTER TABLE {SCHEMA}.order_items    ADD FOREIGN KEY (product_id)  REFERENCES {SCHEMA}.products(product_id);
ALTER TABLE {SCHEMA}.order_items    ADD FOREIGN KEY (seller_id)   REFERENCES {SCHEMA}.sellers(seller_id);
ALTER TABLE {SCHEMA}.order_payments ADD FOREIGN KEY (order_id)    REFERENCES {SCHEMA}.orders(order_id);
ALTER TABLE {SCHEMA}.order_reviews  ADD FOREIGN KEY (order_id)    REFERENCES {SCHEMA}.orders(order_id);

CREATE INDEX idx_orders_data_compra   ON {SCHEMA}.orders(data_compra);
CREATE INDEX idx_orders_status        ON {SCHEMA}.orders(order_status);
CREATE INDEX idx_items_product        ON {SCHEMA}.order_items(product_id);
CREATE INDEX idx_items_seller         ON {SCHEMA}.order_items(seller_id);
CREATE INDEX idx_customers_unique     ON {SCHEMA}.customers(customer_unique_id);
CREATE INDEX idx_customers_state      ON {SCHEMA}.customers(customer_state);
CREATE INDEX idx_products_category    ON {SCHEMA}.products(product_category_name);
"""

# Granularidade: 1 linha por ITEM vendido (use para receita, categorias, vendedores)
SQL_VW_ITENS = f"""
CREATE VIEW {SCHEMA}.vw_fato_itens AS
SELECT
    i.order_id, i.order_item_id, i.product_id, i.seller_id,
    o.customer_id, c.customer_unique_id,
    o.order_status, o.order_purchase_timestamp, o.data_compra,
    i.price, i.freight_value, i.valor_total_item,
    p.product_category_name, p.product_category_name_english,
    c.customer_city, c.customer_state,
    s.seller_city, s.seller_state,
    o.dias_entrega_real, o.dias_entrega_estimada, o.dias_atraso, o.entregue_com_atraso,
    r.nota_media AS review_score
FROM {SCHEMA}.order_items i
JOIN {SCHEMA}.orders    o ON o.order_id   = i.order_id
JOIN {SCHEMA}.customers c ON c.customer_id = o.customer_id
JOIN {SCHEMA}.products  p ON p.product_id = i.product_id
JOIN {SCHEMA}.sellers   s ON s.seller_id  = i.seller_id
LEFT JOIN (
    SELECT order_id, ROUND(AVG(review_score), 2) AS nota_media
    FROM {SCHEMA}.order_reviews GROUP BY order_id
) r ON r.order_id = i.order_id;
"""

# Granularidade: 1 linha por PEDIDO (use para ticket médio, entrega, pagamento, satisfação)
SQL_VW_PEDIDOS = f"""
CREATE VIEW {SCHEMA}.vw_pedidos AS
SELECT
    o.*,
    c.customer_unique_id, c.customer_city, c.customer_state,
    COALESCE(it.qtd_itens, 0)        AS qtd_itens,
    COALESCE(it.valor_produtos, 0)   AS valor_produtos,
    COALESCE(it.valor_frete, 0)      AS valor_frete,
    pg.valor_pago, pg.parcelas_max, pg.forma_pagamento_principal,
    r.nota_media
FROM {SCHEMA}.orders o
JOIN {SCHEMA}.customers c ON c.customer_id = o.customer_id
LEFT JOIN (
    SELECT order_id, COUNT(*) AS qtd_itens, SUM(price) AS valor_produtos, SUM(freight_value) AS valor_frete
    FROM {SCHEMA}.order_items GROUP BY order_id
) it ON it.order_id = o.order_id
LEFT JOIN (
    SELECT order_id,
           SUM(payment_value)        AS valor_pago,
           MAX(payment_installments) AS parcelas_max,
           (ARRAY_AGG(payment_type ORDER BY payment_value DESC))[1] AS forma_pagamento_principal
    FROM {SCHEMA}.order_payments GROUP BY order_id
) pg ON pg.order_id = o.order_id
LEFT JOIN (
    SELECT order_id, ROUND(AVG(review_score), 2) AS nota_media
    FROM {SCHEMA}.order_reviews GROUP BY order_id
) r ON r.order_id = o.order_id;
"""

ORDEM_CARGA = ["customers", "sellers", "products", "geolocation", "dim_calendario",
               "orders", "order_items", "order_payments", "order_reviews"]


def criar_engines(args):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    senha = os.getenv("PGPASSWORD") or getpass(f"Senha do PostgreSQL (usuário {args.user}): ")

    def url(db):
        return URL.create("postgresql+psycopg2", username=args.user, password=senha,
                          host=args.host, port=args.port, database=db)

    return create_engine(url(args.db)), create_engine(url("postgres"), isolation_level="AUTOCOMMIT")


def garantir_banco(admin_engine, nome: str) -> None:
    from sqlalchemy import text

    with admin_engine.connect() as con:
        existe = con.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": nome}).scalar()
        if existe:
            log.info("Banco '%s' já existe.", nome)
            return
        try:
            con.execute(text(f'CREATE DATABASE "{nome}" WITH ENCODING \'UTF8\' TEMPLATE template0'))
        except Exception:  # noqa: BLE001 - no Windows o locale pode impedir UTF8 com template0
            log.warning("Não foi possível forçar UTF8; criando com as configurações padrão.")
            con.execute(text(f'CREATE DATABASE "{nome}"'))
        log.info("Banco '%s' criado.", nome)


def carregar_postgres(tabelas: dict[str, pd.DataFrame], args) -> None:
    from sqlalchemy import text

    engine, admin = criar_engines(args)
    garantir_banco(admin, args.db)

    with engine.begin() as con:
        con.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        con.execute(text(f"CREATE SCHEMA {SCHEMA}"))

    for nome in ORDEM_CARGA:
        df = tabelas[nome]
        log.info("Gravando %s.%s (%s linhas)...", SCHEMA, nome, f"{len(df):,}")
        df.to_sql(nome, engine, schema=SCHEMA, if_exists="replace", index=False,
                  chunksize=10_000, method="multi")

    log.info("Criando chaves, índices e views...")
    with engine.begin() as con:
        for comando in SQL_CONSTRAINTS.strip().split(";"):
            if comando.strip():
                con.execute(text(comando))
        con.execute(text(SQL_VW_ITENS))
        con.execute(text(SQL_VW_PEDIDOS))
        con.execute(text(f"ANALYZE"))

    log.info("Validação das contagens no banco:")
    with engine.connect() as con:
        for nome in ORDEM_CARGA + ["vw_fato_itens", "vw_pedidos"]:
            n = con.execute(text(f"SELECT COUNT(*) FROM {SCHEMA}.{nome}")).scalar()
            esperado = len(tabelas[nome]) if nome in tabelas else None
            marca = "" if esperado is None or esperado == n else f"  <-- DIVERGE (esperado {esperado})"
            log.info("  %-16s %9s%s", nome, f"{n:,}", marca)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="ETL Olist -> PostgreSQL")
    ap.add_argument("--projeto", help="caminho da pasta projeto-olist (padrão: procura em Documentos)")
    ap.add_argument("--skip-db", action="store_true", help="não carrega no PostgreSQL")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=5432)
    ap.add_argument("--user", default="postgres")
    ap.add_argument("--db", default="olist")
    args = ap.parse_args()

    projeto = localizar_projeto(args.projeto)
    raw_dir, processed_dir, report_dir = (projeto / "data" / "raw", projeto / "data" / "processed",
                                          projeto / "reports")
    log.info("Projeto: %s", projeto)

    csvs = preparar_dados_brutos(projeto, raw_dir)
    raw = carregar(csvs)

    q = Qualidade()
    tabelas = limpar(raw, q)
    salvar_arquivos(tabelas, q, raw, processed_dir, report_dir)

    if args.skip_db:
        log.info("--skip-db: carga no PostgreSQL ignorada.")
    else:
        carregar_postgres(tabelas, args)
    log.info("Concluído.")


if __name__ == "__main__":
    main()
