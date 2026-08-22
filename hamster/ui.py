from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text


console = Console()

THEME = {
    "primary": "gold3",
    "secondary": "cyan",
    "success": "green",
    "warning": "yellow",
    "danger": "red",
}

HAMSTER_LOGO = """
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠞⡄⠀⣀⢢⡖⣴⢲⡀⠀⠀⠴⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡶⣏⢷⣺⡱⢧⣛⡵⣠⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⣀⣠⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡀⠀⠐⣮⡕⠮⢳⠶⣭⢳⡽⡸⣇⡖⠀⢀⣀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣸⣿⣿⣿⣿⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠐⠀⢨⢳⠞⣡⢬⡙⠮⢓⡄⠳⣭⢎⠀⠐⠋⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⢀⣰⣶⣘⣿⣿⣿⣿⣿⣿⣇⣠⣴⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠨⢟⡼⣓⢮⡳⢏⡾⣹⠎⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⣀⣸⣿⣿⣿⣿⡿⢿⣿⣿⣿⣿⣿⣿⣿⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡀⠉⠸⢹⢶⢹⡉⠶⠁⠀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠟⠛⡟⣯⠛⠃⢻⣏⠾⣽⢣⡏⠛⠙⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠛⠀⠀⠀⠉⠈⠁⠉⠀⠀⠀⠙⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⣀⡀⠀⠀⠀⠀⠀⢀⡀⠀⢀⠀⠀⠀⠀⠀⠀⠀⣀⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⣿⠛⠛⣿⣿⣤⠀⠀⣄⣄⣾⣷⣾⡟⠀⠀⠀⠀⠀⣤⣿⣿⡛⣛⣿⡤⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢰⡟⡱⡝⠆⢸⣿⣿⣾⣿⣿⣿⣿⣿⣿⡇⢀⣤⣾⣿⣷⣾⣿⡇⠰⣣⢎⣿⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣷⡳⢉⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣿⣿⣿⣿⣿⣿⣿⣿⣶⡁⢯⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢛⣷⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣞⠙⠀⠀⠀⠀⠀⠀⢀⣰⣿⣿⣖⡀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣾⣿⣿⣿⣿⣿⣥⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣦⣿⣿⣿⣿⣿⣿⣖⠀⠀⠀⠀⢠⣴⣤⣿⡿⣿⣿⢷⣧⡄⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣸⣿⣿⣿⣿⣿⡟⠀⠤⢻⣿⣿⣿⣿⣿⣿⣿⣿⡿⠥⠀⠙⣿⣿⣿⣿⣿⣿⣇⠀⠀⠀⠈⠉⠙⠂⠙⠑⠋⠁⠁⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣿⣿⣿⠋⡭⣉⢃⠀⠀⣹⣿⣿⠻⠧⠸⠿⣿⣿⣯⡀⠀⢀⠫⣩⠝⢿⣿⣿⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣿⣿⣿⣇⠻⡔⢥⣋⣿⣿⣿⣿⣿⣷⡿⣿⣿⣿⣿⣿⣿⣿⠈⣇⠎⣜⡂⣿⣿⣿⣧⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣮⣼⣧⣾⣿⣿⡟⢿⠏⡉⣂⢦⡉⡉⡛⡛⣿⣿⣿⣮⣽⣦⣾⣿⣿⣿⣿⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠿⣿⣿⣿⣿⣿⣿⣿⣿⠏⡁⢯⡖⡦⢝⠮⣥⢺⡵⠃⠉⠽⣿⣿⣿⣿⣿⣿⣿⡿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢿⣿⣿⣿⣿⣿⣿⣿⣇⠢⣜⠶⡙⠈⠀⠀⠈⠀⢵⢫⣏⠓⣸⣿⣿⣿⣿⣿⣿⣷⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿⣿⣿⣿⣿⡧⢀⡬⢯⡁⠀⠀⠀⠀⠀⢨⢳⢦⡁⢼⣿⣿⣿⣿⣿⣿⣿⣇⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣸⣿⣿⣿⣿⣿⣿⣿⣧⣆⡍⡈⣱⢲⠤⠀⠀⠀⡠⢶⡩⠌⢡⣴⣿⣿⣿⣿⣿⣿⣿⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢹⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⡀⠷⠏⡸⢹⢿⢸⡹⠈⠉⢰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⡋⠿⢿⣿⣿⣿⡷⡠⣅⠌⠃⢀⣌⠠⣿⣿⣿⣿⡿⢟⣿⣿⣿⣿⣿⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⢿⣿⣷⣎⣉⡛⠛⠃⠑⠦⠁⠀⠐⠬⠓⠿⠟⢛⣨⣴⣾⣿⣿⣿⣿⣿⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⣿⣿⡟⢀⢦⢒⡌⢻⡿⠀⠤⠀⠄⠀⠀⠀⠀⢻⣽⣷⣿⣆⣿⢁⡔⣠⢂⢻⣿⣿⣿⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠩⣻⣿⣇⡐⣎⠡⡺⢅⢀⡠⠄⠁⠠⣀⣤⣇⠠⠈⢿⣿⣿⡿⢁⡺⡈⢱⠎⣸⣿⡿⡟⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠒⠛⠷⠌⠳⣙⠮⠸⠟⠿⠿⠯⠿⠿⠿⠦⠤⠾⠟⠿⠃⠼⡱⡭⠓⠴⠟⠋⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀"""

HAMSTER_EXIT_LOGO = """
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠘⢣⣆⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣶⣦⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣶⡿⣿⣤⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢘⡾⣥⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⣤⣹⡿⣻⣿⣥⣤⡀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠐⠙⠒⠁⠉⠁⠀⠀⠀⠀⠀⠀⢂⡀⠀⢀⣠⠾⣽⠖⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠩⠻⠝⠚⠥⠻⠝⠯⠛⠛⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠛⠝⠫⠏⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⡀⠀⠀⠀⠀⠀⠠⢤⡄⠠⣄⡁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⢊⣤⠆⡨⡑⡄⠀⢀⡀⠠⠬⠄⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⠄⠀⣃⣾⡇⠸⣰⢘⠸⢀⣐⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣴⡼⢿⠿⣦⣄⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⢠⣼⡿⣿⣦⣄⠀⠀⠀⠀⠀⠀⠠⠨⣀⣩⠀⠀⢨⣿⣿⣿⣿⣶⣿⣿⣶⣤⣭⡑⡒⠤⢀⡀⠀⠀⠀⠀⠈⠁⠛⠈⠋⠈⠉⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠁⠈⠓⠃⠀⠉⠁⠀⠀⡠⠀⠀⢌⣰⣿⣿⣷⣰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣭⠢⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⡰⠟⢿⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣌⠂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢄⢁⠆⢌⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⢋⡟⡋⡍⣻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣄⠠⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠢⡍⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣿⣧⣓⣘⣼⡿⣱⣿⣿⣿⣿⣿⣿⣿⣿⡆⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡇⢿⣿⣿⣿⡿⣿⣿⣟⠻⢟⣿⣿⣿⣿⡿⢫⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡘⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠜⢸⣿⠿⢋⢴⣿⣿⣴⣾⣿⣿⣿⣿⠇⢠⡙⠿⠿⢛⣽⣿⣿⣿⣿⣿⣿⣿⡇⡁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡇⢻⣿⡘⠣⣦⡿⠿⠛⠻⢿⣛⣿⣼⣆⡀⢁⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⠇⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢣⡑⢿⣿⣿⣿⣿⣿⠁⠮⠄⣿⣿⣿⠋⠁⡛⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢣⢡⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢤⣀⠖⡆⣖⠂⣀⠀⠀⠀⢸⠼⣿⣿⡟⢁⠠⡐⢿⣿⣿⡀⢈⡰⢄⢻⣿⣿⣿⣿⣿⣿⢟⡯⠁⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⢖⡪⠈⠀⠀⠀⠋⢪⡤⡀⠈⠠⡉⢮⣛⢷⡀⠢⡜⣠⢙⢿⢿⣄⠓⠌⡰⢽⡛⡟⣯⢭⡞⠣⡡⠊⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⡤⢥⠀⠀⠀⠀⠀⢥⠥⡀⠀⠀⠈⠢⢌⡃⠝⡲⢄⡁⣔⢫⠞⡴⢣⢞⡩⣇⢯⡙⠖⢋⡠⠊⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠉⢠⠪⢠⠀⡤⡘⠦⠀⠀⠀⠀⠀⠀⠀⠈⠑⠐⠀⢌⡈⣁⢉⡈⣁⡈⣁⠀⠀⠔⠈⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀"""

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def print_logo() -> None:
    # ── Braille art rendered inside a high-contrast gold panel on startup ──
    logo_text = Text(HAMSTER_LOGO, style="bold gold3")
    console.print(
        Panel(
            Align.center(logo_text),
            border_style=THEME["primary"],
            padding=(0, 2),
            subtitle=f"[dim]🐹 Hamster — OpenRouter engineering agent[/dim]",
        )
    )
    metrics = Table.grid(padding=(0, 2))
    metrics.add_column(style="bold white")
    metrics.add_column(style="dim")
    metrics.add_row("Flow", "draft quietly · review once · save or discard")
    metrics.add_row("Review", "press v at the save prompt to inspect code")
    metrics.add_row("Mood", "supportive, sharp, tiny bit cheeky")
    metrics.add_row("Search", "ripgrep required · brew install ripgrep")
    console.print(Panel(metrics, border_style="gold3", title="[bold gold3]Ready[/]", title_align="left"))


def print_exit_logo() -> None:
    # ── Running/waving exit Braille hamster rendered in a farewell panel ──
    exit_text = Text(HAMSTER_EXIT_LOGO, style="bold gold3")
    farewell = Text("Bye! 🐹", style="bold gold3")
    console.print(
        Panel(
            Align.center(
                Text.assemble(exit_text, Text("\n"), farewell)
            ),
            border_style="gold3",
            title="[bold gold3]See you soon[/]",
            padding=(0, 2),
        )
    )


def print_help() -> None:
    table = Table(title=f"[bold {THEME['primary']}]Hamster Commands[/]", border_style=THEME["secondary"], box=box.ROUNDED)
    table.add_column("Command", style=f"bold {THEME['secondary']}", no_wrap=True)
    table.add_column("Action", style="white")
    table.add_row("/help", "Show this command guide")
    table.add_row("/files", "List files in the current draft")
    table.add_row("/search <query>", "Ask Hamster to search technical documentation")
    table.add_row("/pending", "Show pending draft changes")
    table.add_row("/apply", "Save pending draft changes")
    table.add_row("/sync", "Refresh draft state")
    table.add_row("/undo [N]", "Revert workspace N turns (default 1), keeps conversation log")
    table.add_row("/login", "Log in with Google (OAuth 2.0 PKCE flow)")
    table.add_row("/whoami", "Show the currently logged-in user")
    table.add_row("/logout", "Clear saved Google credentials")
    table.add_row("/clear", "Clear the terminal and redraw the splash")
    table.add_row("/exit", "Leave Hamster (prints farewell graphic)")
    console.print(table)
    console.print()
    tip = Text()
    tip.append("CLI tip: ", style="bold gold3")
    tip.append("hamster list-sessions", style="bold cyan")
    tip.append("  ·  ", style="dim")
    tip.append("hamster resume <session_id>", style="bold cyan")
    console.print(tip)


def print_session_resumed(session_id: str, msg_count: int, working_dir: str = "") -> None:
    """Print a banner when a saved session is restored."""
    body = Table.grid(padding=(0, 1))
    body.add_column(style="dim")
    body.add_column(style="white")
    body.add_row("Session", f"[bold cyan]{session_id}[/]")
    if working_dir:
        body.add_row("Working dir", working_dir)
    body.add_row("Messages", f"{msg_count} message{'' if msg_count == 1 else 's'} restored")
    console.print(
        Panel(
            body,
            title="[bold gold3]🐹 Resuming session[/]",
            border_style=THEME["primary"],
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def print_sessions_table(sessions: list[dict]) -> None:
    """Render a Rich table of past sessions for `hamster list-sessions`."""
    if not sessions:
        console.print(
            Panel(
                "No saved sessions yet.\nStart a new session with [bold cyan]hamster[/].",
                border_style=THEME["secondary"],
                title="[bold gold3]Sessions[/]",
            )
        )
        return

    table = Table(
        title=f"[bold {THEME['primary']}]Saved Sessions[/]",
        border_style=THEME["secondary"],
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("Session ID", style=f"bold {THEME['secondary']}", no_wrap=True)
    table.add_column("Created", style="dim", no_wrap=True)
    table.add_column("Last Active", style="dim", no_wrap=True)
    table.add_column("Working Dir", style="white", overflow="fold")
    table.add_column("Last Prompt", style="italic white", overflow="fold")

    for s in sessions:
        created = s.get("created_at", "")[:16].replace("T", " ")
        updated = s.get("updated_at", "")[:16].replace("T", " ")
        wdir = s.get("working_dir", "") or "—"
        prompt_raw = s.get("last_prompt") or "—"
        prompt = prompt_raw[:60] + "…" if len(prompt_raw) > 60 else prompt_raw
        table.add_row(s["session_id"], created, updated, wdir, prompt)

    console.print(table)
    console.print(
        f"  Resume with: [bold cyan]hamster resume <session_id>[/]",
        style="dim",
    )


def print_undo_result(message: str, success: bool = True) -> None:
    """Render the result of an /undo operation.

    Args:
        message: The status string returned by :func:`hamster.tools.undo_workspace`.
        success: When *True* renders a gold success panel; when *False* renders
                 an amber warning panel.
    """
    if success:
        console.print(
            Panel(
                Text(f"🔙  {message}", style="bold white"),
                title="[bold gold3]Undo[/]",
                border_style=THEME["primary"],
                box=box.ROUNDED,
                padding=(0, 2),
            )
        )
    else:
        console.print(
            Panel(
                Text(f"⚠️  {message}", style="bold yellow"),
                title="[bold yellow]Undo — Nothing to Revert[/]",
                border_style=THEME["warning"],
                box=box.ROUNDED,
                padding=(0, 2),
            )
        )


def print_login_success(email: str) -> None:
    """Render a success banner after ``hamster login`` completes."""
    console.print(
        Panel(
            Text.assemble(
                ("🐹  Logged in as ", "bold white"),
                (email, f"bold {THEME['secondary']}"),
            ),
            title="[bold gold3]Login Successful[/]",
            border_style=THEME["success"],
            box=box.ROUNDED,
            padding=(0, 2),
        )
    )


def print_whoami(profile: dict) -> None:
    """Render a Rich panel showing the currently logged-in user's profile.

    Args:
        profile: Dict with keys ``email``, ``name``, ``picture``, ``sub``.
    """
    body = Table.grid(padding=(0, 2))
    body.add_column(style="dim", no_wrap=True)
    body.add_column(style="white")
    if profile.get("name"):
        body.add_row("🧪 Name",    profile["name"])
    if profile.get("email"):
        body.add_row("📧 Email",   profile["email"])
    if profile.get("sub"):
        body.add_row("🔑 Google ID", profile["sub"])
    if profile.get("picture"):
        body.add_row("🖼️  Picture",  f"[link={profile['picture']}]{profile['picture']}[/link]")
    console.print(
        Panel(
            body,
            title="[bold gold3]🐹 Hamster — Logged-in Account[/]",
            border_style=THEME["secondary"],
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def render_action_summary(action: str, details: Mapping[str, str]) -> None:
    """Minimal action indicator - suppressed for cleaner UI."""
    pass


def render_files_summary(rows: Sequence[Mapping[str, str]]) -> None:
    """File access indicator - suppressed for cleaner UI."""
    pass


def render_diff(filepath: str, diff_lines: Sequence[str]) -> None:
    # ── Tokenized color diff: additions=green, deletions=red, metadata=cyan ──
    additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++ "))
    deletions = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("--- "))

    body = Text()
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++ "):
            body.append(line + "\n", style="bold green")
        elif line.startswith("-") and not line.startswith("--- "):
            body.append(line + "\n", style="bold red")
        elif line.startswith("@@") or line.startswith("--- ") or line.startswith("+++ "):
            # Boundary / hunk headers and file paths rendered in cyan
            body.append(line + "\n", style="bold cyan")
        else:
            body.append(line + "\n", style="white")

    meta = Text.assemble(
        (f"+{additions} addition{'s' if additions != 1 else ''}", "green"),
        ("  ", "white"),
        (f"-{deletions} deletion{'s' if deletions != 1 else ''}", "red"),
        ("  ", "white"),
        (f"[{filepath}]", "bold cyan"),
    )
    console.print(Rule(title=meta, style="cyan"))
    console.print(
        Panel(
            body,
            title=f"[bold {THEME['secondary']}]Diff Preview[/]",
            subtitle=f"[dim]{filepath}[/]",
            border_style=THEME["secondary"],
            padding=(0, 1),
        )
    )


def render_security_violation(message: str) -> None:
    console.print(Panel(message, title="Security Violation", border_style="bold red", style="red"))


def request_save_changes(changes: list[str], diff_lines: list[str]) -> str:
    body = "\n".join(["I drafted the changes. Looking good from here.", "", *changes[:20]])
    if len(changes) > 20:
        body += f"\n... and {len(changes) - 20} more"
    body += "\n\nSave everything, discard everything, or peek at the diff first."

    options = Table.grid(padding=(0, 1))
    options.add_column(no_wrap=True)
    options.add_column()
    options.add_row("[bold green]a[/]", "save all")
    options.add_row("[bold red]r[/]", "discard all")
    options.add_row("[bold yellow]v[/]", "view diff")

    # Build the panel once and reuse for the first prompt
    def _render_panel() -> None:
        panel_body = Table.grid(expand=True)
        panel_body.add_column()
        panel_body.add_row(Text(body, style="white"))
        panel_body.add_row("")
        panel_body.add_row(options)
        console.print(
            Panel(
                panel_body,
                title="[bold gold3]Review Changes[/]",
                subtitle="[dim]a save all · r discard all · v view diff[/dim]",
                border_style=THEME["primary"],
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    _render_panel()
    while True:
        answer = prompt_user(
            f"[bold {THEME['primary']}]Choice[/] "
            f"[green]a[/]/[red]r[/]/[yellow]v[/] ([dim]r[/]): "
        ).strip().lower()
        if answer in {"a", "accept", "accept all", "y", "yes"}:
            return "accept"
        if answer in {"r", "reject", "reject all", "n", "no", ""}:
            return "reject"
        if answer in {"v", "view"}:
            render_diff("Draft changes", diff_lines)
            # After showing the diff just re-ask inline — no full panel repeat
            console.print(
                f"[dim]a save all · r discard all[/dim]",
                justify="right",
            )
            continue
        console.print("Please answer a, r, or v.", style=THEME["warning"])


def render_tool_result(name: str, content: str) -> None:
    """Render tool result with minimal UI overhead. Suppress for read operations."""
    # Skip rendering for successful read operations (content shows as file excerpt)
    if name == "read_file" and content and not content.startswith("ERROR:"):
        return
    # Skip for search_codebase with results (agent already sees results)
    if name == "search_codebase" and content and content != "No matches." and not content.startswith("Denied"):
        return
    # Skip for denied/successful quiet operations
    if content in ("Denied.", "User denied."):
        return
    # SECURITY VIOLATION strings are already rendered by render_security_violation()
    # called inside _security_violation() — do NOT render a second panel here.
    if content.startswith("SECURITY VIOLATION:"):
        return
    # Minimal render for errors and other status messages
    if content.startswith("ERROR:"):
        console.print(Panel(content, border_style=THEME["danger"], title="⚠️  Tool Error"))
    elif content.startswith("Denied") or content.startswith("User denied"):
        console.print(Panel(f"🐹 {content}", border_style=THEME["warning"], title="Hamster Notice"))


def render_model_error(message: str) -> None:
    console.print(Panel(message, title="Model Error", border_style="red"))


def print_assistant_delta(text: str) -> None:
    console.print(text, end="", markup=False, highlight=False)


def prompt_user(prompt: str) -> str:
    return console.input(prompt)


def status(message: str):
    """Generic status spinner (used for fast local operations)."""
    return console.status(message, spinner="dots", spinner_style="gold3")


def remote_status(message: str):
    """Visually distinct spinner for remote OpenRouter API calls (slow network).

    Uses a slower 'earth' spinner and a muted blue style so operators can
    immediately distinguish remote model latency from rapid local operations.
    """
    return console.status(message, spinner="earth", spinner_style="steel_blue1")


def sandbox_status(message: str):
    """Explicit spinner for fast local operations (reads, patches, search).

    Uses the 'dots2' spinner and gold styling to signal an in-process,
    approval-gated local action rather than a remote call.
    """
    return console.status(message, spinner="dots2", spinner_style="gold3")


def confirm(prompt: str) -> bool:
    while True:
        answer = prompt_user(
            f"[bold {THEME['primary']}] {prompt} [/][green](y)[/]/[red](n)[/] : "
        ).strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        console.print("Please answer y or n.", style=THEME["warning"])
