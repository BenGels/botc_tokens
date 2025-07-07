"""Create printable sheets based on a script json file."""
# Standard Library
import math
from pathlib import Path

# Third Party
from wand.image import Image

from .token_components import TokenComponents
from ..helpers.text_tools import fit_ability_text_block, fit_ability_text_block_with_font


# Application Specific


class Printable:
    """Create printable sheets based on a script json file."""
    def __init__(
            self,
            output_dir,
            page_width=2550,
            page_height=3300,
            basename="page",
            margin_horizontal=74,
            margin_vertical=74,
            padding=0,
            diameter=None,
            close_packing=True,
            scriptname=None
    ):
        """Create a new printable object.

        Args:
            output_dir (str|Path): The directory to save the pages to.
            page_width (int): The width of the page in pixels.
            page_height (int): The height of the page in pixels.
            basename (str): The base name to use for the pages.
            margin_horizontal (int): The margin (in pixels) between the left/right edge of the paper and the tokens.
            margin_vertical (int): The margin (in pixels) between the top/bottom of the paper and the tokens.
            padding (int): The padding (in pixels) between tokens.
            diameter (int): The diameter (in pixels) to allocate per token. If unspecified, the first token's largest
                dimension will be used.
            close_packing (bool): Whether to use close packing of circles. If True, the tokens will be arranged in a
                hexagonal pattern. If False, the tokens will be arranged in a grid.
        """
        # 8.5"x11" at 300dpi is 2550 x 3300px
        # Subtracting 74px from each side to account for printer margins leaves our default of 2402 x 3152px
        self.scriptname = None
        self.page_width = page_width - (margin_horizontal * 2)
        self.page_height = page_height - (margin_vertical * 2)
        self.page = None
        self.document = Image()
        self.document.resolution = (300, 300)
        self.current_x = 0
        self.current_y = 0
        self.next_row_should_be_inset = False
        self.output_dir = Path(output_dir)
        self.page_number = 1
        self.basename = basename
        self.margin_horizontal = margin_horizontal
        self.margin_vertical = margin_vertical
        self.padding = padding
        self.diameter = diameter
        self.close_packing = close_packing
        self.start_x = 0
        self.start_y = 0

        self.save_page()  # Initializes the first page

    def write_typeline(self, components, character_type):
        ability_text_img = fit_ability_text_block_with_font(
            text=character_type.upper(),
            font_size=40,
            first_line_width=300,
            left=0,
            components=components,
            font=components.RoleNameFont
        )

        self.page.composite(ability_text_img, left=(self.page_width - 300), top=self.current_y-80)
        ability_text_img.close()

    def write_scriptname(
            self,
            scriptname: str,
            components: TokenComponents):
        ability_text_img = fit_ability_text_block(
            text=scriptname,
            font_size=50,
            first_line_width=200,
            left=0,
            components=components
        )

        self.page.composite(ability_text_img, left=(self.page_width - 800), top=100)
        ability_text_img.close()

    def set_linebreak(self, linebreak_file):
        self.linebreak = linebreak_file

    def set_linebreak_switch(self, linebreak_switch):
        self.linebreak_switch = linebreak_switch

    def set_start(self, x, y):
        self.start_x = x
        self.start_y = y
        self.reset_start()

    def reset_start(self):
        self.current_x = self.start_x
        self.current_y = self.start_y

    def save_page(self):
        """Save the current page and reset the state."""
        if not (self.current_x == 0 and self.current_y == 0):  # Only save if we added content
            # Add the margins in by creating a new image and compositing the current page onto it
            new_page = Image(
                width=self.page_width + (self.margin_horizontal * 2),
                height=self.page_height + (self.margin_vertical * 2)
            )
            new_page.composite(self.page, left=self.margin_horizontal, top=self.margin_vertical)
            self.page = new_page

            # Save the page to the document, reset our cursors, and increment the page number
            self.document.sequence.append(self.page)
            self.current_x, self.current_y = 0, 0
            self.page_number += 1
            self.next_row_should_be_inset = False
        self.page = Image(width=self.page_width, height=self.page_height)

    def write(self):
        """Write everything to disk."""
        # Save the last page if it has content
        if self.current_x != 0 or self.current_y != 0:
            self.save_page()
        if self.document.sequence:
            self.document.save(filename=self.output_dir / f"{self.basename}.pdf", adjoin=True)

    def close(self):
        """Close all Wand objects."""
        self.document.close()
        self.page.close()

    def add_token(self, token_file):
        """Add a token to the current page."""
        with Image(filename=token_file) as token:
            # Unless we have a fixed diameter, use the largest dimension of the first token as the diameter
            if self.diameter is None:
                self.diameter = token.width if token.width > token.height else token.height
            if token.width > self.diameter or token.height > self.diameter:
                token.resize(width=self.diameter, height=self.diameter)
            self.page.composite(token, left=int(self.current_x), top=int(self.current_y))
            self.current_x += self.diameter + self.padding
            # Check bounds
            if self.current_x + self.diameter > self.page.width:
                if self.close_packing:
                    # When close packing circles, we alternate each row by half the diameter
                    self.current_x = 0 + (0 if self.next_row_should_be_inset else self.diameter * 0.5 + self.padding)
                    self.next_row_should_be_inset = not self.next_row_should_be_inset  # Toggle the row inset
                    # Due to close packing, we can't just use the token diameter to move the new y. Instead, we make a
                    # right-angle triangle with the hypotenuse connecting the center of the next circle to the center of
                    # the circle above it in the previous row. In order to prevent overlap, the triangle must have a
                    # base equal to the radius of the circle and a hypotenuse equal to the diameter (2r).
                    # Solving for height will give us the distance we need to move the new y value, and it comes out
                    # to be `radius * sqrt(3)`.
                    self.current_y += ((self.diameter // 2) * math.sqrt(3)) + self.padding
                else:
                    self.current_x = 0
                    self.current_y += self.diameter + self.padding

                # Check to see if we have reached the end of the page
                if self.current_y + self.diameter > self.page.height:
                    self.save_page()


    def set_background(self, background):
        """Add a background to the pdf"""
        background.resize(width=(background.width - (self.margin_horizontal * 2)), height=(background.height - (self.margin_vertical * 2)))
        self.page.composite(background, left=0, top=0)

        self.scriptname = None


    def add_breakline(self, position):

        if(position % 2 == 1):
            self.current_y += 5
            self.page.composite(self.linebreak, left=int(self.start_x+50), top=int(self.current_y))
            self.current_y += 5 + self.linebreak.height
        else:
            self.page.composite(self.linebreak_switch, left=int(self.start_x+50), top=int(self.current_y-40))
            self.current_y += 5 + self.linebreak.height

    def add_night_token(self, token_file, firstnight):
        with Image(filename=token_file) as token:
            if (firstnight == False):
                self.current_x -= (token.width + 10)
            self.page.composite(token, left=int(self.current_x), top=int(self.current_y))
            if(firstnight == True):
                self.current_x += (token.width + 10)



    def add_script_token(self, token_file, forceSwitch):
        """Add a token to the current page."""

        with Image(filename=token_file) as token:
            token_width = int((self.page_width - (self.margin_horizontal * 2) - self.start_x) / 2)
            print(f"\n[red]Error:[/][bold] {token_file} width {forceSwitch}")
            token.resize(width=token_width)
            self.page.composite(token, left=int(self.current_x), top=int(self.current_y))

            self.current_x += token.width
            if self.current_x > token.width + self.start_x or forceSwitch:
                self.current_x = self.start_x
                self.current_y += token.height + 0