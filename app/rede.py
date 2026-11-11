"""Avaliação do teste de rede: transforma as métricas em ok / atenção / reprovado."""
from app import config

_ORDEM = {"ok": 0, "atencao": 1, "reprovado": 2}

# O servidor grava os bytes em lotes de ~2 MB e há streams em paralelo; a folga evita
# falso alarme. Ainda pega quem inventa números sem transferir nada.
TOLERANCIA_BYTES = 8_000_000


def nivel_metrica(regra: dict, valor: float) -> str:
    if regra["tipo"] == "max":
        if valor <= regra["bom"]:
            return "ok"
        return "atencao" if valor <= regra["minimo"] else "reprovado"
    if valor >= regra["bom"]:
        return "ok"
    return "atencao" if valor >= regra["minimo"] else "reprovado"


def avaliar(metricas: dict, alertas: list[str] | None = None) -> tuple[str, dict]:
    """Devolve (resultado_geral, detalhes). O pior nível entre as métricas manda.
    Qualquer alerta de inconsistência (ex.: bytes que não batem) reprova o teste."""
    alertas = list(alertas or [])
    niveis = {}
    for chave, regra in config.CRITERIOS.items():
        valor = metricas.get(chave)
        if valor is not None:
            niveis[chave] = nivel_metrica(regra, valor)

    if not niveis:
        alertas.append("Nenhuma métrica foi medida.")
        resultado = "reprovado"
    else:
        resultado = max(niveis.values(), key=lambda n: _ORDEM[n])
    if alertas:
        resultado = "reprovado"
    return resultado, {"niveis": niveis, "alertas": alertas}


def checar_consistencia(bytes_down_cliente, bytes_up_cliente,
                        bytes_down_servidos, bytes_up_recebidos) -> list[str]:
    """O celular não pode relatar mais dados do que o servidor realmente enviou/recebeu.
    Barra resultado inventado chamando a API na mão."""
    alertas = []
    if bytes_down_cliente and bytes_down_cliente > bytes_down_servidos * 1.1 + TOLERANCIA_BYTES:
        alertas.append("Bytes de download informados não batem com o que o servidor enviou.")
    if bytes_up_cliente and bytes_up_cliente > bytes_up_recebidos * 1.1 + TOLERANCIA_BYTES:
        alertas.append("Bytes de upload informados não batem com o que o servidor recebeu.")
    return alertas
