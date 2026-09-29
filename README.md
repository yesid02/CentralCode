# Central Code

Aplicación web para consultar códigos recientes de plataformas desde una bandeja IMAP sin exponer el correo al usuario final.

## Requisitos

- Python 3.11+
- Una cuenta IMAP. Para Gmail, usa una contraseña de aplicación (no la contraseña principal).

## Puesta en marcha

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` con el host, usuario y contraseña de aplicación del buzón central. Después inicia el servidor:

```powershell
uvicorn app.main:app --reload
```

Abre `http://127.0.0.1:8000`.

## Panel de administración

Abre `http://127.0.0.1:8000/admin` o pulsa **Administrar** arriba a la derecha.

Credenciales predeterminadas:

```text
Correo: admin@centralcode.local
Contraseña: CambiaEstaClave123!
```

Puedes cambiarlas agregando `ADMIN_EMAIL` y `ADMIN_PASSWORD` al archivo `.env`. El panel permite:

1. Registrar **cuentas principales** (bandeja IMAP real). Ahí llegan todos los códigos.
2. Definir un **dominio de subdominios** (ej. `rsd.tudominio.com`) y crear cuentas de streaming con alias como `cliente1@rsd.tudominio.com`.
3. Asociar esas cuentas a clientes y renovar vencimientos.

La misma plataforma no puede asociarse dos veces al mismo cliente.

Configura el bot de renovación en `.env`:

```text
WHATSAPP_BOT_NUMBER=573001234567
WHATSAPP_RENEWAL_MESSAGE=Hola, necesito renovar mi cuenta de {platform}. Mi celular o correo es {identifier}.
```

## Flujo

1. El frontend pide plataforma y **número de celular** del cliente.
2. `POST /api/lookup` valida que exista una cuenta asociada a ese celular y que no esté vencida.
3. Si la cuenta venció, la UI ofrece un enlace a WhatsApp para que el cliente escriba al bot y renueve.
4. Si está vigente, busca el código en mensajes IMAP recientes y muestra un contador del código y del tiempo restante de acceso.
5. Desde el panel admin puedes renovar la fecha de vencimiento de cada cuenta tras atender al cliente.
6. En la página pública, **Comprar cuentas** abre un catálogo con carrito; al comprar se redirige a WhatsApp con el pedido.

Las plataformas de **consulta OTP** están en `app/platforms.py`. El catálogo de **venta** (más amplio) está en `app/shop.py`.

## Producción

- Usa HTTPS y un proxy inverso (`APP_ENV=production` activa HSTS y cookies `Secure`).
- Cambia `ADMIN_PASSWORD` y `SESSION_SECRET` (valores largos y aleatorios). Opcional: `CREDENTIALS_KEY` aparte para cifrar contraseñas IMAP en la base.
- Define `TRUSTED_HOSTS` con tu dominio (ej. `tudominio.com,www.tudominio.com`).
- Guarda secretos en el gestor de secretos del proveedor, no en `.env` dentro del servidor.
- Configura una cuenta IMAP con acceso mínimo y contraseña de aplicación.
- Sustituye el rate limiter en memoria por uno compartido si ejecutas múltiples instancias.

## Seguridad incluida

- Contraseñas IMAP cifradas en SQLite (Fernet).
- Sesión de admin firmada (HMAC) + cookie CSRF + validación de Origin.
- Cookies `__Host-*` en producción (`Secure`, `SameSite=Strict`, HttpOnly en la sesión).
- Rate limit y bloqueo temporal en login; rate limit en lookup y API admin.
- Cabeceras HTTP (CSP, X-Frame-Options, nosniff, CORP, etc.) y `Cache-Control: no-store` en APIs.
- Rutas sensibles bloqueadas (`.env`, `/data`, `/app`, `.git`).
- OpenAPI/`/docs` desactivados por defecto (`OPENAPI_ENABLED=false`).
- En producción no arranca con secretos por defecto; errores IMAP genéricos al público.
- Auditoría de login y cambios en el panel (visible en Resumen).
- Identificadores de consultas hasheados en la tabla `lookups`.
