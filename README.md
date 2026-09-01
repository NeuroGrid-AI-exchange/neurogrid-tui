# mantui

![Python](https://img.shields.io/badge/python-3.14%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-alpha-orange)

**mantui** es una Terminal User Interface (TUI) para interactuar con modelos de IA desde tu terminal. Construida sobre `textual`, `rich` y `asciimatics`, ofrece una experiencia visual envolvente para chatear con la API de OpenAI, gestionar sesiones y ejecutar herramientas MCP.

## Caracteristicas

- **Interfaz TUI inmersiva** — Navegacion por teclado con `textual` y widgets personalizados.
- **Sesiones persistentes** — Guarda el contexto y el historial de conversaciones localmente.
- **Modelos OpenAI** — Soporte para cualquier modelo compatible con la API de OpenAI.
- **MCP integrado** — Ejecuta y conecta servidores MCP desde la propia terminal.
- **Widgets ricos** — Animaciones, logos ASCII y componentes visuales con `rich` y `asciimatics`.
- **CLI + TUI** — Usa `mantui` para la interfaz grafica o `mantui-mcp` para el servidor MCP.

## Requisitos

- Python >= 3.14
- `uv` (gestor de paquetes recomendado)

## Instalacion

```bash
# Clonar el repositorio
git clone https://github.com/<tu-usuario>/mantui.git
cd mantui

# Instalar dependencias
uv sync

# Ejecutar la TUI
uv run mantui

# Ejecutar el servidor MCP
uv run mantui-mcp
```

## Configuracion

Crea un archivo `.env` en la raiz del proyecto con tu clave de OpenAI:

```env
OPENAI_API_KEY=sk-...
```

## Estructura del proyecto

```
mantui/
├── src/mantui/
│   ├── app.py            # Punto de entrada principal
│   ├── api/              # Cliente HTTP para la API de OpenAI
│   ├── config/           # Configuracion y tokens
│   ├── context/          # Estado de la aplicacion y modelos
│   ├── screens/          # Pantallas de la TUI
│   ├── sessions/         # Manejo de sesiones y almacenamiento
│   ├── system/           # Prompts del sistema
│   ├── theme/            # Paleta de colores y estilos
│   ├── widgets/          # Componentes visuales personalizados
│   └── workspace/        # Herramientas, identidad y MCP
├── docs/                 # Reportes y documentacion
└── pyproject.toml        # Dependencias y metadatos del proyecto
```

## Desarrollo

```bash
# Instalar en modo editable
uv sync --dev

# Ejecutar linters / checks (si aplica)
uv run ruff check src/
uv run mypy src/
```

## Licencia

MIT
