"""Solicita la revisión de horarios sin depender del cron de GitHub."""
import json
import os
import signal
import sys
import urllib.error
import urllib.request

BASE = 'https://api.github.com/repos/antonio8aranda98-lang/rfhf-agenda'
WORKFLOW = 'valencia-horarios.yml'
PRODUCTION = {'agenda.yml', 'cartera.yml', WORKFLOW}
ACTIVE = {'in_progress', 'queued', 'waiting', 'pending', 'requested'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(path, token, data=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization': 'Bearer ' + token,
                 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json',
                 'X-GitHub-Api-Version': '2026-03-10',
                 'User-Agent': 'RFHF-fixtures-trigger'},
    )
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
        body = response.read()
        return json.loads(body) if body else None


def dispatch(token, call=request):
    if not token:
        raise ValueError('Falta la credencial de disparo en el entorno.')
    runs = call('/actions/runs?per_page=100&branch=main', token)
    for run in runs['workflow_runs']:
        path = run.get('path', '').rsplit('/', 1)[-1]
        if path in PRODUCTION and run.get('status') in ACTIVE:
            return 'Ya hay una actualización en curso o en espera; no se duplica.'
    call('/actions/workflows/' + WORKFLOW + '/dispatches', token, {'ref': 'main'})
    return 'Revisión de horarios solicitada. GitHub publica el resultado al terminar.'


def main():
    # Límite total de proceso: evita facturar una espera de red indefinida.
    def deadline(signum, frame):
        raise TimeoutError('deadline')
    previous = signal.signal(signal.SIGALRM, deadline)
    signal.alarm(50)
    try:
        print(dispatch(os.environ.get('RFHF_DISPATCH_TOKEN', '')))
    except urllib.error.HTTPError as error:
        print('GitHub rechazó el disparo: HTTP ' + str(error.code), file=sys.stderr)
        return 1
    except Exception:
        # Nunca imprimir objetos Request, cabeceras, cuerpos ni credenciales.
        print('No se pudo solicitar la revisión. Consultar permisos y conectividad.', file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
