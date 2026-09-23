# Uso diario de LOT Bot

Esta guía resume todo lo que necesitas para trabajar con LOT Bot cada día.

## 1. Abrir el programa

Haz doble clic en **LOT-Bot.exe**. Se abre en la pantalla **Asistente**, que es el
centro de todo: le escribes lo que quieres, en español normal, y él lo prepara.

Si ves arriba una franja que dice **MODO DEMOSTRACIÓN**, estás en el modo de
prueba: todo funciona igual, pero **nada se envía a Wallapop**. Es perfecto para
aprender sin miedo a equivocarte.

## 2. Hablar con el asistente

Escribe como hablarías con una persona. Ejemplos:

| Quieres… | Escribe |
|---|---|
| Ver el anuncio de canapés | «prepara el anuncio de canapé» |
| Publicarlo | «sube el canapé» |
| Publicar varias copias | «publica 10 canapés en las cuentas 1 y 2» |
| Ver cómo va la publicación | «¿cómo va la cola?» |
| Pausar / seguir | «pausa la cola» / «reanuda la cola» |
| Cambiar un precio | «cambia el precio del 135x190 a 270 €» |
| Cambiar el precio de lo que estás viendo | «cambia el precio de este anuncio a 250 €» |
| Ver tus anuncios | «enséñame los anuncios activos» |
| Ver mensajes | «qué mensajes tengo sin leer» |
| Contestar a un comprador | «prepara una respuesta para este cliente» |
| Revisar la calidad | «revisa los anuncios con problemas» |

Si el asistente no está seguro de a qué te refieres, **te pregunta** en lugar de
adivinar.

## 3. Confirmar siempre

Antes de publicar, cambiar o borrar algo, el asistente te enseña exactamente lo
que va a hacer. Por ejemplo:

> Voy a cambiar el precio del anuncio «Canapé…» de 230,00 € a 270,00 €. ¿Confirmas?

Pulsa **Confirmar** si es correcto o **Cancelar** si no. Sin tu confirmación no se
hace nada.

## 4. El anuncio principal de canapés

En el menú, **Anuncio principal** guarda tu anuncio de canapés con tus datos:
título, características, precio, descripción con las tres medidas y tu WhatsApp.

* Puedes editar los precios de cada medida y el teléfono desde esa pantalla.
* Cuando cambias el precio **de una publicación concreta**, tu anuncio principal
  **no cambia**.
* Solo cambia si lo pides expresamente: «actualiza la plantilla» (y confirmas).
* El botón **Restaurar datos originales** devuelve los datos iniciales.

## 5. Fotos

Desde **Anuncio principal** o **Productos**, pulsa **Fotografías** para:
añadir fotos, verlas, cambiar su orden (la primera es la portada), eliminarlas y
comprobar que tienen buena calidad. LOT Bot avisa si una foto es demasiado pequeña
o está repetida.

## 6. Conectar tus cuentas de Wallapop

1. Ve a **Configuración → Wallapop**, elige **«Integración mediante navegador»**
   y pulsa **Aplicar**.
2. En **Cuentas**, pulsa **«Añadir cuenta Wallapop»** y ponle un nombre.
3. Se abre una ventana del navegador con Wallapop. **Inicia sesión tú** con
   esa cuenta. Si Wallapop te pide un código o una verificación, complétala
   en esa ventana.
4. Cuando LOT Bot detecte la sesión, te preguntará si quieres conectarla.
   Pulsa **Sí**.

Cada cuenta queda guardada en su propio navegador, separado de las demás. LOT
Bot **nunca ve ni guarda tu contraseña**. Para borrar la sesión guardada,
selecciona la cuenta y pulsa **Desconectar**.

Estas cuentas se conectan para tu uso personal autorizado; no es una
aplicación oficial de Wallapop.

## 7. Publicación automática

Cuando dices «Publica 10 canapés» y confirmas, LOT Bot crea una **cola**:
publica un anuncio, espera **al menos 60 segundos**, publica el siguiente, y
así hasta terminar, repartiéndolos entre tus cuentas.

En la pantalla **Publicación automática** ves en todo momento cuántos van
publicados, cuál es la cuenta actual, la hora de la última publicación y la
de la siguiente. Puedes **Pausar**, **Reanudar**, **Cancelar** y
**Reintentar** un anuncio que haya fallado.

Si Wallapop pide una verificación o la sesión ha caducado, la cola **se
detiene sola**. Ve a **Cuentas**, selecciona la cuenta, pulsa **Abrir
navegador**, haz lo que te pida Wallapop, cierra la ventana y pulsa
**Reanudar**.

El intervalo se puede ampliar en Configuración → Wallapop, pero nunca bajar
de 60 segundos.

## 8. Una foto distinta para cada anuncio (FLUX.2 Pro)

LOT Bot puede crear una fotografía realista distinta para cada anuncio.

1. Consigue una clave de API en Black Forest Labs (bfl.ai).
2. Ve a **Configuración → IA / Imágenes**, pégala y pulsa **Guardar**.
3. Pulsa **Probar conexión y ver saldo** para comprobarla.

La clave se guarda cifrada en tu ordenador. Cada imagen consume créditos de
tu cuenta de Black Forest Labs. En el modo demostración no se gastan
créditos: se usan imágenes de prueba.

## 9. Cuentas

En **Cuentas** puedes **Añadir**, **Conectar**, **Desconectar**, **Volver a
autenticar** y **Eliminar** cada cuenta. Cada cuenta está separada de las demás.
Las cuentas marcadas como **Solo demostración** son de prueba y nunca se conectan a
Wallapop.

LOT Bot **nunca te pide tu contraseña de Wallapop**.

## 10. Mensajes de compradores

En **Mensajes** ves las conversaciones. El asistente prepara respuestas usando
solo los datos reales de tus anuncios. Si un comprador pregunta algo que no está
en el anuncio, la respuesta dirá: «No dispongo de esa información.» Revisa y
edita siempre antes de enviar.

## 11. Si algo no funciona

* **«Esta operación no está disponible con el acceso actual a Wallapop»**: esa
  función todavía no está habilitada para tus cuentas. No es un error tuyo.
* **«La sesión ha caducado»**: ve a **Cuentas** y pulsa **Volver a autenticar**.
* **La cola se ha pausado con «No se ha podido completar el paso…»**: la web
  de Wallapop puede haber cambiado. Avisa a tu técnico; no hace falta
  reinstalar LOT Bot.
* Para cualquier otra cosa, la pantalla **Historial** muestra lo que ha pasado.
