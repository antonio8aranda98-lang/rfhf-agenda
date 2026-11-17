# RFHF · Agenda de scouting

Web pública para consultar los partidos de los jugadores asignados a cada colaborador en Madrid, Cataluña, Murcia y Comunitat Valenciana. El acceso es libre: elegir un colaborador filtra la agenda, sin identificación.

**[Abrir agenda](https://antonio8aranda98-lang.github.io/rfhf-agenda/)**

Piloto con cuatro jugadores y 124 partidos. La sincronización automática de Valencia y las estadísticas individuales de Cataluña y Murcia siguen pendientes de completar; la web señala los datos no disponibles.

## Uso

1. Elige federación y colaborador.
2. Consulta el fin de semana completo, navega entre semanas o busca un jugador, equipo o campo.
3. Abre la ficha de un jugador para consultar resultados del equipo y estadísticas individuales disponibles.
4. Marca visitas (se guardan únicamente en ese navegador) o exporta partidos con horario publicado a un calendario `.ics`.

La web distingue horarios pendientes, estadísticas ausentes y problemas de actualización. Un partido del equipo no garantiza la convocatoria ni participación del jugador. Las comparativas usan datos publicados; un guion nunca equivale a cero.

## Desarrollo

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci
npx playwright install chromium
PYTHON=.venv/bin/python .venv/bin/python scripts/sync.py --browser
npm start
```

Abrir `http://localhost:8765`. La web no requiere compilación ni claves. Los archivos servidos están en `docs/`; los datos publicados son un JSON normalizado, sin contactos, fechas de nacimiento ni HTML completo de las federaciones.

```sh
npm test
.venv/bin/python -m unittest discover -s tests
```

## Jugadores y colaboradores

Editar `data/roster.json` para añadir jugadores y asignaciones. Incluir el identificador federativo y el equipo/categoría correctos; el nombre por sí solo no resuelve homónimos. Los conectores de Madrid, Cataluña y Murcia comprueban la pertenencia a la plantilla antes de actualizar.

Estos datos son **públicos** por decisión del propietario. No añadir datos de contacto ni otra información ajena al seguimiento deportivo.

## Actualización y publicación

El workflow de GitHub Actions consulta las fuentes cada cuatro horas de lunes a jueves y cada hora de viernes a domingo. Los cron se interpretan en UTC; son ejecuciones programadas que pueden retrasarse, no un servicio de tiempo real. En repositorios públicos GitHub puede desactivar los cron tras periodos prolongados sin actividad; revisar Actions si deja de actualizarse.

Para GitHub Pages, elegir **Settings → Pages → Source → GitHub Actions**. El mismo workflow publica `docs/` tras la consulta. Se puede ejecutar manualmente desde Actions.

Si una fuente falla o cambia de formato se conserva su última captura válida, sin actualizar falsamente su fecha de éxito. El estado aparece en la web. El HTML temporal y las respuestas completas permanecen en `.cache/`, fuera de Git. Cada conector solicita solo los equipos seguidos y limita la frecuencia de peticiones. No se utilizan credenciales federativas, plugins de evasión ni resolución automática de CAPTCHA.

## Cobertura

- Madrid: calendario, campo, escudos, resumen individual y participación del acta cuando se puede verificar.
- Cataluña: calendario completo, resultados, campos, coordenadas y escudos. Estadísticas individuales pendientes de validar.
- Murcia: calendario completo y resultados. Fecha sin hora = referencia de jornada; campo y estadísticas individuales pendientes de validar.
- Valencia: conector de navegador público; mantiene datos anteriores si la fuente rechaza la consulta o cambia de formato. Su estado exacto se muestra en la agenda.
- Asistencias: no disponibles por ahora. No se sustituyen por ceros.

Los escudos identifican a los clubes y pertenecen a sus titulares. Cada partido enlaza a su fuente oficial. Los resultados y horarios pueden ser corregidos por las federaciones.

Más detalles en [la comprobación de fuentes](documentation/fuentes.md).
