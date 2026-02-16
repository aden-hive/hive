import psutil
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Label
from textual.reactive import reactive


class PerformanceWidget(Container):
    """Widget to display system performance metrics."""

    DEFAULT_CSS = """
    PerformanceWidget {
        layout: horizontal;
        height: 3;
        background: $panel;
        border-top: solid $primary;
        padding: 0 1;
        dock: bottom;
    }

    PerformanceWidget > Label {
        width: 1fr;
        content-align: center middle;
        color: $text;
    }

    .metric-label {
        color: $text-muted;
    }

    .metric-value {
        text-style: bold;
        color: $accent;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("CPU: --%", id="cpu-val")
        yield Label("RAM: --%", id="mem-val")
        yield Label("Disk: --%", id="disk-val")

    def on_mount(self) -> None:
        self.set_interval(2.0, self.update_metrics)

    def update_metrics(self) -> None:
        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent

            self.query_one("#cpu-val", Label).update(f"CPU: [bold cyan]{cpu:.1f}%[/bold cyan]")
            self.query_one("#mem-val", Label).update(f"RAM: [bold magenta]{mem:.1f}%[/bold magenta]")
            self.query_one("#disk-val", Label).update(f"Disk: [bold yellow]{disk:.1f}%[/bold yellow]")
        except Exception:
            pass
