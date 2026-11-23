# 🛒 Análise de Dados do E-commerce Brasileiro (Olist)

Projeto de análise de dados de ponta a ponta: **extração e limpeza com Python (Pandas) → armazenamento em PostgreSQL → dashboard em Power BI**.

> \*\*Status:\*\* ETL e banco de dados concluídos ✅ · Dashboard em Power BI em desenvolvimento 🚧

## 🎯 Objetivo

Responder perguntas de negócio sobre vendas, produtos, clientes, logística, satisfação, pagamentos e vendedores, usando o dataset público da Olist (≈100 mil pedidos entre 2016 e 2018).

## ❓ Perguntas de negócio

|Área|Perguntas|
|-|-|
|Vendas|Como evoluem receita e pedidos? Qual o ticket médio? Há sazonalidade?|
|Produtos|Quais categorias geram mais receita? Onde o frete pesa mais?|
|Clientes|De onde vêm os clientes? Qual a taxa de recompra?|
|Logística|Qual o prazo médio de entrega? Quanto dos pedidos chega atrasado?|
|Satisfação|**O atraso derruba a nota de avaliação?** Quais categorias têm pior nota?|
|Pagamentos|Quais formas de pagamento dominam? Quantas parcelas o cliente usa?|
|Vendedores|A receita é concentrada em poucos vendedores?|

## 🧰 Tecnologias

* **Python** (Pandas, NumPy, SQLAlchemy, psycopg2)
* **PostgreSQL** (schema relacional com chaves primárias, estrangeiras, índices e views)
* **Power BI** (modelagem, DAX e visualização)

## 🔄 Pipeline

```
Kaggle (.zip, 9 CSVs) ──► etl\_olist.py (Pandas) ──► PostgreSQL (schema olist) ──► Power BI
                              │
                              └─► reports/ (relatório de qualidade dos dados)
```

O script `etl\_olist.py` executa, em ordem:

1. Extrai o `.zip` e carrega os 9 CSVs.
2. Identifica inconsistências e remove duplicidades.
3. Valida a integridade referencial entre as tabelas.
4. Cria colunas derivadas (prazo de entrega, atraso, valor total do item etc.) e uma tabela calendário.
5. Gera relatórios de qualidade em `reports/`.
6. Carrega tudo no PostgreSQL com chaves, índices e duas views para análise.

## 🧹 Qualidade dos dados (principais achados)

Todas as verificações e ocorrências estão em [`reports/relatorio\_qualidade.csv`](reports/relatorio_qualidade.csv).

|Problema encontrado|Ocorrências|Tratamento|
|-|-|-|
|Geolocalização: linhas totalmente duplicadas|279.668|removidas|
|Geolocalização: vários pontos para o mesmo CEP|701.452|consolidados (1 linha por CEP)|
|Geolocalização: coordenadas fora do Brasil|33|removidas|
|Produtos sem categoria|610|marcados como `sem\_categoria`|
|Postagem à transportadora anterior à compra|166|data convertida para nulo|
|Pedidos `delivered` sem data de entrega|8|mantidos, fora das métricas de prazo|
|Pagamentos `not\_defined`|3|removidos|

## 🗄️ Modelo de dados

Schema `olist` no PostgreSQL, com 9 tabelas e 2 views pensadas para o Power BI:

* `vw\_fato\_itens`: uma linha por **item vendido** (receita, categorias, vendedores)
* `vw\_pedidos`: uma linha por **pedido** (ticket, entrega, pagamento, satisfação)
* `dim\_calendario`: tabela de datas para análises temporais

Separar as duas views evita duplicar valores ao cruzar itens com pagamentos.

## 🔍 Primeiros achados (análise preliminar)

* 📈 O pico de vendas foi em **novembro de 2017**, com 7.544 pedidos (Black Friday).
* 🚚 O prazo médio de entrega é de **12,6 dias**, com **6,8%** dos pedidos entregues com atraso.
* ⭐ Pedidos no prazo têm nota média **4,29**; pedidos atrasados, **2,27**.
* 🔁 Apenas **3,1%** dos clientes únicos compraram mais de uma vez.
* 🏪 Os 20% maiores vendedores respondem por **82,7%** da receita.

## ▶️ Como executar

**Pré-requisitos:** Python 3.10+, PostgreSQL instalado e em execução.

```bash
# 1. Clone o repositório
git clone https://github.com/saulocerqueira/olist-ecommerce-analise-dados.git
cd olist-ecommerce-analise-dados

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Baixe o dataset no Kaggle e salve o .zip nesta pasta
#    https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

# 4. Execute o ETL (pede a senha do PostgreSQL)
python etl\_olist.py --projeto .
```

Para rodar só a limpeza, sem banco: `python etl\_olist.py --projeto . --skip-db`.
A senha também pode ser definida na variável de ambiente `PGPASSWORD`.

## 📁 Estrutura do repositório

```
├── etl\_olist.py              # pipeline de ETL (extração, limpeza e carga)
├── requirements.txt
├── reports/                  # relatórios de qualidade dos dados
├── powerbi/
│   ├── tema\_olist\_dark\_red.json   # tema do dashboard
│   └── medidas\_olist.dax          # colunas calculadas e medidas DAX
└── docs/                     # imagens e documentação
```

## 📊 Dashboard

*Em desenvolvimento. Em breve: prints das páginas e arquivo `.pbix`.*

<!-- Quando terminar, adicione prints:
!\[Visão Executiva](docs/pagina1\_visao\_executiva.png)

## 📄 Dados e licença

Dataset: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (Kaggle). Os dados brutos **não** estão neste repositório. Consulte a licença do dataset na página do Kaggle antes de reutilizá-lo.

## 👤 Autor

**Saulo Cerqueira** · [LinkedIn](https://www.linkedin.com/in/saulodecerqueira/) · https://www.linkedin.com/in/saulodecerqueira/

