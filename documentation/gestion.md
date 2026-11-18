# Gestión de la cartera

[Panel de Antonio](https://rfhf-control-antonio.opalescentpaper1.chatgpt.site/).

1. Inicia sesión con la cuenta de Antonio vinculada al panel.
2. Elige **Añadir jugador**, **Dar de baja**, **Cambiar colaborador**, **Reactivar jugador** o **Añadir o actualizar BeSoccer**.
3. Completa los campos y pulsa **Guardar cambios**. No hay incidencias ni confirmaciones en GitHub.
4. Consulta el estado del jugador en el propio panel.

Una nueva alta necesita nombre y apellidos completos, federación, colaborador, enlace del equipo/categoría en la federación o en BeSoccer y duración reglamentaria. La federación seleccionada determina la vista de la agenda también cuando el enlace es de BeSoccer. Para equipos murcianos nuevos con fuente federativa se pide también el enlace de una jornada de su competición. Se verifica la plantilla y el calendario antes de mostrar una identidad nueva. Si falta información o falla la fuente, el panel explica qué revisar; se vuelve a intentar automáticamente.

Puedes añadir un equipo de BeSoccer directamente como fuente principal o completar una ficha federativa con **Equipo en BeSoccer** y, si lo tienes, **Ficha individual en BeSoccer**. El enlace individual es opcional y ayuda a resolver nombres abreviados; siempre se comprueba el nombre completo, la plantilla, competición y temporada. Si hay ambigüedad se pide revisar el enlace individual. El enlace de equipo puede ser su portada, plantilla o partidos; se normaliza a la misma identidad.

Para añadir o cambiar estos enlaces en un jugador existente, elige **Añadir o actualizar BeSoccer**, selecciona el jugador y guarda. La vinculación se verifica antes de usarla. En una ficha con federación, dejar ambos campos vacíos retira el complemento. En una ficha que usa BeSoccer como fuente principal se conserva su equipo; cambiar de club necesita revisar el alta.

Los datos federativos mantienen prioridad. Las participaciones de BeSoccer solo completan campos ausentes de un partido inequívocamente coincidente en fecha, jornada, rival y resultado. El resumen adicional se muestra por separado con su equipo, competición y fecha; no se suman totales de distintas fuentes. Un suplente que no juega sigue siendo convocado; «PS» de BeSoccer no se interpreta como convocatorias ni como todo el banquillo. Si falta una alineación no se supone una ausencia.

Las bajas y asignaciones se reflejan al refrescar la agenda (cada 30 segundos o al volver a la pestaña). Las altas y reactivaciones requieren comprobación y publicación: se comprueban cambios cada cinco minutos mediante GitHub Actions, cuya ejecución puede retrasarse. No se promete una hora exacta de incorporación.

Solo Antonio puede escribir: el servidor coteja la identidad autenticada con la cuenta vinculada durante la activación privada. Ser visitante, conocer un nombre de colaborador o intentar falsificar cabeceras no concede permisos. La lectura de los datos deportivos es pública, autorizada por el propietario. No hay tokens para pegar ni una contraseña compartida.

Dar de baja desactiva el registro; se puede recuperar con **Reactivar**. La baja no borra el historial del repositorio público. No añadas motivos contractuales ni datos de contacto: el registro contiene únicamente información deportiva y asignaciones públicas.

## Importar una lista

Antonio puede elegir **Importar lista de jugadores**, seleccionar la federación y pegar las filas desde su hoja o subir un archivo TSV. Se usan cinco columnas sin cabecera: nombre completo, año de nacimiento, equipo, enlace y colaborador. Las filas sin enlace se omiten; una fila con formato inválido impide guardar el lote entero. Se muestran las altas, los registros existentes actualizados y los omitidos al guardar. No se borran otros territorios y un jugador ya registrado conserva su identidad y fuente. Se actualiza su colaborador y categoría por edad.

El año sirve para clasificar la edad y no se conserva en el registro público. En 2026–2027: 2008–2010 juvenil, 2011–2012 cadete, 2013–2014 infantil y 2007 o anteriores sénior. La duración para calcular minutos corresponde a la categoría del equipo: 90 minutos sénior/juvenil, 80 cadete y 70 infantil. Un jugador joven puede figurar en un equipo de mayor edad; una edad indicada superior a la del equipo requiere revisión antes de activar el registro.

El nombre de la hoja puede ampliarse al nombre completo de una identidad única de la plantilla verificada. Si el nombre no aparece o la ficha no confirma su competición actual, el alta permanece pendiente y se reintenta sin publicar una identidad por parecido. En Madrid, las estadísticas de varias competiciones de una ficha individual no se mezclan: se calculan con las actas del equipo seguido. Las alineaciones históricas ya verificadas se conservan para el mismo resultado y se revisan las dos últimas en cada consulta.

Las comprobaciones de cartera consultan los datos deportivos de las altas nuevas y de los cambios de fuente; el resto conserva sus datos y sus fechas. La actualización periódica de la agenda sigue consultando todas las fuentes. Si BeSoccer entrega una pantalla de verificación o deniega la navegación, el registro queda pendiente con ese motivo: esa respuesta no contiene datos deportivos utilizables por el actualizador.
# Fuentes oficiales alternativas

Las nueve altas que dependían de BeSoccer en Alfaro, La Calzada, Alameda, Azuqueca, Isoba, Trival y Sporting Hortaleza disponen de correspondencias revisadas en `scripts/official_sources.py`. La comprobación valida de nuevo identidad, equipo y temporada ante RFEF, FFCM, RFCYLF o FRF. Se conservan los identificadores del panel, colaboradores y vista territorial. No se consulta BeSoccer al activar estas correspondencias.

La correspondencia se aplica solo a esos nombres completos, enlaces y temporada 2026–2027. Un jugador o club distinto sigue el flujo habitual y requiere una fuente verificable. Las cuatro vistas no representan una restricción sobre la federación que publica los datos de cada club.

El calendario extendido aporta fecha y campo del encuentro; si solo está disponible el calendario básico, se identifica expresamente la fecha de jornada. Las jornadas añaden enlaces a actas y horarios actualizados. Una consulta fallida de acta deja la participación sin dato, conservando el calendario y la última participación compatible. Los nuevos adaptadores tienen pruebas con fragmentos deportivos de las fuentes; no se guardan fotos ni datos de contacto en el feed.

Cuando el portal público devuelve un cuerpo HTTP vacío, el actualizador intenta la navegación ordinaria con Chrome. El respaldo se limita a los cinco dominios oficiales y rutas deportivas permitidas. No actúa ante denegaciones ni interacciona con verificaciones o accesos privados. La ficha de grupo del equipo es otra alternativa oficial al calendario general.

Para Rullán y Contera se incluye una lectura deportiva inicial contrastada el 18/11/2026, con actas de identidad y calendarios oficiales. Solo puede activar su correspondencia exacta durante las 24 horas siguientes a esa lectura. Si se utiliza porque la consulta actual falla, conserva la fecha original y un aviso de actualización incompleta; no se etiqueta como lectura en vivo. Después de la activación se aplica el mismo refresco automático y conservación del último dato válido que al resto.
