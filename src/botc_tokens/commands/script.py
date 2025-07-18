"""Create printable sheets based on a script json file."""
# Standard Library
import argparse
import json
from pathlib import Path
import re
import sys
from zipfile import BadZipFile

# Third Party
from jsonschema import validate, ValidationError
from rich import print
from rich.live import Live
from wand.exceptions import BlobError

# Application Specific
from .. import data_dir
from .. import component_path as default_component_path
from ..helpers.printable import Printable
from ..helpers.progress_group import setup_progress_group
from ..helpers.token_components import TokenComponents


def _parse_args():
    parser = argparse.ArgumentParser(
        prog="botc_tokens script",
        description='Create printable script sheets based on a script json file.'
    )
    parser.add_argument('script', type=str,
                        help='the json file or directory containing the script info.')
    parser.add_argument('--nightorder', type=str,
                        help='the json file containing the nightorder.')
    token_dir_default = 'tokens'
    parser.add_argument('--token-dir', type=str, default=token_dir_default,
                        help="Name of the directory in which to find the token images. Ignored if script is a "
                             f"directory. (Default: {token_dir_default})")
    parser.add_argument('--components', type=str, default=default_component_path,
                        help="The directory or zip in which to find the token components. (leaves, backgrounds, etc.)")
    output_dir_default = 'printables'
    parser.add_argument('-o', '--output-dir', type=str, default=output_dir_default,
                        help=f"Name of the directory in which to output the sheets. (Default: {output_dir_default})")
    margin_default = 74
    parser.add_argument('--margin-horizontal', type=int, default=margin_default,
                        help=f"The margin (in pixels) between the left/right edge of the paper and the tokens. "
                             f"(Default: {margin_default})")
    parser.add_argument('--margin-vertical', type=int, default=margin_default,
                        help=f"The margin (in pixels) between the top/bottom of the paper and the tokens. "
                             f"(Default: {margin_default})")
    paper_width_default = 2550
    parser.add_argument('--paper-width', type=int, default=paper_width_default,
                        help="The width (in pixels) of the paper to use for the tokens. "
                             f"(Default: {paper_width_default})")
    paper_height_default = 3300
    parser.add_argument('--paper-height', type=int, default=paper_height_default,
                        help="The height (in pixels) of the paper to use for the tokens. "
                             f"(Default: {paper_height_default})")
    parser.add_argument("--blocklinebreak", type=bool, default=False, help="Block type switch after type changes")
    args = parser.parse_args(sys.argv[2:])

    return args

def create_order(script, order):
    if isinstance(script[0], dict):
        script.pop(0)
    intersected_roles_night = list(set(script) & set(order))
    sorted_night = sorted(intersected_roles_night, key=lambda x: order.index(x))
    return sorted_night

def run():
    """Create printable sheets based on a script json file."""
    args = _parse_args()

    # Read the script json file
    print(f"[green]Reading {args.script}...[/]")
    try:
        script = load_script(args)
        with open(data_dir / "nightsheet.json", "r") as f:
              nightorder = json.load(f)

    except RuntimeError as e:
        print(f"[red]Error:[/] Unable to load script {args.script}: {str(e)}")
        return 1

    # Find all the token images
    token_files = Path(args.token_dir).rglob("*.png")
    print("[green]Finding Token Images...[/]")
    role_images = find_scriptblocks(token_files)

    # Create the printable sheets
    print(f"[green]Creating sheets in {args.output_dir}...[/]", end="")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    progress_group, overall_progress, step_progress = setup_progress_group()

    with Live(progress_group):
        overall_progress.add_task("Creating Sheets", total=None)
        step_task = step_progress.add_task("Adding roles")
        role_page = Printable(
            output_dir,
            basename="script",
            page_width=args.paper_width,
            page_height=args.paper_height,
            margin_vertical=args.margin_vertical,
            margin_horizontal=args.margin_horizontal
        )
        components = load_components(args.components)
        if components is None:
            print(f"\n[red]Error:[/][bold] Could not load component")
            return

        role_page.set_background(components.get_script_bg())
        role_page.set_linebreak(components.get_script_type_line())
        role_page.set_linebreak_switch(components.get_script_type_line_broken())
        role_page.set_start(200 + role_page.margin_horizontal,320 + role_page.margin_vertical)

        process_tokens(role_images, role_page, script,
                       step_progress, step_task, args.blocklinebreak, components)

        # Save the last pages
        step_progress.update(step_task, description="Saving pages")
        role_page.write()

        # Clean up
        role_page.close()

        create_backside(nightorder, args)
        return None


def create_backside(nightorder, args):
    try:
        script = load_script(args)
    except RuntimeError as e:
        print(f"[red]Error:[/] Unable to load script {args.script}: {str(e)}")
        return 1

    token_files = Path(args.token_dir).rglob("*.png")
    print("[green]Finding Token Images...[/]")
    role_images = find_images(token_files, "nightorder")

    # Create the printable sheets
    print(f"[green]Creating sheets in {args.output_dir}...[/]", end="")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    role_page = Printable(
        output_dir,
        basename="backside",
        page_width=args.paper_width,
        page_height=args.paper_height,
        margin_vertical=args.margin_vertical,
        margin_horizontal=args.margin_horizontal
    )
    components = load_components(args.components)
    if components is None:
        print(f"\n[red]Error:[/][bold] Could not load component")
        return

    role_page.set_background(components.get_script_back())
    role_page.set_start(450,30)
    process_first_night_order(role_images, role_page, nightorder["firstNight"], script, components, True)
    role_page.set_start(args.paper_width - 450, args.paper_height - 150)
    othernight = nightorder["otherNight"].copy()
    othernight.reverse()
    process_first_night_order(role_images, role_page, othernight, script, components, False)
    role_page.write()
    role_page.close()
    return None


def load_components(component_package):
    """Handle loading the components from a directory or zip file, and alerting the user if it fails."""
    try:
        components = TokenComponents(component_package)
    except BlobError as e:
        print(f"\n[red]Error:[/][bold] Could not load component: {str(e)}[/]")
        return None
    except BadZipFile:
        print(f"\n[red]Error:[/][bold] Could not load components from '{component_package}' it does not appear to be a "
              "valid components package.[/]")
        return None
    except FileNotFoundError as e:
        print(f"\n[red]Error:[/][bold] Unable to load components from '{component_package}': {str(e)}")
        return None
    return components

def process_first_night_order(role_images, role_page, nightorder, script, components, firstnight):
    sorted_order = create_order(script.copy(), nightorder)

    for i in range(len(sorted_order)):
        role = sorted_order[i]
        role_name = role.lower().strip()
        role_file = next((t for t in role_images if role_name == t.stem.lower().replace("'", "").replace("-nightorder", "")), None)
        if not role_file:
            print(f"[yellow]Warning:[/] No token found for {role_name}")
            continue

        role_page.add_night_token(role_file, firstnight)

def process_tokens(role_images, role_page, script,
                   step_progress, step_task, blockline, components):
    """Do all the processing.

    If we are being honest, this function exists separate from the run() function only to decrease its complexity.
    """
    last_character = "townsfolk"
    role_page.write_typeline(components, last_character)

    for i in range(len(script)):
        role = script[i]
        forceSwitch = False

        if isinstance(role, dict):
            continue  # Skip metadata

        if i < (len(script)-1) and i > 1:
            last_role = script[i-1]
            if last_role != None and not isinstance(last_role, dict) and get_role_type_by_name(role, role_images) != get_role_type_by_name(last_role, role_images) and (i % 2) == 0:
                if(blockline == True):
                    forceSwitch = True

        role_name = role.lower().strip()

        step_progress.update(step_task, description=f"Adding {role_name.title()}")
        # See if we have tokens for this role
        role_file = next((t for t in role_images if role_name == t.stem.lower().replace("'", "").replace("-scriptblock", "")), None)
        if not role_file:
            continue
        # Check if we should add duplicate tokens
        character_type = get_character_type(str(role_file))

        if character_type != last_character:
            role_page.add_breakline(i)
            role_page.write_typeline(components, character_type)

        role_page.add_script_token(role_file, forceSwitch)
        last_character = character_type

def get_role_type_by_name(role, role_images):
    role_name = role.lower().strip()
    role_file = next(
        (t for t in role_images if role_name == t.stem.lower().replace("'", "").replace("-scriptblock", "")), None)
    if not role_file:
        print(f"[yellow]Warning:[/] No token found for {role_name}")
        return
    return get_character_type(str(role_file))

def get_character_type(role_file):
    if "demon" in role_file:
        return "demon"
    elif "minion" in role_file:
        return "minion"
    elif "outsider" in role_file:
        return "outsider"
    elif "townsfolk" in role_file:
        return "townsfolk"

    return ""

def find_scriptblocks(token_files):
    return find_images(token_files, "scriptblock")

def find_images(token_files, needle):
    """Populate role and reminder lists with the images we find."""
    role_images = []
    for img_file in token_files:

        if needle in img_file.name:
            role_images.append(img_file)
    return role_images


def load_script(args):
    """Load the script from the file or directory."""
    script_path = Path(args.script)
    if not script_path.exists():
        raise RuntimeError(f"File or directory {args.script} does not exist.")
    script = []
    if script_path.is_dir():
        script = [file.stem for file in script_path.rglob("*.png") if "Reminder" not in file.name]
        args.token_dir = str(script_path)
    else:
        with open(args.script, "r") as f:
            script = json.load(f)
    return script
