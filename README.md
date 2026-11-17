# RFHF · Agenda de scouting

Web pública para consultar los partidos de los jugadores asignados a cada colaborador en Madrid, Cataluña, Murcia y Comunitat Valenciana. El acceso es libre: elegir un colaborador filtra la agenda, sin identificación.

**[Abrir agenda](https://antonio8aranda98-lang.github.io/rfhf-agenda/)**

Piloto con cuatro jugadores y 124 partidos. Cada ficha y la comparativa muestran partidos disputados del equipo, convocatorias, titularidades, suplencias, minutos y goles. La web indica la cobertura de actas y mantiene «—» cuando no se puede verificar un total.

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

[Abrir el formulario de gestión](https://antonio8aranda98-lang.github.io/rfhf-agenda/gestion.html). Permite altas, desactivaciones, reactivaciones y cambio de colaborador. Se completa la solicitud iniciando sesión como propietario en GitHub; la consulta de la agenda sigue siendo libre. No utiliza tokens en el navegador ni permite escrituras de visitantes.

Las altas requieren nombre y apellidos completos, colaborador, federación, enlace oficial del equipo/categoría y duración reglamentaria. El conector resuelve identificadores y comprueba plantilla y calendario antes de activar al jugador. Para equipos murcianos nuevos se necesita además el enlace de una jornada con competición/grupo/temporada. No se usan coincidencias parciales ni se escoge el primer homónimo.

El workflow `gestion.yml` procesa únicamente incidencias `[RFHF]` creadas y reabiertas por el propietario del repositorio. También valida la autoría en Python; nunca ejecuta el contenido de la solicitud. Las solicitudes sin identidad/fuente verificable permanecen pendientes, con explicación, sin modificar el registro. Corregir la solicitud y cerrarla/reabrirla permite reintentar. **Las altas FFCV quedan pendientes por ahora**, porque su sincronización desatendida no está validada.

Las bajas marcan `active: false` en `data/roster.json` y eliminan al jugador del feed servido, incluidos partidos compartidos, estadísticas y avisos, incluso si falla la siguiente consulta de la federación. La reactivación vuelve a comprobar el equipo. Las asignaciones se aplican a las carteras sin cambiar la identidad. El historial del repositorio público conserva cambios; desactivar no borra ese historial.

También se puede editar `data/roster.json` directamente. Los datos federativos deben corresponder al equipo y categoría correctos.

Estos datos son **públicos** por decisión del propietario. No añadir datos de contacto ni otra información ajena al seguimiento deportivo.

## Actualización y publicación

El workflow de GitHub Actions consulta las fuentes cada cuatro horas de lunes a jueves y cada hora de viernes a domingo. Los cron se interpretan en UTC; son ejecuciones programadas que pueden retrasarse, no un servicio de tiempo real. En repositorios públicos GitHub puede desactivar los cron tras periodos prolongados sin actividad; revisar Actions si deja de actualizarse.

Para GitHub Pages, elegir **Settings → Pages → Source → GitHub Actions**. El mismo workflow publica `docs/` tras la consulta. Se puede ejecutar manualmente desde Actions.

Si una fuente falla o cambia de formato se conserva su última captura válida, sin actualizar falsamente su fecha de éxito. El estado aparece en la web. El HTML temporal y las respuestas completas permanecen en `.cache/`, fuera de Git. Cada conector solicita solo los equipos seguidos y limita la frecuencia de peticiones. No se utilizan credenciales federativas, plugins de evasión ni resolución automática de CAPTCHA.

## Cobertura

- Madrid: calendario, campo, escudos, resumen individual y participación del acta cuando se puede verificar.
- Cataluña: calendario, resultados, campos, coordenadas, escudos, convocatorias, titularidades, suplencias y goles de actas verificadas. Minutos sin total mientras falten intervalos de sustitución verificables.
- Murcia: calendario, resultados y actas públicas con convocatorias, titulares, suplentes, goles y minutos calculados cuando hay datos completos. Algunos accesos devuelven una respuesta vacía; se conserva la última participación verificada con su fecha. Fecha sin hora = referencia de jornada.
- Valencia: conector de navegador público; mantiene datos anteriores si la fuente rechaza la consulta o cambia de formato. Su estado exacto se muestra en la agenda.
- Asistencias: no disponibles por ahora. No se sustituyen por ceros.

Los cruces se detectan entre los equipos de todos los jugadores activos de la federación, aunque pertenezcan a distintos colaboradores. Se muestra un aviso destacado para el fin de semana elegido, independiente de los filtros de colaborador y búsqueda. Se cotejan códigos oficiales de equipo cuando existen; no se confunden equipos A y B. Es un enfrentamiento entre sus equipos, no una convocatoria confirmada.

Convocado significa figurar como titular o suplente en un acta cerrada; suplente no equivale a haber participado. Los minutos calculados excluyen el añadido y usan sustituciones y expulsiones, sin descartar partidos por amarillas. Solo se suman actas completas para obtener un total; se puede conservar un resumen oficial publicado cuando falta un dato por partido. Los partidos del equipo se cuentan a partir del calendario de la competición seguida; si un resumen federativo abarca otro ámbito puede no coincidir con sus apariciones.

Los escudos identifican a los clubes y pertenecen a sus titulares. Cada partido enlaza a su fuente oficial. Los resultados y horarios pueden ser corregidos por las federaciones.

Más detalles en [la comprobación de fuentes](documentation/fuentes.md).
