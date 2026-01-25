"""
YTAutoPublisher CLI

Command-line interface for YouTube auto-publishing.

Usage:
    python -m src.publisher.main init
    python -m src.publisher.main channel add channel_001
    python -m src.publisher.main channel test channel_001
    python -m src.publisher.main publish proj_xxx
    python -m src.publisher.main publish-all
"""

import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.publisher.config_manager import get_config_manager
from src.publisher.metadata_cleaner import get_metadata_cleaner
from src.publisher.youtube_api import YouTubeAPI
from src.publisher.publisher import Publisher
from src.publisher.models import (
    ChannelConfig,
    ChannelSettings,
    ProxyConfig,
    PrivacyStatus,
)


# Create Typer app
app = typer.Typer(
    name="ytauto",
    help="YTAutoPublisher - Automatic YouTube video publishing",
    add_completion=False,
)

# Sub-commands for channel management
channel_app = typer.Typer(help="Channel management commands")
app.add_typer(channel_app, name="channel")

# Rich console for pretty output
console = Console()


# ============================================================================
# INIT COMMAND
# ============================================================================

@app.command()
def init():
    """Initialize YTAutoPublisher directories and config."""
    console.print("\n[bold blue]Initializing YTAutoPublisher...[/bold blue]\n")

    config = get_config_manager()
    results = config.init_directories()

    for name, created in results.items():
        status = "[green]Created[/green]" if created else "[dim]Exists[/dim]"
        console.print(f"  {status} {name}")

    # Check FFmpeg
    cleaner = get_metadata_cleaner()
    if cleaner.is_ffmpeg_available():
        version = cleaner.get_ffmpeg_version()
        console.print(f"\n[green]FFmpeg available:[/green] {version}")
    else:
        console.print("\n[yellow]Warning:[/yellow] FFmpeg not found. Metadata cleaning will be skipped.")
        console.print("  Install FFmpeg: https://ffmpeg.org/download.html")

    console.print("\n[bold green]System ready![/bold green]")
    console.print("\nNext step: Add a channel with [bold]channel add <channel_id>[/bold]")


# ============================================================================
# CHANNEL COMMANDS
# ============================================================================

@channel_app.command("add")
def channel_add(
    channel_id: str = typer.Argument(..., help="Internal channel ID (e.g., channel_001)"),
):
    """Add and authorize a new YouTube channel."""
    config = get_config_manager()

    if config.channel_exists(channel_id):
        console.print(f"[yellow]Channel already exists:[/yellow] {channel_id}")
        if not typer.confirm("Overwrite existing configuration?"):
            raise typer.Abort()

    console.print(f"\n[bold blue]Adding channel:[/bold blue] {channel_id}\n")

    # Get channel info
    channel_name = typer.prompt("Channel display name")
    youtube_channel_id = typer.prompt("YouTube channel ID (UC...)")
    region = typer.prompt("Region", default="US")
    timezone = typer.prompt("Timezone", default="America/New_York")

    # Proxy configuration
    use_proxy = typer.confirm("Configure proxy?", default=True)
    proxy = None

    if use_proxy:
        proxy = ProxyConfig(
            enabled=True,
            host=typer.prompt("Proxy host"),
            port=int(typer.prompt("Proxy port")),
            username=typer.prompt("Proxy username", default=""),
            password=typer.prompt("Proxy password", default="", hide_input=True),
        )

    # Create channel config
    channel_config = ChannelConfig(
        channel_id=channel_id,
        channel_name=channel_name,
        youtube_channel_id=youtube_channel_id,
        region=region,
        timezone=timezone,
        proxy=proxy,
        settings=ChannelSettings(),
    )

    # Save config
    config.save_channel_config(channel_config)
    console.print(f"\n[green]Config saved to:[/green] config/channels/{channel_id}/")

    # Check for client_secrets.json
    client_secrets_path = config.get_client_secrets_path(channel_id)

    if not client_secrets_path.exists():
        console.print(f"\n[yellow]client_secrets.json not found![/yellow]")
        console.print(f"Please copy your client_secrets.json to:")
        console.print(f"  [bold]{client_secrets_path}[/bold]")
        console.print("\nThen run: [bold]channel auth {channel_id}[/bold]")
        return

    # Run OAuth flow
    console.print("\n[bold]Starting OAuth authorization...[/bold]")
    console.print("A browser window will open. Please authorize access.\n")

    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=client_secrets_path,
        token_path=config.get_token_path(channel_id),
    )

    if youtube.run_oauth_flow():
        console.print("\n[bold green]Channel authorized successfully![/bold green]")
        console.print(f"\nTest connection with: [bold]channel test {channel_id}[/bold]")
    else:
        console.print("\n[bold red]Authorization failed![/bold red]")
        raise typer.Exit(1)


@channel_app.command("auth")
def channel_auth(
    channel_id: str = typer.Argument(..., help="Channel ID to authorize"),
):
    """Run OAuth authorization for existing channel."""
    config = get_config_manager()

    if not config.channel_exists(channel_id):
        console.print(f"[red]Channel not found:[/red] {channel_id}")
        raise typer.Exit(1)

    channel_config = config.load_channel_config(channel_id)
    client_secrets_path = config.get_client_secrets_path(channel_id)

    if not client_secrets_path.exists():
        console.print(f"[red]client_secrets.json not found![/red]")
        console.print(f"Please copy to: {client_secrets_path}")
        raise typer.Exit(1)

    console.print(f"\n[bold]Authorizing channel:[/bold] {channel_id}")
    console.print("A browser window will open...\n")

    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=client_secrets_path,
        token_path=config.get_token_path(channel_id),
    )

    if youtube.run_oauth_flow():
        console.print("\n[bold green]Authorization successful![/bold green]")
    else:
        console.print("\n[bold red]Authorization failed![/bold red]")
        raise typer.Exit(1)


@channel_app.command("test")
def channel_test(
    channel_id: str = typer.Argument(..., help="Channel ID to test"),
):
    """Test connection to a channel."""
    config = get_config_manager()

    if not config.channel_exists(channel_id):
        console.print(f"[red]Channel not found:[/red] {channel_id}")
        raise typer.Exit(1)

    channel_config = config.load_channel_config(channel_id)

    console.print(f"\n[bold]Testing channel:[/bold] {channel_id}\n")

    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=config.get_client_secrets_path(channel_id),
        token_path=config.get_token_path(channel_id),
    )

    success, details = youtube.test_connection()

    # Show results
    proxy_status = "[green]OK[/green]" if details["proxy_ok"] else "[red]Failed[/red]"
    auth_status = "[green]OK[/green]" if details["auth_ok"] else "[red]Failed[/red]"

    console.print(f"  Proxy connection: {proxy_status}")
    console.print(f"  OAuth token: {auth_status}")

    if details["channel_info"]:
        info = details["channel_info"]
        console.print(f"\n  [bold]Channel:[/bold] {info['title']}")
        console.print(f"  [dim]ID: {info['id']}[/dim]")
        console.print(f"  Subscribers: {info['subscribers']}")
        console.print(f"  Videos: {info['videos']}")

    if success:
        console.print("\n[bold green]All tests passed![/bold green]")
    else:
        console.print(f"\n[bold red]Tests failed:[/bold red] {details.get('error', 'Unknown error')}")
        raise typer.Exit(1)


@channel_app.command("list")
def channel_list():
    """List all configured channels."""
    config = get_config_manager()
    channels = config.list_channels()

    if not channels:
        console.print("[dim]No channels configured.[/dim]")
        console.print("Add a channel with: [bold]channel add <channel_id>[/bold]")
        return

    table = Table(title="Configured Channels")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Region")
    table.add_column("Proxy")
    table.add_column("Authorized")
    table.add_column("Active")

    for channel_id in channels:
        channel_config = config.load_channel_config(channel_id)
        if not channel_config:
            continue

        proxy = "[green]Yes[/green]" if channel_config.proxy and channel_config.proxy.enabled else "[dim]No[/dim]"
        authorized = "[green]Yes[/green]" if config.channel_is_authorized(channel_id) else "[red]No[/red]"
        active = "[green]Yes[/green]" if channel_config.settings.active else "[dim]No[/dim]"

        table.add_row(
            channel_id,
            channel_config.channel_name,
            channel_config.region,
            proxy,
            authorized,
            active,
        )

    console.print(table)


# ============================================================================
# PUBLISH COMMANDS
# ============================================================================

@app.command()
def publish(
    project_id: str = typer.Argument(..., help="Project ID to publish"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate without uploading"),
    skip_clean: bool = typer.Option(False, "--skip-clean", help="Skip metadata cleaning"),
    skip_archive: bool = typer.Option(False, "--skip-archive", help="Don't archive after publish"),
):
    """Publish a single project to YouTube."""
    console.print(f"\n{'[DRY RUN] ' if dry_run else ''}[bold]Publishing:[/bold] {project_id}\n")

    publisher = Publisher()

    success, status = publisher.publish(
        project_id=project_id,
        dry_run=dry_run,
        skip_metadata_clean=skip_clean,
        skip_archive=skip_archive,
    )

    if success:
        if dry_run:
            console.print("\n[bold yellow]Dry run completed.[/bold yellow]")
        else:
            console.print(f"\n[bold green]Published successfully![/bold green]")
            console.print(f"URL: {status.video_url}")
    else:
        console.print(f"\n[bold red]Publish failed:[/bold red] {status.error}")
        raise typer.Exit(1)


@app.command("publish-all")
def publish_all(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate without uploading"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum projects to publish"),
):
    """Publish all pending projects."""
    console.print(f"\n{'[DRY RUN] ' if dry_run else ''}[bold]Publishing all pending projects...[/bold]\n")

    publisher = Publisher()
    success_count, fail_count, results = publisher.publish_all(
        dry_run=dry_run,
        limit=limit,
    )

    # Show summary
    if results:
        table = Table(title="Publish Results")
        table.add_column("Project", style="cyan")
        table.add_column("Status")
        table.add_column("URL / Error")

        for result in results:
            status = result["status"]
            if result["success"]:
                status_text = "[green]OK[/green]"
                info = status.video_url or "Dry run"
            else:
                status_text = "[red]Failed[/red]"
                info = status.error or "Unknown error"

            table.add_row(result["project_id"], status_text, info)

        console.print(table)

    console.print(f"\nSuccess: {success_count}, Failed: {fail_count}")


@app.command()
def status(
    project_id: str = typer.Argument(..., help="Project ID to check"),
):
    """Check status of a project."""
    publisher = Publisher()
    status_info = publisher.get_project_status(project_id)

    if not status_info:
        console.print(f"[red]Project not found:[/red] {project_id}")
        raise typer.Exit(1)

    panel = Panel(
        f"""[bold]Title:[/bold] {status_info['title']}
[bold]Target Channel:[/bold] {status_info['target_channel'] or 'Not set'}
[bold]Video Found:[/bold] {'Yes' if status_info['video_found'] else 'No'}
[bold]Video Path:[/bold] {status_info['video_path'] or 'N/A'}

[bold]Publish Status:[/bold]
{_format_publish_status(status_info['publish_status'])}""",
        title=f"Project: {project_id}",
    )

    console.print(panel)


def _format_publish_status(status: Optional[dict]) -> str:
    """Format publish status for display"""
    if not status:
        return "  Not published yet"

    lines = []
    lines.append(f"  Status: {status['status']}")

    if status.get('video_id'):
        lines.append(f"  Video ID: {status['video_id']}")
    if status.get('video_url'):
        lines.append(f"  URL: {status['video_url']}")
    if status.get('published_at'):
        lines.append(f"  Published: {status['published_at']}")
    if status.get('error'):
        lines.append(f"  Error: {status['error']}")

    return "\n".join(lines)


@app.command()
def history(
    days: int = typer.Option(7, "--days", "-d", help="Number of days to show"),
):
    """Show publish history."""
    config = get_config_manager()
    events = config.read_history(days=days)

    if not events:
        console.print(f"[dim]No publish history in the last {days} days.[/dim]")
        return

    table = Table(title=f"Publish History (Last {days} days)")
    table.add_column("Time", style="dim")
    table.add_column("Event")
    table.add_column("Project")
    table.add_column("Details")

    for event in sorted(events, key=lambda e: e.timestamp, reverse=True):
        time_str = event.timestamp.strftime("%m-%d %H:%M")

        details = ""
        if event.video_id:
            details = f"Video: {event.video_id}"
        elif event.error:
            details = f"[red]{event.error}[/red]"

        table.add_row(
            time_str,
            event.event,
            event.project_id or "",
            details,
        )

    console.print(table)


@app.command()
def pending():
    """List projects pending publication."""
    config = get_config_manager()
    projects = config.list_pending_projects()

    if not projects:
        console.print("[dim]No projects pending publication.[/dim]")
        return

    table = Table(title=f"Pending Projects ({len(projects)})")
    table.add_column("Project ID", style="cyan")
    table.add_column("Title")
    table.add_column("Channel")
    table.add_column("Video")

    for project_id in projects:
        brief = config.load_project_brief(project_id)
        video = config.find_video_file(project_id)

        title = brief.youtube.title[:40] + "..." if brief and len(brief.youtube.title) > 40 else (brief.youtube.title if brief else "N/A")
        channel = brief.publish_config.target_channel if brief and brief.publish_config else "Not set"
        video_status = "[green]Found[/green]" if video else "[red]Missing[/red]"

        table.add_row(project_id, title, channel, video_status)

    console.print(table)


# ============================================================================
# MAIN ENTRY
# ============================================================================

def main():
    """Main entry point"""
    app()


if __name__ == "__main__":
    main()
