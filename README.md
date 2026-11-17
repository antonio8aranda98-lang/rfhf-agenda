# RFHF · Agenda de scouting

[Agenda pública](https://antonio8aranda98-lang.github.io/rfhf-agenda/) · [Panel de Antonio](https://rfhf-control-antonio.opalescentpaper1.chatgpt.site/)

Elige federación y colaborador para consultar los partidos del sábado y domingo. Las fichas y comparativas muestran partidos del equipo, convocatorias, titularidades, suplencias, minutos y goles. Los encuentros reprogramados entre semana siguen consultables. Un partido del equipo no confirma la convocatoria del jugador.

Los enfrentamientos entre jugadores activos producen un aviso destacado aunque pertenezcan a distintos colaboradores. Los equipos se vinculan por sus códigos oficiales cuando están disponibles; no se mezclan equipos A y B.

## Gestión

Antonio inicia sesión en el panel, completa el formulario y pulsa **Guardar cambios**. El servidor autoriza únicamente la identidad vinculada a Antonio. Los visitantes consultan; no modifican la cartera.

Las altas se identifican en la plantilla federativa y se comprueba su calendario antes de activarlas. Las bajas y asignaciones se leen en la agenda cada 30 segundos. Las altas y reactivaciones se procesan automáticamente mediante Actions cada cinco minutos, sujetos a retrasos de GitHub y disponibilidad de la fuente. Los errores aparecen en el panel y se reintentan cada 30 minutos. No hay incidencias que gestionar en GitHub.

El registro deseado se guarda en D1. Su endpoint de lectura contiene solo datos deportivos y asignaciones que el propietario autorizó como públicos. `scripts/registry_remote.py` genera el registro federativo validado en `data/roster.json`, retira inactivos de partidos compartidos y publica estados en `docs/data/registry-status.json`. Un fallo de red conserva la última cartera válida. El código del panel vive en el checkout independiente e ignorado `admin-site/`, enlazado a su repositorio de Sites; las credenciales no se guardan en los repositorios.

[Guía de gestión](documentation/gestion.md).

## Datos y cobertura

Los conectores usan las páginas y consultas públicas de las federaciones, con peticiones limitadas a los equipos seguidos. Guardan fuente, fecha y cobertura. Un dato ausente se muestra como «—», nunca como cero. Las asistencias no están validadas.

- Madrid: calendario, campos, escudos, resumen y actas individuales.
- Cataluña: calendario y actas de convocatorias, titulares, suplentes y goles. Falta un total de minutos cuando no se publican intervalos de sustitución verificables.
- Murcia: calendario y actas públicas; algunas rutas antiguas responden vacías. Se conserva la última participación comprobada con su fecha y se señala la cobertura.
- Valencia: consulta HTTP de los mismos endpoints públicos que usa FFCV, incluido su token público de página y cookies normales. Se fija competición, grupo y temporada. Los totales se calculan con las actas del equipo seguido para evitar mezclar apariciones en equipos A/B. No se publican respuestas completas, fotografías de jugadores ni datos de contacto.

Convocado incluye titulares y suplentes, aunque no jueguen. Los minutos calculados usan sustituciones, expulsiones y duración reglamentaria, sin añadido. Una amarilla no elimina los minutos. Solo se suman actas completas para presentar un total; las fichas indican cuántas se han comprobado. Un resumen oficial puede abarcar más competiciones que el calendario de un equipo: no se usa como sustituto de otro ámbito.

## Desarrollo

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/registry_remote.py
.venv/bin/python scripts/sync.py
npm start
```

Abrir `http://localhost:8765`. La agenda es HTML/JS sin compilación y no requiere claves. `docs/` contiene los archivos publicados. Las consultas automáticas actuales usan HTTP; los scripts de navegador del primer piloto quedan solo como referencia de investigación.

```sh
npm test
.venv/bin/python -m unittest discover -s tests
```

## Publicación y operación

GitHub Pages sirve `docs/`. `agenda.yml` actualiza las fuentes cada cuatro horas de lunes a jueves y cada hora de viernes a domingo; `cartera.yml` comprueba cambios del panel cada cinco minutos y solo valida/publica si hay trabajo. Los cron se interpretan en UTC y pueden retrasarse o desactivarse tras inactividad prolongada del repositorio.

Los dos procesos comparten exclusión de publicación para evitar escrituras simultáneas. Una baja se aplica al feed antes de consultar las fuentes, por lo que un fallo posterior no vuelve a publicar al jugador. Las nuevas altas nunca se activan solo por parecido de nombre. Los escudos pertenecen a sus clubes y los horarios pueden ser corregidos por las federaciones: comprueba el enlace oficial antes de desplazarte.
