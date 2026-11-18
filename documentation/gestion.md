# Gestión de la cartera

[Panel de Antonio](https://rfhf-control-antonio.opalescentpaper1.chatgpt.site/).

1. Inicia sesión con la cuenta de Antonio vinculada al panel.
2. Elige **Añadir jugador**, **Dar de baja**, **Cambiar colaborador**, **Reactivar jugador** o **Añadir o actualizar BeSoccer**.
3. Completa los campos y pulsa **Guardar cambios**. No hay incidencias ni confirmaciones en GitHub.
4. Consulta el estado del jugador en el propio panel.

Una nueva alta necesita nombre y apellidos completos, federación, colaborador, enlace del equipo/categoría en la federación o en BeSoccer y duración reglamentaria. La federación seleccionada determina la vista de la agenda también cuando el enlace es de BeSoccer. En Murcia se descubre la competición actual desde la ficha oficial del equipo; si la fuente no identifica un grupo único, el alta permanece pendiente. Se verifica la plantilla y el calendario antes de mostrar una identidad nueva. Si falta información o falla la fuente, el panel explica qué revisar; se vuelve a intentar automáticamente.

Puedes añadir un equipo de BeSoccer directamente como fuente principal o completar una ficha federativa con **Equipo en BeSoccer** y, si lo tienes, **Ficha individual en BeSoccer**. El enlace individual es opcional y ayuda a resolver nombres abreviados; siempre se comprueba el nombre completo, la plantilla, competición y temporada. Si hay ambigüedad se pide revisar el enlace individual. El enlace de equipo puede ser su portada, plantilla o partidos; se normaliza a la misma identidad.

Para añadir o cambiar estos enlaces en un jugador existente, elige **Añadir o actualizar BeSoccer**, selecciona el jugador y guarda. La vinculación se verifica antes de usarla. En una ficha con federación, dejar ambos campos vacíos retira el complemento. En una ficha que usa BeSoccer como fuente principal se conserva su equipo; cambiar de club necesita revisar el alta.

Los datos federativos mantienen prioridad. Las participaciones de BeSoccer solo completan campos ausentes de un partido inequívocamente coincidente en fecha, jornada, rival y resultado. El resumen adicional se muestra por separado con su equipo, competición y fecha; no se suman totales de distintas fuentes. Un suplente que no juega sigue siendo convocado; «PS» de BeSoccer no se interpreta como convocatorias ni como todo el banquillo. Si falta una alineación no se supone una ausencia.

Las bajas y asignaciones se reflejan al refrescar la agenda (cada 30 segundos o al volver a la pestaña). Las altas y reactivaciones requieren comprobación y publicación: se comprueban cambios cada cinco minutos mediante GitHub Actions, cuya ejecución puede retrasarse. No se promete una hora exacta de incorporación.

Las altas nuevas, correcciones y reactivaciones se atienden primero. Su calendario se publica antes de leer las actas históricas. Si una actualización deportiva está en marcha cuando Antonio guarda cambios, conserva el avance válido y cede el turno entre consultas. Sin altas nuevas se revisan tandas pequeñas de pendientes antiguos: hasta dos identidades y hasta tres primeros calendarios contando esas identidades. Un fallo respeta la pausa indicada por la fuente y los intervalos de reintento; no obliga a repetir las comprobaciones del resto de la cartera.

Solo Antonio puede escribir: el servidor coteja la identidad autenticada con la cuenta vinculada durante la activación privada. Ser visitante, conocer un nombre de colaborador o intentar falsificar cabeceras no concede permisos. La lectura de los datos deportivos es pública, autorizada por el propietario. No hay tokens para pegar ni una contraseña compartida.

Dar de baja desactiva el registro; se puede recuperar con **Reactivar**. La baja no borra el historial del repositorio público. No añadas motivos contractuales ni datos de contacto: el registro contiene únicamente información deportiva y asignaciones públicas.

## Importar una lista

Antonio puede elegir **Importar lista de jugadores**, seleccionar la federación y pegar las filas desde su hoja o subir un archivo TSV. Se usan cinco columnas sin cabecera: nombre completo, año de nacimiento, equipo, enlace y colaborador. Las filas sin enlace se omiten; una fila con formato inválido impide guardar el lote entero. Se muestran las altas, los registros existentes actualizados y los omitidos al guardar. No se borran otros territorios y un jugador ya registrado conserva su identidad y fuente. Se actualiza su colaborador y categoría por edad.

El año sirve para clasificar la edad y no se conserva en el registro público. En 2026–2027: 2008–2010 juvenil, 2011–2012 cadete, 2013–2014 infantil y 2007 o anteriores sénior. La duración para calcular minutos corresponde a la categoría del equipo: 90 minutos sénior/juvenil, 80 cadete y 70 infantil. Un jugador joven puede figurar en un equipo de mayor edad; una edad indicada superior a la del equipo requiere revisión antes de activar el registro.

El nombre de la hoja puede ampliarse al nombre completo de una identidad única de la plantilla verificada. Si el nombre no aparece o la ficha no confirma su competición actual, el alta permanece pendiente y se reintenta sin publicar una identidad por parecido. En Madrid, las estadísticas de varias competiciones de una ficha individual no se mezclan: se calculan con las actas del equipo seguido. Las alineaciones históricas verificadas se conservan para el mismo resultado. Las actas con huecos se reintentan por tandas de hasta tres por jugador, con un mínimo de seis horas entre intentos; las dos completas más recientes se pueden revisar cuando su lectura tiene al menos una hora. Las cifras marcadas «Parcial» solo suman los datos confirmados e indican cuántas actas respaldan cada campo.

Las comprobaciones de cartera consultan los datos deportivos de las altas nuevas y de los cambios de fuente; el resto conserva sus datos y sus fechas. La actualización periódica de la agenda sigue consultando todas las fuentes. Si BeSoccer entrega una pantalla de verificación o deniega la navegación, el registro queda pendiente con ese motivo: esa respuesta no contiene datos deportivos utilizables por el actualizador.
# Fuentes oficiales alternativas

Las nueve altas que dependían de BeSoccer en Alfaro, La Calzada, Alameda, Azuqueca, Isoba, Trival y Sporting Hortaleza disponen de correspondencias revisadas en `scripts/official_sources.py`. La comprobación valida de nuevo identidad, equipo y temporada ante RFEF, FFCM, RFCYLF o FRF. Se conservan los identificadores del panel, colaboradores y vista territorial. No se consulta BeSoccer al activar estas correspondencias.

La correspondencia se aplica solo a esos nombres completos, enlaces y temporada 2026–2027. Un jugador o club distinto sigue el flujo habitual y requiere una fuente verificable. Las cuatro vistas no representan una restricción sobre la federación que publica los datos de cada club.

El panel también admite directamente fichas públicas `NFG_VisEquipos` de FFCM, RFCYLF y FRF, con `Codigo_Equipo` numérico y `cod_primaria=1000119`. Se puede mantener la vista Madrid para un club de otra federación. El actualizador contrasta el nombre en la plantilla, consulta el histórico de ese equipo y exige una única competición y grupo en la temporada actual antes de publicar. Las correspondencias de nombres cortos requieren una identidad única con todos los términos facilitados. Los calendarios se identifican por competición y grupo propios del equipo, evitando mezclar diferentes ligas de una misma federación.

El calendario extendido aporta fecha y campo del encuentro; si solo está disponible el calendario básico, se identifica expresamente la fecha de jornada. Las jornadas añaden enlaces a actas y horarios actualizados. Una consulta fallida de acta deja la participación sin dato, conservando el calendario y la última participación compatible. Los nuevos adaptadores tienen pruebas con fragmentos deportivos de las fuentes; no se guardan fotos ni datos de contacto en el feed.

Cuando el portal público devuelve un cuerpo HTTP vacío, el actualizador intenta la navegación ordinaria con Chrome. El respaldo se limita a los cinco dominios oficiales y rutas deportivas permitidas. No actúa ante denegaciones ni interacciona con verificaciones o accesos privados. La ficha de grupo del equipo es otra alternativa oficial al calendario general.

Para Rullán y Contera se incluye una lectura deportiva inicial contrastada el 18/11/2026, con actas de identidad y calendarios oficiales. Solo puede activar su correspondencia exacta durante las 24 horas siguientes a esa lectura. Si se utiliza porque la consulta actual falla, conserva la fecha original y un aviso de actualización incompleta; no se etiqueta como lectura en vivo. Después de la activación se aplica el mismo refresco automático y conservación del último dato válido que al resto.

## Corregir un registro existente

Antonio puede elegir «Corregir nombre o equipo», seleccionar el jugador y guardar nombre, ficha oficial, categoría, duración y colaborador sin generar otra alta. El servidor conserva su identificador y marca la revisión para verificar otra vez la identidad. Una corrección no hereda estadísticas de la identidad anterior: si no se puede validar, el jugador queda pendiente y se retira la ficha deportiva hasta resolverla.

Si la ficha individual RFFM no devuelve competición, se puede añadir el enlace del calendario oficial como apoyo. Se exige que el calendario confirme el equipo y la temporada; no sirve otro filial ni otra temporada. Sus estadísticas se calculan con las actas disponibles y respetando su visibilidad, sin inventar un resumen individual que no devuelve la federación.

## Jugador inscrito en otro filial

En Madrid se pueden guardar el enlace del equipo seguido y la ficha individual RFFM. El calendario pertenece al equipo indicado; no se sustituye por el de la inscripción principal. Se verifican nombre, identificador individual, temporada y competición de ese equipo. Cuando no figura en su plantilla, se exige además un acta cerrada del equipo seguido que lo incluya. Las estadísticas se calculan únicamente con esas actas y sus indicadores de visibilidad; los resúmenes acumulados de varios filiales no se mezclan.

«Corregir lista existente» admite las cinco columnas habituales o seis añadiendo la ficha individual entre el enlace del equipo y el colaborador. Conserva los identificadores, no crea altas y vuelve a validar las identidades. Un nombre abreviado solo se amplía a un único registro existente; las coincidencias ambiguas se rechazan. La corrección de «Jesús Alejandro Rosales Barrios» con la grafía oficial «JESUS ALEJADRO» fue confirmada por Antonio y queda limitada al identificador, equipo y temporada comprobados.

## Dos calendarios para el mismo jugador

Si la ficha oficial confirma participación en otro equipo del mismo club, la agenda incorpora también ese segundo calendario. La cabecera de la ficha individual no se interpreta como prueba de inscripción principal. La tarjeta y el perfil muestran «Dos equipos» y cada cita distingue «Equipo seguido» y «Equipo adicional», con convocatoria por confirmar. La ficha muestra estadísticas separadas por equipo; los indicadores principales y la comparativa mantienen el ámbito del equipo seguido. No se suman partidos ni minutos de los dos calendarios.

Las alertas de cruces consideran ambos equipos y los otros colaboradores, excluyendo enfrentamientos del jugador consigo mismo. Si falla un segundo calendario, se conserva su lectura anterior con su propia fecha y se indica la consulta incompleta.

## Incorporaciones de la FFCV

La consulta de plantilla selecciona antes el equipo en el portal público y verifica su código. Cuando la ficha incluye liga y copa con el mismo equipo, se elige la competición que coincide con la categoría de la ficha del equipo; una selección ambigua queda pendiente. La duración corresponde a la categoría oficial del equipo (incluida la denominación valenciana Cadet), y se mantiene separada de la categoría por año facilitada por Antonio.

Durante la comprobación de una nueva identidad se contrastan jornadas del principio y del final del calendario. Para publicar antes la agenda, la primera ficha consulta solo las tres jornadas más cercanas a la fecha actual y deja señalado el calendario incompleto. La actualización deportiva posterior descarga todas las jornadas y las actas pendientes. Mientras tanto, los encuentros conocidos no se presentan como el total de temporada. La comprobación inicial no consulta actas individuales por duplicado.

Las consultas FFCV se espacian al menos dos segundos. Si el portal responde con un límite de frecuencia, se guarda el plazo `Retry-After` y se suspenden las nuevas consultas hasta ese momento, incluso en la siguiente ejecución. Las fichas valencianas con lectura más antigua tienen prioridad para que el límite no deje siempre al mismo jugador al final de la cola. Las identidades deportivas de Blake Liu / Liu Peigeng y Álvaro Sandoval / Álvaro fueron confirmadas por Antonio y se vinculan únicamente a su identificador, equipo y temporada revisados.

La agenda distingue los jugadores asignados en el registro de las fichas deportivas ya publicadas. Los colaboradores nuevos pueden seleccionarse mientras se prepara su calendario; se muestra cuántos jugadores siguen pendientes y, cuando hay límite de consultas, hasta cuándo está pausada la fuente. Las pausas operativas en `settings.json` complementan el plazo devuelto por la fuente y nunca acortan un `Retry-After` posterior. Una ficha que solo aparecía como rival en el calendario de otro jugador no se publica como si hubiera completado su propia primera lectura.

La comprobación de cartera también detecta identidades verificadas cuyo primer calendario aún no se ha publicado. Se reintentan al vencer la pausa de la fuente, sin necesitar una nueva alta ni un cambio de revisión. Esto no cambia la política de estadísticas parciales ni la revisión de campos de actas antiguas reservadas para «mejora datos».
