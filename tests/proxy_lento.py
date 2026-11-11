import asyncio, time, sys
DOWN_BPS = float(sys.argv[1]) * 1e6 / 8   # servidor -> cliente
UP_BPS = float(sys.argv[2]) * 1e6 / 8     # cliente -> servidor
ATRASO = float(sys.argv[3]) / 1000        # por sentido
class Balde:
    def __init__(s, bps): s.bps, s.livre = bps, 0.0
    async def passar(s, n):
        t = max(time.monotonic(), s.livre); s.livre = t + n / s.bps
        d = t - time.monotonic()
        if d > 0: await asyncio.sleep(d)
bd, bu = Balde(DOWN_BPS), Balde(UP_BPS)
async def ler(r, fila):
    try:
        while True:
            dados = await r.read(16384)
            await fila.put((time.monotonic(), dados))
            if not dados: break
    except Exception:
        await fila.put((time.monotonic(), b""))
async def escrever(w, fila, balde):
    try:
        while True:
            t, dados = await fila.get()
            if not dados: break
            espera = t + ATRASO - time.monotonic()      # atraso de propagação sem serializar
            if espera > 0: await asyncio.sleep(espera)
            await balde.passar(len(dados))
            w.write(dados); await w.drain()
    except Exception: pass
    finally:
        try: w.close()
        except Exception: pass
async def bombear(r, w, balde):
    fila = asyncio.Queue()
    await asyncio.gather(ler(r, fila), escrever(w, fila, balde))
async def conexao(cr, cw):
    sr, sw = await asyncio.open_connection("127.0.0.1", 8765)
    await asyncio.gather(bombear(cr, sw, bu), bombear(sr, cw, bd))
async def main():
    s = await asyncio.start_server(conexao, "127.0.0.1", 8766)
    async with s: await s.serve_forever()
asyncio.run(main())
