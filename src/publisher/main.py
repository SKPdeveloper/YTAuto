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
from src.publisher.ab_models import ABStatus, VariantData, VideoABRecord, parse_metadata_variants
from src.publisher.ab_store import ABStore
from src.publisher.ab_monitor import ABMonitor


# Create Typer app
app = typer.Typer(
    name="ytauto",
    help="YTAutoPublisher - Automatic YouTube video publishing",
    add_completion=False,
)

# Sub-commands for channel management
channel_app = typer.Typer(help="Channel management commands")
app.add_typer(channel_app, name="channel")

# Sub-commands for A/B metadata rotation
ab_app = typer.Typer(help="A/B metadata rotation commands")
app.add_typer(ab_app, name="ab")

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
    adspower: str = typer.Option(None, "--adspower", "-a", help="AdsPower profile ID to use for auth"),
):
    """Run OAuth authorization for existing channel.

    Use --adspower to open auth in AdsPower browser instead of system default.
    Example: channel auth glaze_city --adspower j5yrx8v
    """
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

    if adspower:
        console.print(f"[cyan]Using AdsPower profile:[/cyan] {adspower}")
        console.print("Authorization page will open in AdsPower browser...\n")
    else:
        console.print("A browser window will open...\n")

    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=client_secrets_path,
        token_path=config.get_token_path(channel_id),
    )

    if youtube.run_oauth_flow(adspower_profile_id=adspower):
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
# UPLOAD COMMANDS (resumable uploads)
# ============================================================================

@app.command("uploads")
def list_uploads(
    channel_id: str = typer.Argument(..., help="Channel ID to check uploads"),
):
    """List pending/interrupted uploads that can be resumed."""
    config = get_config_manager()

    if not config.channel_exists(channel_id):
        console.print(f"[red]Channel not found:[/red] {channel_id}")
        raise typer.Exit(1)

    channel_config = config.load_channel_config(channel_id)
    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=config.get_client_secrets_path(channel_id),
        token_path=config.get_token_path(channel_id),
    )

    pending = youtube.list_pending_uploads()

    if not pending:
        console.print("[dim]No pending uploads found.[/dim]")
        return

    table = Table(title=f"Pending Uploads ({len(pending)})")
    table.add_column("Project ID", style="cyan")
    table.add_column("Title")
    table.add_column("Progress")
    table.add_column("Last Updated")

    for upload in pending:
        title = upload["title"][:35] + "..." if len(upload["title"]) > 35 else upload["title"]
        table.add_row(
            upload["project_id"],
            title,
            upload["progress"],
            str(upload["last_updated"])[:19] if upload["last_updated"] else "Unknown",
        )

    console.print(table)
    console.print("\n[dim]Use 'resume <project_id> <channel_id>' to continue upload[/dim]")


@app.command()
def resume(
    project_id: str = typer.Argument(..., help="Project ID to resume"),
    channel_id: str = typer.Argument(..., help="Channel ID"),
):
    """Resume an interrupted upload."""
    config = get_config_manager()

    if not config.channel_exists(channel_id):
        console.print(f"[red]Channel not found:[/red] {channel_id}")
        raise typer.Exit(1)

    channel_config = config.load_channel_config(channel_id)
    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=config.get_client_secrets_path(channel_id),
        token_path=config.get_token_path(channel_id),
    )

    console.print(f"\n[bold]Resuming upload:[/bold] {project_id}\n")

    def progress_callback(uploaded: int, total: int) -> None:
        if total > 0:
            pct = int(uploaded / total * 100)
            console.print(f"[dim]Progress: {pct}% ({uploaded / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB)[/dim]")

    success, video_id, error = youtube.resume_upload(
        project_id=project_id,
        progress_callback=progress_callback,
    )

    if success:
        console.print(f"\n[bold green]Upload completed![/bold green]")
        console.print(f"Video ID: {video_id}")
        console.print(f"URL: https://youtube.com/shorts/{video_id}")
    else:
        console.print(f"\n[bold red]Upload failed:[/bold red] {error}")
        raise typer.Exit(1)


# ============================================================================
# COMMENT PINNING
# ============================================================================

@app.command("test-pin")
def test_pin_comment(
    video_id: str = typer.Argument(..., help="YouTube video ID"),
    channel_id: str = typer.Argument(..., help="Channel ID"),
    comment: str = typer.Option("Test pinned comment from YTAuto", "--comment", "-c", help="Comment text"),
):
    """Test comment pinning via AdsPower browser automation."""
    config = get_config_manager()

    if not config.channel_exists(channel_id):
        console.print(f"[red]Channel not found:[/red] {channel_id}")
        raise typer.Exit(1)

    channel_config = config.load_channel_config(channel_id)

    if not channel_config.adspower_profile_id:
        console.print(f"[red]AdsPower profile not configured for channel:[/red] {channel_id}")
        console.print("[dim]Add 'adspower_profile_id' to channel config.json[/dim]")
        raise typer.Exit(1)

    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=config.get_client_secrets_path(channel_id),
        token_path=config.get_token_path(channel_id),
    )

    console.print(f"\n[bold]Testing add + pin comment on video:[/bold] {video_id}")
    console.print(f"[bold]Using AdsPower profile:[/bold] {channel_config.adspower_profile_id}")
    console.print(f"[bold]Comment:[/bold] {comment}\n")

    console.print("[yellow]AdsPower browser will open to add and pin comment...[/yellow]\n")

    # Use HumanCommenter for browser automation
    try:
        import asyncio
        from src.human_commenter import HumanCommenter, CommenterConfig
    except ImportError:
        console.print("[red]HumanCommenter not available. Install playwright dependencies.[/red]")
        raise typer.Exit(1)

    commenter = HumanCommenter(CommenterConfig())
    result = asyncio.get_event_loop().run_until_complete(
        commenter.add_and_pin_comment(
            video_id=video_id,
            comment_text=comment,
            profile_id=channel_config.adspower_profile_id,
        )
    )

    if result.success:
        console.print(f"\n[bold green]Comment added and pinned successfully![/bold green]")
        console.print(f"Video: https://youtube.com/shorts/{video_id}")
    else:
        console.print(f"\n[bold red]Failed:[/bold red] {result.error}")
        raise typer.Exit(1)


@app.command("pin")
def pin_existing_comment(
    video_id: str = typer.Argument(..., help="YouTube video ID"),
    channel_id: str = typer.Argument(..., help="Channel ID"),
):
    """Pin an existing comment on a video via AdsPower (pins first comment)."""
    config = get_config_manager()

    if not config.channel_exists(channel_id):
        console.print(f"[red]Channel not found:[/red] {channel_id}")
        raise typer.Exit(1)

    channel_config = config.load_channel_config(channel_id)

    if not channel_config.adspower_profile_id:
        console.print(f"[red]AdsPower profile not configured for channel:[/red] {channel_id}")
        raise typer.Exit(1)

    youtube = YouTubeAPI(
        channel_config=channel_config,
        client_secrets_path=config.get_client_secrets_path(channel_id),
        token_path=config.get_token_path(channel_id),
    )

    console.print(f"\n[bold]Pinning comment on video:[/bold] {video_id}")
    console.print("[yellow]AdsPower browser will open...[/yellow]\n")

    # Use HumanCommenter for browser automation
    try:
        import asyncio
        from src.human_commenter import HumanCommenter, CommenterConfig
    except ImportError:
        console.print("[red]HumanCommenter not available. Install playwright dependencies.[/red]")
        raise typer.Exit(1)

    commenter = HumanCommenter(CommenterConfig())
    result = asyncio.get_event_loop().run_until_complete(
        commenter.add_and_pin_comment(
            video_id=video_id,
            comment_text="",  # empty = just pin existing
            profile_id=channel_config.adspower_profile_id,
        )
    )

    if result.success:
        console.print(f"\n[bold green]Comment pinned![/bold green]")
    else:
        console.print(f"\n[bold red]Pin failed:[/bold red] {result.error}")
        raise typer.Exit(1)


# ============================================================================
# A/B ROTATION COMMANDS
# ============================================================================

@ab_app.command("status")
def ab_status():
    """Show status of all A/B monitored videos."""
    config = get_config_manager()
    store = ABStore(config_dir=config.config_dir)
    videos = store.get_all_videos()

    if not videos:
        console.print("[dim]No videos in A/B rotation.[/dim]")
        console.print("Videos are registered automatically on upload if gen1_output.json has metadata_variants.")
        return

    table = Table(title="A/B Metadata Rotation")
    table.add_column("Video ID", style="cyan")
    table.add_column("Variant", style="bold")
    table.add_column("Views")
    table.add_column("Hours")
    table.add_column("Swaps")
    table.add_column("Status")
    table.add_column("Next Check")

    from datetime import datetime as dt, timezone as tz

    for v in videos:
        now = dt.now(tz.utc)
        hours = (now - v.variant_start_time).total_seconds() / 3600
        latest_views = v.metrics_log[-1].views if v.metrics_log else 0

        status_color = {
            ABStatus.MONITORING: "yellow",
            ABStatus.SUCCESS: "green",
            ABStatus.EXHAUSTED: "red",
            ABStatus.MANUAL: "red",
            ABStatus.ERROR: "red",
            ABStatus.STOPPED: "dim",
        }.get(v.status, "white")

        # Determine next check
        next_check = "—"
        if v.status == ABStatus.MONITORING:
            from src.publisher.ab_config import THRESHOLDS
            for check_name in ["check_1", "check_2", "check_3"]:
                if check_name not in v.checks_completed:
                    check_hours = THRESHOLDS[check_name]["hours"]
                    remaining = check_hours - hours
                    if remaining > 0:
                        next_check = f"{check_name} in {remaining:.1f}h"
                    else:
                        next_check = f"{check_name} (due)"
                    break

        table.add_row(
            v.video_id,
            v.current_variant,
            str(latest_views),
            f"{hours:.1f}",
            str(len(v.swap_history)),
            f"[{status_color}]{v.status.value}[/{status_color}]",
            next_check,
        )

    console.print(table)


@ab_app.command("start")
def ab_start():
    """Start the A/B monitor daemon (runs every 30 min)."""
    console.print("[bold blue]Starting A/B Monitor Daemon...[/bold blue]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    from src.publisher.ab_daemon import run_daemon
    run_daemon()


@ab_app.command("check")
def ab_check(
    video_id: str = typer.Argument(..., help="YouTube video ID to check"),
):
    """Run a single evaluation cycle for one video."""
    console.print(f"\n[bold]Checking video:[/bold] {video_id}\n")

    config = get_config_manager()
    monitor = ABMonitor(store=ABStore(config_dir=config.config_dir))
    result = monitor.check_single(video_id)

    console.print(f"Result: [bold]{result}[/bold]")


@ab_app.command("history")
def ab_history(
    video_id: Optional[str] = typer.Argument(None, help="Video ID (omit for all)"),
):
    """Show swap history and metrics for monitored videos."""
    config = get_config_manager()
    store = ABStore(config_dir=config.config_dir)

    if video_id:
        videos = [store.get_video(video_id)]
        if not videos[0]:
            console.print(f"[red]Video not found:[/red] {video_id}")
            raise typer.Exit(1)
    else:
        videos = store.get_all_videos()

    if not videos:
        console.print("[dim]No videos in A/B rotation.[/dim]")
        return

    for v in videos:
        console.print(f"\n[bold cyan]Video:[/bold cyan] {v.video_id}")
        console.print(f"  Project: {v.project_id} | Channel: {v.channel_id}")
        console.print(f"  Status: {v.status.value} | Current: variant {v.current_variant}")

        if v.swap_history:
            swap_table = Table(title="Swap History", show_header=True)
            swap_table.add_column("From")
            swap_table.add_column("To")
            swap_table.add_column("Views")
            swap_table.add_column("Reason")
            swap_table.add_column("Time")

            for swap in v.swap_history:
                swap_table.add_row(
                    swap.from_variant,
                    swap.to_variant,
                    str(swap.views_at_swap),
                    swap.reason,
                    swap.timestamp.strftime("%m-%d %H:%M"),
                )

            console.print(swap_table)
        else:
            console.print("  [dim]No swaps yet[/dim]")

        if v.metrics_log:
            console.print(f"  Metrics: {len(v.metrics_log)} snapshots, latest: {v.metrics_log[-1].views} views")


@ab_app.command("stop")
def ab_stop(
    video_id: str = typer.Argument(..., help="YouTube video ID to stop monitoring"),
):
    """Stop monitoring a specific video."""
    config = get_config_manager()
    store = ABStore(config_dir=config.config_dir)
    success = store.stop_video(video_id)

    if success:
        console.print(f"[green]Stopped monitoring:[/green] {video_id}")
    else:
        console.print(f"[red]Video not found:[/red] {video_id}")
        raise typer.Exit(1)


@ab_app.command("register")
def ab_register(
    video_id: str = typer.Argument(..., help="YouTube video ID"),
    project_id: str = typer.Argument(..., help="YTAuto project ID"),
    channel_id: str = typer.Argument(..., help="Internal channel ID"),
):
    """Manually register an already-uploaded video for A/B monitoring."""
    import json

    config = get_config_manager()

    # Try to load gen1_output.json
    project_dir = config.get_project_dir(project_id)
    gen1_path = project_dir / "gen1_output.json"

    if not gen1_path.exists():
        console.print(f"[red]gen1_output.json not found:[/red] {gen1_path}")
        console.print("[dim]Ensure the project directory has gen1_output.json with metadata_variants[/dim]")
        raise typer.Exit(1)

    with open(gen1_path, "r", encoding="utf-8") as f:
        gen1_data = json.load(f)

    # Parse variants via shared utility
    variants, warnings = parse_metadata_variants(gen1_data)
    for w in warnings:
        console.print(f"[yellow]{w}[/yellow]")

    if len(variants) < 2:
        console.print(f"[red]Only {len(variants)} valid variants found, need at least 2[/red]")
        raise typer.Exit(1)

    # Use first available variant (usually "A")
    first_variant = sorted(variants.keys())[0]

    record = VideoABRecord(
        video_id=video_id,
        project_id=project_id,
        channel_id=channel_id,
        current_variant=first_variant,
        variants=variants,
        gen1_output_path=str(gen1_path),
    )

    store = ABStore(config_dir=config.config_dir)
    store.register_video(record)

    console.print(f"[green]Registered {video_id} for A/B monitoring ({len(variants)} variants)[/green]")

    # Show variants summary
    table = Table(title="Registered Variants")
    table.add_column("Variant", style="bold")
    table.add_column("Trigger")
    table.add_column("Title")

    for letter, vd in sorted(variants.items()):
        title_preview = vd.title[:50] + "..." if len(vd.title) > 50 else vd.title
        table.add_row(letter, vd.trigger, title_preview)

    console.print(table)


# ============================================================================
# MAIN ENTRY
# ============================================================================

def main():
    """Main entry point"""
    app()


if __name__ == "__main__":
    main()
