# TLP Técnico

Conclusão de atividade com validação de rede pela central de contorno.

**Fluxo:** o técnico entra com **usuário e senha**, vê as OS dele e toca em *Concluir com sucesso* →
a central vê o pedido, clica em *Testar Wi‑Fi* → o celular do técnico roda o teste (latência, jitter,
perda, download, upload) → a central vê os números com semáforo e **aprova ou recusa**.
O "ok" fica só no controle interno (não vai para a Vivo).

## Rodar no seu computador

```
pip install -r requirements.txt
python -m scripts.seed_demo          # cria dados FICTÍCIOS e imprime as senhas de teste
python -m uvicorn app.main:app --reload
```
Abra `http://localhost:8000` (técnico no celular: use o IP do PC na rede, ex. `http://192.168.0.10:8000`,
e suba com `--host 0.0.0.0`). Sem `DATABASE_URL`, usa um SQLite local só para teste.

## Colocar no ar (Neon + hospedagem)

1. No Neon, crie um **projeto novo** (a cota gratuita vale por projeto). Copie a connection string **pooled** (`-pooler`).
2. Copie `.env.example` para `.env` e preencha `DATABASE_URL` e `SECRET_KEY`; use `AMBIENTE=producao`.
3. Crie os usuários (o técnico recebe um login NOVO; a matrícula só liga o login às OS):
   ```
   python -m scripts.criar_usuario --login joao.silva --nome "João Silva" --perfil tecnico --matricula 12345
   python -m scripts.criar_usuario --login central01 --nome "Central 01" --perfil central
   ```
4. Copie as OS da base tratada (rode de novo sempre que a base atualizar; é seguro repetir):
   ```
   python -m scripts.sincronizar_base --excel "D:\DASH EM STREAMILIT\TLP_ANALYTICS\data\PRODUCAO_TLP_TRATADA.xlsx"
   ```
   (ou `--origem-url` / `ORIGEM_DATABASE_URL` para ler direto do Neon do dashboard). Dá para encadear como mais um passo do orquestrador.
5. Hospedagem: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`
   e `CONFIAR_PROXY=1`. Não usa WebSocket (a atualização é por consulta a cada 2–3 s), então roda também em hospedagem serverless (use `DB_POOL=null`).

## Ajustar o critério de "rede OK"

Edite `criterios_rede.json`: `bom` = até aqui fica verde; `minimo` = até aqui fica amarelo (atenção); além disso, vermelho.
**Os valores que vêm no arquivo são só um ponto de partida** — defina conforme o plano contratado e a exigência da Vivo.
Regras da central (em `app/servico.py`): só aprova com teste concluído há ≤ 15 min; rede reprovada não aprova;
rede em atenção exige justificativa; recusar exige motivo.

## O que o teste mede (e o que não mede)

Mede, no navegador do celular: latência, jitter, perda de pacotes, download e upload **até este servidor**.
O navegador **não** enxerga nome da rede, sinal do Wi‑Fi nem quem é o dono dela; por isso o IP público e o tipo de rede
(quando o navegador informa) ficam registrados. Os números são da conexão do aparelho até o servidor, não o plano contratado do cliente.
O servidor confere os bytes realmente transferidos para barrar resultado inventado chamando a API na mão.

## Segurança

Senha com bcrypt; bloqueio de 10 min após 5 erros; sessão por cookie assinado (12 h); o técnico só vê as próprias OS e pedidos;
a política de conteúdo (CSP) bloqueia scripts de fora; rotas que alteram dados exigem cabeçalho próprio (proteção CSRF).
Ainda **não** há limite de tentativas por IP nem troca de senha pelo próprio usuário.

## Testes

```
python -m pytest tests -q            # 21 testes da API
tests/rodar_node.sh                  # motor do teste de rede contra um servidor real (precisa de Node)
tests/rodar_e2e.sh [com_proxy]       # dois navegadores reais (precisa de playwright)
```
`tests/proxy_lento.py` limita a rede (20 Mbps / 5 Mbps / 60 ms) para conferir a precisão da medição.

## Atenção com o Neon gratuito

Cada consulta mantém o banco "acordado" (ele só dorme após ~5 min parado). A central abre a fila a cada 3–8 s,
então o banco fica ligado durante todo o expediente e isso consome horas de compute. Acompanhe o consumo no console do Neon nas primeiras semanas.
