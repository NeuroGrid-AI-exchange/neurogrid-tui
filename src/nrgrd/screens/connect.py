"""The "Connect to a model" screen.

Runs automatically the first time nrgrd starts with no key stored, and
again whenever the user asks for it. The user is expected to arrive with
the three things a NeuroGrid deployment hands them — an endpoint, a key,
and a model name — and nothing else.
"""

from rich.box import ROUNDED
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table

from nrgrd.api import ModelProvider, OpenAICompatibleProvider, ProviderError
from nrgrd.config import Config, save_config
from nrgrd.config.credentials import CredentialStore
from nrgrd.theme.colors import (
    BORDER,
    ERROR,
    GREEN,
    GREEN_BRIGHT,
    GREEN_VIVID,
    MUTED,
    PINK,
    PINK_LIGHT,
    TEXT,
    WARNING,
)

MAX_LISTED_MODELS = 30

# Shown when no endpoint is configured yet. Deliberately host-agnostic:
# a deploy is served over a generated tunnel URL, so the host varies per
# deployment. Only the shape is fixed — whatever the console shows, plus /v1.
ENDPOINT_EXAMPLE = "https://<neurogrid-deploy>/v1"

# The old built-in default. Treated as "nothing configured" so the example
# shows instead of a localhost URL the user never chose.
LEGACY_DEFAULT_ENDPOINT = "http://localhost:8000/v1"


def run_connect_screen(
    console: Console,
    config: Config,
    credentials: CredentialStore,
    current_api_key: str = "",
) -> str | None:
    """Collect and save the connection settings.

    Returns the API key now in effect, or ``None`` if the user backed out
    without completing the screen.
    """
    _print_intro(console, credentials)

    current_endpoint = config.base_url.strip()
    if current_endpoint == LEGACY_DEFAULT_ENDPOINT:
        current_endpoint = ""

    endpoint_label = f"[bold {PINK}]Endpoint[/bold {PINK}]"
    if not current_endpoint:
        endpoint_label += f" [{MUTED}](e.g. {ENDPOINT_EXAMPLE})[/]"

    try:
        # Only offer a default once there is a real endpoint to keep;
        # otherwise Enter would accept an address the user never chose.
        endpoint = (
            Prompt.ask(endpoint_label, default=current_endpoint, console=console)
            if current_endpoint
            else Prompt.ask(endpoint_label, console=console)
        ).strip()

        api_key = Prompt.ask(
            f"[bold {PINK}]API key[/bold {PINK}]"
            + (f" [{MUTED}](Enter keeps the stored key)[/]" if current_api_key else ""),
            password=True,
            default="",
            console=console,
        ).strip()
    except (KeyboardInterrupt, EOFError):
        console.print(f"[{MUTED}]Setup cancelled; nothing was saved.[/]")
        return None

    api_key = api_key or current_api_key
    if not endpoint or not api_key:
        console.print(
            f"[{ERROR}]● An endpoint and an API key are both required.[/]"
        )
        return None

    provider = OpenAICompatibleProvider(endpoint=endpoint, api_key=api_key)
    models = _discover_models(console, provider)

    try:
        model = _choose_model(console, models, config.model)
    except (KeyboardInterrupt, EOFError):
        console.print(f"[{MUTED}]Setup cancelled; nothing was saved.[/]")
        return None

    config.base_url = endpoint
    config.model = model
    config.api_key = ""  # The key belongs in the credential store, not here.
    save_config(config)
    credentials.set(api_key)

    _print_summary(console, credentials, endpoint, model)
    return api_key


def _print_intro(console: Console, credentials: CredentialStore) -> None:
    body = Table.grid(padding=(0, 1))
    body.add_column(style=f"bold {PINK_LIGHT}", no_wrap=True)
    body.add_column(style=TEXT)
    body.add_row("Provider", f"{OpenAICompatibleProvider.name} endpoint")
    body.add_row(
        "Works with",
        "NeuroGrid deployments, vLLM, Ollama, LM Studio, and anything else "
        "serving the same API",
    )
    body.add_row("Endpoint", "the deploy URL from your NeuroGrid console")
    body.add_row("API key", f"stored in your {credentials.name}")

    console.print(
        Panel(
            body,
            title=f"[bold {GREEN_BRIGHT}]Connect to a model[/bold {GREEN_BRIGHT}]",
            subtitle=f"[{MUTED}]a NeuroGrid deployment gives you all three[/]",
            border_style=BORDER,
            box=ROUNDED,
            padding=(1, 2),
        )
    )


def _discover_models(console: Console, provider: ModelProvider) -> list[str]:
    """Ask the endpoint what it serves; an empty list means we could not."""
    spinner = Spinner("dots12", text="Contacting the endpoint…", style=GREEN_VIVID)
    try:
        with Live(spinner, console=console, refresh_per_second=20):
            models = provider.list_models()
    except ProviderError as error:
        console.print(
            Panel(
                f"{error.summary}\n\n[{MUTED}]{error.detail}[/]\n\n{error.hint}",
                title=f"[bold {WARNING}]Could not reach the endpoint[/bold {WARNING}]",
                border_style=WARNING,
                box=ROUNDED,
                padding=(0, 1),
            )
        )
        console.print(
            f"[{MUTED}]You can still enter a model name and fix the "
            "connection later.[/]"
        )
        return []

    console.print(f"[{GREEN_VIVID}]● Connected[/]")
    return models


def _choose_model(console: Console, models: list[str], current: str) -> str:
    """Settle on a model, asking only when there is a real choice to make.

    A NeuroGrid deployment serves a single model, so the common path is to
    take the one the endpoint reported and move on.
    """
    if not models:
        return Prompt.ask(
            f"[bold {PINK}]Model[/bold {PINK}]",
            default=current,
            console=console,
        ).strip()

    if len(models) == 1:
        only = models[0]
        console.print(
            f"[{GREEN_VIVID}]● Model[/] [bold {TEXT}]{only}[/] "
            f"[{MUTED}](the only one this endpoint serves)[/]"
        )
        return only

    listing = Table(
        box=ROUNDED,
        border_style=BORDER,
        header_style=f"bold {PINK}",
        padding=(0, 1),
    )
    listing.add_column("#", style=GREEN_VIVID, no_wrap=True)
    listing.add_column("Model", style=TEXT)
    for number, model in enumerate(models[:MAX_LISTED_MODELS], start=1):
        listing.add_row(str(number), model)
    console.print(listing)
    if len(models) > MAX_LISTED_MODELS:
        console.print(f"[{MUTED}]… and {len(models) - MAX_LISTED_MODELS} more[/]")

    default = current if current in models else models[0]
    answer = Prompt.ask(
        f"[bold {PINK}]Model[/bold {PINK}] [{MUTED}](number or name)[/]",
        default=default,
        console=console,
    ).strip()

    if answer.isdigit() and 1 <= int(answer) <= len(models):
        return models[int(answer) - 1]
    return answer


def _print_summary(
    console: Console,
    credentials: CredentialStore,
    endpoint: str,
    model: str,
) -> None:
    summary = Table.grid(padding=(0, 1))
    summary.add_column(style=f"bold {GREEN}", no_wrap=True)
    summary.add_column(style=TEXT)
    summary.add_row("Endpoint", endpoint)
    summary.add_row("Model", model or "Not selected")
    summary.add_row("API key", f"saved to your {credentials.name}")

    console.print(
        Panel(
            summary,
            title=f"[bold {GREEN_VIVID}]Ready[/bold {GREEN_VIVID}]",
            subtitle=f"[{MUTED}]/config edit to change this later[/]",
            border_style=BORDER,
            box=ROUNDED,
            padding=(0, 1),
        )
    )
