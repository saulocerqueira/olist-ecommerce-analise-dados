# 🛒 Análise de Dados do E-commerce Brasileiro (Olist)

Projeto de análise de dados de ponta a ponta: **extração e limpeza com Python (Pandas) → armazenamento em PostgreSQL → dashboard em Power BI**.

> **Status:** ETL e banco de dados concluídos ✅ · Modelo, medidas DAX e dashboard de 5 páginas com tema próprio ✅ · Prints, PDF e vídeo de apresentação 🚧

## 🎯 Objetivo

Responder perguntas de negócio sobre vendas, produtos, clientes, logística, satisfação, pagamentos e vendedores, usando o dataset público da Olist (≈100 mil pedidos entre 2016 e 2018).

## ❓ Perguntas de negócio

| Área | Perguntas |
|---|---|
| Vendas | Como evoluem receita e pedidos? Qual o ticket médio? Há sazonalidade? |
| Produtos | Quais categorias geram mais receita? Onde o frete pesa mais? |
| Clientes | De onde vêm os clientes? Qual a taxa de recompra? |
| Logística | Qual o prazo médio de entrega? Quanto dos pedidos chega atrasado? |
| Satisfação | **O atraso derruba a nota de avaliação?** Quais categorias têm pior nota? |
| Pagamentos | Quais formas de pagamento dominam? Quantas parcelas o cliente usa? |
| Vendedores | A receita é concentrada em poucos vendedores? |

## 🧰 Tecnologias

- **Python** (Pandas, NumPy, SQLAlchemy, psycopg2)
- **PostgreSQL** (schema relacional com chaves primárias, estrangeiras, índices e views)
- **Power BI** (modelagem, DAX e visualização)

## 🔄 Pipeline

```
Kaggle (.zip, 9 CSVs) ──► etl_olist.py (Pandas) ──► PostgreSQL (schema olist) ──► Power BI
                              │
                              └─► reports/ (relatório de qualidade dos dados)
```

O script `etl_olist.py` executa, em ordem:

1. Extrai o `.zip` e carrega os 9 CSVs.
2. Identifica inconsistências e remove duplicidades.
3. Valida a integridade referencial entre as tabelas.
4. Cria colunas derivadas (prazo de entrega, atraso, valor total do item etc.) e uma tabela calendário.
5. Gera relatórios de qualidade em `reports/`.
6. Carrega tudo no PostgreSQL com chaves, índices e duas views para análise.

## 🧹 Qualidade dos dados (principais achados)

Todas as verificações e ocorrências estão em [`reports/relatorio_qualidade.csv`](reports/relatorio_qualidade.csv).

| Problema encontrado | Ocorrências | Tratamento |
|---|---|---|
| Geolocalização: linhas totalmente duplicadas | 279.668 | removidas |
| Geolocalização: vários pontos para o mesmo CEP | 701.452 | consolidados (1 linha por CEP) |
| Geolocalização: coordenadas fora do Brasil | 33 | removidas |
| Produtos sem categoria | 610 | marcados como `sem_categoria` |
| Postagem à transportadora anterior à compra | 166 | data convertida para nulo |
| Pedidos `delivered` sem data de entrega | 8 | mantidos, fora das métricas de prazo |
| Pagamentos `not_defined` | 3 | removidos |

## 🗄️ Modelo de dados

Schema `olist` no PostgreSQL, com 9 tabelas e 2 views pensadas para o Power BI:

- `vw_fato_itens`: uma linha por **item vendido** (receita, categorias, vendedores)
- `vw_pedidos`: uma linha por **pedido** (ticket, entrega, pagamento, satisfação)
- `dim_calendario`: tabela de datas para análises temporais

Separar as duas views evita duplicar valores ao cruzar itens com pagamentos.

No Power BI, as **45 medidas DAX** ficam organizadas em pastas (Vendas, Clientes, Logística, Satisfação, Pagamentos, Vendedores e Textos dinâmicos) na tabela `_Medidas`. Regra de negócio: **receita e pedidos desconsideram status `canceled` e `unavailable`**. O código completo está em [`powerbi/medidas_olist.dax`](powerbi/medidas_olist.dax) (colunas calculadas e medidas) e [`powerbi/medidas_olist.tmdl`](powerbi/medidas_olist.tmdl) (script para a visão TMDL).

## 📊 Dashboard

Relatório em [`powerbi/relatorio_olist.pbix`](powerbi/relatorio_olist.pbix), com 5 páginas (1920×1080), navegador de páginas no topo e filtros de **ano** e **trimestre** sincronizados entre todas as páginas. Cada página segue o mesmo layout: título, 6 KPIs e 4 a 5 visuais. Os gráficos mensais mostram jan/2017 a ago/2018, os meses com dados completos (2016 e set–out/2018 têm poucos pedidos).

| Página | O que responde | Principais visuais |
|---|---|---|
| **1. Visão Executiva** | Como está o negócio como um todo? | KPIs (receita, pedidos, ticket médio, nota, % atraso, recompra), receita mensal vs. ano anterior, receita por estado e por região, participação das formas de pagamento |
| **2. Vendas e Produtos** | O que vende e quanto o frete pesa? | Treemap de receita por categoria, itens vendidos por mês, peso do frete por estado, ranking de categorias |
| **3. Clientes e Geografia** | De onde vêm os clientes e quantos voltam? | Clientes por estado, por região e por mês, ranking de cidades com taxa de recompra, texto de insight |
| **4. Logística e Satisfação** | O atraso derruba a nota? | Nota média por faixa de atraso, prazo real vs. estimado por mês, prazo e % de atraso por estado, nota no prazo vs. atrasados |
| **5. Pagamentos e Vendedores** | Como o cliente paga e quão concentrada é a receita? | Formas de pagamento, pedidos por número de parcelas, receita por estado do vendedor, curva de Pareto, ranking de vendedores |

### 🎨 Tema

Tema escuro próprio, **preto com vermelho em destaque**, em [`powerbi/tema_olist_dark_red.json`](powerbi/tema_olist_dark_red.json) (Exibição > Temas > Procurar temas). Já vem aplicado no `.pbix`.

| Uso | Cor |
|---|---|
| Fundo da página | `#0A0A0B` |
| Cartões e visuais | `#141416` (borda `#2A2A2E`) |
| Destaque principal | `#E5383B` |
| Variações de vermelho | `#FF6B6B` · `#A4161A` · `#660708` |
| Texto | `#F5F5F5` (secundário `#B8B8C0`) |

### 🖼️ Prints e PDF

*Prints das páginas, PDF e vídeo de apresentação: em breve na pasta `docs/`.*

Para gerar: abra o `.pbix` e use **Arquivo > Exportar > Exportar para PDF** (exporta as 5 páginas). Para os prints, recolha os painéis laterais, ajuste **Exibição > Ajustar à página** e capture cada página (Win + Shift + S), salvando em `docs/prints/`.

## 🔍 Principais achados

Valores calculados com a regra do dashboard (sem pedidos cancelados ou indisponíveis).

**Vendas e produtos**
- 💰 Receita de **R$ 13,49 milhões** em **98.199 pedidos**, com ticket médio de **R$ 137,42**.
- 📈 O pico mensal foi **novembro de 2017**: 7.423 pedidos e R$ 1,00 milhão (Black Friday). Mesmo incompleto, 2018 (R$ 7,34 mi) já supera 2017 inteiro (R$ 6,11 mi).
- 🛍️ As 3 maiores categorias, beleza e saúde (9,3%), relógios e presentes (8,9%) e cama, mesa e banho (7,7%), somam 25,9% da receita.
- 🚛 O frete equivale a **16,6%** da receita. Pesa 28,5% em Roraima e 26,3% no Maranhão, contra 13,8% em São Paulo.

**Clientes e geografia**
- 🗺️ **São Paulo** responde por 38,3% da receita; com Rio e Minas, 63,4%. O Sudeste concentra 68,6% dos clientes únicos.
- 🔁 Apenas **3,1%** dos clientes únicos (2.997 de 96.096) compraram mais de uma vez: o negócio vive de aquisição, não de recompra.

**Logística e satisfação**
- 🚚 Entrega média de **12,6 dias**, contra 23,7 estimados. **6,8%** dos pedidos chegam atrasados, em média 10,6 dias depois do prometido.
- ⭐ Pedidos no prazo têm nota média **4,29**; atrasados, **2,27**. A nota cai de 3,29 (1 a 3 dias de atraso) para 2,11 (4 a 7 dias) e fica abaixo de 1,8 acima de 8 dias.
- 🧭 A distância pesa: a entrega leva 8,8 dias em SP e passa de 26 dias em RR, AP e AM.
- 🛋️ Entre as categorias com ao menos 500 pedidos, a pior nota é de móveis de escritório (3,49).

**Pagamentos e vendedores**
- 💳 **75,4%** dos pedidos são pagos com cartão de crédito e **19,9%** com boleto. No cartão, a média é de 3,6 parcelas e 68% dos pedidos são parcelados.
- 🏪 Dos 3.053 vendedores ativos, os **20% maiores respondem por 82,6%** da receita e os 30 maiores (1%), por 25,8%. Vendedores de SP geram 64,4% da receita.

## ▶️ Como executar

**Pré-requisitos:** Python 3.10+, PostgreSQL instalado e em execução e Power BI Desktop (versão mais recente).

```bash
# 1. Clone o repositório
git clone https://github.com/saulocerqueira/olist-ecommerce-analise-dados.git
cd olist-ecommerce-analise-dados

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Baixe o dataset no Kaggle e salve o .zip nesta pasta
#    https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

# 4. Execute o ETL (pede a senha do PostgreSQL)
python etl_olist.py --projeto .
```

Para rodar só a limpeza, sem banco: `python etl_olist.py --projeto . --skip-db`.
A senha também pode ser definida na variável de ambiente `PGPASSWORD`.

Para abrir o dashboard, execute o ETL, abra `powerbi/relatorio_olist.pbix` e, se necessário, ajuste a conexão em Transformar dados > Configurações da fonte de dados (servidor, banco `olist`, schema `olist`).

## 📁 Estrutura do repositório

```
├── etl_olist.py                       # pipeline de ETL (extração, limpeza e carga)
├── requirements.txt
├── reports/                           # relatórios de qualidade dos dados
├── powerbi/
│   ├── relatorio_olist.pbix           # dashboard com 5 páginas
│   ├── tema_olist_dark_red.json       # tema preto e vermelho
│   ├── medidas_olist.dax              # colunas calculadas e medidas DAX
│   └── medidas_olist.tmdl             # medidas em TMDL
└── docs/                              # prints, PDF e vídeo do dashboard
```

## 📄 Dados e licença

Dataset: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (Kaggle). Os dados brutos **não** estão neste repositório. Consulte a licença do dataset na página do Kaggle antes de reutilizá-lo.

## 👤 Autor

**Saulo Cerqueira** · [LinkedIn](https://www.linkedin.com/in/saulodecerqueira/)
