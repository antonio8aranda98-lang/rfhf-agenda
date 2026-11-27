# Disparador de horarios RFHF

Autorizado por Antonio el 27/11/2026. Servicio independiente del panel y de los demás proyectos.

- Nombre: `rfhf-horarios-trigger`.
- Repositorio público `antonio8aranda98-lang/rfhf-agenda`, rama `main`.
- Render Cron Job, Python, plan `0.5c-512mb`, sin base de datos ni disco.
- Frecuencia UTC: `0,15,30,45 * * * *`.
- Build: `python3 -m py_compile scripts/dispatch_fixtures.py`.
- Ejecución: `python3 scripts/dispatch_fixtures.py`.
- **Auto Deploy: No**. Los commits frecuentes de datos no deben reconstruir este servicio.
- Credencial: `RFHF_DISPATCH_TOKEN`, introducida personalmente por Antonio en Render. Nunca en el repositorio, chat, archivos o logs. Token fine-grained del repositorio indicado, permiso Actions read/write; sin Contents write.

El script comprueba si hay una actualización de producción activa/en espera y, si no, solicita `workflow_dispatch` de `valencia-horarios.yml`. Ese workflow consulta los cuatro territorios y publica la agenda. No modifica la cartera ni cancela ejecuciones. El script no imprime las cabeceras ni mensajes de error que puedan contener secretos. Tiene un límite total de 50 segundos y no instala dependencias.

Precio consultado el 27/11/2026: mínimo **1 USD/mes por cron**, con consumo a 0,00016 USD/minuto en este plan. Se factura el mayor entre mínimo y uso, más impuestos aplicables. Con 96 ejecuciones diarias de menos de 50 segundos, el tiempo del script debería quedar por debajo del mínimo (no es un límite contractual de factura). Mantener el workspace Hobby si es el plan ya elegido; no contratar Pro para esta tarea. Revisar la factura real del primer mes.

Fuentes: [cron y mínimo mensual](https://render.com/docs/cronjobs), [tarifas](https://render.com/pricing).

## Comprobación

Un build `live` solo prepara el programa. Para darlo por operativo también hay que verificar una ejecución del cron, el evento de GitHub y el feed público publicado. Una ejecución que diga que ya hay trabajo en curso evita duplicados; no acredita por sí misma una revisión nueva.

Límites: el disparador evita depender del evento `schedule` de GitHub. Sigue sujeto a la cola de Actions y a la disponibilidad o restricciones de las federaciones. No elimina el HTTP 403 de la FCF. No prometer actualización exacta cada 15 minutos ni todos los horarios publicados.

## Cambios posteriores

Tras modificar el script, desplegar manualmente el commit concreto y verificarlo. La expiración o revocación de la credencial requiere que Antonio la renueve personalmente en el entorno de Render. No reutilizar credenciales de otras apps.
