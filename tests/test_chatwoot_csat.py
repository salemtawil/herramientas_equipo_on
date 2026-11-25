from utils.chatwoot_reportes import ChatwootClient


def _cliente():
    return ChatwootClient(base_url="https://chatwoot.invalid", account_id="2", api_token="x")


def test_respuestas_csat_pagina_hasta_vacia():
    client = _cliente()
    paginas = [[{"id": 1}, {"id": 2}], [{"id": 2}, {"id": 3}], []]
    llamadas = []

    def fake_get(path, params=None):
        llamadas.append((path, dict(params)))
        return paginas[len(llamadas) - 1]

    client.get = fake_get

    assert [r["id"] for r in client.respuestas_csat(100, 200)] == [1, 2, 3]
    assert llamadas[0] == (
        "/api/v1/accounts/2/csat_survey_responses",
        {"since": "100", "until": "200", "page": 1},
    )
    assert llamadas[1][1]["page"] == 2
    assert len(llamadas) == 3


def test_respuestas_csat_respeta_max_paginas():
    client = _cliente()
    llamadas = []

    def fake_get(path, params=None):
        llamadas.append(params["page"])
        return [{"id": params["page"]}]

    client.get = fake_get

    assert len(client.respuestas_csat(1, 2, max_paginas=3)) == 3
    assert llamadas == [1, 2, 3]


def test_metricas_csat_usa_endpoint_metrics():
    client = _cliente()
    llamadas = []

    def fake_get(path, params=None):
        llamadas.append((path, params))
        return {"total_count": 70, "ratings_count": {"1": 5}}

    client.get = fake_get

    assert client.metricas_csat(100, 200)["total_count"] == 70
    assert llamadas[0] == (
        "/api/v1/accounts/2/csat_survey_responses/metrics",
        {"since": "100", "until": "200"},
    )
