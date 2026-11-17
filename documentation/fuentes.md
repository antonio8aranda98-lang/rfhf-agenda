# Comprobación de fuentes federativas

Fecha de consulta: 17 de noviembre de 2026. Temporada comprobada: 2026/2027.

Investigación inicial y notas de implementación. La aplicación se sirve desde `docs/`; las asignaciones públicas autorizadas se gestionan en `data/roster.json`. La copia original en `private/piloto.json` sigue excluida de Git. No publicar respuestas completas de las federaciones: algunas incluyen datos personales y de contacto ajenos al objetivo deportivo.

## Madrid — RFFM

- Ficha de equipo: https://www.rffm.es/fichaequipo/2023
- Ficha de jugador comprobada: https://www.rffm.es/fichajugador/7998819
- Calendario: https://www.rffm.es/competicion/calendario?competicion=26737715&grupo=26737716&temporada=22&tipojuego=1
- Campo del próximo encuentro: https://www.rffm.es/campo/1718
- Competición: Primera División Autonómica Juvenil, grupo 2.
- Extracción HTTP pública comprobada: páginas Next.js con JSON en `__NEXT_DATA__`, dentro de `props.pageProps`. Equipo: `team`; calendario: `calendar`; jugador: `player`; acta: `game`; campo: `field`.
- Calendario: `calendar.rounds[].equipos[]`. Hay códigos de acta, equipo y campo; fecha, hora, resultado y rutas de escudos. Vincular por identificadores, no por coincidencia parcial de nombres.
- La ficha de campo incluye dirección y coordenadas.
- Las respuestas contienen indicadores de visibilidad (`vis_estadistica`, `vis_goles`, `vis_minutos`, también por competición). Hay que verificar cómo los aplica la web y respetarlos al decidir qué mostrar. La presencia de un valor en JSON no basta para dar por validada su publicación en nuestra aplicación.
- Próximo partido del equipo comprobado: C.D. Daganzo A – E.F. Ciudad de Getafe B, sábado 21/11/2026 a las 16:00. Campo Francisco Javier López, Daganzo de Arriba. Acta 5584386. Sujeto a cambios de la federación.

## Comunitat Valenciana — FFCV

- Portal actual de competición: https://ffcv.es/competiciones/
- Equipo comprobado: https://ffcv.es/competiciones/equipos/equipo.php?cod_equipo=14347
- Jugador: código 9820597. Competición correcta 905431880, grupo 905431882, temporada 22.
- Página del grupo: https://ffcv.es/competiciones/index.php?view=partidos&cod_temporada=22&cod_competicion=905431880&cod_grupo=905431882&cod_jornada=9#partidos
- Confirmada la plantilla del EAF Valencia A en Primera FFCV Juvenil, grupo 2.
- Ficha pública del jugador: convocatorias, titularidades, suplencias, partidos jugados, goles y tarjetas. No se han validado minutos ni asistencias.
- La navegación desde el buscador puede arrastrar un `cod_competicion` de otra competición: se observó 905431604, correspondiente a Tercera Federación, mezclado con el grupo juvenil. Eso produjo una pestaña de partidos vacía. Usar siempre competición y grupo verificados juntos; no interpretar una respuesta vacía como ausencia de partidos.
- La página principal y JavaScript se descargaron por HTTP. Una llamada directa al filtro público de temporadas respondió 403; el navegador normal cargó el buscador, plantillas y partidos. Automatización desatendida pendiente de validar con acceso público normal, sin eludir controles.
- Próximo partido comprobado en la ficha del encuentro: C.D. Buñol A – EAF Valencia A, sábado 21/11/2026 a las 12:00. Campo Beltrán Báguena Buñol F-11. Sujeto a cambios de la federación.

## Región de Murcia — FFRM

- Equipo comprobado: https://www.ffrm.es/pnfg/NPcd/NFG_VisEquipos?cod_primaria=3001860&Codigo_Equipo=24069902
- Calendario del equipo: https://www.ffrm.es/pnfg/NPcd/NFG_VisCompeticiones_Grupo?cod_primaria=1000123&codequipo=24069902&codgrupo=24032710
- Unión Molinense C.F., Primera Cadete, grupo segundo, temporada 22. La plantilla incluye al jugador del piloto.
- El navegador normal permite consulta pública sin iniciar sesión. Algunas peticiones HTTP directas a portada y rutas antiguas redirigen a `NLogin?NSess=1`; eso no demuestra que los datos requieran una cuenta. Hay que validar una sesión pública normal del cliente de extracción.
- Actas públicas indexadas incluyen titulares, suplentes, goles, sustituciones con minuto y tarjetas; la cobertura y cálculo de minutos actuales deben validarse por partido.
- Próximo cruce en el calendario: Unión Molinense – E.F. Molina Transportes Logismur, jornada 10, fecha 22/11/2026. Sin hora publicada en la consulta. Esta fecha se debe etiquetar como fecha de jornada pendiente de horario; no convertirla en cita confirmada ni completar el campo con el estadio habitual sin comprobar la ficha del partido.

## Catalunya — FCF

- Equipo comprobado: https://www.fcf.cat/ca/clubs/unio-f-base-jabac-i-terrassa/categories/unio-f-base-jabac-i-terrassa-a-1j
- Acta comprobada: https://www.fcf.cat/ca/partit/2026-2027/juvenil-primera-divisio/grup-8/jornada-3/gimnastic-manresa-cf-c-1j-vs-unio-f-base-jabac-i-terrassa-a-1j
- Ruta antigua que redirige al acta actual: https://www.fcf.cat/ca/competicio/acta/4194887
- Juvenil Primera Divisió, grupo 8, equipo A. Plantilla y acta confirman el jugador del piloto.
- La página del equipo muestra 30 partidos, resultados, fechas y horas; dispone de botón Exportar ICS. La extracción ICS no se ha probado.
- El acta muestra resultado, alineaciones, banquillo, goles y tarjetas. No atribuir participación ni minutos solo por aparecer en el banquillo. Cobertura de sustituciones y estadísticas individuales pendiente de validar.
- HTTP directo desde el entorno respondió 403; navegador normal accedió sin iniciar sesión. Automatización desatendida pendiente de validar con acceso público normal.
- Próximo partido publicado: Jàbac i Terrassa A – Manresa B, domingo 22/11/2026 a las 18:15. La ficha del equipo indica Can Jofresa como terreno habitual; verificar el campo concreto en la ficha del encuentro antes de publicarlo como confirmado.

## Reglas propuestas para implementar

1. Conector independiente por federación y modelo de datos común. Descargar solo equipos y competiciones necesarios para el seguimiento; ampliar cobertura progresivamente.
2. Guardar URL de origen, fecha de consulta y estado de sincronización por fuente. Conservar último dato válido ante un fallo y señalar su antigüedad.
3. Diferenciar dato ausente (`null`) de cero real; horario pendiente, fecha de jornada, aplazamiento y partido confirmado.
4. Presentar próximos partidos de los equipos de los jugadores; no prometer que un jugador estará convocado o jugará antes de existir confirmación.
5. Calcular minutos únicamente con participación, sustituciones, expulsiones y duración de categoría verificadas. Indicar si son calculados y la cobertura de partidos.
6. Las asistencias no están validadas en estas cuatro pruebas: mostrar no disponible o permitir registro manual identificado, sin inventar ceros.
7. Comparativas por temporada y categoría, con cobertura visible. No equiparar automáticamente goles o minutos con rendimiento global.
8. Elegir un nombre de colaborador es un filtro de interfaz. Para limitar acceso a sus jugadores hace falta autenticación y autorización en servidor. Mantener asignaciones fuera del código público hasta decidir el acceso.
9. Programar actualizaciones una vez probados los cuatro conectores; revisar frecuencias según volumen y condiciones de acceso de cada fuente. El scrapeo puede requerir mantenimiento al cambiar las webs.

## Estado de implementación del piloto

- Acceso público por decisión expresa del propietario: cualquiera puede seleccionar un colaborador.
- Madrid, Cataluña y Murcia: sincronización HTTP pública probada; 34, 30 y 30 partidos respectivamente.
- Valencia: 30 partidos verificados con navegación pública; el navegador de extracción local no logra completar la consulta. Se conserva una captura verificada, marcada con aviso y con fecha propia. No se considera validada su sincronización desatendida hasta que una ejecución real la complete.
- El nuevo calendario valenciano muestra algunos nombres de día que no corresponden a su fecha numérica. La aplicación utiliza día/mes/año y calcula el día de la semana por sí misma.
- Faltan estadísticas individuales de Cataluña y Murcia; tampoco se han validado asistencias. No se publican ceros sustitutivos.
