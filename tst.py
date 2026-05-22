import time
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# ============================================================
# CONFIGURAÇÕES
# ============================================================

TIMES_ALVO = {
    "Cleveland Cavaliers",
    "New York Knicks",
    "San Antonio Spurs",
    "Oklahoma City Thunder",
}

INTERVALO_ATUALIZACAO = 10  # segundos

URL_SCOREBOARD = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
URL_BOXSCORE = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"

HEADERS_NBA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
}


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def montar_nome_time(team_data: Dict[str, Any]) -> str:
    if not team_data:
        return ""

    cidade = team_data.get("teamCity", "")
    nome = team_data.get("teamName", "")

    return f"{cidade} {nome}".strip()


def jogo_envolve_times_alvo(game: Dict[str, Any]) -> bool:
    home_team = game.get("homeTeam", {})
    away_team = game.get("awayTeam", {})

    home_name = montar_nome_time(home_team)
    away_name = montar_nome_time(away_team)

    return home_name in TIMES_ALVO or away_name in TIMES_ALVO


# ============================================================
# FUNÇÕES DE API NBA
# ============================================================

def consultar_json_nba(url: str) -> Dict[str, Any]:
    try:
        response = requests.get(
            url,
            headers=HEADERS_NBA,
            timeout=20,
        )

        if response.status_code == 403:
            raise Exception(
                "A NBA recusou temporariamente a consulta. "
                "Isso pode ocorrer por bloqueio da CDN, IP do servidor ou limitação temporária."
            )

        if response.status_code == 404:
            raise Exception(
                "O recurso ainda não está disponível. "
                "O jogo pode ainda não ter começado ou o boxscore ainda não foi publicado."
            )

        if response.status_code != 200:
            raise Exception(
                f"Erro HTTP {response.status_code} ao consultar: {url}"
            )

        if not response.text.strip():
            raise Exception("A NBA retornou uma resposta vazia.")

        try:
            return response.json()
        except ValueError:
            raise Exception("A resposta da NBA não veio em JSON válido.")

    except requests.exceptions.Timeout:
        raise Exception("Tempo limite ao consultar a NBA.")

    except requests.exceptions.ConnectionError:
        raise Exception("Erro de conexão ao consultar a NBA.")

    except requests.exceptions.RequestException as e:
        raise Exception(f"Erro inesperado ao consultar a NBA: {e}")


def buscar_scoreboard_direto() -> Dict[str, Any]:
    return consultar_json_nba(URL_SCOREBOARD)


def buscar_boxscore_direto(game_id: str) -> Dict[str, Any]:
    url = URL_BOXSCORE.format(game_id=game_id)
    return consultar_json_nba(url)


# ============================================================
# TRATAMENTO DOS DADOS
# ============================================================

def extrair_jogadores_do_time(
    game_id: str,
    game_info: Dict[str, Any],
    team_data: Dict[str, Any],
) -> List[Dict[str, Any]]:

    registros = []

    if not team_data:
        return registros

    time_nome = montar_nome_time(team_data)

    if time_nome not in TIMES_ALVO:
        return registros

    status_jogo = game_info.get("gameStatusText")
    periodo = game_info.get("period")
    relogio = game_info.get("gameClock")

    time_sigla = team_data.get("teamTricode")
    team_id = team_data.get("teamId")

    players = team_data.get("players", [])

    for player in players:
        stats = player.get("statistics", {})

        jogador = player.get("name") or stats.get("name")
        person_id = player.get("personId")

        minutos = stats.get("minutes")

        # Ignora jogador que ainda não entrou em quadra
        if not minutos:
            continue

        registro = {
            "DATA_ATUALIZACAO": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "GAME_ID": game_id,
            "STATUS": status_jogo,
            "PERIODO": periodo,
            "RELOGIO": relogio,

            "TEAM_ID": team_id,
            "TIME": time_nome,
            "SIGLA": time_sigla,

            "PERSON_ID": person_id,
            "JOGADOR": jogador,
            "MINUTOS": minutos,

            "PONTOS": safe_int(stats.get("points")),
            "REBOTES": safe_int(stats.get("reboundsTotal")),
            "ASSISTENCIAS": safe_int(stats.get("assists")),

            "CESTA_2_CONV": safe_int(stats.get("twoPointersMade")),
            "CESTA_2_TENT": safe_int(stats.get("twoPointersAttempted")),
            "CESTA_3_CONV": safe_int(stats.get("threePointersMade")),
            "CESTA_3_TENT": safe_int(stats.get("threePointersAttempted")),

            "ROUBOS": safe_int(stats.get("steals")),
            "BLOQUEIOS": safe_int(stats.get("blocks")),
            "TURNOVERS": safe_int(stats.get("turnovers")),
            "FALTAS": safe_int(stats.get("foulsPersonal")),
            "PLUS_MINUS": safe_float(stats.get("plusMinusPoints")),
        }

        registros.append(registro)

    return registros


def buscar_dados_ao_vivo() -> pd.DataFrame:
    registros = []

    try:
        dados_scoreboard = buscar_scoreboard_direto()
    except Exception as e:
        st.warning(f"Não foi possível consultar o scoreboard da NBA agora: {e}")
        return pd.DataFrame()

    games = dados_scoreboard.get("scoreboard", {}).get("games", [])

    if not games:
        return pd.DataFrame()

    jogos_alvo = [
        game for game in games
        if jogo_envolve_times_alvo(game)
    ]

    if not jogos_alvo:
        return pd.DataFrame()

    for game in jogos_alvo:
        game_id = game.get("gameId")

        if not game_id:
            continue

        try:
            dados_boxscore = buscar_boxscore_direto(game_id)
        except Exception as e:
            st.warning(f"Erro ao buscar boxscore do jogo {game_id}: {e}")
            continue

        game_info = dados_boxscore.get("game", {})

        home_team = game_info.get("homeTeam", {})
        away_team = game_info.get("awayTeam", {})

        registros += extrair_jogadores_do_time(game_id, game_info, home_team)
        registros += extrair_jogadores_do_time(game_id, game_info, away_team)

        time.sleep(0.5)

    return pd.DataFrame(registros)


def calcular_metricas_estatisticas(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    df["PRA"] = (
        df["PONTOS"]
        + df["REBOTES"]
        + df["ASSISTENCIAS"]
    )

    df["ACOES_POSITIVAS"] = (
        df["PONTOS"]
        + df["REBOTES"]
        + df["ASSISTENCIAS"]
        + df["ROUBOS"]
        + df["BLOQUEIOS"]
    )

    df["IMPACTO_ESTATISTICO"] = (
        df["PONTOS"]
        + df["REBOTES"]
        + df["ASSISTENCIAS"]
        + df["ROUBOS"]
        + df["BLOQUEIOS"]
        - df["TURNOVERS"]
        - df["FALTAS"]
    )

    df["TOTAL_ARREMESSOS"] = (
        df["CESTA_2_TENT"]
        + df["CESTA_3_TENT"]
    )

    df["TOTAL_CONVERTIDOS"] = (
        df["CESTA_2_CONV"]
        + df["CESTA_3_CONV"]
    )

    df["APROVEITAMENTO_GERAL_%"] = df.apply(
        lambda row: round(
            (row["TOTAL_CONVERTIDOS"] / row["TOTAL_ARREMESSOS"]) * 100,
            2
        )
        if row["TOTAL_ARREMESSOS"] > 0 else 0,
        axis=1,
    )

    df["APROVEITAMENTO_2P_%"] = df.apply(
        lambda row: round(
            (row["CESTA_2_CONV"] / row["CESTA_2_TENT"]) * 100,
            2
        )
        if row["CESTA_2_TENT"] > 0 else 0,
        axis=1,
    )

    df["APROVEITAMENTO_3P_%"] = df.apply(
        lambda row: round(
            (row["CESTA_3_CONV"] / row["CESTA_3_TENT"]) * 100,
            2
        )
        if row["CESTA_3_TENT"] > 0 else 0,
        axis=1,
    )

    df["ERROS_E_RISCOS"] = (
        df["TURNOVERS"]
        + df["FALTAS"]
    )

    df["PARTICIPACAO_OFENSIVA"] = (
        df["PONTOS"]
        + df["ASSISTENCIAS"]
    )

    df["CONTRIBUICAO_SEM_PONTUAR"] = (
        df["REBOTES"]
        + df["ASSISTENCIAS"]
        + df["ROUBOS"]
        + df["BLOQUEIOS"]
    )

    return df


# ============================================================
# CONFIGURAÇÃO STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Dashboard NBA Estatístico",
    layout="wide",
)


st.markdown(
    """
    <style>
        [data-testid="stToolbar"] {
            visibility: hidden;
            height: 0%;
            position: fixed;
        }

        .stDeployButton {
            display: none;
        }

        #MainMenu {
            visibility: hidden;
        }

        footer {
            visibility: hidden;
        }

        header {
            visibility: hidden;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# DASHBOARD
# ============================================================

st.title("Dashboard NBA Estatístico ao Vivo")

st.caption(
    f"Atualização automática a cada {INTERVALO_ATUALIZACAO} segundos. "
    f"Times monitorados: {', '.join(sorted(TIMES_ALVO))}"
)

st.info(
    "Este painel mostra estatísticas ao vivo para análise de desempenho dos jogadores. "
    "Os dados não garantem resultados futuros."
)

with st.spinner("Consultando dados da NBA..."):
    df = buscar_dados_ao_vivo()
    df = calcular_metricas_estatisticas(df)


# ============================================================
# EXIBIÇÃO SEM DADOS
# ============================================================

if df.empty:
    st.info("Nenhum dado encontrado para os times monitorados no momento.")

    st.write("Possíveis motivos:")
    st.write("- Não há jogo ao vivo agora envolvendo esses times.")
    st.write("- O jogo ainda não começou.")
    st.write("- O boxscore ainda não foi disponibilizado pela NBA.")
    st.write("- A NBA retornou instabilidade temporária ou bloqueou a consulta.")
    st.write("- Os times monitorados não jogam hoje.")


# ============================================================
# EXIBIÇÃO COM DADOS
# ============================================================

else:
    ultima_atualizacao = df["DATA_ATUALIZACAO"].max()

    st.success(f"Dados atualizados em: {ultima_atualizacao}")

    # --------------------------------------------------------
    # CARDS GERAIS
    # --------------------------------------------------------

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Jogadores", len(df))
    col2.metric("Total de Pontos", int(df["PONTOS"].sum()))
    col3.metric("Total de Rebotes", int(df["REBOTES"].sum()))
    col4.metric("Total de Assistências", int(df["ASSISTENCIAS"].sum()))
    col5.metric("Times no Dashboard", df["TIME"].nunique())

    st.divider()

    # --------------------------------------------------------
    # FILTRO POR TIME
    # --------------------------------------------------------

    times_disponiveis = sorted(df["TIME"].dropna().unique())

    times_selecionados = st.multiselect(
        "Filtrar por time",
        options=times_disponiveis,
        default=times_disponiveis,
    )

    df_filtrado = df[df["TIME"].isin(times_selecionados)].copy()

    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado para o filtro selecionado.")

    else:
        # ====================================================
        # DESTAQUES ESTATÍSTICOS
        # ====================================================

        st.subheader("Destaques estatísticos ao vivo")

        col_a, col_b, col_c, col_d = st.columns(4)

        top_pontos = df_filtrado.sort_values("PONTOS", ascending=False).head(1)
        top_pra = df_filtrado.sort_values("PRA", ascending=False).head(1)
        top_impacto = df_filtrado.sort_values("IMPACTO_ESTATISTICO", ascending=False).head(1)
        top_aproveitamento = df_filtrado[df_filtrado["TOTAL_ARREMESSOS"] > 0].sort_values(
            "APROVEITAMENTO_GERAL_%",
            ascending=False,
        ).head(1)

        if not top_pontos.empty:
            col_a.metric(
                "Maior pontuador",
                top_pontos.iloc[0]["JOGADOR"],
                f'{top_pontos.iloc[0]["PONTOS"]} pontos',
            )

        if not top_pra.empty:
            col_b.metric(
                "Maior PRA",
                top_pra.iloc[0]["JOGADOR"],
                f'{top_pra.iloc[0]["PRA"]} P+R+A',
            )

        if not top_impacto.empty:
            col_c.metric(
                "Maior impacto",
                top_impacto.iloc[0]["JOGADOR"],
                f'{top_impacto.iloc[0]["IMPACTO_ESTATISTICO"]}',
            )

        if not top_aproveitamento.empty:
            col_d.metric(
                "Melhor aproveitamento",
                top_aproveitamento.iloc[0]["JOGADOR"],
                f'{top_aproveitamento.iloc[0]["APROVEITAMENTO_GERAL_%"]}%',
            )

        st.divider()

        # ====================================================
        # TABELA RANKING ESTATÍSTICO
        # ====================================================

        st.subheader("Ranking estatístico geral dos jogadores")

        colunas_ranking = [
            "TIME",
            "JOGADOR",
            "MINUTOS",
            "PONTOS",
            "REBOTES",
            "ASSISTENCIAS",
            "PRA",
            "ROUBOS",
            "BLOQUEIOS",
            "TURNOVERS",
            "FALTAS",
            "PLUS_MINUS",
            "TOTAL_ARREMESSOS",
            "TOTAL_CONVERTIDOS",
            "APROVEITAMENTO_GERAL_%",
            "APROVEITAMENTO_2P_%",
            "APROVEITAMENTO_3P_%",
            "PARTICIPACAO_OFENSIVA",
            "CONTRIBUICAO_SEM_PONTUAR",
            "ERROS_E_RISCOS",
            "IMPACTO_ESTATISTICO",
        ]

        df_ranking = df_filtrado[colunas_ranking].sort_values(
            by="IMPACTO_ESTATISTICO",
            ascending=False,
        )

        st.dataframe(
            df_ranking,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        # ====================================================
        # GRÁFICO 1 - PONTOS POR JOGADOR
        # ====================================================

        st.subheader("Pontos por jogador")

        df_pontos = df_filtrado.sort_values("PONTOS", ascending=False)

        fig_pontos = px.bar(
            df_pontos,
            x="JOGADOR",
            y="PONTOS",
            color="TIME",
            text="PONTOS",
            hover_data=[
                "TIME",
                "MINUTOS",
                "REBOTES",
                "ASSISTENCIAS",
                "PRA",
                "APROVEITAMENTO_GERAL_%",
            ],
            title="Pontuação dos jogadores",
        )

        fig_pontos.update_layout(
            xaxis_title="Jogador",
            yaxis_title="Pontos",
            legend_title="Time",
        )

        st.plotly_chart(fig_pontos, use_container_width=True)

        # ====================================================
        # GRÁFICO 2 - PRA
        # ====================================================

        st.subheader("PRA por jogador")

        df_pra = df_filtrado.sort_values("PRA", ascending=False)

        fig_pra = px.bar(
            df_pra,
            x="JOGADOR",
            y="PRA",
            color="TIME",
            text="PRA",
            hover_data=[
                "PONTOS",
                "REBOTES",
                "ASSISTENCIAS",
                "MINUTOS",
                "PLUS_MINUS",
            ],
            title="Pontos + Rebotes + Assistências por jogador",
        )

        fig_pra.update_layout(
            xaxis_title="Jogador",
            yaxis_title="PRA",
            legend_title="Time",
        )

        st.plotly_chart(fig_pra, use_container_width=True)

        # ====================================================
        # GRÁFICO 3 - IMPACTO ESTATÍSTICO
        # ====================================================

        st.subheader("Impacto estatístico por jogador")

        df_impacto = df_filtrado.sort_values(
            "IMPACTO_ESTATISTICO",
            ascending=False,
        )

        fig_impacto = px.bar(
            df_impacto,
            x="JOGADOR",
            y="IMPACTO_ESTATISTICO",
            color="TIME",
            text="IMPACTO_ESTATISTICO",
            hover_data=[
                "PONTOS",
                "REBOTES",
                "ASSISTENCIAS",
                "ROUBOS",
                "BLOQUEIOS",
                "TURNOVERS",
                "FALTAS",
                "PLUS_MINUS",
            ],
            title="Impacto estatístico dos jogadores",
        )

        fig_impacto.update_layout(
            xaxis_title="Jogador",
            yaxis_title="Impacto estatístico",
            legend_title="Time",
        )

        st.plotly_chart(fig_impacto, use_container_width=True)

        # ====================================================
        # GRÁFICO 4 - APROVEITAMENTO GERAL
        # ====================================================

        st.subheader("Aproveitamento geral de arremessos")

        df_aproveitamento = df_filtrado[df_filtrado["TOTAL_ARREMESSOS"] > 0].sort_values(
            "APROVEITAMENTO_GERAL_%",
            ascending=False,
        )

        if df_aproveitamento.empty:
            st.info("Ainda não há arremessos suficientes para calcular aproveitamento.")
        else:
            fig_aproveitamento = px.bar(
                df_aproveitamento,
                x="JOGADOR",
                y="APROVEITAMENTO_GERAL_%",
                color="TIME",
                text="APROVEITAMENTO_GERAL_%",
                hover_data=[
                    "TOTAL_CONVERTIDOS",
                    "TOTAL_ARREMESSOS",
                    "APROVEITAMENTO_2P_%",
                    "APROVEITAMENTO_3P_%",
                ],
                title="Aproveitamento geral de arremessos por jogador",
            )

            fig_aproveitamento.update_layout(
                xaxis_title="Jogador",
                yaxis_title="Aproveitamento %",
                legend_title="Time",
            )

            st.plotly_chart(fig_aproveitamento, use_container_width=True)

        # ====================================================
        # GRÁFICO 5 - PONTOS, REBOTES E ASSISTÊNCIAS
        # ====================================================

        st.subheader("Comparação: pontos, rebotes e assistências")

        df_comparativo = df_filtrado.sort_values("PRA", ascending=False)

        fig_comparativo = px.bar(
            df_comparativo,
            x="JOGADOR",
            y=["PONTOS", "REBOTES", "ASSISTENCIAS"],
            barmode="group",
            title="Comparativo de pontos, rebotes e assistências",
        )

        fig_comparativo.update_layout(
            xaxis_title="Jogador",
            yaxis_title="Quantidade",
            legend_title="Indicador",
        )

        st.plotly_chart(fig_comparativo, use_container_width=True)

        # ====================================================
        # GRÁFICO 6 - REBOTES X ASSISTÊNCIAS
        # ====================================================

        st.subheader("Rebotes x Assistências")

        fig_reb_ast = px.scatter(
            df_filtrado,
            x="REBOTES",
            y="ASSISTENCIAS",
            size="PONTOS",
            color="TIME",
            hover_name="JOGADOR",
            hover_data=[
                "MINUTOS",
                "PONTOS",
                "PRA",
                "ROUBOS",
                "BLOQUEIOS",
                "TURNOVERS",
                "PLUS_MINUS",
            ],
            title="Relação entre rebotes, assistências e pontos",
        )

        fig_reb_ast.update_layout(
            xaxis_title="Rebotes",
            yaxis_title="Assistências",
            legend_title="Time",
        )

        st.plotly_chart(fig_reb_ast, use_container_width=True)

        # ====================================================
        # GRÁFICO 7 - PARTICIPAÇÃO OFENSIVA
        # ====================================================

        st.subheader("Participação ofensiva")

        df_ofensiva = df_filtrado.sort_values(
            "PARTICIPACAO_OFENSIVA",
            ascending=False,
        )

        fig_ofensiva = px.bar(
            df_ofensiva,
            x="JOGADOR",
            y="PARTICIPACAO_OFENSIVA",
            color="TIME",
            text="PARTICIPACAO_OFENSIVA",
            hover_data=[
                "PONTOS",
                "ASSISTENCIAS",
                "PRA",
                "MINUTOS",
            ],
            title="Participação ofensiva: pontos + assistências",
        )

        fig_ofensiva.update_layout(
            xaxis_title="Jogador",
            yaxis_title="Pontos + Assistências",
            legend_title="Time",
        )

        st.plotly_chart(fig_ofensiva, use_container_width=True)

        # ====================================================
        # GRÁFICO 8 - CONTRIBUIÇÃO SEM PONTUAR
        # ====================================================

        st.subheader("Contribuição sem pontuar")

        df_sem_pontuar = df_filtrado.sort_values(
            "CONTRIBUICAO_SEM_PONTUAR",
            ascending=False,
        )

        fig_sem_pontuar = px.bar(
            df_sem_pontuar,
            x="JOGADOR",
            y="CONTRIBUICAO_SEM_PONTUAR",
            color="TIME",
            text="CONTRIBUICAO_SEM_PONTUAR",
            hover_data=[
                "REBOTES",
                "ASSISTENCIAS",
                "ROUBOS",
                "BLOQUEIOS",
                "MINUTOS",
            ],
            title="Contribuição sem pontuar: rebotes + assistências + roubos + bloqueios",
        )

        fig_sem_pontuar.update_layout(
            xaxis_title="Jogador",
            yaxis_title="Contribuição",
            legend_title="Time",
        )

        st.plotly_chart(fig_sem_pontuar, use_container_width=True)

        # ====================================================
        # GRÁFICO 9 - ERROS E RISCOS
        # ====================================================

        st.subheader("Erros e riscos por jogador")

        df_erros = df_filtrado.sort_values(
            "ERROS_E_RISCOS",
            ascending=False,
        )

        fig_erros = px.bar(
            df_erros,
            x="JOGADOR",
            y="ERROS_E_RISCOS",
            color="TIME",
            text="ERROS_E_RISCOS",
            hover_data=[
                "TURNOVERS",
                "FALTAS",
                "MINUTOS",
            ],
            title="Erros e riscos: turnovers + faltas",
        )

        fig_erros.update_layout(
            xaxis_title="Jogador",
            yaxis_title="Turnovers + Faltas",
            legend_title="Time",
        )

        st.plotly_chart(fig_erros, use_container_width=True)

        # ====================================================
        # GRÁFICO 10 - CESTAS DE 2 PONTOS
        # ====================================================

        st.subheader("Cestas de 2 pontos")

        df_2p = df_filtrado.sort_values("CESTA_2_TENT", ascending=False)

        fig_2p = px.bar(
            df_2p,
            x="JOGADOR",
            y=["CESTA_2_CONV", "CESTA_2_TENT"],
            barmode="group",
            title="Cestas de 2 pontos convertidas x tentadas",
        )

        fig_2p.update_layout(
            xaxis_title="Jogador",
            yaxis_title="Quantidade",
            legend_title="Indicador",
        )

        st.plotly_chart(fig_2p, use_container_width=True)

        # ====================================================
        # GRÁFICO 11 - CESTAS DE 3 PONTOS
        # ====================================================

        st.subheader("Cestas de 3 pontos")

        df_3p = df_filtrado.sort_values("CESTA_3_TENT", ascending=False)

        fig_3p = px.bar(
            df_3p,
            x="JOGADOR",
            y=["CESTA_3_CONV", "CESTA_3_TENT"],
            barmode="group",
            title="Cestas de 3 pontos convertidas x tentadas",
        )

        fig_3p.update_layout(
            xaxis_title="Jogador",
            yaxis_title="Quantidade",
            legend_title="Indicador",
        )

        st.plotly_chart(fig_3p, use_container_width=True)

        # ====================================================
        # TABELA DETALHADA
        # ====================================================

        st.subheader("Tabela detalhada do jogo")

        colunas_tabela = [
            "STATUS",
            "PERIODO",
            "RELOGIO",
            "TIME",
            "JOGADOR",
            "MINUTOS",
            "PONTOS",
            "REBOTES",
            "ASSISTENCIAS",
            "PRA",
            "CESTA_2_CONV",
            "CESTA_2_TENT",
            "CESTA_3_CONV",
            "CESTA_3_TENT",
            "TOTAL_CONVERTIDOS",
            "TOTAL_ARREMESSOS",
            "APROVEITAMENTO_GERAL_%",
            "APROVEITAMENTO_2P_%",
            "APROVEITAMENTO_3P_%",
            "ROUBOS",
            "BLOQUEIOS",
            "TURNOVERS",
            "FALTAS",
            "PLUS_MINUS",
            "IMPACTO_ESTATISTICO",
            "DATA_ATUALIZACAO",
            "GAME_ID",
        ]

        st.dataframe(
            df_filtrado[colunas_tabela].sort_values(
                by=["TIME", "IMPACTO_ESTATISTICO"],
                ascending=[True, False],
            ),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# AUTO REFRESH
# ============================================================

st.divider()

st.caption(
    f"A página será atualizada automaticamente em {INTERVALO_ATUALIZACAO} segundos."
)

time.sleep(INTERVALO_ATUALIZACAO)
st.rerun()