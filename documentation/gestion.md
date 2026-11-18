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
